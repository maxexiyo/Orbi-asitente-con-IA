"""Escribir texto como si fuera el teclado (SendInput con KEYEVENTF_UNICODE).

Por qué no el portapapeles: Discord y otras apps Electron leen el portapapeles de forma asíncrona; si Orbi lo restauraba
muy pronto, pegaba el texto viejo (o nada) y "a veces sí, a veces no". SendInput manda cada carácter directo, con
acentos, ñ y emojis, y no toca tu portapapeles.
"""
import ctypes, sys, time
from ctypes import wintypes

KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
INPUT_KEYBOARD = 1
VK_RETURN, VK_SHIFT = 0x0D, 0x10


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16), ("wParamH", ctypes.c_uint16)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUT_UNION)]


def _unicode_events(text: str, newline_shift: bool):
    """Lista de INPUT para el texto. Los saltos de línea: Shift+Enter (en chats Enter enviaría el mensaje)."""
    ev = []
    data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-16-le")
    units = [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]
    for unit in units:
        if unit == 0x0A:
            vk_events = []
            if newline_shift:
                vk_events.append((VK_SHIFT, 0))
            vk_events.append((VK_RETURN, 0))
            vk_events.append((VK_RETURN, KEYEVENTF_KEYUP))
            if newline_shift:
                vk_events.append((VK_SHIFT, KEYEVENTF_KEYUP))
            for vk, fl in vk_events:
                i = INPUT(type=INPUT_KEYBOARD); i.u.ki = KEYBDINPUT(vk, 0, fl, 0, 0); ev.append(i)
            continue
        for fl in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            i = INPUT(type=INPUT_KEYBOARD); i.u.ki = KEYBDINPUT(0, unit, fl, 0, 0); ev.append(i)
    return ev


def type_text(text: str, newline_shift: bool = True, batch: int = 40, delay: float = 0.008) -> bool:
    """Escribe `text` en la ventana en foco. Devuelve False si no es Windows o SendInput falló."""
    if sys.platform != "win32":
        return False
    send = ctypes.windll.user32.SendInput
    send.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    send.restype = wintypes.UINT
    events = _unicode_events(text, newline_shift)
    step = batch * 2
    for i in range(0, len(events), step):
        chunk = events[i:i + step]
        arr = (INPUT * len(chunk))(*chunk)
        if send(len(chunk), arr, ctypes.sizeof(INPUT)) != len(chunk):
            return False
        time.sleep(delay)                     # deja que la app procese (Electron se traba si le llega todo junto)
    return True
