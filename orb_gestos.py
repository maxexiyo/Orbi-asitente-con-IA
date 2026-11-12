"""Biblioteca de gestos predefinidos (modo «animaciones programadas»): funciones de tiempo → desplazamientos que se suman al cuerpo y la cara."""
import math
from orb_consts import R0


def _env(u):
    return math.sin(math.pi * max(0.0, min(1.0, u)))


def _hold(u, a=0.25):
    s = max(0.0, min(1.0, min(u / a, (1 - u) / a)))
    return s * s * (3 - 2 * s)


GESTO_FN = {
    # cada gesto mueve el cuerpo/cabeza Y la cara (ojos, cejas, mirada): una cabeza que cabecea con la cara congelada se ve de muñeco
    "asentir": lambda u, k: {"ghy": math.sin(u * 4 * math.pi) * R0 * 0.26 * k * _env(u), "grot": math.sin(u * 4 * math.pi) * 2.5 * k * _env(u),
                             "geh": -0.14 * max(0.0, math.sin(u * 4 * math.pi)) * _env(u)},
    "negar": lambda u, k: {"ghx": math.sin(u * 6 * math.pi) * R0 * 0.26 * k * _env(u), "grot": math.sin(u * 6 * math.pi) * 7 * k * _env(u),
                           "gbrow": -0.25 * k * _env(u), "geh": -0.10 * _env(u)},
    "ladear": lambda u, k: {"grot": _hold(u) * 22 * k, "ghx": _hold(u) * R0 * 0.08 * k, "ghy": _hold(u) * R0 * 0.03 * k,
                            "gbrow": _hold(u) * 0.30 * k, "gly": -_hold(u) * 0.25},
    "brincar": lambda u, k: {"gdy": -math.sin(math.pi * u) * R0 * 1.15 * k, "gsc": 0.06 * math.sin(math.pi * u) * k,
                             "geh": 0.28 * math.sin(math.pi * u), "gbrow": 0.55 * math.sin(math.pi * u)},
    "rebotar": lambda u, k: {"gdy": -abs(math.sin(3 * math.pi * u)) * R0 * 0.8 * k * (1 - 0.5 * u), "gsc": 0.03 * abs(math.sin(3 * math.pi * u)) * k,
                             "geh": 0.12 * _env(u)},
    "temblar": lambda u, k: {"gdx": math.sin(u * 32 * math.pi) * R0 * 0.06 * k * _env(u), "grot": math.sin(u * 24 * math.pi) * 2 * k * _env(u),
                             "geh": 0.22 * _env(u), "gbrow": 0.5 * _env(u)},
    "suspirar": lambda u, k: {"gsc": math.sin(math.pi * u) * 0.11 * k, "ghy": _hold(u) * R0 * 0.12 * k, "grot": _hold(u) * -3 * k,
                              "geh": -0.38 * _hold(u, 0.3), "gly": 0.35 * _hold(u, 0.3)},
    "inflar": lambda u, k: {"gsc": _hold(u) * 0.19 * k, "gdy": -_hold(u) * R0 * 0.05 * k, "gbrow": -0.45 * _hold(u) * k, "geh": -0.12 * _hold(u)},
    "encoger": lambda u, k: {"gsc": -_hold(u) * 0.17 * k, "ghy": _hold(u) * R0 * 0.12 * k, "gdy": _hold(u) * R0 * 0.06 * k,
                             "gbrow": 0.45 * _hold(u) * k, "gly": 0.7 * _hold(u)},
    "bailecito": lambda u, k: {"gdx": math.sin(u * 4 * math.pi) * R0 * 0.45 * k * _env(u),
                               "grot": math.sin(u * 4 * math.pi) * 14 * k * _env(u),
                               "gdy": -abs(math.sin(u * 4 * math.pi)) * R0 * 0.25 * k * _env(u)},
    "parpadear": lambda u, k: {},                                  # no mueve nada: dispara dos parpadeos (ver Orb.gesto)
    # --- más humanos: cosas que se hacen con la cara más que con el cuerpo
    "no_se": lambda u, k: {"gsc": -_hold(u, 0.2) * 0.07 * k, "ghy": _hold(u, 0.2) * R0 * 0.10 * k, "grot": _hold(u, 0.2) * 8 * k,
                           "gbrow": 0.55 * _hold(u, 0.2) * k, "gdy": _hold(u, 0.2) * R0 * 0.04 * k, "gly": -0.2 * _hold(u, 0.2)},
    "reirse": lambda u, k: {"gdy": -abs(math.sin(u * 10 * math.pi)) * R0 * 0.10 * k * _env(u), "grot": math.sin(u * 8 * math.pi) * 5 * k * _env(u),
                            "geh": -0.35 * _hold(u, 0.15), "gbrow": 0.2 * _env(u)},
    "guinar": lambda u, k: {"gwl": _hold(u, 0.22), "grot": _hold(u, 0.22) * 5 * k, "gbrow": 0.25 * _hold(u, 0.22)},
    "ceja_arriba": lambda u, k: {"gbrow": 0.95 * _hold(u, 0.2) * k, "geh": 0.14 * _hold(u, 0.2), "grot": _hold(u, 0.2) * -3 * k},
    "de_reojo": lambda u, k: {"glx": 1.9 * _hold(u, 0.2) * k, "geh": -0.22 * _hold(u, 0.2), "gbrow": -0.3 * _hold(u, 0.2),
                              "grot": -4 * _hold(u, 0.2) * k},
    "inclinarse": lambda u, k: {"gsc": 0.10 * _hold(u, 0.3) * k, "gdy": R0 * 0.05 * _hold(u, 0.3) * k, "gbrow": 0.3 * _hold(u, 0.3),
                                "geh": 0.12 * _hold(u, 0.3)},
    "entrecerrar": lambda u, k: {"geh": -0.45 * _hold(u, 0.2) * k, "gbrow": -0.5 * _hold(u, 0.2) * k, "ghx": R0 * 0.03 * _hold(u, 0.2)},

}
GESTO_DUR = {"asentir": 1.1, "negar": 1.2, "ladear": 1.6, "brincar": 0.7, "rebotar": 1.3, "temblar": 1.0, "suspirar": 2.0,
             "inflar": 1.6, "encoger": 1.6, "bailecito": 1.8, "parpadear": 0.6,
             "no_se": 1.4, "reirse": 1.6, "guinar": 0.9, "ceja_arriba": 1.4, "de_reojo": 1.6, "inclinarse": 2.0, "entrecerrar": 1.6}
_G0 = {"ghx": 0.0, "ghy": 0.0, "grot": 0.0, "gdx": 0.0, "gdy": 0.0, "gsc": 0.0,
       "gbrow": 0.0, "geh": 0.0, "gwl": 0.0, "gwr": 0.0, "glx": 0.0, "gly": 0.0,       # + cara: cejas, alto de ojos, guiño izq/der, mirada
       # + rig (pose libre de la IA): ojo izq/der, pupila, ceja izq/der, boca (abierta, sonrisa, ancho), rubor, resplandor
       "gancho": 0.0, "galto": 0.0, "garc": 0.0, "gel": 0.0, "ger": 0.0, "gpup": 0.0, "gbl": 0.0, "gbr": 0.0, "gmo": 0.0, "gsm": 0.0, "gmw": 0.0, "grub": 0.0, "gglow": 0.0}
_LOOK_DIR = {"izquierda": (-1.6, 0.0), "derecha": (1.6, 0.0), "arriba": (0.0, -1.0), "abajo": (0.0, 1.0), "centro": (0.0, 0.0)}
