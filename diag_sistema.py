"""Orbi: diagnóstico de recursos para cazar fugas que se notan solo tras muchas horas (y que siguen aunque cierres Orbi).

Con "mem_debug": true en config.json, live_orb.py llama a registrar() cada 2 min. Anota UNA línea por muestra en  orbi_diag.csv
(junto a la config de Orbi) y la imprime en la consola / orbi.log. Mide DOS cosas:

  ORBI:     RAM, handles, hilos, objetos GDI y USER de este proceso, hilos de Python, cuántos recorders de loopback hay abiertos.
  SISTEMA:  memoria del kernel (no paginada / paginada), handles totales, commit, y los procesos que ensucian el audio y las ventanas:
            audiodg.exe (servicio de audio de Windows) y dwm.exe (compositor de ventanas).

Cómo leerlo: abre orbi_diag.csv en Excel y grafica las columnas contra «hora». Una fuga es una columna que SOLO SUBE:
  - orbi_handles / orbi_gdi / orbi_user / orbi_hilos subiendo      -> fuga dentro de Orbi
  - loop_abiertos mayor a 1, o loop_aperturas disparándose           -> fallo en la captura del audio de la PC
  - audiodg_handles / audiodg_mb subiendo                            -> Orbi está dejando clientes de audio colgados en Windows
  - sis_nopaginado_mb subiendo (y no baja al cerrar Orbi)            -> fuga en un driver / memoria del kernel
  - dwm_mb / dwm_handles subiendo                                    -> la ventana de la bolita está desgastando el compositor
  - mic_reaperturas / bocina_atoradas subiendo                       -> el micro o la bocina se traban una y otra vez
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from pathlib import Path

_COLS = ["hora", "orbi_ram_mb", "orbi_handles", "orbi_hilos", "orbi_gdi", "orbi_user", "py_hilos",
         "sis_ram_pct", "sis_commit_mb", "sis_nopaginado_mb", "sis_paginado_mb", "sis_handles",
         "audiodg_mb", "audiodg_handles", "audiodg_cpu", "dwm_mb", "dwm_handles", "dwm_cpu",
         "loop_abiertos", "loop_aperturas", "loop_cierres_error", "loop_errores", "loop_cambios_bocina",
         "mic_reaperturas", "bocina_reaperturas", "bocina_atoradas"]
_MAX_BYTES = 1_500_000                    # si el CSV pasa de esto, el viejo se guarda como orbi_diag_anterior.csv y se empieza otro
_lock = threading.Lock()
_procs: dict = {}                         # nombre -> psutil.Process (se reutiliza para que cpu_percent mida entre muestras)


def _kernel() -> dict:
    """Memoria del kernel y handles de TODO el sistema (GetPerformanceInfo). {} si no es Windows."""
    if sys.platform != "win32":
        return {}
    try:
        SZ = ctypes.c_size_t

        class _PERF(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("CommitTotal", SZ), ("CommitLimit", SZ), ("CommitPeak", SZ),
                        ("PhysicalTotal", SZ), ("PhysicalAvailable", SZ), ("SystemCache", SZ), ("KernelTotal", SZ),
                        ("KernelPaged", SZ), ("KernelNonpaged", SZ), ("PageSize", SZ), ("HandleCount", ctypes.c_ulong),
                        ("ProcessCount", ctypes.c_ulong), ("ThreadCount", ctypes.c_ulong)]
        pi = _PERF(); pi.cb = ctypes.sizeof(pi)
        if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(pi), pi.cb):
            return {}
        mb = pi.PageSize / 1048576.0
        return dict(sis_commit_mb=pi.CommitTotal * mb, sis_nopaginado_mb=pi.KernelNonpaged * mb,
                    sis_paginado_mb=pi.KernelPaged * mb, sis_handles=pi.HandleCount)
    except Exception:                                             # noqa: BLE001
        return {}


def _gui() -> tuple:
    """(objetos GDI, objetos USER) de ESTE proceso. Si suben sin parar, Orbi está dejando ventanas/dibujos sin liberar."""
    if sys.platform != "win32":
        return -1, -1
    try:
        h = ctypes.windll.kernel32.GetCurrentProcess()
        u = ctypes.windll.user32
        return int(u.GetGuiResources(h, 0)), int(u.GetGuiResources(h, 1))
    except Exception:                                             # noqa: BLE001
        return -1, -1


def _otro(nombre: str, psutil) -> dict:
    """RAM (MB), handles y CPU % de un proceso del sistema por nombre (audiodg.exe, dwm.exe). -1 si no se puede leer (permisos)."""
    p = _procs.get(nombre)
    try:
        if p is None or not p.is_running():
            p = next((x for x in psutil.process_iter(["name"]) if (x.info["name"] or "").lower() == nombre), None)
            _procs[nombre] = p
        if p is None:
            return dict(mb=-1, handles=-1, cpu=-1)
    except Exception:                                             # noqa: BLE001
        return dict(mb=-1, handles=-1, cpu=-1)
    out = dict(mb=-1, handles=-1, cpu=-1)
    for clave, fn in (("mb", lambda: p.memory_info().rss / 1048576.0),
                      ("handles", lambda: p.num_handles()),
                      ("cpu", lambda: p.cpu_percent(None))):
        try:
            out[clave] = fn()
        except Exception:                                         # noqa: BLE001  (AccessDenied en procesos protegidos)
            pass
    return out


def muestra(extra: dict | None = None) -> dict:
    """Una lectura completa (tarda ~50 ms). `extra` suma contadores de Orbi (p. ej. session.diag)."""
    import psutil
    m = {"hora": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        p = psutil.Process()
        m["orbi_ram_mb"] = p.memory_info().rss / 1048576.0
        m["orbi_hilos"] = p.num_threads()
        try:
            m["orbi_handles"] = p.num_handles()
        except Exception:                                         # noqa: BLE001  (no existe fuera de Windows)
            m["orbi_handles"] = p.num_fds() if hasattr(p, "num_fds") else -1
    except Exception:                                             # noqa: BLE001
        pass
    m["orbi_gdi"], m["orbi_user"] = _gui()
    m["py_hilos"] = threading.active_count()
    try:
        m["sis_ram_pct"] = psutil.virtual_memory().percent
    except Exception:                                             # noqa: BLE001
        pass
    m.update(_kernel())
    for nombre, pref in (("audiodg.exe", "audiodg"), ("dwm.exe", "dwm")):
        o = _otro(nombre, psutil)
        m[f"{pref}_mb"], m[f"{pref}_handles"], m[f"{pref}_cpu"] = o["mb"], o["handles"], o["cpu"]
    try:
        from loopback_hub import hub
        h = hub()
        s = h.stats
        m.update(loop_abiertos=h.abiertos, loop_aperturas=s["aperturas"], loop_cierres_error=s["cierres_con_error"],
                 loop_errores=s["errores"], loop_cambios_bocina=s["reaperturas_por_cambio"])
    except Exception:                                             # noqa: BLE001
        pass
    m.update(extra or {})
    return m


def _fmt(x) -> str:
    return f"{x:.1f}" if isinstance(x, float) else str(x)


def resumen(m: dict) -> str:
    g = lambda k: m.get(k, "?")                                   # noqa: E731
    f = lambda k: _fmt(m[k]) if k in m else "?"                   # noqa: E731
    return (f"[diag] ORBI: RAM {f('orbi_ram_mb')} MB · handles {g('orbi_handles')} · hilos {g('orbi_hilos')} (py {g('py_hilos')}) · "
            f"GDI {g('orbi_gdi')} · USER {g('orbi_user')} | SISTEMA: RAM {f('sis_ram_pct')} % · kernel no paginado {f('sis_nopaginado_mb')} MB · "
            f"handles {g('sis_handles')} | audiodg {f('audiodg_mb')} MB / {g('audiodg_handles')} handles | dwm {f('dwm_mb')} MB / {g('dwm_handles')} handles | "
            f"loopback abiertos {g('loop_abiertos')} (aperturas {g('loop_aperturas')}, errores {g('loop_errores')}) · "
            f"mic reabierto {g('mic_reaperturas')} · bocina atorada {g('bocina_atoradas')}")


def registrar(ruta, extra: dict | None = None, imprimir: bool = True) -> dict:
    """Toma una muestra, la anota en el CSV `ruta` (con encabezado la primera vez) y la imprime. Devuelve la muestra."""
    m = muestra(extra)
    ruta = Path(ruta)
    with _lock:
        try:
            if ruta.exists() and ruta.stat().st_size > _MAX_BYTES:
                ruta.replace(ruta.with_name("orbi_diag_anterior.csv"))
            nuevo = not ruta.exists()
            with open(ruta, "a", encoding="utf-8", newline="") as f:
                if nuevo:
                    f.write(",".join(_COLS) + "\n")
                f.write(",".join(_fmt(m.get(c, "")) for c in _COLS) + "\n")
        except Exception as e:                                    # noqa: BLE001
            print(f"[diag] no pude escribir {ruta}: {type(e).__name__}: {e}")
    if imprimir:
        print(resumen(m))
    return m
