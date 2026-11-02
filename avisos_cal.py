"""Avisos de eventos del calendario (#46): Orbi te avisa ANTES de tus eventos, las veces que tú quieras.

Ejemplos de avisos: al iniciar (0), 15 min antes, 1 hora antes, 1 día antes. Puedes tener varios a la vez.

Se configura de tres formas (todas guardan lo mismo):
  · Ajustes → Calendarios → «Avisos de eventos»
  · por voz o texto: «avísame de mis eventos 15 minutos antes y 1 día antes» (herramienta `avisos_calendario`)
  · config.json / orbi_config_ventana.json:  "avisos_calendario": {"activo": true, "antes_min": [1440, 15, 0], "voz": true}

Cómo funciona:
  · Cada ~10 min baja los eventos de los próximos días (tus calendarios ICS y/o tu cuenta de Google) y cada 20 s revisa si toca avisar.
  · Cada aviso se dice UNA sola vez por evento (queda anotado en orbi_avisos_cal.json, así que reiniciar Orbi no repite nada).
  · Si Orbi estaba cerrada y te perdiste un aviso, al abrirla te dice UNA vez cuánto falta de verdad («en 10 min»). Un evento que ya
    empezó hace más de 5 minutos no se avisa.
  · Los eventos de todo el día no se avisan (no tienen hora).
  · En tu horario de silencio (Ajustes → Notificaciones) el aviso sale solo en la burbuja y la mini ventana, sin voz.
  · El título del evento es solo un dato que se muestra: nunca se obedece como instrucción.
"""
import json, os, re, threading, time
from datetime import datetime, timedelta
from pathlib import Path

DEFAULTS = {"activo": True, "antes_min": [15], "voz": True}
MAX_AVISOS, MAX_MIN = 8, 7 * 1440          # hasta 8 avisos por evento, hasta 7 días antes
GRACIA_S = 300                              # un evento que empezó hace más de 5 min ya no se avisa
REFRESCAR_S = 600                           # cada cuánto se vuelven a pedir los eventos al calendario
PRESETS = [(0, "Al iniciar"), (5, "5 min antes"), (10, "10 min antes"), (15, "15 min antes"), (30, "30 min antes"),
           (60, "1 hora antes"), (120, "2 horas antes"), (1440, "1 día antes")]

_AL_INICIAR = re.compile(r"\b(al iniciar|al empezar|al comenzar|cuando (empiece|inicie|comience)|a la hora|en punto|ahora|inicio)\b", re.I)
_NUM = re.compile(r"(\d+(?:[.,]\d+)?|media|un|una|dos|tres|cuatro|cinco)\s*(minutos?|mins?|min|m|horas?|hrs?|h|d[ií]as?|d|semanas?)\b", re.I)
_PALABRA = {"media": 0.5, "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}


def parse_antes(txt) -> int | None:
    """'15 minutos' -> 15 · '1 hora' -> 60 · '1 día' -> 1440 · 'al iniciar' -> 0 · número suelto = minutos. None si no se entiende."""
    if isinstance(txt, (int, float)):
        v = int(txt)
        return v if 0 <= v <= MAX_MIN else None
    t = str(txt or "").strip().lower()
    if not t:
        return None
    if re.fullmatch(r"\d+", t):
        v = int(t)
        return v if 0 <= v <= MAX_MIN else None
    if _AL_INICIAR.search(t) and not _NUM.search(t):
        return 0
    m = _NUM.search(t)
    if not m:
        return None
    n = m.group(1).lower()
    n = _PALABRA.get(n) if n in _PALABRA else float(n.replace(",", "."))
    u = m.group(2).lower()
    mult = 1 if u.startswith("m") else 60 if u.startswith("h") else 1440 if u.startswith("d") else 10080
    v = int(round(n * mult))
    return v if 0 <= v <= MAX_MIN else None


def parse_lista(txt) -> list:
    """'al iniciar, 15 minutos y 1 día' (o una lista) -> [1440, 15, 0] sin repetidos, de mayor a menor."""
    trozos = txt if isinstance(txt, (list, tuple)) else re.split(r"[,;/]|\s+y\s+|\s+e\s+", str(txt or ""))
    out = []
    for t in trozos:
        v = parse_antes(t)
        if v is not None and v not in out:
            out.append(v)
    return sorted(out, reverse=True)[:MAX_AVISOS]


def etiqueta(m: int) -> str:
    if m == 0:
        return "al iniciar"
    if m % 1440 == 0:
        d = m // 1440
        return "1 día antes" if d == 1 else f"{d} días antes"
    if m % 60 == 0:
        h = m // 60
        return "1 hora antes" if h == 1 else f"{h} horas antes"
    return f"{m} min antes"


def describir(o: dict) -> str:
    if not o.get("activo"):
        return "Los avisos de eventos están apagados."
    lista = ", ".join(etiqueta(m) for m in o["antes_min"]) or "(ninguno)"
    return f"Te aviso de tus eventos: {lista}" + (" (con voz)." if o.get("voz") else " (solo en pantalla, sin voz).")


def cuando_txt(inicio: datetime, ahora: datetime) -> str:
    """Cuánto falta, en palabras: «ya empieza», «en 15 min», «en 2 h», «mañana a las 10:00»."""
    seg = (inicio - ahora).total_seconds()
    if seg < 60:
        return "ya empieza" if seg > -GRACIA_S else "empezó hace un momento"
    m = int(round(seg / 60))
    if m < 90:
        return f"en {m} min"
    if inicio.date() == ahora.date():
        return f"hoy a las {inicio:%H:%M}" if m >= 360 else f"en {m // 60} h" + (f" {m % 60} min" if m % 60 else "")
    if inicio.date() == (ahora + timedelta(days=1)).date():
        return f"mañana a las {inicio:%H:%M}"
    return f"el {inicio.day}/{inicio.month} a las {inicio:%H:%M}"


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


class AvisosCalendario:
    """`agenda.eventos(dias)` -> [{inicio, todo_el_dia, titulo, lugar, calendario, id}]. `on_aviso(items, voz)` recibe lo que hay que decir."""

    def __init__(self, agenda, on_aviso, get_cfg, enabled=lambda: True, state_path: Path | None = None, ovr_path: Path | None = None):
        self.agenda, self.on_aviso, self.get_cfg, self.enabled = agenda, on_aviso, get_cfg, enabled
        self._path, self._ovr = state_path, ovr_path
        self._stop = threading.Event()
        self._thread = None
        self._evs, self._t_evs, self._dias_evs = [], 0.0, 0.0
        self._hechos = self._load()                      # {"<id o título>|<inicio>|<min>": inicio_epoch}
        self.last_error = ""

    # ------------------------------------------------------------ opciones
    def opciones(self) -> dict:
        o = self.get_cfg().get("avisos_calendario")
        o = o if isinstance(o, dict) else {}
        antes = o.get("antes_min", DEFAULTS["antes_min"])
        antes = parse_lista(antes if isinstance(antes, (list, tuple)) else [antes])
        return dict(activo=bool(o.get("activo", DEFAULTS["activo"])), antes_min=antes, voz=bool(o.get("voz", DEFAULTS["voz"])))

    def configurar(self, activo=None, antes_min=None, voz=None) -> dict:
        """Cambia las opciones (solo lo que se pase), las aplica YA en la configuración viva y las guarda en orbi_config_ventana.json."""
        o = self.opciones()
        if activo is not None:
            o["activo"] = bool(activo)
        if antes_min is not None:
            o["antes_min"] = parse_lista(antes_min)
        if voz is not None:
            o["voz"] = bool(voz)
        cfg = self.get_cfg()
        cfg["avisos_calendario"] = {**(cfg.get("avisos_calendario") if isinstance(cfg.get("avisos_calendario"), dict) else {}), **o}
        if self._ovr:
            try:
                try:
                    previo = json.loads(self._ovr.read_text(encoding="utf-8"))
                except Exception:                         # noqa: BLE001
                    previo = {}
                previo["avisos_calendario"] = o
                tmp = self._ovr.with_suffix(".tmp")
                tmp.write_text(json.dumps(previo, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, self._ovr)
            except OSError as e:
                print(f"[calendario] no pude guardar los avisos: {e}")
        self._t_evs = 0.0                                 # que la próxima revisión baje los eventos de nuevo
        return o

    # ------------------------------------------------------------ estado (qué ya se avisó)
    def _load(self) -> dict:
        try:
            d = json.loads(self._path.read_text(encoding="utf-8")) if self._path else {}
            return d if isinstance(d, dict) else {}
        except Exception:                                 # noqa: BLE001
            return {}

    def _save(self):
        try:
            if self._path:
                corte = time.time() - 86400                # lo de eventos que ya pasaron hace más de un día se olvida
                self._hechos = {k: v for k, v in self._hechos.items() if v >= corte}
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._hechos), encoding="utf-8")
                os.replace(tmp, self._path)
        except OSError:
            pass

    # ------------------------------------------------------------ ciclo
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(20.0):
            try:
                self.revisar()
            except Exception as e:                        # noqa: BLE001
                msg = f"{type(e).__name__}: {str(e)[:100]}"
                if msg != self.last_error:
                    self.last_error = msg
                    print(f"[calendario] avisos: {msg}")

    def _eventos(self, o: dict, ahora: datetime) -> list:
        dias = min(31.0, max(1.0, max(o["antes_min"] or [0]) / 1440 + 1))
        if time.time() - self._t_evs < REFRESCAR_S and dias <= self._dias_evs:
            return self._evs
        evs = self.agenda.eventos(dias)
        self._evs, self._t_evs, self._dias_evs = evs, time.time(), dias
        return evs

    def revisar(self, ahora: datetime | None = None) -> list:
        """Un ciclo: decide qué avisar. Devuelve los items avisados (para pruebas)."""
        o = self.opciones()
        if not o["activo"] or not o["antes_min"] or not self.enabled():
            return []
        ahora = ahora or datetime.now()
        avisar, cambios = [], False
        for e in self._eventos(o, ahora):
            if e.get("todo_el_dia"):
                continue
            ini = e["inicio"]
            base = f"{e.get('id') or e['titulo']}|{ini:%Y-%m-%d %H:%M}"
            vencidos = [m for m in o["antes_min"] if ini - timedelta(minutes=m) <= ahora]
            pend = [m for m in vencidos if f"{base}|{m}" not in self._hechos]
            if not pend:
                continue
            epoch = ini.timestamp()
            for m in pend:                                 # todos los avisos que ya tocaban quedan hechos: se dice UNA sola vez
                self._hechos[f"{base}|{m}"] = epoch
            cambios = True
            if (ahora - ini).total_seconds() > GRACIA_S:   # ya empezó hace rato (p. ej. abriste Orbi tarde): no avisar
                continue
            avisar.append(dict(titulo=str(e["titulo"])[:90], lugar=str(e.get("lugar", ""))[:60], cuando=cuando_txt(ini, ahora),
                               inicio=ini.isoformat(timespec="minutes"), calendario=str(e.get("calendario", ""))))
        if cambios:
            self._save()
        if avisar:
            avisar.sort(key=lambda x: x["inicio"])
            voz = o["voz"] and not _en_silencio(self.get_cfg())
            self.on_aviso(avisar, voz)
        return avisar
