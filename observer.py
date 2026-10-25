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
import json, os, re, threading, time, unicodedata
from pathlib import Path

import llm
from screen import ChangeDetector, capture
from windows import foreground_info, foreground_is_fullscreen

CHECK_EVERY = 20         # s entre revisiones (es solo cada cuánto MIRA; hablar lo decide la IA)
COOLDOWN = 0             # s de silencio obligatorio tras un comentario (0 = ninguno)
MAX_PER_HOUR = 0         # tope de comentarios por hora (0 = sin tope)
SENSITIVE = ("contraseña", "password", "banco", "bank", "bbva", "banorte", "santander", "hsbc", "paypal",
             "login", "iniciar sesión", "sign in", "keepass", "bitwarden", "1password", "lastpass",
             "tarjeta", "cvv", "token", "otp", "wallet", "incógnito", "incognito", "inprivate")

MEMORIA_PATH = Path(__file__).parent / "orbi_observaciones.json"     # lo que ya comentó: sobrevive a minimizar/abrir ventanas y a reiniciar
MEMORIA_HORAS = 24            # cuánto se acuerda de un comentario (no lo repite en ese tiempo, aunque cambie la pantalla)
ESPERA_REPETIR_S = 600        # tras avisar de algo, espera este rato (le da tiempo de corregirlo); si sigue igual en pantalla, avisa otra vez
MAX_AVISOS = 2                # veces máximas que avisa del MISMO asunto (el primer aviso + un recordatorio)
SIMILAR = 0.55                # parecido (0-1) entre dos comentarios/evidencias para contarlos como «lo mismo»

PROMPT = """Eres Orbi, un compañero que mira la pantalla de {quien} y SOLO habla cuando de verdad ayuda.
Tono: {tono}. Ventana activa: «{ventana}».
{perfil}
Comentarios que ya hiciste, con cuánto hace (no repitas uno hecho hace poco ni digas algo parecido):
{previos}
Si uno de hace MÁS de {espera} min SIGUE igual en la captura (no lo corrigió, seguramente no se dio cuenta), puedes avisarlo UNA
vez más, con otras palabras y breve. Si ya lo corrigió o ya no está en pantalla, NO digas nada (comentar=false).
{propio}

Mira la captura. Comenta SOLO si ves algo claramente útil, por ejemplo:
- un error visible (mensaje de error, traza, código rojo, fallo de compilación)
- un typo o dato evidentemente mal en lo que está escribiendo
- una forma bastante mejor de hacer lo que parece estar haciendo
- algo importante que seguramente no notó (una advertencia, una fecha, un botón que falta)
NO comentes: lo obvio, lo que ya comentaste, opiniones de gusto, ni cosas que solo describen la pantalla.
Tampoco comentes avisos de límite o cuota (que se acabaron los mensajes, tokens o créditos gratis de una IA o servicio, «vuelve más
tarde», suscripciones, actualizaciones disponibles): {quien} ya los vio y no puede hacer nada; comentarlos es ruido.
Aunque cierre y vuelva a abrir una ventana, lo que ya comentaste sigue contando como comentado.
No hay límite de frecuencia: TÚ decides libremente si ahora vale la pena hablar; si ya lo dijiste, no lo repitas.
Si no hay nada que valga la pena interrumpir: comentar=false. Ante la duda, calla.
ANTES de corregir algo (typo, dato, código), LEE el texto exacto en la captura y compáralo: si no puedes leerlo con
total claridad o no estás seguro de que está mal, NO comentes (muchas veces lo que parece error está bien o es otro
idioma/nombre propio/código). Para comentar debes citar en "evidencia" el texto EXACTO que ves en pantalla.
Si comentas: máximo 25 palabras, español, en tu tono, dirigido a {quien}, sin saludos ni markdown.
No leas en voz alta contraseñas, tarjetas ni datos privados.
Si el error está en un texto que TÚ (Orbi) escribiste (aparece en «lo que tú escribiste» arriba), o el texto se ve encimado, duplicado,
cortado o mezclado por tu escritura, NO es culpa de {quien}: pon "es_mio": true y en "mensaje" describe qué quedó mal y cómo debe quedar
(sin decirle a {quien} que se equivocó). Si el error es de {quien}, "es_mio": false.
Responde SOLO este JSON: {{"comentar": true|false, "evidencia": "texto exacto visto", "seguro": true|false, "es_mio": true|false, "mensaje": "..."}}"""


class Observer:
    def __init__(self, pool, models, emit, get_profile, can_speak, enabled=lambda: True,
                 check_every=None, cooldown=None, max_per_hour=None, own_text=lambda: []):
        self.own_text = own_text                 # -> [(t, texto, ventana)] lo que Orbi tecleó hace poco
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
        self._mem_lock = threading.Lock()
        self._mem = self._mem_load()
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
        while not self._stop.wait(max(1.0, self.check_every)):
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
        res = self._ask(jpeg, title)
        if res:
            msg, es_mio = res
            self._said.append((time.time(), msg))
            self._cool_until = time.time() + self.cooldown
            self.emit("self_fix" if es_mio else "suggestion", msg)

    def _ask(self, jpeg: bytes, title: str):
        from perfil import call_name, profile_summary, TONOS

        prof = self.get_profile() or {}
        quien = call_name(prof) or "tu dueño"
        prompt = PROMPT.format(
            quien=quien, tono=TONOS.get(prof.get("tono", "casual"), TONOS["casual"]), ventana=title or "desconocida",
            perfil=("Lo que sabes de él/ella: " + profile_summary(prof)) if profile_summary(prof) else "",
            previos="\n".join(f"- (hace {max(1, int((time.time() - float(x.get('t', 0))) / 60))} min, avisado {int(x.get('n', 1))}×) {x.get('msg')}"
                              for x in self._recientes(10)) or "(ninguno todavía)",
            espera=int(ESPERA_REPETIR_S // 60),
            propio=self._propio())
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
            ev = str(data.get("evidencia", "")).strip()
            prev = self._buscar_dicho(ev, msg)
            if prev is not None:
                edad = time.time() - float(prev.get("t", 0))
                if edad < ESPERA_REPETIR_S or int(prev.get("n", 1)) >= MAX_AVISOS:
                    self._cool_until = time.time() + 120           # lo mismo de antes: no vuelvas a preguntarle al modelo en 2 min
                    return None
                self._reavisar(prev, msg)                          # pasó el rato y SIGUE ahí: no se dio cuenta -> un recordatorio
                return msg, data.get("es_mio") is True
            self._recordar(ev, msg)
            return msg, data.get("es_mio") is True
        return None

    # ------------------------------------------------------------------ memoria persistente de lo ya comentado
    @staticmethod
    def _toks(t: str) -> set:
        t = unicodedata.normalize("NFD", str(t or "").lower())
        t = "".join(c for c in t if unicodedata.category(c) != "Mn")
        return {w for w in re.findall(r"[a-z0-9ñ]+", t) if len(w) > 3}

    def _horas(self) -> float:
        return float(MEMORIA_HORAS)

    def _mem_load(self) -> list:
        try:
            d = json.loads(MEMORIA_PATH.read_text(encoding="utf-8"))
            lim = time.time() - self._horas() * 3600
            return [x for x in d if isinstance(x, dict) and float(x.get("t", 0)) > lim][-40:]
        except Exception:                                         # noqa: BLE001
            return []

    def _mem_save(self):
        try:
            tmp = MEMORIA_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._mem[-40:], ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, MEMORIA_PATH)
        except OSError:
            pass

    def _recientes(self, n: int = 10) -> list:
        lim = time.time() - self._horas() * 3600
        with self._mem_lock:
            return [x for x in self._mem if float(x.get("t", 0)) > lim][-n:]

    def _buscar_dicho(self, evidencia: str, mensaje: str):
        """La entrada de lo que ya comentó sobre esto (o algo casi igual) en las últimas horas, o None."""
        for x in reversed(self._recientes(40)):
            for a, b in ((mensaje, x.get("msg")), (evidencia, x.get("ev"))):
                ta, tb = self._toks(a), self._toks(b)
                if ta and tb and len(ta & tb) / min(len(ta), len(tb)) >= SIMILAR:
                    return x
        return None

    def _reavisar(self, entrada: dict, mensaje: str):
        with self._mem_lock:
            entrada["t"] = time.time()
            entrada["n"] = int(entrada.get("n", 1)) + 1
            entrada["msg"] = str(mensaje)[:300]
            self._mem_save()

    def _recordar(self, evidencia: str, mensaje: str):
        with self._mem_lock:
            self._mem.append(dict(t=time.time(), n=1, ev=str(evidencia)[:200], msg=str(mensaje)[:300]))
            self._mem = self._mem[-40:]
            self._mem_save()

    def _propio(self) -> str:
        """Lo que Orbi tecleó hace poco: así distingue un error SUYO (que él arregla) de un typo de su dueño."""
        try:
            items = self.own_text() or []
        except Exception:                                         # noqa: BLE001
            items = []
        if not items:
            return "Lo que tú escribiste en su PC hace poco: (nada)"
        partes = [f"- en «{(v or 'una ventana')[:50]}»: {t[:400]!r}" for _t, t, v in items[-3:]]
        return "Lo que tú (Orbi) escribiste con el teclado hace poco, TEXTO EXACTO:\n" + "\n".join(partes)
