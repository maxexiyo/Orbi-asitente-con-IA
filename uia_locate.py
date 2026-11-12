"""Orbi: ubicar un elemento de la interfaz con la ACCESIBILIDAD de Windows (UI Automation), sin IA: exacto y en milisegundos.

Word, Excel, el Explorador, Configuración, la mayoría de las apps de escritorio y los navegadores exponen sus botones, pestañas y menús con nombre y
posición. Aquí se busca por NOMBRE el elemento dentro de la ventana activa y se devuelve su posición exacta en píxeles de la pantalla.
Necesita:  python -m pip install -U uiautomation      (si no está, `buscar` devuelve None y Orbi sigue con otras formas de señalar)
"""
from __future__ import annotations

import re
import time
import unicodedata

_PREFERIDOS = {"TabItemControl", "ButtonControl", "MenuItemControl", "ListItemControl", "CheckBoxControl", "RadioButtonControl", "ComboBoxControl",
               "HyperlinkControl", "SplitButtonControl", "TreeItemControl", "DataItemControl", "MenuBarControl"}
_avisado = False


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ñ ]", " ", s)).strip()


def puntaje(nombre: str, q: str, tipo: str = "") -> int:
    """Qué tan bien coincide el nombre de un elemento con lo que se busca (0 = nada)."""
    n = norm(nombre)
    if not n or not q:
        return 0
    if n == q:
        p = 100
    elif n.startswith(q + " ") or q.startswith(n + " ") and len(n) >= 3:
        p = 60
    elif len(q) >= 3 and q in n:
        p = 40
    elif len(n) >= 4 and n in q:
        p = 30
    else:
        return 0
    if tipo in _PREFERIDOS:
        p += 15                                                         # botones, pestañas y menús ganan a cuadros de texto sueltos
    return p - min(len(n), 60) // 20                                    # a igualdad, el nombre más corto


def buscar(nombre: str, limite_s: float = 2.5):
    """{"px","py","etiqueta"} (centro en píxeles de pantalla) del mejor elemento llamado `nombre` en la ventana activa, o None."""
    global _avisado
    try:
        import uiautomation as auto
    except ImportError:
        if not _avisado:
            _avisado = True
            print("[señalar] sin uiautomation (python -m pip install -U uiautomation): no puedo ubicar por accesibilidad")
        return None
    q = norm(nombre)
    if not q:
        return None
    fin = time.time() + limite_s
    mejor, mejor_p = None, 0
    with auto.UIAutomationInitializerInThread():
        fg = auto.GetForegroundControl()
        win = fg.GetTopLevelControl() if fg else None
        if win is None:
            return None
        for c, _prof in auto.WalkControl(win, includeTop=False, maxDepth=16):
            if time.time() > fin:
                break
            try:
                n = c.Name
                if not n:
                    continue
                p = puntaje(n, q, c.ControlTypeName)
                if p <= mejor_p:
                    continue
                if c.IsOffscreen:
                    continue
                r = c.BoundingRectangle
                if r.right - r.left < 4 or r.bottom - r.top < 4:
                    continue
                mejor, mejor_p = {"px": (r.left + r.right) // 2, "py": (r.top + r.bottom) // 2, "etiqueta": n.strip()[:80]}, p
                if p >= 115:                                            # nombre exacto en un botón/pestaña/menú: no hace falta seguir
                    break
            except Exception:                                           # noqa: BLE001  (el elemento desapareció mientras se leía)
                continue
    return mejor
