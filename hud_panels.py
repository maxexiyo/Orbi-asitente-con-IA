"""Modo DASHBOARD de Orbi: varios paneles estilo HUD (borde neón, esquinas, líneas de escaneo) que Orbi suelta de golpe
cuando la respuesta se entiende mejor viéndola en conjunto (resumen del día, agenda + correos + alarmas, comparaciones...).

La bolita NO cambia de diseño: solo (opcional) se va a la esquina inferior derecha mientras el dashboard está abierto y vuelve
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
  dash = HudDashboard(get_anchor, on_action=None, get_opacity=None, move_orb=None, restore_orb=None)
  dash.mostrar(titulo, paneles, segundos=90)   -> abre (reemplaza el anterior)
  dash.ocultar()                               -> cierra con animación
  parse_paneles(raw) -> (lista_normalizada, error)   (raw = JSON en texto, lista o dict con "paneles")
"""
import json
import math
import os
import re
import threading
import urllib.request
from datetime import datetime

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QTimer, QUrl, QVariantAnimation, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

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


# ---------------------------------------------------------------------------------- piezas de dibujo
class _Bars(QWidget):
    def __init__(self, valores, etiquetas, parent=None):
        super().__init__(parent)
        self.v, self.e, self.k = valores, etiquetas, 0.0
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
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n, mx = len(self.v), max(max(self.v), 1e-9)
        slot = self.width() / n
        bw = min(26.0, slot * 0.6)
        base = self.height() - 16
        f = QFont(self.font()); f.setPixelSize(10); p.setFont(f)
        p.setPen(QPen(QColor(90, 200, 255, 60), 1))
        p.drawLine(0, base, self.width(), base)
        for i, v in enumerate(self.v):
            h = max(2.0, (base - 14) * (v / mx) * self.k)
            x = slot * i + (slot - bw) / 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(90, 200, 255, 215 if v == mx else 140))
            p.drawRect(int(x), int(base - h), int(bw), int(h))
            p.setPen(QColor(220, 235, 247, 230))
            txt = f"{v:g}"
            p.drawText(QRect(int(x - 6), int(base - h - 14), int(bw + 12), 13), Qt.AlignCenter, txt)
            p.setPen(QColor(127, 155, 179))
            p.drawText(QRect(int(slot * i), base + 2, int(slot), 13), Qt.AlignCenter, self.e[i] if i < len(self.e) else "")


class _Progress(QWidget):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.items, self.k = items, 0.0
        self.setFixedHeight(max(28, 32 * len(items)))
        self._an = QVariantAnimation(self, duration=800, startValue=0.0, endValue=1.0)
        self._an.setEasingCurve(QEasingCurve.OutCubic)
        self._an.valueChanged.connect(self._set_k)
        QTimer.singleShot(250, self._an.start)

    def _set_k(self, k):
        self.k = float(k)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font()); f.setPixelSize(11); p.setFont(f)
        for i, it in enumerate(self.items):
            y = i * 32
            p.setPen(QColor(220, 235, 247))
            p.drawText(QRect(0, y, self.width() - 40, 14), Qt.AlignLeft | Qt.AlignVCenter, it["etiqueta"])
            p.setPen(QColor(160, 228, 255))
            p.drawText(QRect(self.width() - 40, y, 40, 14), Qt.AlignRight | Qt.AlignVCenter, f"{it['valor']:.0f}%")
            ty = y + 18
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(90, 200, 255, 38))
            p.drawRect(0, ty, self.width(), 6)
            w = int(self.width() * it["valor"] / 100.0 * self.k)
            p.setBrush(QColor(90, 200, 255, 230))
            p.drawRect(0, ty, w, 6)
            if w > 2:  # puntito brillante en la punta
                p.setBrush(ACC_HI)
                p.drawRect(max(0, w - 3), ty - 1, 3, 8)


class _Img(QLabel):
    clicked = Signal()
    _got = Signal(bytes)

    def __init__(self, src, w, h=104, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:rgba(90,200,255,16);border:1px solid rgba(90,200,255,60);")
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


# ---------------------------------------------------------------------------------- una ventanita HUD
_FLAGS = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus


class _Hud(QWidget):
    """Base: ventana sin foco con fade + deslizamiento de entrada y de salida."""

    def __init__(self):
        super().__init__(None, _FLAGS)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._flash = 0.0
        self._op = 0.95
        self._anims = []

    def aparecer(self, target: QPoint, delay: int, op: float) -> None:
        self._op = op

        def go():
            self.setWindowOpacity(0.0)
            self.move(target + QPoint(0, 22))
            self.show()
            a = QPropertyAnimation(self, b"pos", self, duration=380, startValue=target + QPoint(0, 22), endValue=target)
            a.setEasingCurve(QEasingCurve.OutCubic)
            b = QPropertyAnimation(self, b"windowOpacity", self, duration=300, startValue=0.0, endValue=op)
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

    def paint_frame(self, p: QPainter, tag: str, header: bool = True) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(BG)
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor(120, 200, 255, 9))                       # líneas de escaneo
        for y in range(r.top() + 2, r.bottom(), 3):
            p.drawLine(r.left() + 1, y, r.right() - 1, y)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(90, 200, 255, int(105 + 120 * self._flash)), 1))
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QPen(QColor(160, 228, 255, 240), 2))            # esquinas
        L, x0, y0, x1, y1 = 12, r.left(), r.top(), r.right(), r.bottom()
        for (cx, cy, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            p.drawLine(cx, cy, cx + dx * L, cy)
            p.drawLine(cx, cy, cx, cy + dy * L)
        if header:
            f = QFont(self.font()); f.setPixelSize(10); f.setBold(True); f.setLetterSpacing(QFont.AbsoluteSpacing, 1.6)
            p.setFont(f)
            p.setPen(ACC)
            p.drawText(QRect(16, 7, self.width() - 60, 16), Qt.AlignLeft | Qt.AlignVCenter, "◆ " + tag)
            p.setPen(QColor(90, 200, 255, 55))
            p.drawLine(16, 27, self.width() - 16, 27)


class _Banner(_Hud):
    """Barrita de arriba del dashboard: título a la izquierda, hora y fecha a la derecha."""

    def __init__(self, titulo: str, width: int, on_menu):
        super().__init__()
        self.titulo, self.on_menu = (titulo or "ORBI").upper()[:40], on_menu
        self.setFixedSize(width, 30)
        self._t = QTimer(self); self._t.timeout.connect(self.update); self._t.start(1000)

    def paintEvent(self, _e):
        p = QPainter(self)
        self.paint_frame(p, "", header=False)
        f = QFont(self.font()); f.setPixelSize(11); f.setBold(True); f.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        p.setFont(f)
        p.setPen(ACC_HI)
        p.drawText(QRect(16, 0, self.width() - 140, 30), Qt.AlignLeft | Qt.AlignVCenter, "◆ " + self.titulo)
        f.setBold(False); f.setLetterSpacing(QFont.AbsoluteSpacing, 1.0); p.setFont(f)
        p.setPen(QColor(160, 190, 215))
        now = datetime.now()
        p.drawText(QRect(self.width() - 150, 0, 136, 30), Qt.AlignRight | Qt.AlignVCenter, f"{now:%d/%m}  {now:%H:%M}")

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.on_menu(self, e.globalPosition().toPoint())


class HudPanel(_Hud):
    def __init__(self, spec: dict, on_open, on_close, on_menu):
        super().__init__()
        self.spec, self.on_open, self.on_close_req, self.on_menu = spec, on_open, on_close, on_menu
        self._links: dict = {}
        self.setFixedWidth(PANEL_W)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 34, 16, 14)
        lay.setSpacing(8)
        if spec["titulo"]:
            t = QLabel((spec["icono"] + " " if spec["icono"] else "") + spec["titulo"])
            t.setStyleSheet(f"color:#ffffff;font-size:14px;font-weight:bold;")
            t.setWordWrap(True)
            lay.addWidget(t)
        self._body(lay)
        self._x = QPushButton("✕", self)
        self._x.setFixedSize(18, 18)
        self._x.setCursor(Qt.PointingHandCursor)
        self._x.setFocusPolicy(Qt.NoFocus)
        self._x.setStyleSheet("QPushButton{color:#8fb4cf;background:transparent;border:none;font-size:11px;}"
                              "QPushButton:hover{color:#fff;background:rgba(255,80,80,150);border-radius:9px;}")
        self._x.clicked.connect(lambda: self.on_close_req(self))
        self.setStyleSheet("QLabel{background:transparent;}")
        lay.activate()
        self.adjustSize()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._x.move(self.width() - 26, 5)

    # --- contenido por tipo
    def _a(self, inner: str, target) -> str:
        k = str(len(self._links))
        self._links[k] = target
        return f"<a href='orbi://{k}' style='{LINK}'>{inner}</a>"

    def _label(self, html: str, size=12) -> QLabel:
        l = QLabel(html)
        l.setTextFormat(Qt.RichText)
        l.setWordWrap(True)
        l.setStyleSheet(f"color:{TXT};font-size:{size}px;")
        l.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        l.setOpenExternalLinks(False)
        l.linkActivated.connect(lambda h: self.on_open(self._links.get(str(h).replace("orbi://", ""))))
        return l

    def _body(self, lay: QVBoxLayout) -> None:
        s, tipo = self.spec, self.spec["tipo"]
        esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
        if tipo == "lista":
            rows = []
            for ln in s["lineas"]:
                txt = esc(ln["texto"])
                if ln["target"]:
                    txt = self._a(txt, ln["target"])
                else:
                    txt = _URL.sub(lambda m: self._a(esc(m.group(1)[:40]), m.group(1)), txt)
                rows.append(f"<div style='margin:2px 0'><span style='color:#5ac8ff'>▸</span> {txt}</div>")
            lay.addWidget(self._label("".join(rows) or f"<span style='color:{DIM}'>Sin datos</span>"))
        elif tipo == "texto":
            lay.addWidget(self._label(esc(s["texto"])))
        elif tipo == "cifra":
            big = QLabel(f"{esc(s['valor'])}<span style='font-size:15px;color:{DIM}'> {esc(s['unidad'])}</span>")
            big.setTextFormat(Qt.RichText)
            big.setStyleSheet("color:#a0e4ff;font-size:40px;font-weight:bold;")
            lay.addWidget(big)
            if s["texto"]:
                lay.addWidget(self._label(f"<span style='color:{DIM}'>{esc(s['texto'])}</span>", 11))
        elif tipo == "barras":
            lay.addWidget(_Bars(s["valores"], s["etiquetas"]))
        elif tipo == "progreso":
            lay.addWidget(_Progress(s["items"]))
        else:
            im = _Img(s["imagen"], PANEL_W - 32)
            if s.get("url"):
                im.setCursor(Qt.PointingHandCursor)
                im.clicked.connect(lambda u=s["url"]: self.on_open(u))
            lay.addWidget(im)
            if s["texto"]:
                lay.addWidget(self._label(f"<span style='color:{DIM}'>{esc(s['texto'])}</span>", 11))

    def paintEvent(self, _e):
        self.paint_frame(QPainter(self), self.spec["etiqueta"])

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.on_menu(self, e.globalPosition().toPoint())


# ---------------------------------------------------------------------------------- el dashboard
class HudDashboard:
    def __init__(self, get_anchor=None, on_action=None, get_opacity=None, move_orb=None, restore_orb=None):
        self.get_anchor, self.on_action, self.get_opacity = get_anchor, on_action, get_opacity
        self.move_orb, self.restore_orb = move_orb, restore_orb
        self.wins: list = []
        self._moved = False
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.ocultar)

    @property
    def visible(self) -> bool:
        return bool(self.wins)

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
                t = str(target)
                if re.match(r"(https?://|mailto:)", t):
                    QDesktopServices.openUrl(QUrl(t))
                elif os.path.exists(t):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(t))
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
        if not any(isinstance(w, HudPanel) for w in self.wins):
            self.ocultar()

    def _screen_geo(self):
        ctr = None
        try:
            a = self.get_anchor() if self.get_anchor else None
            ctr, r = (a[0], a[1]) if a else (None, 52)
        except Exception:  # noqa: BLE001
            ctr, r = None, 52
        scr = (QGuiApplication.screenAt(ctr) if ctr is not None else None) or QGuiApplication.primaryScreen()
        return scr.availableGeometry(), int(r)

    def mostrar(self, titulo, paneles, segundos: float = 90.0) -> int:
        """Abre el dashboard. Devuelve cuántos paneles cupieron."""
        specs = normalize(paneles)
        if not specs:
            return 0
        self._cerrar_ya()
        g, r = self._screen_geo()
        region = g.adjusted(24, 24, -24, -24)
        side = int(r * 3.4)                                       # zona de la bolita en la esquina: nada se pone encima
        corner = QPoint(g.right() - side // 2 - 12, g.bottom() - side // 2 - 12)
        reserved = QRect(corner.x() - side // 2, corner.y() - side // 2, side, side)
        panels = [HudPanel(sp, self._abrir, self._cerrar_uno, self._menu) for sp in specs]
        sizes = [(p.width(), p.height()) for p in panels]
        pos, cols = plan_layout(sizes, region, reserved, GAP, top=30 + GAP)
        shown = [(p, q) for p, q in zip(panels, pos) if q is not None]
        for p, q in zip(panels, pos):
            if q is None:
                p.deleteLater()
        if not shown:
            return 0
        bw = cols * PANEL_W + (cols - 1) * GAP
        banner = _Banner(titulo, bw, self._menu)
        op = max(0.3, min(1.0, (self.get_opacity() if self.get_opacity else 95) / 100.0))
        x0 = region.left() + (region.width() - bw) // 2
        banner.aparecer(QPoint(x0, region.top()), 0, op)
        self.wins = [banner] + [p for p, _ in shown]
        for i, (p, q) in enumerate(shown):
            p.aparecer(q, 120 + i * 90, op)
        if self.move_orb:
            try:
                self.move_orb(corner)
                self._moved = True
            except Exception:  # noqa: BLE001
                self._moved = False
        try:
            seg = max(10.0, min(600.0, float(segundos or 90)))
        except (TypeError, ValueError):
            seg = 90.0
        self._timer.start(int(seg * 1000))
        return len(shown)

    def _cerrar_ya(self) -> None:
        self._timer.stop()
        for w in self.wins:
            w.close()
            w.deleteLater()
        self.wins = []

    def ocultar(self) -> None:
        self._timer.stop()
        for i, w in enumerate(self.wins):
            w.desaparecer(i * 40)
        self.wins = []
        if self._moved and self.restore_orb:
            try:
                self.restore_orb()
            except Exception:  # noqa: BLE001
                pass
        self._moved = False
