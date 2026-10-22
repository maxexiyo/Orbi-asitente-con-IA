"""Modo compañero: Orbi mira tu pantalla de vez en cuando y, solo si ve algo útil, te avisa.

Funciona con una llamada de visión aparte (texto, modelo barato) que decide SI vale la pena hablar.
Solo si decide comentar, el mensaje se muestra en la burbuja y se le pasa a la voz de Live.

Frenos para no ser pesado:
  - mira cada CHECK_EVERY s, y solo si la pantalla cambió
  - SIN temporizador de silencio ni tope por hora (COOLDOWN=0, MAX_PER_HOUR=0): la IA decide libremente si vale la pena
    hablar; se puede volver a poner en config.json -> "companero" (ver config.example.json)
  - no habla si estás hablando con Orbi, si el micro está silenciado o si Orbi está dormida
  - se salta ventanas sensibles (banco, contraseñas, login...) sin siquiera capturarlas
  - no repite lo que ya dijo (le pasa sus últimos comentarios)
"""
import json, threading, time

import llm
from screen import ChangeDetector, capture
from windows import foreground_info, foreground_is_fullscreen

CHECK_EVERY = 20         # s entre revisiones (es solo cada cuánto MIRA; hablar lo decide la IA)
COOLDOWN = 0             # s de silencio obligatorio tras un comentario (0 = ninguno)
MAX_PER_HOUR = 0         # tope de comentarios por hora (0 = sin tope)
SENSITIVE = ("contraseña", "password", "banco", "bank", "bbva", "banorte", "santander", "hsbc", "paypal",
             "login", "iniciar sesión", "sign in", "keepass", "bitwarden", "1password", "lastpass",
             "tarjeta", "cvv", "token", "otp", "wallet", "incógnito", "incognito", "inprivate")

PROMPT = """Eres Orbi, un compañero que mira la pantalla de {quien} y SOLO habla cuando de verdad ayuda.
Tono: {tono}. Ventana activa: «{ventana}».
{perfil}
Comentarios que ya hiciste (no los repitas ni digas algo parecido):
{previos}

Mira la captura. Comenta SOLO si ves algo claramente útil, por ejemplo:
- un error visible (mensaje de error, traza, código rojo, fallo de compilación)
- un typo o dato evidentemente mal en lo que está escribiendo
- una forma bastante mejor de hacer lo que parece estar haciendo
- algo importante que seguramente no notó (una advertencia, una fecha, un botón que falta)
NO comentes: lo obvio, lo que ya comentaste, opiniones de gusto, ni cosas que solo describen la pantalla.
No hay límite de frecuencia: TÚ decides libremente si ahora vale la pena hablar; si ya lo dijiste, no lo repitas.
Si no hay nada que valga la pena interrumpir: comentar=false. Ante la duda, calla.
ANTES de corregir algo (typo, dato, código), LEE el texto exacto en la captura y compáralo: si no puedes leerlo con
total claridad o no estás seguro de que está mal, NO comentes (muchas veces lo que parece error está bien o es otro
idioma/nombre propio/código). Para comentar debes citar en "evidencia" el texto EXACTO que ves en pantalla.
Si comentas: máximo 25 palabras, español, en tu tono, dirigido a {quien}, sin saludos ni markdown.
No leas en voz alta contraseñas, tarjetas ni datos privados.
Responde SOLO este JSON: {{"comentar": true|false, "evidencia": "texto exacto visto", "seguro": true|false, "mensaje": "..."}}"""


class Observer:
    def __init__(self, pool, models, emit, get_profile, can_speak, enabled=lambda: True,
                 check_every=None, cooldown=None, max_per_hour=None):
        self.check_every = float(CHECK_EVERY if check_every is None else check_every)
        self.cooldown = float(COOLDOWN if cooldown is None else cooldown)
        self.max_per_hour = int(MAX_PER_HOUR if max_per_hour is None else max_per_hour)
        self.pool = pool if isinstance(pool, llm.KeyPool) else llm.KeyPool(pool)
        self.models = [models] if isinstance(models, str) else list(models)
        self.emit = emit
        self.get_profile, self.can_speak, self.enabled = get_profile, can_speak, enabled
        self._stop = threading.Event()
        self._thread = None
        self._det = ChangeDetector(threshold=2.5)
        self._said = []          # [(timestamp, texto)]
        self._cool_until = 0.0
        self.last_check = 0.0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._det.reset()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------
    def _loop(self):
        while not self._stop.wait(max(5.0, self.check_every)):
            try:
                self._tick()
            except Exception as e:
                self.emit("info", f"[compañero] {type(e).__name__}: {e}")

    def _tick(self):
        now = time.time()
        if not self.enabled() or not self.can_speak() or now < self._cool_until:
            return
        self._said = [(t, m) for t, m in self._said if now - t < 3600]
        if self.max_per_hour and len(self._said) >= self.max_per_hour:
            return
        if foreground_is_fullscreen():                 # juego / presentación / video: no molestes
            return
        title = foreground_info()["title"]
        if any(w in title.lower() for w in SENSITIVE):
            self._det.reset()                      # ni capturamos: ventana sensible
            return
        jpeg, _ = capture(max_side=1600, quality=75)
        if not self._det.changed(jpeg):
            return
        msg = self._ask(jpeg, title)
        if msg:
            self._said.append((time.time(), msg))
            self._cool_until = time.time() + self.cooldown
            self.emit("suggestion", msg)

    def _ask(self, jpeg: bytes, title: str):
        from perfil import call_name, profile_summary, TONOS

        prof = self.get_profile() or {}
        quien = call_name(prof) or "tu dueño"
        prompt = PROMPT.format(
            quien=quien, tono=TONOS.get(prof.get("tono", "casual"), TONOS["casual"]), ventana=title or "desconocida",
            perfil=("Lo que sabes de él/ella: " + profile_summary(prof)) if profile_summary(prof) else "",
            previos="\n".join("- " + m for _, m in self._said[-5:]) or "(ninguno todavía)")
        from google.genai import types
        try:
            r, _model = llm.generate(
                self.pool, self.models,
                [types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), prompt],
                types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4))
            data = json.loads((r.text or "{}").strip().strip("`").removeprefix("json").strip())
        except llm.AllBusy as e:
            self.emit("info", f"[compañero] no pude revisar: {str(e)[:150]}")
            self._cool_until = time.time() + 90
            return None
        except (ValueError, TypeError):
            return None
        msg = str(data.get("mensaje", "")).strip()
        if data.get("comentar") is True and data.get("seguro") is True and str(data.get("evidencia", "")).strip() \
                and 3 <= len(msg) <= 300:
            return msg
        return None
