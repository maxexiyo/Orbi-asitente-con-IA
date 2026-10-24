"""Captura de pantalla para que Orbi "vea" (mss + Pillow, sin tocar la interfaz de Qt).

capture()  -> (jpeg_bytes, monitor)   monitor = dict(left, top, width, height) del monitor capturado
changed()  -> True si la pantalla cambió lo suficiente respecto a la captura anterior
"""
import io, time

MAX_SIDE = 1600      # lado más largo del JPEG que se manda (antes 1280: en pantallas grandes el texto chico no se leía)
QUALITY = 78         # config.json: pantalla_max_side / pantalla_quality (ver configure())
info = {}            # datos de la ÚLTIMA captura: monitor, tamaño enviado, escala, KB (para diagnóstico y logs)
_warned = set()


_click = {"t": 0.0, "x": 0, "y": 0}      # último clic de Orbi (píxeles de pantalla) para dibujarlo en las capturas
MARK_TTL_S = 25.0                          # cuánto tiempo se sigue dibujando la marca del último clic
last_capture_t = 0.0                       # instante (time.time()) de la última captura tomada


def configure(max_side=None, quality=None) -> None:
    """live_orb lo llama con lo que diga config.json (pantalla_max_side / pantalla_quality)."""
    global MAX_SIDE, QUALITY
    if max_side:
        MAX_SIDE = max(640, min(4096, int(max_side)))
    if quality:
        QUALITY = max(40, min(95, int(quality)))


def resumen() -> str:
    """Una línea: qué ve Orbi en la última captura (monitor real -> tamaño enviado)."""
    if not info:
        return "(todavía no hay capturas)"
    m, e = info["monitor"], info["enviado"]
    return (f"monitor {m[0]}x{m[1]} -> Orbi recibe {e[0]}x{e[1]} ({info['escala'] * 100:.0f}% del tamaño real, "
            f"{info['kb']:.0f} KB, calidad JPEG {info['calidad']})")


def _anotar(kind: str, mon: dict, img, nbytes: int, quality: int) -> None:
    esc = img.width / max(1, mon["width"])
    info.update(tipo=kind, monitor=(mon["width"], mon["height"]), enviado=(img.width, img.height), escala=esc,
                kb=nbytes / 1024, calidad=quality)
    if esc < 0.5 and kind not in _warned:                  # menos de la mitad de los píxeles de cada lado: el texto chico se mancha
        _warned.add(kind)
        print(f"[pantalla] OJO ({kind}): {resumen()}. Si Orbi no lee texto chico sube pantalla_max_side en config.json "
              "o usa acercar_pantalla / leer_pantalla.")


def note_click(px: int, py: int) -> None:
    """pc_tools lo llama al hacer clic: la próxima captura (con mark=True) dibuja dónde cayó."""
    _click.update(t=time.time(), x=int(px), y=int(py))


def _draw_click_mark(img, mon, sx: float, sy: float):
    """Anillo rojo con borde blanco + cruz en el último clic, para que la IA vea DÓNDE cayó (y si fue donde quería)."""
    if time.time() - _click["t"] > MARK_TTL_S:
        return img
    from PIL import ImageDraw
    cx, cy = (_click["x"] - mon["left"]) * sx, (_click["y"] - mon["top"]) * sy
    if not (0 <= cx < img.width and 0 <= cy < img.height):
        return img
    d = ImageDraw.Draw(img)
    r = max(10, round(min(img.size) / 60))
    for rad, col, w in ((r + 2, (255, 255, 255), 2), (r, (255, 40, 40), 3)):
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=col, width=w)
    d.line([cx - r * 1.8, cy, cx + r * 1.8, cy], fill=(255, 40, 40), width=2)
    d.line([cx, cy - r * 1.8, cx, cy + r * 1.8], fill=(255, 40, 40), width=2)
    return img


def _grab_full():
    import mss
    from PIL import Image
    with mss.mss() as sct:                       # se crea en cada llamada: seguro desde cualquier hilo
        mon = dict(sct.monitors[1])              # monitor principal
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    return img, mon


def capture(max_side: int | None = None, quality: int | None = None, mark: bool = False):
    """Captura NUEVA de la pantalla completa. `mark=True` dibuja el último clic de Orbi (círculo rojo)."""
    global last_capture_t
    from PIL import Image
    max_side, quality = max_side or MAX_SIDE, quality or QUALITY
    img, mon = _grab_full()
    last_capture_t = time.time()
    scale = min(1.0, max_side / max(img.size))
    if scale < 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    if mark:
        img = _draw_click_mark(img, mon, img.width / mon["width"], img.height / mon["height"])
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    _anotar("pantalla", mon, img, buf.tell(), quality)
    return buf.getvalue(), mon


def capture_region(box, max_side: int = 1600, quality: int = 88, mark: bool = True):
    """Zoom: recorta una zona de la pantalla a resolución COMPLETA (y la agranda si es chica) para leer texto pequeño.

    `box` = [ymin, xmin, ymax, xmax] en 0..1000 sobre la pantalla completa. Devuelve (jpeg, mon, box_px).
    """
    global last_capture_t
    from PIL import Image
    img, mon = _grab_full()
    last_capture_t = time.time()
    ymin, xmin, ymax, xmax = (max(0.0, min(1000.0, float(v))) for v in box)
    ymin, ymax = sorted((ymin, ymax))
    xmin, xmax = sorted((xmin, xmax))
    W, H = img.size
    l, t, r, b = round(xmin / 1000 * W), round(ymin / 1000 * H), round(xmax / 1000 * W), round(ymax / 1000 * H)
    if r - l < 40 or b - t < 40:                 # zona diminuta: ábrela un poco para que tenga contexto
        l, t, r, b = max(0, l - 40), max(0, t - 40), min(W, r + 40), min(H, b + 40)
    if mark:
        img = _draw_click_mark(img, mon, W / mon["width"], H / mon["height"])
    crop = img.crop((l, t, r, b))
    f = min(max_side / max(crop.size), 3.0)      # agranda hasta 3x (texto chico), o reduce si es enorme
    if abs(f - 1.0) > 0.05:
        crop = crop.resize((max(1, round(crop.width * f)), max(1, round(crop.height * f))), Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=quality)
    return buf.getvalue(), mon, (l, t, r, b)


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
