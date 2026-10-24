"""¿La bolita (o su burbuja) está tapando texto? Detector LOCAL de «zonas con texto»: sin IA y sin gastar cuota.

Cómo funciona
  - Se toma una captura chiquita (mss) en grises y se mide qué tanto «parece texto»: muchos saltos bruscos de brillo en poco
    espacio, repartidos en renglones, sobre un fondo de dos tonos (fondo + tinta). Fotos, degradados, botones lisos y rayas
    puntúan bajo (ver text_score).
  - La bolita NO se mide por debajo (ella misma saldría en la captura): se miran las 4 franjas que la rodean. Si hay texto a
    los dos lados (o arriba y abajo), lo más probable es que esté encima de un párrafo (ver cover_score).
  - Para elegir a dónde irse se mide cada hueco candidato (ahí la bolita no está, así que la captura sale limpia).

Todo está en PÍXELES FÍSICOS (los de mss). La conversión desde los de Qt la hace Orb.avoid_text.
Ajustes: constantes de abajo; en config.json se pueden mover desde live_orb ("apartarse_*").
"""
import numpy as np

EDGE = 40          # salto de gris (0-255) que cuenta como borde de una letra
BAND = 46          # px de ancho de cada franja que rodea a la bolita
MIN_SIDE = 14      # una franja más chica que esto no se mide (casi fuera de la pantalla)
COVER_ON = 0.45    # cover_score desde el que la bolita se aparta (menos = más nerviosa)
EMPTY_MAX = 0.12   # el hueco elegido debe tener menos texto que esto (y menos de la mitad del que tapa ahora)


def grab_gray(left, top, width, height):
    """Captura de esa zona en grises (uint8, alto x ancho) o None si no se pudo (mss no instalado, zona vacía...)."""
    try:
        import mss
        if width < 1 or height < 1:
            return None
        with mss.mss() as sct:
            sh = sct.grab({"left": int(left), "top": int(top), "width": int(width), "height": int(height)})
        a = np.asarray(sh)                                           # BGRA
        return (a[..., 2] * 0.299 + a[..., 1] * 0.587 + a[..., 0] * 0.114).astype(np.uint8)
    except Exception:                                                # noqa: BLE001
        return None


def text_score(g) -> float:
    """0 (nada de texto) a 1 (claramente texto) para una zona en grises."""
    if g is None or getattr(g, "ndim", 0) != 2 or g.shape[0] < MIN_SIDE or g.shape[1] < MIN_SIDE:
        return 0.0
    g = g.astype(np.int16)
    dx = np.abs(np.diff(g, axis=1)) >= EDGE
    dy = np.abs(np.diff(g, axis=0)) >= EDGE
    ex, ey = float(dx.mean()), float(dy.mean())
    if min(ex, ey) < 0.006:                       # liso, o solo rayas en un sentido (bordes, tablas, líneas)
        return 0.0
    # dos tonos: casi todo el área es fondo + tinta (en una foto o un degradado los niveles se reparten)
    hist = np.bincount((g >> 4).ravel(), minlength=16).astype(float)
    top2 = float(np.sort(hist)[-2:].sum() / hist.sum())
    # renglones: filas con varias letras (texto = filas con letras intercaladas con interlineado)
    filas = dx.sum(axis=1) >= max(3, g.shape[1] // 45)
    act = float(filas.mean())
    # reparto: las letras ponen bordes por TODA la zona; una tabla, un marco o un ícono los concentran en pocas columnas/filas
    cols = float(dx.any(axis=0).mean())
    rows_y = float(dy.any(axis=1).mean())
    s_edge = min(1.0, ((ex + ey) / 2) / 0.05)
    s_rows = min(1.0, act / 0.30)
    s_tone = min(1.0, max(0.0, (top2 - 0.50) / 0.30))
    s_spread = min(1.0, min(cols, rows_y) / 0.55)
    return float(s_edge * s_rows * s_spread * (0.15 + 0.85 * s_tone))


def _slice(g, org, x0, y0, x1, y1):
    """Recorte (en coordenadas de pantalla) de una captura que empieza en `org`=(ox, oy); None si queda muy chico."""
    ox, oy = org
    a, b = int(max(x0, ox) - ox), int(max(y0, oy) - oy)
    c, d = int(min(x1, ox + g.shape[1]) - ox), int(min(y1, oy + g.shape[0]) - oy)
    if c - a < MIN_SIDE or d - b < MIN_SIDE:
        return None
    return g[b:d, a:c]


def cover_score(rect, bounds, band=BAND) -> float:
    """Qué tan probable es (0-1) que `rect` (x0,y0,x1,y1) esté ENCIMA de texto, mirando las franjas que lo rodean.
    `bounds` = (x0,y0,x1,y1) de la pantalla. Una sola captura."""
    x0, y0, x1, y1 = (int(v) for v in rect)
    mx0, my0, mx1, my1 = bounds
    gx0, gy0, gx1, gy1 = max(mx0, x0 - band), max(my0, y0 - band), min(mx1, x1 + band), min(my1, y1 + band)
    g = grab_gray(gx0, gy0, gx1 - gx0, gy1 - gy0)
    return cover_score_from(g, (gx0, gy0), rect, band)


def cover_score_from(g, org, rect, band=BAND) -> float:
    """Igual que cover_score pero sobre una captura ya hecha `g` que empieza en `org` (sirve para probar sin pantalla)."""
    if g is None:
        return 0.0
    x0, y0, x1, y1 = (int(v) for v in rect)
    sides = {
        "l": _slice(g, org, x0 - band, y0, x0, y1), "r": _slice(g, org, x1, y0, x1 + band, y1),
        "t": _slice(g, org, x0, y0 - band, x1, y0), "b": _slice(g, org, x0, y1, x1, y1 + band),
    }
    sc = {k: (text_score(v) if v is not None else None) for k, v in sides.items()}
    pares = [min(sc[a], sc[b]) for a, b in (("l", "r"), ("t", "b")) if sc[a] is not None and sc[b] is not None]
    return max(pares) if pares else 0.0


def area_score(g, org, rect) -> float:
    """Texto dentro de `rect` según una captura ya hecha (para medir los huecos candidatos)."""
    s = _slice(g, org, *rect)
    return text_score(s) if s is not None else 0.0


def _inter(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def choose_spot(g, org, bounds, cur_rect, spots, half, bub_rel=None, cov=1.0):
    """Elige el hueco con MENOS texto entre los centros candidatos `spots` [(x, y)] o None si ninguno es lo bastante vacío.
    g/org: captura (grises) de la pantalla; bounds: (x0,y0,x1,y1) de la pantalla; cur_rect: zona que ocupa ahora (bolita + burbuja);
    half: radio de la bolita; bub_rel: (dx0,dy0,dx1,dy1) de la burbuja relativo al centro de la bolita (None = sin burbuja)."""
    mx0, my0, mx1, my1 = bounds
    mejor, mejor_s = None, 9.0
    cx, cy = (cur_rect[0] + cur_rect[2]) / 2, (cur_rect[1] + cur_rect[3]) / 2
    for sx, sy in spots:
        r = [sx - half, sy - half, sx + half, sy + half]
        if bub_rel:
            r = [min(r[0], sx + bub_rel[0]), min(r[1], sy + bub_rel[1]), max(r[2], sx + bub_rel[2]), max(r[3], sy + bub_rel[3])]
        area = (r[2] - r[0]) * (r[3] - r[1])
        r = [max(mx0, r[0]), max(my0, r[1]), min(mx1, r[2]), min(my1, r[3])]
        if r[2] <= r[0] or r[3] <= r[1] or (r[2] - r[0]) * (r[3] - r[1]) < 0.7 * area:
            continue                                   # se saldría de la pantalla
        if _inter(r, cur_rect):
            continue                                   # ahí todavía estaría ella misma (saldría en la captura)
        sc = area_score(g, org, r)
        # a igualdad de texto, el hueco más cercano (camina menos)
        sc_rank = sc + 0.0002 * (((sx - cx) ** 2 + (sy - cy) ** 2) ** 0.5) / 10
        if sc_rank < mejor_s:
            mejor, mejor_s, mejor_real = (sx, sy), sc_rank, sc
    if mejor is None or mejor_real > min(EMPTY_MAX, cov * 0.5):
        return None
    return mejor
