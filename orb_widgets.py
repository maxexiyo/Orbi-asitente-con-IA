"""Ventanitas auxiliares de Orbi: burbuja de texto (Bubble) y puntero que señala (Pointer)."""
import math, time
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QPoint
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QFont, QFontMetrics
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from orb_consts import *


class Bubble(QWidget):
    """Burbuja de texto que flota sobre la bolita."""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(); self.label.setWordWrap(True); self.label.setMaximumWidth(340)
        self.label.setStyleSheet(
            "background: rgba(18,28,58,235); color: #eaf2ff; border: 1px solid rgba(120,170,255,120);"
            "border-radius: 16px; padding: 10px 14px; font-size: 14px; font-family: 'Segoe UI';")
        lay.addWidget(self.label)
        self.hide_timer = QTimer(self); self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

    def show_text(self, text, anchor: QPoint, orb_radius, seconds=None):
        self.label.setText(text)
        self.label.adjustSize(); self.adjustSize()
        self.place(anchor, orb_radius)
        self.show()
        seconds = seconds if seconds is not None else max(3.5, min(14, len(text) * 0.07))
        self.hide_timer.start(int(seconds * 1000))

    def place(self, anchor: QPoint, orb_radius):
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x = anchor.x() - self.width() // 2
        y = anchor.y() - orb_radius - 18 - self.height()
        if y < g.top() + 4:                      # no cabe arriba -> abajo
            y = anchor.y() + orb_radius + 18
        x = max(g.left() + 4, min(x, g.right() - self.width() - 4))
        self.move(x, y)


class Pointer(QWidget):
    """Anillo pulsante transparente al ratón para SEÑALAR algo en la pantalla."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(170, 170)
        self._t0 = 0.0; self._until = 0.0
        self._timer = QTimer(self); self._timer.timeout.connect(self._tick)

    def show_at(self, gx, gy, seconds=5.0):
        self.move(int(gx - 85), int(gy - 85))
        self._t0 = time.time(); self._until = self._t0 + seconds
        self.show(); self.raise_(); self._timer.start(16)

    def _tick(self):
        if time.time() > self._until:
            self._timer.stop(); self.hide(); return
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        now = time.time(); t = now - self._t0
        fade = max(0.0, min(1.0, (self._until - now) / 0.6))
        c = QPointF(85, 85)
        for k in (0.0, 0.5):
            ph = (t * 1.2 + k) % 1.0
            col = QColor(255, 190, 60, int(230 * (1 - ph) * fade))
            p.setBrush(Qt.NoBrush); p.setPen(QPen(col, 4))
            rr = 14 + ph * 58
            p.drawEllipse(c, rr, rr)
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 120, 40, int(230 * fade)))
        p.drawEllipse(c, 6, 6)


# ------------------------------------------------------------------ lenguaje corporal libre (cuerpo.py)
# Cada gesto es una función (u 0..1, k intensidad) -> desplazamientos que se SUMAN al baile y al resto: ghx/ghy (cabeza), grot (inclinación,
# grados), gdx/gdy (cuerpo), gsc (escala). Los dispara la IA con la herramienta `lenguaje_corporal`; aquí solo se animan en local.
