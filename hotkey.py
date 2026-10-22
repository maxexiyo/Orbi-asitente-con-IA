"""Atajos globales (Windows, sin librerías extra ni permisos de administrador).

  Ctrl+Espacio       abre/cierra el chat de texto
  Ctrl+Alt+Espacio   "hablar ahora": abre la ventana de conversación (modo palabra/atajo)
  Ctrl+Alt+O         trae a Orbi de vuelta si se perdió detrás de otra ventana
"""
import sys, threading

from PySide6.QtCore import QObject, Signal

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
VK_SPACE, VK_O, WM_HOTKEY = 0x20, 0x4F, 0x0312


class GlobalHotkey(QObject):
    pressed = Signal()

    def __init__(self, mods=MOD_CONTROL, vk=VK_SPACE, hid=1, label="Ctrl+Espacio"):
        super().__init__()
        self.mods, self.vk, self.hid, self.label = mods, vk, hid, label

    def start(self):
        if sys.platform != "win32":
            return
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, self.hid, self.mods | MOD_NOREPEAT, self.vk):
            print(f"[atajo] No pude registrar {self.label} (¿otra app lo usa?).")
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and msg.wParam == self.hid:
                self.pressed.emit()
        user32.UnregisterHotKey(None, self.hid)
