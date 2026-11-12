"""Orbi: qué apps hay en la PC (#38): instaladas (registro de Windows, menú Inicio, apps de la Tienda) y programas PORTABLES (.exe sueltos en el disco).

Un escaneo en segundo plano (al abrir Orbi y desde el menú) arma un índice que se guarda en apps_detectadas.json. Orbi lo usa para:
  · saber qué tienes (herramienta `listar_apps`, y un resumen dentro de la descripción de `abrir_app`);
  · abrir un portable por su nombre (`abrir_app`); la PRIMERA vez que abre cada programa portable pide tu OK (config `apps_portables_pedir_ok`).
Solo se indexan .exe que están FUERA de Windows, Program Files, AppData y carpetas de desarrollo (esos ya salen en el registro o el menú Inicio).

config.json (todo opcional):
  apps_escanear_carpetas   lista de carpetas a revisar a fondo (por defecto: tu carpeta de usuario)
  apps_escanear_discos     true (por defecto) = también la raíz de cada disco, poco profunda
  apps_prof_usuario (6) · apps_prof_disco (3) · apps_escanear_max_s (120) · apps_portables_pedir_ok (true)
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent
CACHE = ROOT / "apps_detectadas.json"
APROBADAS = ROOT / "apps_aprobadas.json"

_EXCLUIR = {"windows", "program files", "program files (x86)", "programdata", "$recycle.bin", "system volume information", "appdata",
            "node_modules", ".git", "__pycache__", "site-packages", "venv", ".venv", "windowsapps", "recovery", "msocache",
            "perflogs", "winsxs", "$windows.~bt", "$windows.~ws", "onedrivetemp", ".gradle", ".android", ".cache", ".vscode", ".npm"}
_BASURA = re.compile(r"(unins|uninst|setup|install|updat|upgrad|redist|crash|helper|elevate|migrat|dxwebsetup|dotnet|repair|cleanup|"
                     r"bootstrap|vcredist|7zs|stub|diag|report|notifier)", re.I)
_RUIDO_REG = re.compile(r"(^kb\d|update for|security update|hotfix|redistributable|runtime|\bsdk\b|driver|visual c\+\+|\.net |webview2)", re.I)

_cfg = dict(carpetas=None, discos=True, prof_usuario=6, prof_disco=3, max_s=120.0, pedir_ok=True)
_est = dict(instaladas=[], portables=[], fecha=0.0, escaneando=False)
_lock = threading.Lock()


def configurar(cfg: dict) -> None:
    c = cfg or {}
    _cfg["carpetas"] = c.get("apps_escanear_carpetas")
    _cfg["discos"] = bool(c.get("apps_escanear_discos", True))
    _cfg["prof_usuario"] = int(c.get("apps_prof_usuario", 6)); _cfg["prof_disco"] = int(c.get("apps_prof_disco", 3))
    _cfg["max_s"] = float(c.get("apps_escanear_max_s", 120)); _cfg["pedir_ok"] = bool(c.get("apps_portables_pedir_ok", True))


def pedir_ok() -> bool:
    return bool(_cfg["pedir_ok"])


def cargar() -> None:
    try:
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        with _lock:
            _est["instaladas"] = list(d.get("instaladas") or []); _est["portables"] = list(d.get("portables") or []); _est["fecha"] = float(d.get("fecha") or 0)
    except Exception:                                                       # noqa: BLE001
        pass


# ------------------------------------------------------------------ instaladas
def _registro() -> list[str]:
    if sys.platform != "win32":
        return []
    import winreg
    out = []
    for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                      (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")):
        try:
            k = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(k)[0]):
            try:
                with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sk:
                    nombre = str(winreg.QueryValueEx(sk, "DisplayName")[0]).strip()
                    try:
                        if winreg.QueryValueEx(sk, "SystemComponent")[0] == 1:
                            continue
                    except OSError:
                        pass
                    try:
                        winreg.QueryValueEx(sk, "ParentKeyName"); continue          # es una actualización de otra cosa
                    except OSError:
                        pass
                if nombre and not _RUIDO_REG.search(nombre):
                    out.append(nombre)
            except OSError:
                continue
    return out


def _menu_inicio() -> list[str]:
    out = []
    for base in (os.environ.get("ProgramData"), os.environ.get("APPDATA")):
        if not base:
            continue
        raiz = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        try:
            for p in raiz.rglob("*.lnk"):
                n = p.stem.strip()
                if n and not re.search(r"(uninstall|desinstal|readme|license|licencia|help|ayuda|manual|website|sitio)", n, re.I):
                    out.append(n)
        except OSError:
            pass
    return out


def _tienda() -> list[str]:
    """Apps de la Tienda y todo lo del menú Inicio (Get-StartApps)."""
    if sys.platform != "win32":
        return []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-StartApps | Select-Object -ExpandProperty Name"],
                           capture_output=True, text=True, timeout=25, creationflags=0x08000000, encoding="utf-8", errors="replace")
        return [x.strip() for x in r.stdout.splitlines() if x.strip()]
    except Exception:                                                       # noqa: BLE001
        return []


def _instaladas() -> list[str]:
    vistos = {}
    for n in _registro() + _menu_inicio() + _tienda():
        if re.search(r"(uninstall|desinstal)", n, re.I):
            continue
        vistos.setdefault(n.lower(), n)
    return sorted(vistos.values(), key=str.lower)


# ------------------------------------------------------------------ portables
def _raices() -> list[tuple[str, int]]:
    raices = []
    carp = _cfg["carpetas"]
    if isinstance(carp, list) and carp:
        raices += [(str(c), _cfg["prof_usuario"]) for c in carp]
    else:
        raices.append((str(Path.home()), _cfg["prof_usuario"]))
    if _cfg["discos"] and sys.platform == "win32":
        try:
            import ctypes
            mask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if mask & (1 << i):
                    d = f"{chr(65 + i)}:\\"
                    if ctypes.windll.kernel32.GetDriveTypeW(d) in (2, 3):     # extraíble o fijo
                        raices.append((d, _cfg["prof_disco"]))
        except Exception:                                                   # noqa: BLE001
            pass
    return raices


def _limpiar(stem: str) -> str:
    s = re.sub(r"[_\-.]+", " ", stem).strip()
    s = re.sub(r"\s+(x64|x86|win64|win32|portable|64bit|32bit)$", "", s, flags=re.I)
    return s.strip() or stem


def _portables(limite: float) -> list[dict]:
    hallados: dict[str, dict] = {}
    for raiz, prof in _raices():
        pila = [(raiz, 0)]
        while pila and time.time() < limite:
            ruta, nivel = pila.pop()
            try:
                with os.scandir(ruta) as it:
                    for e in it:
                        try:
                            if e.is_dir(follow_symlinks=False):
                                if nivel < prof and e.name.lower() not in _EXCLUIR and not e.name.startswith("$"):
                                    pila.append((e.path, nivel + 1))
                            elif e.name.lower().endswith(".exe") and not _BASURA.search(e.name):
                                st = e.stat()
                                if st.st_size < 200_000:
                                    continue
                                nombre = _limpiar(Path(e.name).stem)
                                k = nombre.lower()
                                if k not in hallados or st.st_mtime > hallados[k]["mtime"]:
                                    hallados[k] = {"nombre": nombre, "ruta": e.path, "mtime": st.st_mtime}
                        except OSError:
                            continue
            except OSError:
                continue
            if len(hallados) > 3000:
                break
    return sorted(hallados.values(), key=lambda d: d["nombre"].lower())


# ------------------------------------------------------------------ escaneo
def iniciar(on_done=None, force: bool = False) -> bool:
    """Arranca el escaneo en segundo plano. Sin `force`, no repite si el último tiene menos de 12 h."""
    with _lock:
        if _est["escaneando"]:
            return False
        if not force and _est["fecha"] and time.time() - _est["fecha"] < 12 * 3600:
            return False
        _est["escaneando"] = True

    def run():
        try:
            inst = _instaladas()
            port = _portables(time.time() + _cfg["max_s"])
            with _lock:
                _est["instaladas"], _est["portables"], _est["fecha"] = inst, port, time.time()
            try:
                CACHE.write_text(json.dumps({"fecha": _est["fecha"], "instaladas": inst, "portables": port}, ensure_ascii=False, indent=0), encoding="utf-8")
            except OSError as e:
                print(f"[apps] no pude guardar el índice: {e}")
            print(f"[apps] {len(inst)} instaladas y {len(port)} portables encontradas")
        except Exception as e:                                              # noqa: BLE001
            print(f"[apps] falló el escaneo: {type(e).__name__}: {str(e)[:100]}")
        finally:
            with _lock:
                _est["escaneando"] = False
            if on_done:
                try:
                    on_done()
                except Exception:                                           # noqa: BLE001
                    pass
    threading.Thread(target=run, daemon=True, name="orbi-apps").start()
    return True


def conteo() -> tuple[int, int]:
    with _lock:
        return len(_est["instaladas"]), len(_est["portables"])


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"[_\-.]+", " ", str(s).lower())).strip()


def buscar(filtro: str = "", n: int = 40) -> dict:
    f = _norm(filtro)
    with _lock:
        inst, port = list(_est["instaladas"]), list(_est["portables"])
    if f:
        inst = [x for x in inst if f in _norm(x)]
        port = [x for x in port if f in _norm(x["nombre"])]
    return {"instaladas": inst[:n], "portables": [{"nombre": p["nombre"], "ruta": p["ruta"]} for p in port[:n]],
            "total_instaladas": len(inst), "total_portables": len(port)}


def resolver_portable(nombre: str):
    """El portable que mejor coincide con `nombre` (exacto, contenido o parecido) o None."""
    q = _norm(nombre)
    if not q:
        return None
    with _lock:
        port = list(_est["portables"])
    for p in port:
        if _norm(p["nombre"]) == q:
            return p
    cont = [p for p in port if q in _norm(p["nombre"]) or (len(_norm(p["nombre"])) >= 4 and _norm(p["nombre"]) in q)]
    if len(cont) >= 1:
        return min(cont, key=lambda p: len(p["nombre"]))
    mejor = difflib.get_close_matches(q, [_norm(p["nombre"]) for p in port], n=1, cutoff=0.82)
    return next((p for p in port if _norm(p["nombre"]) == mejor[0]), None) if mejor else None


def resumen(n_inst: int = 60, n_port: int = 25) -> str:
    """Texto corto para la descripción de `abrir_app`: Orbi sabe qué hay sin tener que preguntar."""
    with _lock:
        inst, port = list(_est["instaladas"]), [p["nombre"] for p in _est["portables"]]
    if not inst and not port:
        return ""
    t = ""
    if inst:
        t += f" Apps instaladas detectadas ({len(inst)}): " + ", ".join(inst[:n_inst]) + ("…" if len(inst) > n_inst else "") + "."
    if port:
        t += f" Programas portables (.exe sueltos) ({len(port)}): " + ", ".join(port[:n_port]) + ("…" if len(port) > n_port else "") + "."
    return t + " Para la lista completa o filtrar, usa listar_apps."


# ------------------------------------------------------------------ aprobación de portables
def _aprobadas() -> set:
    try:
        return set(json.loads(APROBADAS.read_text(encoding="utf-8")))
    except Exception:                                                       # noqa: BLE001
        return set()


def aprobada(ruta: str) -> bool:
    return str(ruta).lower() in _aprobadas()


def aprobar(ruta: str) -> None:
    a = _aprobadas(); a.add(str(ruta).lower())
    try:
        APROBADAS.write_text(json.dumps(sorted(a), ensure_ascii=False, indent=0), encoding="utf-8")
    except OSError:
        pass


cargar()
