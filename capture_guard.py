"""Que Orbi NO salga en sus propias capturas de pantalla.

Orbi captura el monitor entero para «ver». Como su bolita, su burbuja y su chat son ventanas encima de todo, si estaban sobre lo
que estás escribiendo, TAPABAN ese texto en la captura y la IA no lo veía. Windows permite marcar una ventana como «excluida de
las capturas» (SetWindowDisplayAffinity con WDA_EXCLUDEFROMCAPTURE, Windows 10 versión 2004 o más nueva): tú la sigues viendo,
pero en la captura aparece lo que hay DEBAJO.

Efecto secundario: Orbi tampoco sale en tus capturas de pantalla, grabaciones ni al compartir pantalla (Discord, Meet...).
Se puede apagar desde el menú de la bolita («Ocultar a Orbi en capturas y pantalla compartida») o con
"ocultar_orbi_en_capturas": false en config.json.
"""
import sys

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011

_state = {"on": True, "filter": None}


def _apply(widget, on: bool) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()),
                                                                  WDA_EXCLUDEFROMCAPTURE if on else WDA_NONE))
    except Exception:                                   # noqa: BLE001  (Windows viejo o ventana sin handle: no pasa nada)
        return False


def enabled() -> bool:
    return bool(_state["on"])


def set_enabled(on: bool) -> None:
    """Enciende/apaga la exclusión en TODAS las ventanas de Orbi (las futuras se marcan al mostrarse)."""
    _state["on"] = bool(on)
    from PySide6.QtWidgets import QApplication
    for w in QApplication.topLevelWidgets():
        if w.isWindow():
            _apply(w, _state["on"])


def install(app, on: bool = True):
    """Marca cada ventana de Orbi al mostrarse (la bolita, la burbuja, el chat, los diálogos) y las que ya existen."""
    from PySide6.QtCore import QObject, QEvent
    from PySide6.QtWidgets import QWidget

    class _Filter(QObject):
        def eventFilter(self, obj, ev):                 # noqa: N802
            if _state["on"] and ev.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
                _apply(obj, True)
            return False

    _state["on"] = bool(on)
    f = _Filter(app)
    app.installEventFilter(f)
    _state["filter"] = f                                # que no lo recoja el recolector de basura
    set_enabled(on)
    return f
