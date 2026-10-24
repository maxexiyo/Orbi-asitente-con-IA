"""Diagnóstico de visión: ¿qué resolución recibe Orbi cuando mira tu pantalla?

    python diag_pantalla.py

Imprime tu(s) monitor(es), la escala de Windows y, para CADA forma en que Orbi mira la pantalla, a qué tamaño le llega.
Guarda esas mismas imágenes en la carpeta `diag_pantalla/` para que las abras y veas EXACTAMENTE lo que ve Orbi
(si tú no alcanzas a leer algo ahí, él tampoco).
"""
import json, sys
from pathlib import Path

import screen

OUT = Path(__file__).parent / "diag_pantalla"
cfg = {}
try:
    cfg = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
except Exception:                                                  # noqa: BLE001
    pass
screen.configure(cfg.get("pantalla_max_side"), cfg.get("pantalla_quality"))

# (nombre, qué lo usa, función que captura). Los valores salen de los mismos defaults que usa el código.
MODOS = [
    ("1_continuo_live", "frames que Live recibe solo cada ~1 s (modo ver todo) y tras cada acción",
     lambda: screen.capture(mark=True)),
    ("2_ver_pantalla", "tool ver_pantalla (a demanda)", lambda: screen.capture(max_side=1920, quality=82, mark=True)),
    ("3_agente_tarea_pc", "agente (tarea_pc): capturas de verificación",
     lambda: screen.capture(max_side=int(cfg.get("agent_shot_side", 1366)), quality=int(cfg.get("agent_shot_quality", 72)))),
    ("4_fin_de_plan", "captura final de ejecutar_plan", lambda: screen.capture(max_side=1600, quality=75, mark=True)),
    ("5_compañero_observador", "modo compañero (observer)", lambda: screen.capture(max_side=1600, quality=75)),
    ("6_pantalla_completa_alta", "acercar_pantalla sin zona", lambda: screen.capture(max_side=2000, quality=85, mark=True)),
]


def main() -> int:
    try:
        import mss
        with mss.mss() as sct:
            mons = [dict(m) for m in sct.monitors]
    except Exception as e:                                         # noqa: BLE001
        print("No pude abrir mss:", type(e).__name__, e)
        return 1
    print("MONITORES (el [1] es el que Orbi mira; los demás NO los ve):")
    for i, m in enumerate(mons):
        print(f"  [{i}] {m['width']}x{m['height']} en ({m['left']},{m['top']})" + ("  <- todos juntos" if i == 0 else ""))
    if len(mons) > 2:
        print("  OJO: tienes varios monitores. Si trabajas en otro que no sea el [1], Orbi no ve esa ventana.")
    if sys.platform == "win32":
        try:
            import ctypes
            esc = ctypes.windll.shcore.GetScaleFactorForDevice(0)
            print(f"Escala de Windows: {esc}%  (mss captura en píxeles reales, no escalados)")
        except Exception:                                          # noqa: BLE001
            pass
    OUT.mkdir(exist_ok=True)
    print(f"\nConfig: pantalla_max_side={screen.MAX_SIDE}, pantalla_quality={screen.QUALITY}, "
          f"agent_shot_side={cfg.get('agent_shot_side', 1366)}, live_media_resolution={cfg.get('live_media_resolution') or '(la del API)'}\n")
    print(f"{'modo':26} {'recibe':>11} {'% real':>7} {'KB':>5}   lo usa")
    for nombre, uso, fn in MODOS:
        jpeg, _mon = fn()
        (OUT / f"{nombre}.jpg").write_bytes(jpeg)
        e = screen.info
        print(f"{nombre:26} {e['enviado'][0]:>5}x{e['enviado'][1]:<5} {e['escala'] * 100:>6.0f}% {e['kb']:>5.0f}   {uso}")
    jpeg, _m, box = screen.capture_region([0, 0, 500, 500])
    (OUT / "7_lupa_zona.jpg").write_bytes(jpeg)
    print(f"{'7_lupa_zona':26} {'(recorte)':>11} {'':>7} {len(jpeg) / 1024:>5.0f}   acercar_pantalla / leer_pantalla con zona (resolución completa)")
    print(f"\nImágenes guardadas en: {OUT}")
    print("Regla práctica: si el texto de tu IDE se ve borroso/chico en 1_continuo_live.jpg, sube pantalla_max_side (p. ej. 1920),")
    print("o prueba live_media_resolution: \"medium\" / \"high\" en config.json (más detalle por frame, gasta más cuota).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
