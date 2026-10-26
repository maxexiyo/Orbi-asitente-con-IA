"""Notificaciones de Windows para Orbi.

Cómo se leen: Windows guarda cada notificación en %LOCALAPPDATA%\\Microsoft\\Windows\\Notifications\\wpndatabase.db
(SQLite). Orbi copia ese archivo (y su -wal) a una carpeta temporal y lo consulta cada pocos segundos. No usa APIs
de Windows que exijan "app empaquetada" ni permisos de administrador. Limitaciones honestas:
  - depende de que tu versión de Windows siga usando ese archivo (Windows 10/11 sí; Microsoft puede cambiarlo);
  - solo ve las notificaciones que Windows muestra (si silenciaste una app en Configuración, no llegan);
  - el texto lo da la app: algunas solo dicen "Nuevo mensaje".

Qué hace con ellas (la parte importante, pensada para todos los casos):
  1. CLASIFICA por app: mensajes / correo / calendario / sistema+seguridad / descargas / otras.
  2. FILTRA: solo avisa de las categorías que dejaste activas (por defecto mensajes, correo, calendario y seguridad).
  3. NO MOLESTA: en pantalla completa (juego, presentación, video) o en tus horas de silencio solo las guarda.
  4. AGRUPA: varias del mismo remitente/app en pocos segundos se dicen como una sola ("3 mensajes de Mamá").
  5. PRIVACIDAD: por defecto dice quién escribió y en qué app, pero NO lee el contenido en voz alta.
     Si le pides "¿qué decía?", entonces sí lo lee (tool leer_notificaciones).
  6. VIP: nombres/palabras que siempre avisan aunque la categoría esté apagada (ej. "mamá").
  7. LÍMITE: máximo N avisos por minuto; el resto queda en la lista.
Todo se ajusta en config.json (ver README, sección Notificaciones).
"""
import datetime, html, os, re, shutil, sqlite3, tempfile, threading, time
from collections import deque
from pathlib import Path

DB_REL = Path("Microsoft") / "Windows" / "Notifications" / "wpndatabase.db"

CATEGORIES = {
    "mensajes": ("whatsapp", "telegram", "discord", "slack", "teams", "messenger", "signal", "instagram", "skype",
                 "line", "viber", "wechat", "messages", "sms", "phonelink", "yourphone", "linkedin"),
    "correo": ("outlook", "mail", "gmail", "thunderbird", "proton", "correo"),
    "calendario": ("calendar", "calendario", "reminder", "recordatorio", "alarm", "alarma", "clock", "todo", "tasks"),
    "seguridad": ("defender", "securityhealth", "security", "seguridad", "windowsupdate", "update", "actualiz", "battery",
                  "bateria", "batería", "firewall"),
    "descargas": ("download", "descarga", "torrent", "steam", "epicgames", "xbox", "store"),
}
DEFAULT_ANNOUNCE = ("mensajes", "correo", "calendario", "seguridad")


def default_db_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / DB_REL


def classify(app: str) -> str:
    a = app.lower()
    for cat, words in CATEGORIES.items():
        if any(w in a for w in words):
            return cat
    return "otras"


# fragmentos del id de la app (en minúsculas) -> nombre que Orbi dice en voz alta. Los de correo traen ids largos y raros:
#   Outlook nuevo   Microsoft.OutlookForWindows_8wekyb3d8bbwe!Microsoft.OutlookForWindows
#   Outlook clásico Microsoft.Office.OUTLOOK.EXE.15
#   Correo (viejo)  microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.mail
APP_NAMES = (("outlook", "Outlook"), ("windowscommunicationsapps", "Correo de Windows"), ("windowslive.mail", "Correo de Windows"),
             ("windowslive.calendar", "Calendario de Windows"))


def pretty_app(app_id: str) -> str:
    """'5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App' -> 'WhatsApp'."""
    low = (app_id or "").lower()
    for frag, nombre in APP_NAMES:
        if frag in low:
            return nombre
    base = re.split(r"[!_]", app_id)[0]
    base = base.split(".")[-1] if "." in base else base
    base = re.sub(r"(?i)desktop|app$", "", base).strip(" .-") or app_id
    names = {"microsoftteams": "Teams", "msteams": "Teams", "microsoftoutlook": "Outlook", "outlook": "Outlook",
             "windowsdefender": "Seguridad de Windows", "securityhealth": "Seguridad de Windows"}
    return names.get(base.lower(), base)


def parse_payload(xml: str) -> tuple:
    """(título, texto) de un payload de toast."""
    texts = [html.unescape(t).strip() for t in re.findall(r"<text[^>]*>(.*?)</text>", xml or "", flags=re.S | re.I)]
    texts = [t for t in texts if t]
    if not texts:
        return "", ""
    return texts[0], " ".join(texts[1:])


_EMAIL = r"[\w.+-]+(?:@|%40)[\w-]+(?:\.[\w-]+)+"


def parse_cuenta(xml: str) -> str:
    """Correo de la CUENTA a la que llegó un toast de correo (mejor esfuerzo: depende de lo que ponga la app).
    Busca primero en el texto de «atribución» (Outlook suele poner ahí la cuenta), luego en un texto que sea solo un correo y
    al final en los argumentos de lanzamiento. Devuelve '' si no se ve. Nunca toma un correo suelto del cuerpo del mensaje."""
    xml = xml or ""
    for m in re.finditer(r"<text[^>]*placement=[\"']attribution[\"'][^>]*>(.*?)</text>", xml, flags=re.S | re.I):
        e = re.search(_EMAIL, html.unescape(m.group(1)))
        if e:
            return e.group(0).replace("%40", "@").lower()
    for m in re.finditer(r"<text[^>]*>(.*?)</text>", xml, flags=re.S | re.I):
        t = html.unescape(m.group(1)).strip()
        if re.fullmatch(_EMAIL, t):
            return t.replace("%40", "@").lower()
    for m in re.finditer(r"(?:launch|arguments)=[\"']([^\"']*)[\"']", xml, flags=re.I):
        e = re.search(_EMAIL, html.unescape(m.group(1)))
        if e:
            return e.group(0).replace("%40", "@").lower()
    return ""


class NotificationWatcher:
    """Lee notificaciones nuevas y las manda a `on_notification(dict)`. `recent()` devuelve las últimas guardadas."""

    def __init__(self, cfg: dict, on_notification, db_path=None, poll: float = 1.5):
        self.cfg = cfg or {}
        self.on_notification = on_notification
        self.db_path = Path(db_path) if db_path else default_db_path()
        self.poll = poll
        self._items = deque(maxlen=60)
        self._last_id = None
        self._stop = threading.Event()
        self._thread = None
        self.last_error = ""

    # ------------------------------------------------------------ control
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._last_id = None                      # al reactivar, lo que llegó mientras estaba apagado no se anuncia
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def recent(self, n: int = 10, app: str = "") -> list:
        items = list(self._items)[::-1]
        if app:
            items = [i for i in items if app.lower() in i["app"].lower()]
        return items[:n]

    def clear(self):
        self._items.clear()

    # ------------------------------------------------------------ lectura
    def _snapshot(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="orbi_wpn_"))
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(self.db_path) + suffix)
            if src.exists():
                try:
                    shutil.copy2(src, tmp / (self.db_path.name + suffix))
                except OSError:
                    if suffix == "":
                        raise
        return tmp / self.db_path.name

    def read_new(self, first_run: bool = False) -> list:
        """Devuelve las notificaciones con Id mayor al último visto (sin tocar el archivo original)."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"No encontré {self.db_path}")
        snap = self._snapshot()
        try:
            con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT n.Id, n.Payload, n.ArrivalTime, h.PrimaryId FROM Notification n "
                    "LEFT JOIN NotificationHandler h ON n.HandlerId = h.RecordId "
                    "WHERE n.Type = 'toast' ORDER BY n.Id").fetchall()
            finally:
                con.close()
        finally:
            shutil.rmtree(snap.parent, ignore_errors=True)
        if not rows:
            return []
        if self._last_id is None:                      # primera lectura: solo marca dónde vamos (no avisa lo viejo)
            self._last_id = rows[-1][0]
            return [] if first_run else []
        out = []
        for rid, payload, arrival, app_id in rows:
            if rid <= self._last_id:
                continue
            self._last_id = rid
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", "replace")
            title, text = parse_payload(payload or "")
            app = pretty_app(app_id or "desconocida")
            cat = classify((app_id or "") + " " + app)
            out.append(dict(id=rid, app=app, titulo=title, texto=text, categoria=cat,
                            cuenta=parse_cuenta(payload or "") if cat == "correo" else "",
                            hora=datetime.datetime.now().strftime("%H:%M")))
        return out

    def _loop(self):
        first = True
        while not self._stop.wait(self.poll):
            try:
                for n in self.read_new(first_run=first):
                    self._items.append(n)
                    self.on_notification(n)
                first = False
                self.last_error = ""
            except Exception as e:                         # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                if msg != self.last_error:
                    self.last_error = msg
                    print("[notificaciones]", msg)

    def diagnose(self) -> str:
        """Texto de diagnóstico para pegarlo si algo no funciona."""
        lines = [f"Ruta: {self.db_path}", f"Existe: {self.db_path.exists()}"]
        try:
            snap = self._snapshot()
            con = sqlite3.connect(f"file:{snap}?mode=ro", uri=True)
            n = con.execute("SELECT COUNT(*) FROM Notification").fetchone()[0]
            hs = con.execute("SELECT COUNT(*) FROM NotificationHandler").fetchone()[0]
            lines.append(f"Notificaciones en la base: {n} · apps: {hs}")
            try:
                ids = [r[0] for r in con.execute("SELECT PrimaryId FROM NotificationHandler").fetchall() if r[0]]
                correo = [i for i in ids if classify(i) == "correo"]
                lines.append("Apps de correo con notificaciones registradas: " + (", ".join(f"{i} -> «{pretty_app(i)}»" for i in correo) or
                             "ninguna (abre Outlook y revisa Configuración > Sistema > Notificaciones)"))
            except sqlite3.Error:
                pass
            con.close(); shutil.rmtree(snap.parent, ignore_errors=True)
        except Exception as e:                             # noqa: BLE001
            lines.append(f"Error al leer: {type(e).__name__}: {e}")
        return "\n".join(lines)


class Announcer:
    """Decide QUÉ notificaciones se dicen en voz alta y CÓMO (filtros, silencio, agrupación, privacidad, VIP)."""

    def __init__(self, cfg: dict, speak, is_busy=lambda: False, is_fullscreen=lambda: False, now=time.time,
                 get_rules=lambda: [], my_names=lambda: []):
        c = cfg or {}
        self.categories = tuple(c.get("categorias", DEFAULT_ANNOUNCE))
        self.vip = [v.lower() for v in c.get("vip", [])]
        self.mute_apps = [a.lower() for a in c.get("silenciar_apps", [])]
        self.quiet = c.get("horas_silencio", ["23:00", "07:00"])
        self.read_content = bool(c.get("leer_contenido", False))
        self.max_per_min = int(c.get("max_por_minuto", 3))
        self.group_window = float(c.get("agrupar_segundos", 2.5))      # antes 8 s: avisaba cuando ya la habías leído
        # {"tu@hotmail.com": "tu correo personal", "tu@ceti.mx": "el de la escuela"}: cómo los dice Orbi en voz alta
        self.cuentas = {str(k).lower(): str(v) for k, v in (c.get("cuentas_correo") or {}).items()}
        self.get_rules, self.my_names = get_rules, my_names
        self.speak, self.is_busy, self.is_fullscreen, self.now = speak, is_busy, is_fullscreen, now
        self._pending = []                   # notificaciones esperando para agruparse
        self._timer = None
        self._spoken = deque(maxlen=20)
        self._lock = threading.Lock()

    def _in_quiet_hours(self) -> bool:
        try:
            a, b = self.quiet
            t = datetime.datetime.now().strftime("%H:%M")
            return (a <= t or t < b) if a > b else (a <= t < b)
        except Exception:
            return False

    def _is_vip(self, n: dict) -> bool:
        blob = f"{n['titulo']} {n['texto']} {n['app']}".lower()
        return any(v in blob for v in self.vip)

    def _rule_verdict(self, n: dict):
        """Aplica las reglas que el dueño dictó (ignorar / bajar importancia / solo si lo mencionan). None = sin regla."""
        blob = f"{n['app']} {n['titulo']}".lower()
        for r in self.get_rules() or []:
            o = r.get("origen", "")
            if not o or o not in blob:
                continue
            modo = r.get("modo")
            if modo == "ignorar":
                return "ignorada"
            if modo == "baja":
                return "guardada"
            if modo == "solo_menciones":
                texto = f"{n['texto']} {n['titulo']}".lower()
                claves = [w for w in (r.get("palabras") or []) if w] or [x.lower() for x in self.my_names() if x]
                if any(k in texto for k in claves) or "@" in n["texto"] and any(k in texto for k in claves):
                    return None                                    # te mencionaron: pasa los filtros normales
                return "guardada"
        return None

    def handle(self, n: dict) -> str:
        """Devuelve 'avisada' | 'en_cola' | 'ignorada' | 'guardada' (para pruebas y para el log)."""
        v = self._rule_verdict(n)
        if v:
            return v
        if any(a in n["app"].lower() for a in self.mute_apps):
            return "ignorada"
        vip = self._is_vip(n)
        if not vip and n["categoria"] not in self.categories:
            return "guardada"
        if (self._in_quiet_hours() or self.is_fullscreen()) and not vip:
            return "guardada"
        with self._lock:
            self._pending.append(n)
            if self._timer is None:
                self._timer = threading.Timer(self.group_window, self._flush)
                self._timer.daemon = True
                self._timer.start()
        return "en_cola"

    def _flush(self):
        with self._lock:
            batch, self._pending, self._timer = self._pending, [], None
        if not batch:
            return
        if self.is_busy():                                   # estás hablando con Orbi: espera un poco
            with self._lock:
                self._pending = batch + self._pending
                self._timer = threading.Timer(4.0, self._flush); self._timer.daemon = True; self._timer.start()
            return
        t = self.now()
        recent = [x for x in self._spoken if t - x < 60]
        if len(recent) >= self.max_per_min:
            return                                           # límite: quedan en la lista, se pueden consultar
        self._spoken.append(t)
        texto = self.summarize(batch)
        try:
            self.speak(texto, batch)                         # el lote va aparte para que la mini ventana pueda hacerlo clicable
        except TypeError:                                    # speak antiguo de un solo argumento
            self.speak(texto)

    def summarize(self, batch: list) -> str:
        groups = {}
        for n in batch:
            key = (n["app"], n["titulo"] if n["categoria"] == "mensajes" else (n["app"] + "|" + n.get("cuenta", "")))
            groups.setdefault(key, []).append(n)
        parts = []
        for (app, who), items in groups.items():
            k = len(items)
            if items[0]["categoria"] == "mensajes":
                quien = items[0]["titulo"] or "alguien"
                parts.append(f"{quien} te escribió por {app}" if k == 1 else f"{k} mensajes de {quien} en {app}")
                if self.read_content and k == 1 and items[0]["texto"]:
                    parts[-1] += f": {items[0]['texto'][:140]}"
            elif items[0]["categoria"] == "correo":
                cta = items[0].get("cuenta", "")
                donde = f"a {self.cuentas.get(cta, cta)}" if cta else f"en {app}"         # «a tu correo personal» / «a tu@hotmail.com»
                parts.append(f"{'llegó un correo' if k == 1 else f'llegaron {k} correos'} {donde}"
                             + (f" de {items[0]['titulo']}" if items[0]["titulo"] and k == 1 else ""))
                if self.read_content and k == 1 and items[0]["texto"]:
                    parts[-1] += f": {items[0]['texto'][:140]}"
            elif items[0]["categoria"] == "calendario":
                parts.append(f"recordatorio de {app}: {items[0]['titulo'] or items[0]['texto']}"[:160])
            else:
                parts.append(f"{app}: {items[0]['titulo'] or items[0]['texto']}"[:140])
        return "; ".join(parts)
