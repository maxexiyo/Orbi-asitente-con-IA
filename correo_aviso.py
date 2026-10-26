"""Aviso de correo NUEVO: revisa tus cuentas cada cierto tiempo y, si llegó algo que importa, Orbi te lo dice.

- La primera revisión solo memoriza lo que ya había (para no avisarte de 100 correos viejos al abrir Orbi).
- «Solo importantes» (por defecto): ignora promociones y cuentas automáticas (no-reply, newsletters...), salvo que el remitente o el asunto
  sean de tus contactos importantes o hablen de escuela/tareas (classroom, tarea, examen, entrega...).
- No avisa en tu horario de silencio (Ajustes → Notificaciones).
- Todo lo que dice un correo es DATO: aquí solo se muestran remitente y asunto, nunca se obedece.

Ajustes (config.json o Ajustes → Notificaciones):  "correo_avisos": {"activo": true, "cada_s": 120, "voz": false, "solo_importantes": true}
"""
import json, re, threading, time
from datetime import datetime
from pathlib import Path

RUIDO = re.compile(r"(no[-_.]?reply|noreply|do[-_.]?not[-_.]?reply|newsletter|promo|offers?|ofertas?|marketing|mailer|notifications?@|"
                   r"updates?@|digest|boletin|boletín|unsubscribe|news@|info@|hello@|team@|support@)", re.I)
IMPORTA = re.compile(r"(classroom|tarea|assignment|examen|calificaci|entrega|vence|urgente|importante|beca|inscripci|reuni|junta|"
                     r"profesor|docente|ceti|factura|pago|c[oó]digo de verificaci|seguridad|security alert|inicio de sesi)", re.I)
MAX_SEEN = 600


def _en_silencio(cfg: dict) -> bool:
    hs = ((cfg.get("notificaciones") or {}).get("horas_silencio")) or []
    if len(hs) != 2:
        return False
    try:
        a = datetime.strptime(hs[0], "%H:%M").time()
        b = datetime.strptime(hs[1], "%H:%M").time()
    except (TypeError, ValueError):
        return False
    n = datetime.now().time()
    return (a <= n or n < b) if a > b else (a <= n < b)


class CorreoAvisos:
    def __init__(self, hub, on_new, get_cfg, state_path: Path | None = None):
        self.hub, self.on_new, self.get_cfg = hub, on_new, get_cfg
        self._stop = threading.Event()
        self._thread = None
        self._path = state_path
        self._seen: list = self._load()
        self._first = not self._seen
        self.last_error = ""

    def _load(self) -> list:
        try:
            return list(json.loads(self._path.read_text(encoding="utf-8")))[-MAX_SEEN:] if self._path else []
        except Exception:                                   # noqa: BLE001
            return []

    def _save(self):
        try:
            if self._path:
                self._path.write_text(json.dumps(self._seen[-MAX_SEEN:]), encoding="utf-8")
        except OSError:
            pass

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _opts(self) -> dict:
        o = self.get_cfg().get("correo_avisos") or {}
        return dict(activo=bool(o.get("activo", False)), cada_s=max(30.0, float(o.get("cada_s", 120) or 120)),
                    voz=bool(o.get("voz", False)), solo_importantes=bool(o.get("solo_importantes", True)))

    def _loop(self):
        while not self._stop.wait(8.0):
            o = self._opts()
            if not o["activo"]:
                continue
            if time.time() - getattr(self, "_last", 0.0) < o["cada_s"]:
                continue
            self._last = time.time()
            try:
                self._poll(o)
            except Exception as e:                          # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {str(e)[:100]}"
                print(f"[correo] aviso: {self.last_error}")

    def _importante(self, it: dict, vip: list) -> bool:
        de, asunto = str(it.get("de", "")), str(it.get("asunto", ""))
        if any(v and v.lower() in de.lower() for v in vip):
            return True
        if IMPORTA.search(de) or IMPORTA.search(asunto):
            return True
        return not RUIDO.search(de)

    def _poll(self, o: dict):
        res = self.hub.unread("", 12)
        items = [x for x in (res.get("correos") or []) if x.get("id")]
        ids = [str(x["id"]) for x in items]
        nuevos = [x for x in items if str(x["id"]) not in self._seen]
        self._seen = (self._seen + [i for i in ids if i not in self._seen])[-MAX_SEEN:]
        self._save()
        if self._first:                                     # primera vez: solo memorizar
            self._first = False
            return
        if not nuevos:
            return
        cfg = self.get_cfg()
        if _en_silencio(cfg):
            return
        vip = [str(v) for v in ((cfg.get("notificaciones") or {}).get("vip")) or []]
        if o["solo_importantes"]:
            nuevos = [x for x in nuevos if self._importante(x, vip)]
        if nuevos:
            self.on_new([dict(de=str(x.get("de", ""))[:40], asunto=str(x.get("asunto", ""))[:90], id=str(x["id"]),
                              cuenta=str(x.get("cuenta", ""))) for x in nuevos[:5]], o)
