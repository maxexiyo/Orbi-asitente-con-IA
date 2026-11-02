"""Modo DASHBOARD de Orbi: varios paneles que Orbi suelta de golpe
cuando la respuesta se entiende mejor viéndola en conjunto (resumen del día, agenda + correos + alarmas, comparaciones...).

El ESTILO sale del tema elegido en Ajustes → Apariencia (temas.py): «órbita» (predeterminado: la bolita se va al centro y los paneles
la rodean), «vidrio», «juego», «editorial», «terminal», «neobrutalista», «cinta» (una barra con chips arriba), «reloj» (anillo de 24 h con tu
agenda) y «hud» (el original). La bolita NO cambia de diseño: solo se mueve (al centro o a la esquina) mientras el dashboard está abierto y vuelve
a donde estaba al cerrarse. Cada panel es una ventanita propia (sin foco, siempre encima), así que no hay una capa a pantalla
completa que estorbe el mouse: solo lo que se ve recibe clics.

Tipos de panel (dict por panel; `etiqueta` = rótulo chiquito arriba, `titulo` = título):
  lista     {"lineas": [str | {"texto","url"} | {"texto","accion","datos"}]}   · también valen agenda, correos, alarmas, notificaciones
  texto     {"texto": "párrafo corto"}
  cifra     {"valor": "20", "unidad": "min", "texto": "descripción corta"}
  barras    {"valores": [3, 7, 5], "etiquetas": ["L", "M", "X"]}               · también vale grafica
  progreso  {"items": [{"etiqueta": "Tarea de mate", "valor": 60}, ...]}       (valor 0-100)
  imagen    {"imagen": "C:\\ruta.png" | "https://...", "texto": "pie", "url": "enlace al hacer clic"}

API que usa live_orb.py:
  dash = HudDashboard(get_anchor, on_action=None, get_opacity=None, move_orb=None, restore_orb=None, get_tema=None)
  dash.mostrar(titulo, paneles, segundos=90, estilo=None)   -> abre (reemplaza el anterior); estilo = id de tema solo para esta vez
  dash.ocultar()                               -> cierra con animación
  parse_paneles(raw) -> (lista_normalizada, error)   (raw = JSON en texto, lista o dict con "paneles")
"""
import json
import math
import os
import re
import threading
import urllib.request
import time
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QTimer, QUrl, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

import temas

PANEL_W = 290
GAP = 14
MAX_PANELES = 8
ACC = QColor(90, 200, 255)
ACC_HI = QColor(160, 228, 255)
BG = QColor(6, 12, 22, 232)
TXT = "#dcebf7"
DIM = "#7f9bb3"
LINK = "color:#9fdcff;text-decoration:none"
_URL = re.compile(r"(https?://[^\s<>\"']+)")

ALIAS = {"agenda": "lista", "correos": "lista", "correo": "lista", "alarmas": "lista", "notificaciones": "lista",
         "recordatorios": "lista", "grafica": "barras", "grafico": "barras", "gráfica": "barras", "gráfico": "barras",
         "numero": "cifra", "número": "cifra", "dato": "cifra", "foto": "imagen", "miniatura": "imagen"}
ETIQUETA = {"lista": "DATOS", "texto": "NOTA", "cifra": "DATO", "barras": "GRÁFICA", "progreso": "PROGRESO", "imagen": "IMAGEN"}


# ---------------------------------------------------------------------------------- datos (sin GUI, se puede probar solo)
def _s(x, n) -> str:
    return str(x if x is not None else "").strip()[:n]


def _linea(x) -> dict:
    if isinstance(x, dict):
        tgt = x.get("url") or ({"accion": x["accion"], "datos": x.get("datos") or {}} if x.get("accion") else None)
        return {"texto": _s(x.get("texto") or x.get("text"), 90), "target": tgt}
    return {"texto": _s(x, 220 if ("http" in str(x) or ":\\" in str(x)) else 90), "target": None}


def _num(x, default=0.0) -> float:
    try:
        return float(str(x).replace("%", "").replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


def normalize(paneles) -> list:
    """Limpia lo que mande el modelo: tipos válidos, textos cortos, máximo MAX_PANELES paneles."""
    out = []
    for p in (paneles or []):
        if not isinstance(p, dict):
            continue
        tipo = _s(p.get("tipo"), 20).lower()
        tipo = ALIAS.get(tipo, tipo)
        if tipo not in ETIQUETA:
            tipo = "lista" if p.get("lineas") else "progreso" if p.get("items") else "barras" if p.get("valores") \
                else "cifra" if p.get("valor") not in (None, "") else "imagen" if p.get("imagen") else "texto"
        d = dict(tipo=tipo, titulo=_s(p.get("titulo"), 40), etiqueta=(_s(p.get("etiqueta"), 14) or ETIQUETA[tipo]).upper(),
                 icono=_s(p.get("icono"), 4))
        if tipo == "lista":
            raw = p.get("lineas")
            if isinstance(raw, str):
                raw = [x.strip() for x in raw.splitlines() if x.strip()]
            d["lineas"] = [_linea(x) for x in (raw or [])][:8]
            if not d["lineas"] and p.get("texto"):
                d["lineas"] = [_linea(p["texto"])]
        elif tipo == "texto":
            d["texto"] = _s(p.get("texto") or " ".join(map(str, p.get("lineas") or [])), 360)
        elif tipo == "cifra":
            d.update(valor=_s(p.get("valor"), 10), unidad=_s(p.get("unidad"), 12), texto=_s(p.get("texto"), 80))
        elif tipo == "barras":
            vals = [max(0.0, _num(v)) for v in (p.get("valores") or [])][:8]
            et = [_s(e, 6) for e in (p.get("etiquetas") or [])][:8]
            d.update(valores=vals, etiquetas=et + [""] * (len(vals) - len(et)))
        elif tipo == "progreso":
            its = []
            for it in (p.get("items") or [])[:6]:
                if isinstance(it, dict):
                    its.append({"etiqueta": _s(it.get("etiqueta") or it.get("texto"), 34), "valor": max(0.0, min(100.0, _num(it.get("valor"))))})
            d["items"] = its
        else:  # imagen
            d.update(imagen=_s(p.get("imagen") or p.get("ruta") or p.get("url_imagen"), 400), texto=_s(p.get("texto"), 80),
                     url=_s(p.get("url"), 400))
        out.append(d)
        if len(out) >= MAX_PANELES:
            break
    return out


def parse_paneles(raw):
    """JSON (texto, lista o dict con 'paneles') -> (lista normalizada, error)."""
    try:
        if isinstance(raw, str):
            t = raw.strip()
            t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
            raw = json.loads(t) if t else []
        if isinstance(raw, dict):
            raw = raw.get("paneles") or raw.get("panels") or [raw]
        if not isinstance(raw, list):
            return [], "`paneles` debe ser una lista JSON de paneles."
    except (ValueError, TypeError) as e:
        return [], f"`paneles` no es un JSON válido ({str(e)[:60]})."
    out = normalize(raw)
    return (out, "") if out else ([], "No había ningún panel válido que mostrar.")


def plan_layout(sizes, region: QRect, reserved: QRect | None = None, gap: int = GAP, max_cols: int = 4, top: int = 0):
    """Reparte los paneles en columnas (la más baja primero) sin pisar la zona reservada (la bolita en la esquina).
    sizes = [(w, h)]. Devuelve (posiciones, columnas): QPoint o None si ese panel no cabe."""
    n = len(sizes)
    if not n:
        return [], 0
    w = max(s[0] for s in sizes)
    fit = max(1, (region.width() + gap) // (w + gap))
    cols = max(1, min(max_cols, fit, n if n <= 3 else 3 if n <= 6 else 4))
    x0 = region.left() + (region.width() - (cols * w + (cols - 1) * gap)) // 2
    heights = [region.top() + top] * cols
    out = []
    for (pw, ph) in sizes:
        spot = None
        for c in sorted(range(cols), key=lambda i: (heights[i], i)):
            r = QRect(x0 + c * (w + gap), heights[c], pw, ph)
            if r.bottom() <= region.bottom() and not (reserved is not None and r.intersects(reserved)):
                spot = (c, r)
                break
        if spot is None:
            out.append(None)
            continue
        heights[spot[0]] = spot[1].bottom() + 1 + gap
        out.append(spot[1].topLeft())
    return out, cols


# ---------------------------------------------------------------------------------- utilidades de pintura
_FLAGS = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
_FLAGS_CT = _FLAGS | Qt.WindowTransparentForInput          # ventana por la que el mouse «pasa» (anillos, textos sueltos)


def _c(hexs: str, a: int = 255) -> QColor:
    q = QColor(hexs)
    q.setAlpha(a)
    return q


def _font(t, px: int, bold: bool = False, titulo: bool = False, spacing: float = 0.0) -> QFont:
    f = temas.qfont(t, px, bold, titulo)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def _colores(t, i: int):
    """(color del panel, color de acento para barras y etiquetas) según el modo de paleta del tema."""
    col = QColor(t.paleta[i % len(t.paleta)]) if t.paleta else None
    if t.paleta_modo == "borde" and col is not None:
        return col, col
    if t.paleta_modo == "relleno":
        return col, QColor("#111111")
    return col, QColor(t.acento)


def _track(t) -> QColor:
    return QColor(255, 255, 255, 36) if t.oscuro else QColor(0, 0, 0, 30)


class _Bars(QWidget):
    def __init__(self, valores, etiquetas, t, ac, parent=None):
        super().__init__(parent)
        self.v, self.e, self.t, self.ac, self.k = valores, etiquetas, t, ac, 0.0
        self.setFixedHeight(98)
        self._an = QVariantAnimation(self, duration=750, startValue=0.0, endValue=1.0)
        self._an.setEasingCurve(QEasingCurve.OutCubic)
        self._an.valueChanged.connect(self._set_k)
        QTimer.singleShot(250, self._an.start)

    def _set_k(self, k):
        self.k = float(k)
        self.update()

    def paintEvent(self, _e):
        if not self.v:
            return
        t, p = self.t, QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n, mx = len(self.v), max(max(self.v), 1e-9)
        slot = self.width() / n
        bw = min(20.0 if t.barras == "redonda" else 30.0, slot * 0.6)
        base = self.height() - 16
        p.setFont(_font(t, 10))
        p.setPen(QPen(QColor(t.borde[0], t.borde[1], t.borde[2], 90), 1))
        p.drawLine(0, base, self.width(), base)
        bordered = t.barras in ("segmentos", "gruesa")
        for i, v in enumerate(self.v):
            h = max(6.0, (base - 14) * (v / mx) * self.k)
            x, y = slot * i + (slot - bw) / 2, base - h
            col = QColor(self.ac)
            if bordered and t.paleta:
                col = QColor(t.paleta[i % len(t.paleta)])
            elif v != mx:
                col.setAlpha(140)
            p.setBrush(col)
            p.setPen(QPen(QColor(*t.borde), 3 if bordered else 0) if bordered else Qt.NoPen)
            if t.barras == "redonda":
                p.drawRoundedRect(int(x), int(y), int(bw), int(h), min(bw / 2, h / 2), min(bw / 2, h / 2))
            elif t.barras == "segmentos":
                p.drawRoundedRect(int(x), int(y), int(bw), int(h), min(8, h / 2), min(8, h / 2))
            else:
                p.drawRect(int(x), int(y), int(bw), int(h))
            p.setPen(QColor(t.texto))
            p.drawText(QRect(int(x - 8), int(y - 15), int(bw + 16), 13), Qt.AlignCenter, f"{v:g}")
            p.setPen(QColor(t.tenue))
            p.drawText(QRect(int(slot * i), base + 2, int(slot), 13), Qt.AlignCenter, self.e[i] if i < len(self.e) else "")


class _Progress(QWidget):
    def __init__(self, items, t, ac, parent=None):
        super().__init__(parent)
        self.items, self.t, self.ac, self.k = items, t, ac, 0.0
        self.setFixedHeight(max(34, 36 * len(items)))
        self._an = QVariantAnimation(self, duration=800, startValue=0.0, endValue=1.0)
        self._an.setEasingCurve(QEasingCurve.OutCubic)
        self._an.valueChanged.connect(self._set_k)
        QTimer.singleShot(250, self._an.start)

    def _set_k(self, k):
        self.k = float(k)
        self.update()

    def paintEvent(self, _e):
        t, p = self.t, QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()
        for i, it in enumerate(self.items):
            y, frac = i * 36, it["valor"] / 100.0 * self.k
            p.setFont(_font(t, 12, bold=t.barras in ("gruesa", "segmentos")))
            p.setPen(QColor(t.texto))
            p.drawText(QRect(0, y, W - 44, 15), Qt.AlignLeft | Qt.AlignVCenter, it["etiqueta"])
            p.drawText(QRect(W - 44, y, 44, 15), Qt.AlignRight | Qt.AlignVCenter, f"{it['valor']:.0f}%")
            ty, st = y + 20, t.barras
            if st == "bloques":                                  # estilo consola: [█████░░░░░]
                n = round(it["valor"] / 10.0 * self.k)
                p.setPen(self.ac)
                p.drawText(QRect(0, ty - 3, W, 16), Qt.AlignLeft | Qt.AlignVCenter, "[" + "█" * n + "░" * (10 - n) + "]")
            elif st == "segmentos":
                n, gap = 10, 3
                sw = (W - gap * 9) / 10.0
                for k in range(n):
                    on = k < round(it["valor"] / 10.0 * self.k)
                    p.setPen(QPen(QColor(*t.borde), 2)); p.setBrush(self.ac if on else QColor(239, 227, 200))
                    p.drawRoundedRect(QRect(int(k * (sw + gap)), ty, int(sw), 12), 4, 4)
            elif st == "gruesa":
                p.setPen(QPen(QColor(*t.borde), 3)); p.setBrush(QColor("#ffffff"))
                p.drawRect(1, ty, W - 2, 16)
                p.setPen(Qt.NoPen); p.setBrush(self.ac)
                p.drawRect(3, ty + 2, int((W - 6) * frac), 12)
            else:                                                # redonda / linea
                h = 3 if st == "linea" else 8
                p.setPen(Qt.NoPen); p.setBrush(_track(t))
                r = h / 2 if st == "redonda" else 0
                p.drawRoundedRect(0, ty + (4 if st == "linea" else 0), W, h, r, r)
                p.setBrush(self.ac)
                w = int(W * frac)
                p.drawRoundedRect(0, ty + (4 if st == "linea" else 0), w, h, r, r)
                if st == "linea" and w > 2:
                    p.drawRect(max(0, w - 3), ty + 2, 3, h + 4)


class _Img(QLabel):
    clicked = Signal()
    _got = Signal(bytes)

    def __init__(self, src, w, t, h=104, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"background:rgba({t.borde[0]},{t.borde[1]},{t.borde[2]},30);border:1px solid rgba({t.borde[0]},{t.borde[1]},{t.borde[2]},90);")
        self._got.connect(self._set)
        if re.match(r"https?://", src or ""):
            threading.Thread(target=self._fetch, args=(src,), daemon=True).start()
        elif src and os.path.isfile(src):
            try:
                with open(src, "rb") as fh:
                    self._set(fh.read(8_000_000))
            except OSError:
                pass

    def _fetch(self, u):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                self._got.emit(r.read(4_000_000))
        except Exception:  # noqa: BLE001
            pass

    def _set(self, data):
        p = QPixmap()
        if p.loadFromData(data):
            self.setPixmap(p.scaled(self.width(), self.height(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        else:
            e.ignore()


# ---------------------------------------------------------------------------------- una ventanita (con el tema)
class _Hud(QWidget):
    """Base: ventana sin foco con fade + deslizamiento de entrada y de salida, y marco pintado según el tema."""

    def __init__(self, t, idx: int = 0, flags=_FLAGS):
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.t, self.idx = t, idx
        self.col, self.ac = _colores(t, idx)
        self._flash, self._op, self._anims = 0.0, 0.95, []
        self._pad = 6 if t.brillo else 0                        # espacio para el resplandor
        self._sh = (t.sombra[0], t.sombra[1]) if t.sombra else (0, 0)

    def aparecer(self, target: QPoint, delay: int, op: float, desde: QPoint = QPoint(0, 22)) -> None:
        self._op = op

        def go():
            self.setWindowOpacity(0.0)
            self.move(target + desde)
            self.show()
            a = QPropertyAnimation(self, b"pos", self, duration=420, startValue=target + desde, endValue=target)
            a.setEasingCurve(QEasingCurve.OutCubic)
            b = QPropertyAnimation(self, b"windowOpacity", self, duration=320, startValue=0.0, endValue=op)
            f = QVariantAnimation(self, duration=700, startValue=1.0, endValue=0.0)
            f.valueChanged.connect(self._set_flash)
            self._anims = [a, b, f]
            for x in self._anims:
                x.start()
        QTimer.singleShot(max(0, delay), go)

    def _set_flash(self, v):
        self._flash = float(v)
        self.update()

    def desaparecer(self, delay: int = 0) -> None:
        def go():
            if not self.isVisible():
                self.close()
                return
            b = QPropertyAnimation(self, b"windowOpacity", self, duration=220, startValue=self.windowOpacity(), endValue=0.0)
            b.finished.connect(self.close)
            self._anims = [b]
            b.start()
        QTimer.singleShot(max(0, delay), go)

    def paint_frame(self, p: QPainter, tag: str = "", band: str = "") -> None:
        t, col = self.t, self.col
        p.setRenderHint(QPainter.Antialiasing)
        pad, (sdx, sdy) = self._pad, self._sh
        r = QRect(1 + pad, 1 + pad, self.width() - 2 - 2 * pad - sdx, self.height() - 2 - 2 * pad - sdy)
        rad = t.radio
        if t.sombra:                                             # sombra dura (juego, neobrutalista)
            p.setPen(Qt.NoPen); p.setBrush(QColor(*t.sombra[2]))
            p.drawRoundedRect(r.translated(sdx, sdy), rad, rad)
        if t.brillo and col is not None:                         # resplandor del color del panel
            p.setBrush(Qt.NoBrush)
            for k in range(6):
                p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), int(46 * (1 - k / 6.0))), 1 + k))
                p.drawRoundedRect(r.adjusted(-k, -k, k, k), rad + k, rad + k)
        relleno = col if (t.paleta_modo == "relleno" and col is not None) else QColor(*t.bg)
        p.setPen(Qt.NoPen); p.setBrush(relleno)
        p.drawRoundedRect(r, rad, rad)
        if t.paleta_modo == "banda" and col is not None:        # franja de color arriba con el título
            clip = QPainterPath(); clip.addRoundedRect(r, rad, rad)
            p.save(); p.setClipPath(clip)
            p.fillRect(QRect(r.left(), r.top(), r.width(), 44), col)
            p.setPen(QPen(QColor(*t.borde), t.borde_px)); p.drawLine(r.left(), r.top() + 44, r.right(), r.top() + 44)
            p.restore()
        if t.scan:                                               # líneas de escaneo
            p.setPen(QColor(120, 255, 180, 9) if t.id == "terminal" else QColor(120, 200, 255, 9))
            for y in range(r.top() + 2, r.bottom(), 3):
                p.drawLine(r.left() + 1, y, r.right() - 1, y)
        a = int(min(255, t.borde[3] + 120 * self._flash))
        bc = QColor(col.red(), col.green(), col.blue(), max(a, 150)) if (t.paleta_modo == "borde" and col is not None) else QColor(t.borde[0], t.borde[1], t.borde[2], a)
        p.setBrush(Qt.NoBrush); p.setPen(QPen(bc, t.borde_px))
        p.drawRoundedRect(r, rad, rad)
        if t.esquinas:                                           # esquinitas del HUD clásico
            p.setPen(QPen(QColor(160, 228, 255, 240), 2))
            L, x0, y0, x1, y1 = 12, r.left(), r.top(), r.right(), r.bottom()
            for (cx, cy, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
                p.drawLine(cx, cy, cx + dx * L, cy); p.drawLine(cx, cy, cx, cy + dy * L)
        if band and t.paleta_modo == "banda":
            p.setFont(_font(t, 17, True, titulo=True)); p.setPen(QColor(t.texto))
            p.drawText(QRect(r.left() + 18, r.top(), r.width() - 70, 44), Qt.AlignLeft | Qt.AlignVCenter, band)
        elif tag and t.etiqueta != "ninguna":
            ac = self.ac
            if t.etiqueta == "llaves":
                p.setFont(_font(t, 12, True)); p.setPen(ac)
                p.drawText(QRect(r.left() + 14, r.top() + 6, r.width() - 60, 18), Qt.AlignLeft | Qt.AlignVCenter, f"┌─ {tag.lower()} ─┐")
            else:
                p.setFont(_font(t, 10, True, spacing=1.6)); p.setPen(ac)
                p.drawText(QRect(r.left() + 16, r.top() + 8, r.width() - 60, 16), Qt.AlignLeft | Qt.AlignVCenter, ("◆ " if t.etiqueta == "punto" else "") + tag)
            p.setPen(QColor(ac.red(), ac.green(), ac.blue(), 60))
            p.drawLine(r.left() + 16, r.top() + 28, r.right() - 16, r.top() + 28)


class HudPanel(_Hud):
    def __init__(self, spec: dict, idx: int, t, on_open, on_close, on_menu):
        super().__init__(t, idx)
        self.spec, self.on_open, self.on_close_req, self.on_menu = spec, on_open, on_close, on_menu
        self._links: dict = {}
        self.setFixedWidth(PANEL_W + 2 * self._pad + self._sh[0])
        band = t.paleta_modo == "banda"
        self._band = (spec["titulo"] or spec["etiqueta"].title()) if band else ""
        top = 52 if band else (34 if t.etiqueta != "ninguna" else 16)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16 + self._pad, top + self._pad, 16 + self._pad + self._sh[0], 14 + self._pad + self._sh[1])
        lay.setSpacing(8)
        if spec["titulo"] and not band:
            tt = ((spec["icono"] + " " if spec["icono"] else "") + spec["titulo"])
            lb = QLabel(tt.upper() if t.mayus else tt)
            lb.setFont(_font(t, 17 if t.fuente_titulo else 14, True, titulo=True))
            lb.setStyleSheet(f"color:{t.texto};background:transparent;")
            lb.setWordWrap(True)
            lay.addWidget(lb)
        self._body(lay)
        self._x = QPushButton("✕", self)
        self._x.setFixedSize(20, 20)
        self._x.setCursor(Qt.PointingHandCursor)
        self._x.setFocusPolicy(Qt.NoFocus)
        self._x.setStyleSheet(f"QPushButton{{color:{t.texto};background:transparent;border:none;font-size:11px;}}"
                              "QPushButton:hover{background:rgba(255,80,80,190);color:white;border-radius:10px;}")
        self._x.clicked.connect(lambda: self.on_close_req(self))
        self.setStyleSheet("QLabel{background:transparent;}")
        lay.activate()
        self.adjustSize()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._x.move(self.width() - 28 - self._pad - self._sh[0], 8 + self._pad + (6 if self._band else 0))
        self._x.raise_()

    def _a(self, inner: str, target) -> str:
        k = str(len(self._links))
        self._links[k] = target
        return f"<a href='orbi://{k}' style='color:{self.t.enlace};text-decoration:none'>{inner}</a>"

    def _label(self, html: str, size=12) -> QLabel:
        l = QLabel(html)
        l.setTextFormat(Qt.RichText)
        l.setWordWrap(True)
        l.setFont(_font(self.t, size))
        l.setStyleSheet(f"color:{self.t.texto};background:transparent;")
        l.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        l.setOpenExternalLinks(False)
        l.linkActivated.connect(lambda h: self.on_open(self._links.get(str(h).replace("orbi://", ""))))
        return l

    def _body(self, lay: QVBoxLayout) -> None:
        s, tipo, t, ac = self.spec, self.spec["tipo"], self.t, self.ac
        esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
        punto = "▸" if t.id != "terminal" else ">"
        if tipo == "lista":
            rows = []
            for ln in s["lineas"]:
                txt = esc(ln["texto"])
                txt = self._a(txt, ln["target"]) if ln["target"] else _URL.sub(lambda m: self._a(esc(m.group(1)[:40]), m.group(1)), txt)
                rows.append(f"<div style='margin:2px 0'><span style='color:{ac.name()}'>{punto}</span> {txt}</div>")
            lay.addWidget(self._label("".join(rows) or f"<span style='color:{t.tenue}'>Sin datos</span>", 13))
        elif tipo == "texto":
            lay.addWidget(self._label(esc(s["texto"]), 13))
        elif tipo == "cifra":
            big = QLabel(f"{esc(s['valor'])}<span style='font-size:15px;color:{t.tenue}'> {esc(s['unidad'])}</span>")
            big.setTextFormat(Qt.RichText)
            big.setFont(_font(t, 42, True, titulo=True))
            big.setStyleSheet(f"color:{ac.name() if t.paleta_modo != 'relleno' else '#111111'};background:transparent;")
            lay.addWidget(big)
            if s["texto"]:
                lay.addWidget(self._label(f"<span style='color:{t.tenue}'>{esc(s['texto'])}</span>", 12))
        elif tipo == "barras":
            lay.addWidget(_Bars(s["valores"], s["etiquetas"], t, ac))
        elif tipo == "progreso":
            lay.addWidget(_Progress(s["items"], t, ac))
        else:
            im = _Img(s["imagen"], PANEL_W - 32, t)
            if s.get("url"):
                im.setCursor(Qt.PointingHandCursor)
                im.clicked.connect(lambda u=s["url"]: self.on_open(u))
            lay.addWidget(im)
            if s["texto"]:
                lay.addWidget(self._label(f"<span style='color:{t.tenue}'>{esc(s['texto'])}</span>", 12))

    def paintEvent(self, _e):
        self.paint_frame(QPainter(self), self.spec["etiqueta"], self._band)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.on_menu(self, e.globalPosition().toPoint())


# ---------------------------------------------------------------------------------- piezas sueltas de cada distribución
class _Banner(_Hud):
    """Barrita de arriba (cuadrícula): título a la izquierda, hora y fecha a la derecha."""

    def __init__(self, titulo: str, width: int, t, on_menu):
        t = replace(t, paleta=(), paleta_modo="", brillo=False)
        super().__init__(t, 0)
        self.titulo, self.on_menu = (titulo or "ORBI").upper()[:40], on_menu
        self.col, self.ac = (QColor(t.acento), QColor(t.acento))
        self.setFixedSize(width + 2 * self._pad + self._sh[0], 30 + 2 * self._pad + self._sh[1])
        self._t = QTimer(self); self._t.timeout.connect(self.update); self._t.start(1000)

    def paintEvent(self, _e):
        t, p = self.t, QPainter(self)
        self.paint_frame(p)
        r = self.rect().adjusted(self._pad, self._pad, -self._pad - self._sh[0], -self._pad - self._sh[1])
        p.setFont(_font(t, 11, True, titulo=True, spacing=2.0)); p.setPen(self.ac)
        p.drawText(QRect(r.left() + 16, r.top(), r.width() - 140, r.height()), Qt.AlignLeft | Qt.AlignVCenter, "◆ " + self.titulo)
        p.setFont(_font(t, 11, spacing=1.0)); p.setPen(QColor(t.tenue))
        now = datetime.now()
        p.drawText(QRect(r.right() - 150, r.top(), 136, r.height()), Qt.AlignRight | Qt.AlignVCenter, f"{now:%d/%m}  {now:%H:%M}")

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.on_menu(self, e.globalPosition().toPoint())


class _Cabecera(_Hud):
    """Saludo grande arriba a la izquierda y «se cierra en…» + «Cerrar todo» a la derecha (sin marco): lo usa el reloj."""

    def __init__(self, titulo: str, t, dash, width: int):
        super().__init__(t, 0)
        self.dash = dash
        self.setFixedSize(width, 76)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        self.lb_t = QLabel(); self.lb_t.setFont(_font(t, 13)); self.lb_t.setStyleSheet(f"color:{t.tenue};background:transparent;")
        self.bt = QPushButton("Cerrar todo")
        self.bt.setCursor(Qt.PointingHandCursor); self.bt.setFixedHeight(40); self.bt.setFont(_font(t, 13, True))
        self.bt.setStyleSheet(f"QPushButton{{color:{t.texto};background:transparent;border:1px solid rgba({t.borde[0]},{t.borde[1]},{t.borde[2]},140);"
                              f"border-radius:20px;padding:0 20px;}}QPushButton:hover{{border-color:{t.acento};}}")
        self.bt.clicked.connect(dash.ocultar)
        lay.addWidget(self.lb_t); lay.addSpacing(12); lay.addWidget(self.bt)
        self.titulo = titulo or "Tu día"
        self._tm = QTimer(self); self._tm.timeout.connect(self._tick); self._tm.start(1000); self._tick()

    def _tick(self):
        self.lb_t.setText(self.dash.restante_txt())
        self.update()

    def paintEvent(self, _e):
        t, p = self.t, QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(_font(t, 30, True, titulo=True)); p.setPen(QColor(t.texto))
        p.drawText(QRect(0, 0, self.width() - 280, 44), Qt.AlignLeft | Qt.AlignVCenter, self.titulo)
        p.setFont(_font(t, 14)); p.setPen(QColor(t.tenue))
        p.drawText(QRect(0, 44, self.width() - 280, 24), Qt.AlignLeft | Qt.AlignVCenter, _fecha_larga())


def _fecha_larga() -> str:
    d = datetime.now()
    dias = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
    meses = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    return f"{dias[d.weekday()]} {d.day} de {meses[d.month - 1]}"


class _Anillos(_Hud):
    """Órbita: elipses punteadas y tres «lunas» alrededor de la bolita (el mouse las atraviesa)."""

    def __init__(self, t, region: QRect, centro: QPoint):
        super().__init__(t, 0, _FLAGS_CT)
        self.setGeometry(region)
        self.c = centro - region.topLeft()
        self.rx, self.ry = int(region.width() * 0.33), int(region.height() * 0.31)
        self._a = 0.0
        self._tm = QTimer(self); self._tm.timeout.connect(self._giro); self._tm.start(60)

    def _giro(self):
        self._a = (self._a + 0.004) % 6.2832
        self.update()

    def paintEvent(self, _e):
        t, p = self.t, QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(t.borde[0], t.borde[1], t.borde[2], 70)
        p.setBrush(Qt.NoBrush)
        pen = QPen(c, 1.5); pen.setStyle(Qt.DotLine); p.setPen(pen)
        p.drawEllipse(self.c, self.rx, self.ry)
        p.setPen(QPen(QColor(t.borde[0], t.borde[1], t.borde[2], 45), 1))
        p.drawEllipse(self.c, int(self.rx * 0.64), int(self.ry * 0.62))
        p.setPen(Qt.NoPen)
        for k, hexs in enumerate(t.paleta[:3] or (t.acento,)):
            a = self._a + k * 2.0944
            p.setBrush(_c(hexs))
            p.drawEllipse(QPoint(int(self.c.x() + self.rx * math.cos(a)), int(self.c.y() + self.ry * math.sin(a))), 6, 6)


class _Centro(_Hud):
    """Órbita: saludo debajo de la bolita."""

    def __init__(self, titulo: str, t, ancho: int = 520):
        super().__init__(t, 0, _FLAGS_CT)
        self.setFixedSize(ancho, 92)
        self.titulo = titulo or "Tu día"

    def paintEvent(self, _e):
        t, p = self.t, QPainter(self)
        p.setFont(_font(t, 30, True, titulo=True)); p.setPen(QColor(t.texto))
        p.drawText(QRect(0, 0, self.width(), 46), Qt.AlignCenter, self.titulo)
        p.setFont(_font(t, 14)); p.setPen(QColor(t.tenue))
        p.drawText(QRect(0, 48, self.width(), 24), Qt.AlignCenter, _fecha_larga())


_HORA = re.compile(r"^\s*(\d{1,2})[:.](\d{2})(?:\s*[-–a]\s*(\d{1,2})[:.](\d{2}))?\s*[·\-–:]?\s*(.*)$")


def eventos_del_dia(specs: list):
    """(índice del panel, [(hora_inicio, hora_fin, texto)]) del panel de lista con más líneas que empiezan con una hora (HH:MM); (None, []) si no hay."""
    mejor, evs = None, []
    for i, sp in enumerate(specs):
        if sp["tipo"] != "lista":
            continue
        cur = []
        for ln in sp["lineas"]:
            m = _HORA.match(ln["texto"])
            if m:
                h0 = int(m.group(1)) + int(m.group(2)) / 60.0
                h1 = (int(m.group(3)) + int(m.group(4)) / 60.0) if m.group(3) else h0 + 1.0
                if h1 <= h0:
                    h1 = h0 + 1.0
                cur.append((min(h0, 24.0), min(h1, 24.0), m.group(5).strip() or ln["texto"]))
        if len(cur) > len(evs):
            mejor, evs = i, cur
    return mejor, evs


class _Reloj(_Hud):
    """Reloj del día: anillo de 24 h con los eventos como arcos, el punto de «ahora» y el evento en curso al centro."""

    def __init__(self, t, eventos: list, size: int = 560):
        super().__init__(t, 0, _FLAGS_CT)
        self.ev = eventos
        self.setFixedSize(size, size)
        self._tm = QTimer(self); self._tm.timeout.connect(self.update); self._tm.start(20000)

    def _ang(self, h: float) -> float:
        return h / 24.0 * 360.0

    def paintEvent(self, _e):
        t, p = self.t, QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W = self.width()
        cx = cy = W / 2.0
        R = W * 0.38
        ink = QColor(t.texto)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 24) if t.oscuro else QColor(0, 0, 0, 25), 26)); p.drawEllipse(QPoint(int(cx), int(cy)), int(R), int(R))
        for h in range(24):                                      # marcas de cada hora
            a = math.radians(self._ang(h) - 90)
            r1, r2 = R + 26, R + (38 if h % 6 == 0 else 32)
            p.setPen(QPen(QColor(t.tenue), 2 if h % 6 == 0 else 1))
            p.drawLine(int(cx + r1 * math.cos(a)), int(cy + r1 * math.sin(a)), int(cx + r2 * math.cos(a)), int(cy + r2 * math.sin(a)))
        p.setFont(_font(t, 13)); p.setPen(QColor(t.tenue))
        for h in (0, 6, 12, 18):
            a = math.radians(self._ang(h) - 90)
            p.drawText(QRect(int(cx + (R + 50) * math.cos(a)) - 14, int(cy + (R + 50) * math.sin(a)) - 9, 28, 18), Qt.AlignCenter, str(h))
        cols = [QColor(t.acento), QColor("#ffb347"), QColor("#ff5e8a"), QColor("#c9b3a0")]
        box = QRect(int(cx - R), int(cy - R), int(2 * R), int(2 * R))
        for k, (h0, h1, _x) in enumerate(self.ev):               # un arco por evento (los muy cortos se ven como un punto redondo)
            p.setPen(QPen(cols[k % len(cols)], 26, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(box, int((90 - self._ang(h0)) * 16), int(-max(self._ang(h1 - h0), 2.0) * 16))
        now = datetime.now()
        hn = now.hour + now.minute / 60.0
        a = math.radians(self._ang(hn) - 90)
        p.setPen(QPen(ink, 2, Qt.DotLine)); p.drawLine(int(cx + (R - 40) * math.cos(a)), int(cy + (R - 40) * math.sin(a)), int(cx + R * math.cos(a)), int(cy + R * math.sin(a)))
        p.setPen(QPen(QColor(t.ventana), 4)); p.setBrush(ink)
        p.drawEllipse(QPoint(int(cx + R * math.cos(a)), int(cy + R * math.sin(a))), 10, 10)
        actual = next((e for e in self.ev if e[0] <= hn < e[1]), None)
        sig = next((e for e in self.ev if e[0] > hn), None)
        p.setFont(_font(t, 64, True, titulo=True)); p.setPen(ink)
        p.drawText(QRect(0, int(cy - 78), W, 76), Qt.AlignCenter, f"{now:%H:%M}")
        p.setFont(_font(t, 18, True)); p.drawText(QRect(int(cx - 170), int(cy), 340, 28), Qt.AlignCenter, (actual or sig or (0, 0, "Sin eventos hoy"))[2][:34])
        p.setFont(_font(t, 13)); p.setPen(QColor(t.tenue))
        if actual:
            q = int(round((actual[1] - hn) * 60))
            sub = f"termina a las {int(actual[1]):02d}:{int(round((actual[1] % 1) * 60)) % 60:02d} · quedan {q // 60} h {q % 60} min" if q >= 60 else \
                  f"termina a las {int(actual[1]):02d}:{int(round((actual[1] % 1) * 60)) % 60:02d} · quedan {q} min"
        elif sig:
            sub = f"empieza a las {int(sig[0]):02d}:{int(round((sig[0] % 1) * 60)) % 60:02d}"
        else:
            sub = "nada más por hoy"
        p.drawText(QRect(int(cx - 170), int(cy + 30), 340, 22), Qt.AlignCenter, sub)


class _Cinta(_Hud):
    """Barra compacta arriba: un chip por panel (etiqueta + resumen); el de la izquierda abre su panel debajo."""

    def __init__(self, titulo: str, specs: list, t, dash, width: int):
        super().__init__(t, 0)
        self.dash, self.specs, self.chips = dash, specs, []
        self.setFixedSize(width, 68)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 12, 0)
        lay.setSpacing(8)
        lb = QLabel(titulo or "Tu día"); lb.setFont(_font(t, 15, True, titulo=True)); lb.setStyleSheet(f"color:{t.texto};background:transparent;")
        lay.addWidget(lb); lay.addSpacing(10)
        for i, sp in enumerate(specs):
            b = QPushButton(f"{(sp['titulo'] or sp['etiqueta']).upper()[:14]}\n{_resumen(sp)}")
            b.setCheckable(True); b.setFixedHeight(46); b.setMinimumWidth(130); b.setCursor(Qt.PointingHandCursor); b.setFont(_font(t, 12, True))
            b.setStyleSheet(f"QPushButton{{color:{t.texto};background:transparent;border:1px solid transparent;border-radius:14px;padding:0 14px;text-align:left;}}"
                            f"QPushButton:hover{{border-color:rgba({t.borde[0]},{t.borde[1]},{t.borde[2]},120);}}"
                            f"QPushButton:checked{{background:rgba(127,155,255,45);border-color:{t.acento};}}")
            b.clicked.connect(lambda _=False, i=i: dash._cinta_abrir(i))
            lay.addWidget(b); self.chips.append(b)
        lay.addStretch(1)
        self.lb_t = QLabel(); self.lb_t.setFont(_font(t, 12)); self.lb_t.setStyleSheet(f"color:{t.tenue};background:transparent;")
        x = QPushButton("✕"); x.setFixedSize(34, 34); x.setCursor(Qt.PointingHandCursor)
        x.setStyleSheet(f"QPushButton{{color:{t.tenue};background:transparent;border:none;font-size:13px;}}QPushButton:hover{{color:white;background:rgba(255,80,80,190);border-radius:17px;}}")
        x.clicked.connect(dash.ocultar)
        lay.addWidget(self.lb_t); lay.addWidget(x)
        self._tm = QTimer(self); self._tm.timeout.connect(lambda: self.lb_t.setText(self.dash.restante_txt())); self._tm.start(1000)
        self.lb_t.setText(dash.restante_txt())

    def marcar(self, i: int) -> None:
        for k, b in enumerate(self.chips):
            b.setChecked(k == i)

    def paintEvent(self, _e):
        self.paint_frame(QPainter(self))


def _resumen(sp: dict) -> str:
    tp = sp["tipo"]
    if tp == "lista":
        return (sp["lineas"][0]["texto"] if sp["lineas"] else "—")[:22]
    if tp == "cifra":
        return f"{sp['valor']} {sp['unidad']}".strip()[:22]
    if tp == "progreso":
        v = [i["valor"] for i in sp["items"]]
        return f"{sum(v) / len(v):.0f} % en promedio" if v else "—"
    if tp == "barras":
        return f"{len(sp['valores'])} datos"
    if tp == "texto":
        return sp["texto"][:22]
    return (sp["titulo"] or "imagen")[:22]


# ---------------------------------------------------------------------------------- el dashboard
class HudDashboard:
    def __init__(self, get_anchor=None, on_action=None, get_opacity=None, move_orb=None, restore_orb=None, get_tema=None):
        self.get_anchor, self.on_action, self.get_opacity = get_anchor, on_action, get_opacity
        self.move_orb, self.restore_orb = move_orb, restore_orb
        self.get_tema = get_tema or temas.actual
        self.region_override = None                              # solo para pruebas (QRect)
        self.wins: list = []
        self._moved, self._deadline, self._t, self._specs, self._cinta, self._cinta_panel = False, 0.0, None, [], None, None
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.ocultar)

    @property
    def visible(self) -> bool:
        return bool(self.wins)

    def restante_txt(self) -> str:
        s = max(0, int(self._deadline - time.time()))
        return f"se cierra en {s // 60}:{s % 60:02d}"

    def _abrir(self, target) -> None:
        try:
            if target is None:
                return
            if callable(target):
                target()
            elif isinstance(target, dict):
                if target.get("url"):
                    self._abrir(target["url"])
                elif self.on_action and target.get("accion"):
                    self.on_action(target["accion"], target.get("datos") or {})
            else:
                x = str(target)
                if re.match(r"(https?://|mailto:)", x):
                    QDesktopServices.openUrl(QUrl(x))
                elif os.path.exists(x):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(x))
        except Exception:  # noqa: BLE001
            pass

    def _menu(self, win, pos) -> None:
        m = QMenu()
        if isinstance(win, HudPanel):
            m.addAction("Cerrar este panel", lambda: self._cerrar_uno(win))
        m.addAction("Cerrar dashboard", self.ocultar)
        m.exec(pos)

    def _cerrar_uno(self, win) -> None:
        if win in self.wins:
            self.wins.remove(win)
        win.desaparecer()
        if not any(isinstance(w, HudPanel) for w in self.wins) and self._cinta is None:
            self.ocultar()

    def _screen_geo(self):
        if self.region_override is not None:
            return QRect(self.region_override), 52
        ctr = None
        try:
            a = self.get_anchor() if self.get_anchor else None
            ctr, r = (a[0], a[1]) if a else (None, 52)
        except Exception:  # noqa: BLE001
            ctr, r = None, 52
        scr = (QGuiApplication.screenAt(ctr) if ctr is not None else None) or QGuiApplication.primaryScreen()
        return scr.availableGeometry(), int(r)

    def _op(self) -> float:
        return max(0.3, min(1.0, (self.get_opacity() if self.get_opacity else 95) / 100.0))

    def _paneles(self, specs, t):
        return [HudPanel(sp, i, t, self._abrir, self._cerrar_uno, self._menu) for i, sp in enumerate(specs)]

    # ---- punto de entrada
    def mostrar(self, titulo, paneles, segundos: float = 90.0, estilo=None) -> int:
        """Abre el dashboard con el tema actual (o `estilo`). Devuelve cuántos paneles cupieron."""
        specs = normalize(paneles)
        if not specs:
            return 0
        t = temas.get(estilo) if estilo else self.get_tema()
        self._cerrar_ya()
        try:
            seg = max(10.0, min(600.0, float(segundos or 90)))
        except (TypeError, ValueError):
            seg = 90.0
        self._deadline, self._t, self._specs = time.time() + seg, t, specs
        g, r = self._screen_geo()
        fn = {"orbita": self._lay_orbita, "cinta": self._lay_cinta, "reloj": self._lay_reloj}.get(t.layout, self._lay_grid)
        n = fn(titulo, specs, t, g, r)
        if n:
            self._timer.start(int(seg * 1000))
        return n

    def _mover_bolita(self, punto: QPoint) -> None:
        if self.move_orb:
            try:
                self.move_orb(punto)
                self._moved = True
            except Exception:  # noqa: BLE001
                self._moved = False

    def _esquina(self, g: QRect, r: int):
        side = int(r * 3.4)
        corner = QPoint(g.right() - side // 2 - 12, g.bottom() - side // 2 - 12)
        return corner, QRect(corner.x() - side // 2, corner.y() - side // 2, side, side)

    # ---- cuadrícula (vidrio, juego, editorial, terminal, neobrutalista, hud)
    def _lay_grid(self, titulo, specs, t, g, r) -> int:
        region = g.adjusted(24, 24, -24, -24)
        corner, reserved = self._esquina(g, r)
        panels = self._paneles(specs, t)
        sizes = [(p.width(), p.height()) for p in panels]
        pos, cols = plan_layout(sizes, region, reserved, GAP, top=30 + GAP + 2 * (6 if t.brillo else 0))
        shown = [(p, q) for p, q in zip(panels, pos) if q is not None]
        for p, q in zip(panels, pos):
            if q is None:
                p.deleteLater()
        if not shown:
            return 0
        bw = cols * (PANEL_W + 2 * (6 if t.brillo else 0) + (t.sombra[0] if t.sombra else 0)) + (cols - 1) * GAP
        banner = _Banner(titulo, bw, t, self._menu)
        x0 = region.left() + (region.width() - cols * panels[0].width() - (cols - 1) * GAP) // 2
        op = self._op()
        banner.aparecer(QPoint(x0, region.top()), 0, op)
        self.wins = [banner] + [p for p, _ in shown]
        for i, (p, q) in enumerate(shown):
            p.aparecer(q, 120 + i * 90, op)
        self._mover_bolita(corner)
        return len(shown)

    # ---- órbita: la bolita al centro y los paneles alrededor
    def _lay_orbita(self, titulo, specs, t, g, r) -> int:
        region = g.adjusted(24, 24, -24, -24)
        c = g.center() - QPoint(0, 24)
        side = int(r * 4.2)
        reserved = QRect(c.x() - side // 2, c.y() - side // 2, side, side + 110)            # la bolita y su saludo
        panels = self._paneles(specs, t)
        ph = lambda p: (p.width(), p.height())                                              # noqa: E731
        slots = ("TL", "TR", "BL", "BR", "TC", "BC", "ML", "MR")
        placed, shown = [], []
        for p in panels:
            w, h = ph(p)
            for s in slots:
                x = region.left() if s[1] == "L" else region.right() - w + 1 if s[1] == "R" else region.center().x() - w // 2
                if s == "ML":
                    x, y = region.left(), region.center().y() - h // 2
                elif s == "MR":
                    x, y = region.right() - w + 1, region.center().y() - h // 2
                elif s[0] == "T":
                    y = region.top() + (60 if s in ("TC",) else 0)
                else:
                    y = region.bottom() - h + 1
                rect = QRect(x, y, w, h)
                if rect.intersects(reserved) or any(rect.intersects(o.adjusted(-8, -8, 8, 8)) for o in placed) or not region.contains(rect):
                    continue
                placed.append(rect); shown.append((p, rect.topLeft(), s)); slots = tuple(k for k in slots if k != s)
                break
            else:
                p.deleteLater()
        if not shown:
            return 0
        op = self._op()
        anillos = _Anillos(t, g, c)
        centro = _Centro(titulo, t)
        anillos.aparecer(g.topLeft(), 0, 1.0, QPoint(0, 0))
        centro.aparecer(QPoint(c.x() - centro.width() // 2, c.y() + int(r * 1.45)), 200, op, QPoint(0, 10))
        self.wins = [anillos, centro] + [p for p, _, _ in shown]
        desde = {"TL": QPoint(-40, -20), "TR": QPoint(40, -20), "BL": QPoint(-40, 20), "BR": QPoint(40, 20), "TC": QPoint(0, -30), "BC": QPoint(0, 30), "ML": QPoint(-40, 0), "MR": QPoint(40, 0)}
        for i, (p, q, s) in enumerate(shown):
            p.aparecer(q, 150 + i * 110, op, desde[s])
        self._mover_bolita(c)
        return len(shown)

    # ---- reloj: anillo de 24 h al centro y las demás tarjetas a los lados
    def _lay_reloj(self, titulo, specs, t, g, r) -> int:
        region = g.adjusted(24, 24, -24, -24)
        corner, reserved = self._esquina(g, r)
        idx, evs = eventos_del_dia(specs)
        resto = [sp for i, sp in enumerate(specs) if i != idx] if evs else list(specs)
        panels = self._paneles(resto, t)
        size = min(560, region.height() - 160, region.width() - 2 * (PANEL_W + 40))
        size = max(360, size)
        anillo = _Reloj(t, evs, size)
        cab = _Cabecera(titulo, t, self, region.width())
        cols_y = {"L": region.top() + 96, "R": region.top() + 96}
        shown = []
        for i, p in enumerate(panels):
            lado = "L" if i % 2 == 0 else "R"
            x = region.left() if lado == "L" else region.right() - p.width() + 1
            rect = QRect(x, cols_y[lado], p.width(), p.height())
            if rect.bottom() > region.bottom() or rect.intersects(reserved):
                p.deleteLater()
                continue
            cols_y[lado] = rect.bottom() + 1 + GAP
            shown.append((p, rect.topLeft(), lado))
        if not shown and not evs:
            return 0
        op = self._op()
        self.wins = [cab, anillo] + [p for p, _, _ in shown]
        cab.aparecer(region.topLeft(), 0, op, QPoint(0, -12))
        cx = region.center().x() - size // 2
        anillo.aparecer(QPoint(cx, region.top() + 100 + max(0, (region.height() - 100 - size) // 2 - 20)), 150, op, QPoint(0, 16))
        for i, (p, q, lado) in enumerate(shown):
            p.aparecer(q, 250 + i * 110, op, QPoint(-40 if lado == "L" else 40, 0))
        self._mover_bolita(corner)
        return len(shown) + (1 if evs else 0)

    # ---- cinta: barra arriba y un panel a la vez
    def _lay_cinta(self, titulo, specs, t, g, r) -> int:
        region = g.adjusted(24, 24, -24, -24)
        width = min(region.width(), 1328)
        bar = _Cinta(titulo, specs, t, self, width)
        self._cinta = bar
        x0 = region.left() + (region.width() - width) // 2
        self.wins = [bar]
        bar.aparecer(QPoint(x0, region.top()), 0, self._op(), QPoint(0, -16))
        self._cinta_pos = (x0, region.top() + 68 + 8, region)
        self._cinta_abrir(0)
        return len(specs)

    def _cinta_abrir(self, i: int) -> None:
        if self._cinta is None or i >= len(self._specs):
            return
        if self._cinta_panel is not None:
            if self._cinta_panel in self.wins:
                self.wins.remove(self._cinta_panel)
            self._cinta_panel.desaparecer()
        t = self._t
        p = HudPanel(self._specs[i], 0, t, self._abrir, lambda _w: self._cinta_cerrar_panel(), self._menu)
        x0, y, region = self._cinta_pos
        chip = self._cinta.chips[i]
        x = max(region.left(), min(x0 + chip.x(), region.right() - p.width()))
        self._cinta.marcar(i)
        self._cinta_panel = p
        self.wins.append(p)
        p.aparecer(QPoint(x, y), 0, self._op(), QPoint(0, -10))

    def _cinta_cerrar_panel(self) -> None:
        if self._cinta_panel is not None:
            if self._cinta_panel in self.wins:
                self.wins.remove(self._cinta_panel)
            self._cinta_panel.desaparecer()
            self._cinta_panel = None
            if self._cinta:
                self._cinta.marcar(-1)

    def _cerrar_ya(self) -> None:
        self._timer.stop()
        for w in self.wins:
            w.close()
            w.deleteLater()
        self.wins, self._cinta, self._cinta_panel = [], None, None

    def ocultar(self) -> None:
        self._timer.stop()
        for i, w in enumerate(self.wins):
            w.desaparecer(i * 40)
        self.wins, self._cinta, self._cinta_panel = [], None, None
        if self._moved and self.restore_orb:
            try:
                self.restore_orb()
            except Exception:  # noqa: BLE001
                pass
        self._moved = False
