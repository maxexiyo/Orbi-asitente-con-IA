"""Ventanas de Windows (ctypes, sin librerías extra).

Lo importante: se puede LISTAR, CERRAR y MINIMIZAR ventanas SIN enfocarlas (PostMessage/ShowWindow),
así que "cierra todas las ventanas del explorador" ya no tiene que ir ventana por ventana en pantalla.
"""
import os, sys, time

OWN_TITLES = ("Orbi pide permiso", "Orbi — configuración", "Orbi")   # ventanas de Orbi: no son "del usuario"
PROTECTED_EXES = {"csrss.exe", "winlogon.exe", "dwm.exe", "lsass.exe", "services.exe", "searchhost.exe",
                  "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe"}


def _api():
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsIconic.argtypes = [wintypes.HWND]
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.GetForegroundWindow.restype = wintypes.HWND
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD)]
    return ctypes, wintypes, u, k


def _text(u, ctypes, hwnd) -> str:
    n = u.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _cls(u, ctypes, hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _pid_exe(u, k, ctypes, wintypes, hwnd):
    pid = wintypes.DWORD(0)
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    h = k.OpenProcess(0x1000, False, pid.value)          # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                exe = os.path.basename(buf.value).lower()
        finally:
            k.CloseHandle(h)
    return pid.value, exe


def list_windows() -> list:
    """[dict(hwnd, title, cls, exe, pid)] de las ventanas visibles normales (las que verías en Alt+Tab)."""
    if sys.platform != "win32":
        return []
    ctypes, wintypes, u, k = _api()
    dwm = ctypes.windll.dwmapi
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        title = _text(u, ctypes, hwnd)
        if not title or title == "Program Manager" or title in OWN_TITLES:
            return True
        if u.GetWindowLongW(hwnd, -20) & 0x80:            # WS_EX_TOOLWINDOW
            return True
        cloaked = wintypes.DWORD(0)                       # ventanas "fantasma" de apps UWP
        dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value:
            return True
        pid, exe = _pid_exe(u, k, ctypes, wintypes, hwnd)
        if pid == os.getpid():
            return True
        out.append(dict(hwnd=int(hwnd), title=title, cls=_cls(u, ctypes, hwnd), exe=exe, pid=pid))
        return True

    u.EnumWindows(cb, 0)
    return out


def match_windows(app: str = "", title: str = "") -> list:
    """Ventanas cuyo exe/clase contiene `app` (ej. 'explorer', 'chrome') y/o cuyo título contiene `title`."""
    app, title = (app or "").lower().strip(), (title or "").lower().strip()
    res = []
    for w in list_windows():
        if w["exe"] in PROTECTED_EXES:
            continue
        exe_name = w["exe"].removesuffix(".exe")
        ok_app = (not app) or app in exe_name or app in w["cls"].lower() or \
                 (app in ("explorador", "explorer", "carpetas") and w["cls"] == "CabinetWClass")
        ok_title = (not title) or title in w["title"].lower()
        if ok_app and ok_title:
            res.append(w)
    return res


def close_window(hwnd: int) -> bool:
    """Pide cerrar la ventana (WM_CLOSE) SIN enfocarla. Si tiene cambios sin guardar, la app preguntará como siempre."""
    if sys.platform != "win32":
        return False
    ctypes, wintypes, u, k = _api()
    try:                                                # nunca cierres lo que mantiene vivo a Orbi
        import os as _os
        k.GetConsoleWindow.restype = wintypes.HWND
        if hwnd and hwnd == (k.GetConsoleWindow() or 0):
            return False                                # la consola donde corre Orbi
        pid = wintypes.DWORD(0)
        u.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        if pid.value == _os.getpid():
            return False                                # ventanas de Orbi (bolita, chat...)
    except Exception:                                   # noqa: BLE001
        pass
    return bool(u.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0))


def minimize_window(hwnd: int) -> bool:
    if sys.platform != "win32":
        return False
    ctypes, wintypes, u, _k = _api()
    return bool(u.ShowWindow(wintypes.HWND(hwnd), 7))     # SW_SHOWMINNOACTIVE: minimiza sin activar


def foreground_info() -> dict:
    """dict(title, exe, cls) de la ventana activa."""
    if sys.platform != "win32":
        return dict(title="", exe="", cls="")
    try:
        ctypes, wintypes, u, k = _api()
        h = u.GetForegroundWindow()
        if not h:
            return dict(title="", exe="", cls="")
        _pid, exe = _pid_exe(u, k, ctypes, wintypes, h)
        return dict(title=_text(u, ctypes, h), exe=exe, cls=_cls(u, ctypes, h))
    except Exception:
        return dict(title="", exe="", cls="")


def foreground_hwnd() -> int:
    """hwnd de la ventana activa (0 si no se puede saber)."""
    if sys.platform != "win32":
        return 0
    try:
        _c, _w, u, _k = _api()
        return int(u.GetForegroundWindow() or 0)
    except Exception:
        return 0


def foreground_title() -> str:
    return foreground_info()["title"]


def foreground_is_fullscreen() -> bool:
    """True si la ventana activa ocupa toda la pantalla (juego, presentación, video): no molestar."""
    if sys.platform != "win32":
        return False
    try:
        ctypes, wintypes, u, _k = _api()
        h = u.GetForegroundWindow()
        if not h or _cls(u, ctypes, h) in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        r = wintypes.RECT()
        u.GetWindowRect(h, ctypes.byref(r))
        sw, sh = u.GetSystemMetrics(0), u.GetSystemMetrics(1)
        return (r.right - r.left) >= sw and (r.bottom - r.top) >= sh and r.left <= 0 and r.top <= 0
    except Exception:
        return False


def focus_window(hwnd: int) -> bool:
    if sys.platform != "win32":
        return False
    ctypes, wintypes, u, _k = _api()
    h = wintypes.HWND(hwnd)
    if u.IsIconic(h):
        u.ShowWindow(h, 9)                                # SW_RESTORE
    u.keybd_event(0x12, 0, 0, 0)                          # truco ALT: Windows deja cambiar el foco
    u.keybd_event(0x12, 0, 2, 0)
    return bool(u.SetForegroundWindow(h))


def force_topmost(hwnd: int) -> None:
    """Re-afirma 'siempre encima' sin robar el foco (Windows a veces lo pierde al abrir otras apps)."""
    if sys.platform != "win32":
        return
    try:
        ctypes, wintypes, u, _k = _api()
        # HWND_TOPMOST = -1 ; SWP_NOSIZE|NOMOVE|NOACTIVATE|SHOWWINDOW = 0x0001|0x0002|0x0010|0x0040
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wintypes.UINT]
        u.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
    except Exception:
        pass


def idle_seconds() -> float:
    """Segundos desde la última vez que moviste el mouse o tocaste el teclado (0 si no se puede saber)."""
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = LASTINPUTINFO(); info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return max(0.0, ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0)
    except Exception:
        return 0.0


_START_CACHE = {}


def find_start_app(name: str):
    """Ruta del acceso directo (.lnk) del menú Inicio que mejor coincide con `name` (ej. 'discord'), o None.
    Así se abre cualquier app instalada sin usar el buscador de Windows ni teclear nada."""
    import difflib
    name = (name or "").lower().strip()
    if not name or sys.platform != "win32":
        return None
    if not _START_CACHE:
        roots = [os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
                 os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")]
        for root in roots:
            for dp, _dn, files in os.walk(root):
                for f in files:
                    if f.lower().endswith(".lnk") and "uninstall" not in f.lower() and "desinstal" not in f.lower():
                        _START_CACHE.setdefault(f[:-4].lower(), os.path.join(dp, f))
    if name in _START_CACHE:
        return _START_CACHE[name]
    hits = [k for k in _START_CACHE if name in k or k in name]
    if hits:
        return _START_CACHE[min(hits, key=len)]
    close = difflib.get_close_matches(name, list(_START_CACHE), n=1, cutoff=0.75)
    return _START_CACHE[close[0]] if close else None


def wait_for_window(app: str, timeout: float = 8.0, already=()):
    """Espera (sondeando cada 0.2 s) a que aparezca una ventana de `app` que no estaba en `already` (hwnds). -> ventana o None."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        for w in match_windows(app, ""):
            if w["hwnd"] not in already:
                return w
        time.sleep(0.2)
    return None
