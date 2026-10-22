"""Alarmas y recordatorios de Orbi: se guardan en orbi_alarmas.json (sobreviven reinicios) y Orbi SUENA como alarma.

  - alarma:       a una hora (puede repetirse). Suena (pitidos) hasta que digas «ya» / la apagues, o se pospone.
  - recordatorio: a una hora o dentro de X minutos. Avisa por voz/burbuja, sin sonar.
La hora se calcula AQUÍ con el reloj de la PC (el modelo ya no hace cuentas ni se confunde con las 12 h).
"""
import json, os, re, threading, time, uuid
from datetime import datetime, timedelta
from pathlib import Path

from paths import APP_DIR
PATH = APP_DIR / "orbi_alarmas.json"
DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "sábado": 5,
        "domingo": 6}


def parse_hora(txt: str, ahora: datetime | None = None):
    """'22:20', '10:20 pm', '6 de la tarde', '9am', '21' -> (h, m) o None."""
    t = str(txt).lower().strip().replace(".", "")
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a m|p m|de la mañana|de la manana|de la tarde|de la noche|de la madrugada)?", t)
    if not m:
        return None
    h, mi, suf = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "")
    if mi > 59 or h > 24:
        return None
    if suf in ("pm", "p m", "de la tarde", "de la noche") and h < 12:
        h += 12
    elif suf in ("am", "a m", "de la mañana", "de la manana", "de la madrugada") and h == 12:
        h = 0
    elif not suf and h <= 12 and ahora is not None:          # sin am/pm: la próxima vez que dé esa hora
        cand = [(hh % 24) for hh in (h, h + 12) if hh < 24 or hh == 24]
        best = None
        for hh in cand:
            dt = ahora.replace(hour=hh, minute=mi, second=0, microsecond=0)
            if dt <= ahora:
                dt += timedelta(days=1)
            if best is None or dt < best:
                best = dt
        return best.hour, best.minute
    return h % 24, mi


_DIAS_N = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}


class Alarmas:
    def __init__(self, on_fire):
        self.on_fire = on_fire                 # on_fire(item)  (se llama desde el hilo del reloj)
        self.items = self._load()
        self._lock = threading.Lock()
        self.ringing = None                    # item que está sonando
        self._ring_stop = threading.Event()

    # ------------------------------------------------------------ guardado
    def _load(self):
        try:
            return json.loads(PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self):
        try:
            tmp = PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, PATH)
        except Exception:
            pass

    # ------------------------------------------------------------ crear / listar / quitar
    def add(self, kind: str, when: datetime, texto: str, repetir: str = "no") -> dict:
        it = dict(id=uuid.uuid4().hex[:6], kind=kind, when=when.isoformat(timespec="seconds"),
                  texto=(texto or "").strip()[:160] or ("Alarma" if kind == "alarma" else "Recordatorio"),
                  repetir=repetir if repetir in ("no", "diaria", "laborales") else "no")
        with self._lock:
            self.items.append(it); self._save()
        return it

    def set_by_time(self, kind: str, hora: str = "", minutos=None, texto: str = "", repetir: str = "no", fecha: str = ""):
        """-> (item|None, mensaje de error)"""
        ahora = datetime.now()
        if minutos not in (None, ""):
            try:
                when = ahora + timedelta(minutes=max(0.5, float(minutos)))
            except (TypeError, ValueError):
                return None, "minutos inválidos"
        else:
            hm = parse_hora(hora, ahora)
            if not hm:
                return None, "No entendí la hora. Dime algo como 22:20 o 10:20 pm."
            when = ahora.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
            f = str(fecha or "").lower().strip().replace("á", "a").replace("é", "e")
            iso = re.search(r"\d{4}-\d{2}-\d{2}", f)
            if iso:
                d = datetime.fromisoformat(iso.group(0))
                when = when.replace(year=d.year, month=d.month, day=d.day)
            elif f == "manana":
                when += timedelta(days=1)
            elif f in _DIAS_N:
                when += timedelta(days=(_DIAS_N[f] - ahora.weekday()) % 7)
                if when <= ahora:
                    when += timedelta(days=7)
            elif when <= ahora:                       # solo hora: la próxima vez que dé esa hora
                when += timedelta(days=1)
            if when <= ahora:
                return None, "Esa fecha y hora ya pasó."
        return self.add(kind, when, texto, repetir), ""

    def listing(self) -> list:
        with self._lock:
            return sorted(self.items, key=lambda i: i["when"])

    def remove(self, quien: str) -> int:
        q = (quien or "").lower().strip()
        with self._lock:
            keep = [i for i in self.items if not (q in ("todas", "todos", "") or q == i["id"] or q in i["texto"].lower()
                                                  or q in i["when"][11:16])]
            n = len(self.items) - len(keep)
            self.items = keep; self._save()
        return n

    # ------------------------------------------------------------ reloj
    def tick(self):
        """Llamar cada ~1 s. Dispara lo vencido (y si Orbi estuvo apagada <10 min, lo avisa igual)."""
        now = datetime.now()
        due = []
        with self._lock:
            for it in list(self.items):
                when = datetime.fromisoformat(it["when"])
                if when <= now:
                    due.append(it)
                    rep = it.get("repetir", "no")
                    if rep == "no":
                        self.items.remove(it)
                    else:
                        nxt = when + timedelta(days=1)
                        while nxt <= now or (rep == "laborales" and nxt.weekday() >= 5):
                            nxt += timedelta(days=1)
                        it["when"] = nxt.isoformat(timespec="seconds")
            if due:
                self._save()
        for it in due:
            try:
                self.on_fire(it)
            except Exception as e:
                print("[alarmas] error:", e)

    # ------------------------------------------------------------ sonar
    def ring(self, it: dict, max_seconds: float = 90.0):
        self.stop_ring()
        self.ringing = it
        self._ring_stop.clear()

        def run():
            t0 = time.time()
            try:
                import winsound
                beep = lambda f, d: winsound.Beep(f, d)
            except Exception:
                beep = lambda f, d: time.sleep(d / 1000)
            while not self._ring_stop.is_set() and time.time() - t0 < max_seconds:
                for f, d in ((880, 180), (1175, 180), (880, 180), (1175, 180)):
                    if self._ring_stop.is_set():
                        break
                    beep(f, d)
                self._ring_stop.wait(0.9)
            self.ringing = None
        threading.Thread(target=run, daemon=True).start()

    def stop_ring(self) -> bool:
        was = self.ringing is not None
        self._ring_stop.set()
        return was

    def snooze(self, minutos: float = 10) -> dict | None:
        it = self.ringing
        self.stop_ring()
        if not it:
            return None
        return self.add(it["kind"], datetime.now() + timedelta(minutes=max(1, minutos)), it["texto"])


