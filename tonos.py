"""Tonos de alarma de Orbi.

Los tonos se SINTETIZAN la primera vez (numpy + wave) y se guardan como .wav en la carpeta `tonos/`; después solo se reproducen.
Si quieres un tono propio, copia cualquier .wav a esa carpeta y aparece solo en el menú («Tono de alarma») con su nombre de archivo.

  names()            -> lista de nombres disponibles (los de Orbi + tus .wav)
  play_loop(name)    -> empieza a sonar en bucle (asíncrono). False si no se pudo (no es Windows, etc.)
  stop()             -> corta el sonido al instante
  preview(name, s)   -> suena `s` segundos y se detiene solo (para probar desde el menú)

Elección guardada: «alarma_tono» en los ajustes del perfil (menú de la bolita) o en config.json.
"""
import math, struct, sys, threading, wave
from pathlib import Path

import numpy as np

DIR = Path(__file__).parent / "tonos"
SR = 22050
DEFAULT = "Campana"
CLASSIC = "Clásico (pitidos)"          # el de siempre: se hace con pitidos de winsound, sin archivo

VOLUME = 1.0                           # volumen de las alarmas (1.0 = normal); lo pone live_orb desde Ajustes -> Audio
_lock = threading.Lock()
_timer = {"t": None}


# ------------------------------------------------------------------ síntesis
def _env(n: int, atk: float = 0.005, dec: float = 3.0) -> np.ndarray:
    t = np.arange(n) / SR
    e = np.exp(-dec * t)
    a = max(1, int(atk * SR))
    e[:a] *= np.linspace(0, 1, a)
    return e


def _tone(f: float, dur: float, partials=((1, 1.0),), dec: float = 3.0, atk: float = 0.005) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    y = sum(a * np.sin(2 * math.pi * f * k * t) for k, a in partials)
    return y * _env(n, atk, dec) / max(1.0, sum(a for _, a in partials))


def _place(buf: np.ndarray, snd: np.ndarray, at: float) -> None:
    i = int(at * SR)
    j = min(len(buf), i + len(snd))
    if i < len(buf):
        buf[i:j] += snd[: j - i]


def _bell(f: float, dur: float = 1.6) -> np.ndarray:
    # parciales inarmónicos con caída distinta = timbre de campana
    return _tone(f, dur, ((1, 1.0), (2.76, 0.5), (5.4, 0.28), (8.93, 0.12)), dec=2.6, atk=0.002)


def _mallet(f: float, dur: float = 0.5) -> np.ndarray:
    return _tone(f, dur, ((1, 1.0), (4.0, 0.35), (10.0, 0.1)), dec=7.0, atk=0.002)


def _soft(f: float, dur: float = 0.9) -> np.ndarray:
    return _tone(f, dur, ((1, 1.0), (2, 0.25), (3, 0.08)), dec=2.2, atk=0.03)


def _build(name: str) -> np.ndarray:
    C5, D5, E5, G5, A5, C6, D6, E6, G6 = 523.25, 587.33, 659.25, 783.99, 880.0, 1046.5, 1174.7, 1318.5, 1568.0
    if name == "Campana":                                   # tres campanadas que se apagan; ~3 s por ciclo
        b = np.zeros(int(3.2 * SR))
        for k, f in enumerate((C6, E6, G6, E6)):
            _place(b, _bell(f), 0.0 + k * 0.55)
        return b
    if name == "Arpegio suave":                             # sube C-E-G-C y se queda sonando; amable para despertar
        b = np.zeros(int(3.4 * SR))
        for k, f in enumerate((C5, E5, G5, C6, E6)):
            _place(b, _soft(f, 1.2) * 0.9, k * 0.32)
        return b
    if name == "Marimba":                                   # melodía rápida de pentatónica
        b = np.zeros(int(2.8 * SR))
        seq = (C6, D6, G6, E6, D6, C6, G5, C6)
        for k, f in enumerate(seq):
            _place(b, _mallet(f), k * 0.22)
        return b
    if name == "Digital":                                   # trinos agudos tipo reloj digital
        b = np.zeros(int(2.0 * SR))
        for rep in range(2):
            for k in range(4):
                _place(b, _tone(1760.0, 0.07, ((1, 1.0), (3, 0.2)), dec=12.0, atk=0.001) * 0.8, rep * 0.9 + k * 0.11)
        return b
    if name == "Amanecer":                                  # acorde que va creciendo y respira; el más tranquilo
        n = int(4.5 * SR)
        t = np.arange(n) / SR
        y = sum(np.sin(2 * math.pi * f * t) * a for f, a in ((261.6, 1.0), (329.6, 0.8), (392.0, 0.8), (523.25, 0.6)))
        y = y / 3.2
        swell = (np.sin(math.pi * t / t[-1]) ** 2) * (0.75 + 0.25 * np.sin(2 * math.pi * 1.2 * t))
        return y * swell
    if name == "Jingle alegre":                             # motivo corto y feliz
        b = np.zeros(int(3.0 * SR))
        notes = ((G5, 0.0), (G5, 0.18), (A5, 0.36), (G5, 0.6), (C6, 0.84), (E6, 1.2), (C6, 1.55), (G5, 1.8))
        for f, at in notes:
            _place(b, _tone(f, 0.45, ((1, 1.0), (2, 0.4), (3, 0.15)), dec=4.5, atk=0.004), at)
        return b
    raise KeyError(name)


BUILTIN = ("Campana", "Arpegio suave", "Marimba", "Digital", "Amanecer", "Jingle alegre")


def _write(name: str, path: Path) -> None:
    y = _build(name)
    peak = float(np.max(np.abs(y))) or 1.0
    y = y / peak * 0.85                                     # normalizado, sin saturar
    pcm = (y * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(pcm)


def _path(name: str) -> Path:
    return DIR / f"{name}.wav"


def ensure(name: str) -> Path | None:
    """Ruta del .wav de ese tono (lo genera si es de Orbi y aún no existe). None si no existe ese tono."""
    p = _path(name)
    try:
        DIR.mkdir(exist_ok=True)
        if name in BUILTIN and not p.exists():
            _write(name, p)
    except Exception as e:                                  # noqa: BLE001
        print(f"[tonos] no pude crear «{name}»: {e}")
        return None
    return p if p.exists() else None


def names() -> list[str]:
    """Primero el clásico, luego los de Orbi, al final tus .wav propios."""
    out = [CLASSIC, *BUILTIN]
    try:
        if DIR.exists():
            for f in sorted(DIR.glob("*.wav")):
                if f.stem not in out:
                    out.append(f.stem)
    except Exception:                                       # noqa: BLE001
        pass
    return out


def resolve(name: str | None) -> str:
    """Nombre válido (sin importar mayúsculas/acentos); si no existe, el predeterminado."""
    if not name:
        return DEFAULT
    low = str(name).lower().strip()
    for n in names():
        if n.lower() == low or low in n.lower():
            return n
    return DEFAULT


# ------------------------------------------------------------------ reproducción
def _winsound():
    if sys.platform != "win32":
        return None
    try:
        import winsound
        return winsound
    except Exception:                                       # noqa: BLE001
        return None


def play_loop(name: str) -> bool:
    """Suena en bucle hasta stop(). False = usa el respaldo de pitidos (clásico o sin soporte de audio)."""
    ws = _winsound()
    if ws is None or name == CLASSIC:
        return False
    p = ensure(name)
    if p is None:
        return False
    try:
        with _lock:
            ws.PlaySound(str(_con_volumen(p)), ws.SND_FILENAME | ws.SND_ASYNC | ws.SND_LOOP)
        return True
    except Exception as e:                                  # noqa: BLE001
        print(f"[tonos] no pude reproducir «{name}»: {e}")
        return False


def _con_volumen(p: Path) -> Path:
    """Copia del .wav con el volumen aplicado (winsound no tiene control de volumen). Se guarda en tonos/_vol/ y se reutiliza."""
    v = round(float(VOLUME), 2)
    if abs(v - 1.0) < 0.02:
        return p
    try:
        q = DIR / "_vol" / f"{p.stem}_{int(v * 100)}.wav"
        if not q.exists() or q.stat().st_mtime < p.stat().st_mtime:
            q.parent.mkdir(exist_ok=True)
            with wave.open(str(p), "rb") as r:
                params, frames = r.getparams(), r.readframes(r.getnframes())
            if params.sampwidth == 2:
                a = np.frombuffer(frames, dtype="<i2").astype(np.float32) * v
                frames = np.clip(a, -32768, 32767).astype("<i2").tobytes()
            with wave.open(str(q), "wb") as w:
                w.setparams(params); w.writeframes(frames)
        return q
    except Exception as e:                                  # noqa: BLE001
        print(f"[tonos] no pude ajustar el volumen: {e}")
        return p


def stop() -> None:
    ws = _winsound()
    t = _timer.get("t")
    if t is not None:
        t.cancel()
        _timer["t"] = None
    if ws is not None:
        try:
            with _lock:
                ws.PlaySound(None, ws.SND_PURGE)
        except Exception:                                   # noqa: BLE001
            pass


def preview(name: str, seconds: float = 3.5) -> bool:
    """Prueba un tono: suena unos segundos y se detiene solo."""
    stop()
    if name == CLASSIC:
        ws = _winsound()
        if ws is None:
            return False

        def beeps():
            for f, d in ((880, 180), (1175, 180), (880, 180), (1175, 180)):
                try:
                    ws.Beep(f, d)
                except Exception:                           # noqa: BLE001
                    return
        threading.Thread(target=beeps, daemon=True).start()
        return True
    if not play_loop(name):
        return False
    t = threading.Timer(max(1.0, seconds), stop)
    t.daemon = True
    _timer["t"] = t
    t.start()
    return True


if __name__ == "__main__":                                  # python tonos.py -> genera todos los .wav para revisarlos
    for n in BUILTIN:
        p = ensure(n)
        print(n, "->", p)
