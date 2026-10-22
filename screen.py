"""Captura de pantalla para que Orbi "vea" (mss + Pillow, sin tocar la interfaz de Qt).

capture()  -> (jpeg_bytes, monitor)   monitor = dict(left, top, width, height) del monitor capturado
changed()  -> True si la pantalla cambió lo suficiente respecto a la captura anterior
"""
import io, time

MAX_SIDE = 1280      # lado más largo del JPEG que se manda (menos tokens, más rápido)
QUALITY = 65


def capture(max_side: int = MAX_SIDE, quality: int = QUALITY):
    import mss
    from PIL import Image

    with mss.mss() as sct:                       # se crea en cada llamada: seguro desde cualquier hilo
        mon = dict(sct.monitors[1])              # monitor principal
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    scale = min(1.0, max_side / max(img.size))
    if scale < 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue(), mon


def primary_monitor() -> dict:
    import mss
    with mss.mss() as sct:
        return dict(sct.monitors[1])


def _thumb(jpeg: bytes):
    from PIL import Image
    import numpy as np
    img = Image.open(io.BytesIO(jpeg)).convert("L").resize((48, 27))
    return np.asarray(img, dtype=np.int16)


class ChangeDetector:
    """Para el modo continuo: solo manda un frame si la pantalla cambió (ahorra cuota)."""

    def __init__(self, threshold: float = 3.0):
        self.threshold = threshold
        self._prev = None

    def changed(self, jpeg: bytes) -> bool:
        cur = _thumb(jpeg)
        prev, self._prev = self._prev, cur
        if prev is None:
            return True
        return float(abs(cur - prev).mean()) > self.threshold

    def reset(self):
        self._prev = None


def _thumb_from_mss(sct, mon):
    from PIL import Image
    import numpy as np
    shot = sct.grab(mon)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    return np.asarray(img.convert("L").resize((80, 45), Image.BILINEAR), dtype=np.int16)


def wait_settled(max_s: float, floor_s: float = 0.2, poll: float = 0.06, stable_polls: int = 2,
                 threshold: float = 0.8, grab=None) -> float:
    """Espera a que la pantalla se \"asiente\" tras una acción, en vez de dormir un tiempo fijo. Devuelve lo que esperó.

    - Si la pantalla NO cambia, sale al cumplirse `floor_s` (la mayoría de los clics y teclas).
    - Si cambia, sigue hasta que lleve `stable_polls` revisiones seguidas (~poll s cada una) sin cambiar.
    - `max_s` es el tope duro (un video o una animación nunca se \"asientan\": se corta ahí).
    `grab` es opcional (callable -> miniatura numpy) y sirve para probar sin pantalla.
    """
    if max_s <= 0:
        return 0.0
    t0 = time.time()
    floor_s = min(floor_s, max_s)
    sct = None
    try:
        if grab is None:
            import mss
            sct = mss.mss()
            mon = dict(sct.monitors[1])
            grab = lambda: _thumb_from_mss(sct, mon)          # noqa: E731
        prev = grab()
        changed, stable = False, 0
        while True:
            time.sleep(poll)
            el = time.time() - t0
            if el >= max_s:
                break
            cur = grab()
            moved = float(abs(cur - prev).mean()) > threshold
            prev = cur
            if moved:
                changed, stable = True, 0
            else:
                stable += 1
            if changed and stable >= stable_polls:
                break
            if not changed and el >= floor_s:
                break
    except Exception:                                          # sin pantalla / sin mss: cae al comportamiento de antes
        left = max_s - (time.time() - t0)
        if left > 0:
            time.sleep(left)
    finally:
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass
    return time.time() - t0
