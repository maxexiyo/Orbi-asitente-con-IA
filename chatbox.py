"""Cajita para escribirle a la bolita (aparece junto a ella)."""
import sys

from PySide6.QtCore import Qt, QTimer, QEvent, QPoint, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget, QLineEdit, QVBoxLayout


def force_focus(widget):
    """Windows no deja que una ventana 'robe' el foco; este truco lo permite al usar el atajo global."""
    widget.raise_()
    widget.activateWindow()
    if sys.platform == "win32":
        try:
            import ctypes
            u = ctypes.windll.user32
            u.keybd_event(0x12, 0, 0, 0)          # presiona y suelta ALT
            u.keybd_event(0x12, 0, 2, 0)
            u.SetForegroundWindow(int(widget.winId()))
        except Exception:
            pass


class ChatBox(QWidget):
    submitted = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escríbele a Orbi…  (Enter envía · Esc cierra)")
        self.input.setFixedWidth(340)
        self.input.setStyleSheet(
            "QLineEdit { background: rgba(18,28,58,240); color: #eaf2ff; font: 14px 'Segoe UI';"
            " border: 1px solid rgba(120,170,255,160); border-radius: 16px; padding: 10px 14px; }"
            "QLineEdit:focus { border: 1px solid rgba(140,200,255,255); }")
        lay.addWidget(self.input)
        self.adjustSize()
        self.input.returnPressed.connect(self._send)
        self._was_active = False

    def _send(self):
        text = self.input.text().strip()
        self.input.clear()
        self.hide()
        if text:
            self.submitted.emit(text)

    def open_near(self, anchor: QPoint, orb_radius: int):
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = anchor.x() - w // 2
        y = anchor.y() + orb_radius + 14                       # debajo de la bolita
        if y + h > g.bottom() - 4:                             # no cabe -> al costado
            y = anchor.y() - h // 2
            x = anchor.x() + orb_radius + 16
            if x + w > g.right() - 4:
                x = anchor.x() - orb_radius - 16 - w
        x = max(g.left() + 4, min(x, g.right() - w - 4))
        y = max(g.top() + 4, min(y, g.bottom() - h - 4))
        self.move(x, y)
        self._was_active = False
        self.show()
        force_focus(self)
        self.input.setFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.input.clear(); self.hide()
        else:
            super().keyPressEvent(e)

    def changeEvent(self, e):
        if e.type() == QEvent.ActivationChange:
            if self.isActiveWindow():
                self._was_active = True
            elif self._was_active and self.isVisible():
                QTimer.singleShot(250, self._hide_if_inactive)   # si hacen clic afuera, se cierra
        super().changeEvent(e)

    def _hide_if_inactive(self):
        if self.isVisible() and not self.isActiveWindow() and not self.input.text():
            self.hide()
