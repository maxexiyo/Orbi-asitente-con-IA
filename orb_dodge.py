"""Que Orbi se haga a un lado cuando está trabajando, para no taparse lo que está haciendo.

La lógica de elegir sitio es pura (rectángulos como tuplas x0,y0,x1,y1) para poder probarla sin Qt.
caret_rect() usa Windows para saber dónde está el cursor de texto de la ventana activa (donde se escribe).
"""
import math
import sys


def inflate(r, dx, dy):
    return (r[0] - dx, r[1] - dy, r[2] + dx, r[3] + dy)


def intersects(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def shift(r, dx, dy):
    return (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)


def danger_zone(caret=None, point=None):
    """Zona que NO conviene tapar: alrededor del cursor de texto si se conoce; si no, alrededor del mouse."""
    if caret is not None:
        return inflate(caret, 260, 130)
    if point is not None:
        return (point[0] - 220, point[1] - 150, point[0] + 220, point[1] + 150)
    return None


def _footprints(spot, center, orb_half, bubble_rect):
    rects = [(spot[0] - orb_half, spot[1] - orb_half, spot[0] + orb_half, spot[1] + orb_half)]
    if bubble_rect is not None:                         # la burbuja va pegada a la bolita: se mueve con ella
        rects.append(shift(bubble_rect, spot[0] - center[0], spot[1] - center[1]))
    return rects


def needs_dodge(center, orb_half, bubble_rect, danger) -> bool:
    return danger is not None and any(intersects(r, danger) for r in _footprints(center, center, orb_half, bubble_rect))


def pick_spot(center, spots, orb_half, bubble_rect, danger):
    """El sitio libre más cercano; si ninguno está libre, el más lejos de la zona peligrosa."""
    free = [s for s in spots
            if not any(intersects(r, danger) for r in _footprints(s, center, orb_half, bubble_rect))]
    if free:
        return min(free, key=lambda s: math.hypot(s[0] - center[0], s[1] - center[1]))
    dc = ((danger[0] + danger[2]) / 2, (danger[1] + danger[3]) / 2)
    return max(spots, key=lambda s: math.hypot(s[0] - dc[0], s[1] - dc[1]))


def caret_rect():
    """Rectángulo (píxeles físicos de pantalla) del cursor de texto de la ventana activa, o None si no se sabe.
    Muchas apps (Word, Bloc de notas, Excel) lo informan; los navegadores y apps modernas a veces no: entonces se usa el mouse."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes as wt

        class RECT(ctypes.Structure):
            _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]

        class GTI(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), ("hwndActive", wt.HWND), ("hwndFocus", wt.HWND),
                        ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND), ("hwndMoveSize", wt.HWND),
                        ("hwndCaret", wt.HWND), ("rcCaret", RECT)]

        u = ctypes.windll.user32
        fg = u.GetForegroundWindow()
        if not fg:
            return None
        info = GTI()
        info.cbSize = ctypes.sizeof(GTI)
        if not u.GetGUIThreadInfo(u.GetWindowThreadProcessId(fg, None), ctypes.byref(info)) or not info.hwndCaret:
            return None
        pt = wt.POINT(info.rcCaret.left, info.rcCaret.top)
        u.ClientToScreen(info.hwndCaret, ctypes.byref(pt))
        w, h = info.rcCaret.right - info.rcCaret.left, info.rcCaret.bottom - info.rcCaret.top
        return (pt.x, pt.y, pt.x + max(w, 2), pt.y + max(h, 16))
    except Exception:                                   # noqa: BLE001
        return None
