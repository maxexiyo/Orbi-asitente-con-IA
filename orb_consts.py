"""Constantes y tablas de Orbi (caritas, colores, estados, estilos de baile, ánimo) + lectura de config. Sin Qt de ventanas: solo datos."""
"""La bolita: widget PySide6 con estados, emociones, burbuja y esconderse en el borde."""
import json, math, os, random, re, sys, time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import (QPainter, QRadialGradient, QLinearGradient, QColor, QBrush, QPen,
                           QPainterPath, QCursor, QFont, QGuiApplication)
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QLabel, QVBoxLayout
import orb_dodge
import cuerpo as _cu


def _cfg_val(clave: str, defecto):
    """Valor de config.json / orbi_config_ventana.json (el segundo manda). Sirve para interruptores de diagnóstico de la bolita."""
    val = defecto
    for nombre in ("config.json", "orbi_config_ventana.json"):
        try:
            d = json.loads((Path(__file__).resolve().parent / nombre).read_text(encoding="utf-8"))
            if isinstance(d, dict) and clave in d:
                val = d[clave]
        except Exception:                                           # noqa: BLE001
            pass
    return val

def _cfg_value(key, default):
    """ORBI_<KEY> en el entorno/.env o la clave en config.json (así se ajusta sin tocar el código)."""
    v = os.environ.get("ORBI_" + key.upper())
    if v is None:
        try:
            v = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8")).get(key)
        except Exception:
            v = None
    return default if v is None else v


try:
    SCALE = max(0.4, min(1.5, float(_cfg_value("orb_scale", 0.72))))     # 1.0 = tamaño original
except (TypeError, ValueError):
    SCALE = 0.72
try:
    SLEEP_AFTER = float(_cfg_value("sleep_after_s", 900))                # 0 = nunca se duerme
except (TypeError, ValueError):
    SLEEP_AFTER = 900.0

W = H = round(280 * SCALE)          # tamaño de la ventana
R0 = round(52 * SCALE)              # radio base de la bolita
VIS = round(42 * SCALE)             # px de bolita visibles cuando está escondida en el borde
EDGE_SNAP = 70                      # distancia al borde para que se esconda al soltarla
STANDBY_COLOR = (60, 115, 210)      # un poco más apagada cuando espera la palabra «Orbi»

# ---- Colores base por estado (la emoción los tiñe un poco) ----
STATE_COLORS = {
    "idle": (70, 150, 255),
    "listening": (80, 205, 255),
    "thinking": (140, 120, 255),
    "speaking": (70, 150, 255),
    "sleeping": (55, 85, 150),
}
# pulse = amplitud de la "respiración", speed = rapidez
# cómo baila según el estilo (lo elige live_orb.py por el género de la canción o por el tempo): dx/dy = empuje en cada golpe
# (dy > 0 baja, dy < 0 salta), sway/sw = balanceo entre golpes, decay = qué tan rápido se calma, pulse = cuánto late el cuerpo
COLOR_KEYS = ("er", "eg", "eb", "ew", "tr", "tg", "tb")   # claves de FACES que son COLOR (no forma de la cara)
FACE_SNAP = True            # True: la carita cambia AL INSTANTE cuando cambia la emoción (el color sí se funde con transición); False: todo se funde
DANCE_FACE_SNAP = FACE_SNAP
COLOR_LERP = 0.06           # qué tan rápido se funde el COLOR de la emoción (≈1 s de transición); la carita usa 0.14 y salta por FACE_SNAP
MOOD_HALF_S = 150.0         # el «ánimo» (cómo ha estado últimamente) se va apagando solo, a la mitad cada tantos segundos
EMO_AFTER_S = 5.0           # cuánto se queda en el «eco» de una emoción antes de volver a neutral (feliz → contento → neutral, no de golpe)
try:
    DANCE_SMOOTH = max(0.0, min(1.0, float(_cfg_value("baile_suavidad", 0.65))))   # 0 = brinca seco como antes · 1 = muy suave
    DANCE_GAIN = max(0.2, min(1.5, float(_cfg_value("baile_intensidad", 1.2))))   # qué tan grandes son los movimientos del baile
except (TypeError, ValueError):
    DANCE_SMOOTH, DANCE_GAIN = 0.65, 1.2

DANCE_STYLES = {
    # hx/hsway = la carita se corre de lado, nod = cabeceo (+ baja, - sube), tilt/tsway = inclina la cabeza (grados), caras = expresiones
    "pop":         dict(dx=13, dy=-16, sway=3,  sw=3.0, decay=0.88, pulse=0.08, hx=0.06, hsway=0.03, nod=-0.05, tilt=4, tsway=3, caras=("excited", "happy")),
    "salsa":       dict(dx=16, dy=-7,  sway=5,  sw=4.2, decay=0.90, pulse=0.06, hx=0.10, hsway=0.05, nod=0.02,  tilt=6, tsway=4, caras=("party", "happy", "love")),
    "cumbia":      dict(dx=11, dy=-9,  sway=6,  sw=2.6, decay=0.90, pulse=0.05, hx=0.06, hsway=0.06, nod=0.03,  tilt=4, tsway=5, caras=("happy", "party")),
    "bachata":     dict(dx=9,  dy=-5,  sway=8,  sw=2.0, decay=0.92, pulse=0.04, hx=0.04, hsway=0.08, nod=0.01,  tilt=3, tsway=7, caras=("love", "dreamy")),
    "reggaeton":   dict(dx=5,  dy=14,  sway=2,  sw=3.2, decay=0.90, pulse=0.12, hx=0.02, hsway=0.02, nod=0.08,  tilt=2, tsway=1, caras=("cool", "happy")),
    "hiphop":      dict(dx=4,  dy=11,  sway=2,  sw=1.8, decay=0.91, pulse=0.07, hx=0.02, hsway=0.02, nod=0.07,  tilt=3, tsway=1, caras=("cool",)),
    "rock":        dict(dx=3,  dy=-22, sway=1,  sw=3.0, decay=0.83, pulse=0.12, hx=0.02, hsway=0.01, nod=0.14,  tilt=2, tsway=1, caras=("rocker", "excited")),
    "metal":       dict(dx=2,  dy=-26, sway=1,  sw=4.0, decay=0.80, pulse=0.15, hx=0.01, hsway=0.01, nod=0.17,  tilt=1, tsway=1, caras=("rocker",)),
    "electronica": dict(dx=3,  dy=-24, sway=1,  sw=3.0, decay=0.86, pulse=0.16, hx=0.02, hsway=0.02, nod=-0.10, tilt=2, tsway=2, caras=("party", "surprised", "excited")),
    "regional":    dict(dx=12, dy=-12, sway=2,  sw=3.5, decay=0.84, pulse=0.07, hx=0.07, hsway=0.02, nod=-0.05, tilt=5, tsway=2, caras=("happy", "excited")),
    "disco":       dict(dx=14, dy=-13, sway=4,  sw=3.4, decay=0.88, pulse=0.10, hx=0.08, hsway=0.04, nod=-0.04, tilt=8, tsway=3, caras=("party", "love", "cool")),
    "suave":       dict(dx=4,  dy=-5,  sway=14, sw=1.4, decay=0.93, pulse=0.03, hx=0.02, hsway=0.10, nod=0.01,  tilt=2, tsway=8, caras=("dreamy", "happy")),
}


STATE_MOTION = {
    "idle": (0.03, 1.5), "listening": (0.06, 2.6), "thinking": (0.05, 5.0),
    "speaking": (0.035, 3.0), "sleeping": (0.018, 0.8),
}

# ---- Caras. arc: ojos tipo ^ ^ | curve: sonrisa(+)/tristeza(-) | open: boca abierta
# brow: + preocupada (cejas inclinadas hacia adentro-arriba), - enojada | lx/ly: hacia dónde mira
# tr/tg/tb: tinte de color sumado al color del estado
FACES = {
    "neutral":   dict(eye_h=1.0, eye_w=1.0, arc=0, curve=0.45, open=0, blush=0, brow=0, lx=0, ly=0, tr=0, tg=0, tb=0),
    "attentive": dict(eye_h=1.2, eye_w=1.05, arc=0, curve=0.30, open=0, blush=0, brow=0, lx=0, ly=0, tr=0, tg=0, tb=0),
    "happy":     dict(eye_h=1.0, eye_w=1.1, arc=1, curve=1.25, open=0, blush=0.5, brow=0, lx=0, ly=0, tr=25, tg=35, tb=-25),
    "love":      dict(eye_h=1.0, eye_w=1.1, arc=1, curve=0.9, open=0, blush=1.0, brow=0, lx=0, ly=0, tr=100, tg=-50, tb=-60),
    "sad":       dict(eye_h=0.9, eye_w=1.0, arc=0, curve=-0.8, open=0, blush=0, brow=0.9, lx=0, ly=0.6, tr=-45, tg=-40, tb=-5),
    "surprised": dict(eye_h=1.6, eye_w=1.3, arc=0, curve=0, open=0.75, blush=0, brow=0, lx=0, ly=0, tr=35, tg=35, tb=-15),
    "thinking":  dict(eye_h=0.95, eye_w=1.0, arc=0, curve=0.0, open=0, blush=0, brow=0.35, lx=0.9, ly=-0.8, tr=0, tg=0, tb=0),
    "angry":     dict(eye_h=0.8, eye_w=1.05, arc=0, curve=-0.5, open=0, blush=0, brow=-0.9, lx=0, ly=0, tr=130, tg=-85, tb=-100),
    "excited":   dict(eye_h=1.3, eye_w=1.2, arc=1, curve=1.3, open=0.35, blush=0.3, brow=0, lx=0, ly=0, tr=95, tg=45, tb=-95),
    "sleepy":    dict(eye_h=0.06, eye_w=1.3, arc=0, curve=0.25, open=0, blush=0, brow=0, lx=0, ly=0.3, tr=-10, tg=-10, tb=0),
    # trabajando: ojos entrecerrados, cejas concentradas y mirada que va y viene como leyendo (ver _face_target)
    "working":   dict(eye_h=0.95, eye_w=1.05, arc=0, curve=0.55, open=0, blush=0.05, brow=0, lx=0, ly=0.30, tr=0, tg=0, tb=0),
    # caras por TIPO de chamba (las elige live_orb.py según la herramienta; el movimiento de los ojos está en WORK_MOTION).
    # Todas con sonrisita y SIN cejas (las cejas inclinadas se leían como preocupación/sufrimiento): concentrado, no agobiado.
    "writing":    dict(eye_h=0.9, eye_w=1.05, arc=0, curve=0.60, open=0, blush=0.10, brow=0, lx=0, ly=0.55, tr=0, tg=0, tb=0),     # mirando la hoja, siguiendo el renglón
    "searching":  dict(eye_h=1.2, eye_w=1.10, arc=0, curve=0.40, open=0, blush=0, brow=0, lx=0, ly=0, tr=0, tg=0, tb=0),            # ojos atentos: lupa que recorre la pantalla
    "waiting":    dict(eye_h=1.0, eye_w=1.0, arc=0, curve=0.35, open=0, blush=0, brow=0, lx=0, ly=-0.40, tr=0, tg=0, tb=0),        # mirando hacia arriba, tranquilo, esperando que cargue
    "organizing": dict(eye_h=0.95, eye_w=1.1, arc=0, curve=0.75, open=0, blush=0.20, brow=0, lx=0, ly=0.1, tr=0, tg=0, tb=0),     # sonrisita, ojos que reparten de lado a lado
    # emociones «de transición»: lo que queda un rato después de otra emoción (ver EMO_AFTER) y la duda
    "content":   dict(eye_h=0.9, eye_w=1.05, arc=0, curve=0.85, open=0, blush=0.25, brow=0, lx=0, ly=0, tr=0, tg=0, tb=0),         # contento, relajado
    "down":      dict(eye_h=0.85, eye_w=1.0, arc=0, curve=-0.30, open=0, blush=0, brow=0.35, lx=0, ly=0.35, tr=0, tg=0, tb=0),    # un poco bajoneado
    "confused":  dict(eye_h=1.05, eye_w=1.0, arc=0, curve=-0.10, open=0, blush=0, brow=0.20, lx=0.6, ly=-0.5, tr=0, tg=0, tb=0), # duda (sale un «?» a un lado)
    "curious":   dict(eye_h=1.25, eye_w=1.05, arc=0, curve=0.12, open=0.16, blush=0.12, brow=0.50, lx=0.5, ly=-0.35, tr=0, tg=0, tb=0), # pregunta algo: ojotes, cejas arriba, bocota chica (sale su «?»)
    # caras de baile (las elige DANCE_STYLES según el estilo de la música)
    "party":     dict(eye_h=1.2, eye_w=1.2, arc=1, curve=1.2, open=0.55, blush=0.4, brow=0, lx=0, ly=0, tr=0, tg=0, tb=0),     # ojos ^ ^ y boca abierta cantando
    "cool":      dict(eye_h=0.45, eye_w=1.2, arc=0, curve=0.95, open=0, blush=0, brow=-0.2, lx=0, ly=0.15, tr=0, tg=0, tb=0),  # ojos de lado, sonrisa de medio lado
    "rocker":    dict(eye_h=0.75, eye_w=1.1, arc=0, curve=-0.3, open=0.5, blush=0, brow=-0.75, lx=0, ly=0, tr=0, tg=0, tb=0),  # ceño y grito
    "dreamy":    dict(eye_h=0.3, eye_w=1.2, arc=1, curve=1.0, open=0, blush=0.65, brow=0, lx=0, ly=0.1, tr=0, tg=0, tb=0),     # ojitos cerrados, mejillas rosas
}
# Color propio de CADA emoción (r, g, b, peso 0-1): se mezcla con el color del estado. Antes solo se sumaba un tinte
# pequeño y varias caras (thinking, surprised, sleepy, attentive, working) casi no cambiaban de color.
EMO_COLOR = {
    "neutral":   (0, 0, 0, 0.0),
    "attentive": (120, 215, 255, 0.35),
    "happy":     (110, 220, 130, 0.55),
    "love":      (255, 100, 160, 0.72),
    "sad":       (60, 80, 150, 0.65),
    "surprised": (255, 225, 80, 0.62),
    "thinking":  (165, 120, 255, 0.58),
    "angry":     (240, 45, 40, 0.78),
    "excited":   (255, 130, 40, 0.68),
    "sleepy":    (70, 70, 120, 0.55),
    "working":   (60, 200, 190, 0.45),
    "writing":    (125, 150, 255, 0.55),
    "searching":  (255, 215, 80, 0.58),
    "waiting":    (255, 150, 70, 0.55),
    "organizing": (90, 230, 170, 0.55),
    "content":   (150, 225, 160, 0.40),
    "down":      (80, 100, 160, 0.45),
    "confused":  (190, 150, 255, 0.50),
    "curious":   (105, 205, 240, 0.48),
    "party":     (255, 105, 70, 0.65),
    "cool":      (150, 95, 255, 0.55),
    "rocker":    (235, 40, 60, 0.72),
    "dreamy":    (255, 150, 205, 0.55),
}
# emociones de «chamba» y cómo se mueven los ojos en cada una (lx/ly de -1 a 1)
WORK_EMOS = ("working", "writing", "searching", "waiting", "organizing")
WORK_MOTION = {
    "working":    lambda t: dict(lx=math.sin(t * 2.4) * 0.85),                                   # va y viene como leyendo
    "writing":    lambda t: dict(lx=((t * 1.5) % 1.0) * 1.5 - 0.75),                             # recorre un renglón y salta al siguiente
    "searching":  lambda t: dict(lx=math.cos(t * 2.3) * 0.8, ly=math.sin(t * 2.3) * 0.6),        # círculos, como una lupa
    "waiting":    lambda t: dict(lx=math.sin(t * 0.9) * 0.3),                                    # mirada arriba, casi quieta
    "organizing": lambda t: dict(lx=0.8 if math.sin(t * 4.5) > 0 else -0.8),                     # reparte a izquierda y derecha
}
for _n, _f in FACES.items():
    _c = EMO_COLOR.get(_n, (0, 0, 0, 0.0))
    _f.update(er=_c[0], eg=_c[1], eb=_c[2], ew=_c[3], tr=0, tg=0, tb=0)
# sinónimos: si la IA manda una emoción que no existe, se usa la más parecida (antes caía en neutral = sin color)
EMO_ALIAS = {"curioso": "curious", "preguntando": "curious", "pregunta": "curious", "focused": "working", "concentrated": "working",
             "proud": "happy", "grateful": "love", "affectionate": "love", "tired": "sleepy", "bored": "sleepy",
             "worried": "sad", "disappointed": "sad", "confused": "confused", "dudoso": "confused", "duda": "confused", "doubt": "confused", "unsure": "confused", "puzzled": "confused", "confundido": "confused", "embarrassed": "surprised",
             "shocked": "surprised", "playful": "excited", "joyful": "happy", "calm": "attentive", "mad": "angry",
             "frustrated": "angry", "scared": "surprised", "nervous": "surprised", "alegre": "happy", "triste": "sad",
             "enojado": "angry", "emocionado": "excited", "sorprendido": "surprised", "pensando": "thinking",
             "cansado": "sleepy", "amor": "love", "feliz": "happy"}


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


COLOR_PRESETS = {
    "Azul (clásico)": (70, 150, 255), "Verde": (60, 200, 150), "Rosa": (255, 130, 190), "Morado": (170, 110, 255),
    "Naranja": (255, 170, 60), "Rojo": (255, 90, 70), "Turquesa": (90, 190, 200), "Blanco": (225, 232, 245),
}
EMOTIONS = ["neutral", "happy", "love", "sad", "surprised", "thinking", "sleepy", "angry", "excited", "confused", "curious"]
# lo que queda DESPUÉS de una emoción (en vez de saltar a neutral de golpe): las emociones se apagan poco a poco, como en una persona
EMO_AFTER = {"excited": "happy", "happy": "content", "love": "content", "dreamy": "content", "surprised": "attentive",
             "sad": "down", "angry": "down", "party": "happy"}
# cuánto sube o baja el «ánimo» cada emoción nueva (el ánimo tiñe la cara neutral: sonrisita si ha ido bien, más serio si ha ido mal)
MOOD_VALENCE = {"happy": 0.12, "love": 0.20, "excited": 0.15, "content": 0.05, "party": 0.08, "dreamy": 0.10, "cool": 0.04,
                "sad": -0.20, "angry": -0.20, "down": -0.05, "confused": -0.04}
# objeto que sostiene (con una mano invisible) según lo que está haciendo; None = nada
PROP_FOR = {"writing": "pen", "searching": "lupa", "working": "gear", "organizing": "folder", "waiting": "hourglass", "confused": "question",
            "curious": "question", "thinking": "nube"}      # «?» cuando pregunta o duda; nube con «...» cuando piensa

LERP_KEYS = list(FACES["neutral"].keys())


EMOTION_RULES = [  # (emoción, puntos, patrón)
    ("love", 3, r"❤|💙|💕|😍|🥰"), ("love", 2, r"te quiero|te amo|con cariño"),
    ("sad", 3, r"😢|😔|😞|🥲|😭"),
    ("sad", 2, r"lo siento|perdón|disculpa|qué mal|lamentablemente|lamento"),
    ("sad", 1, r"no pude|no puedo|\berror\b|no encontré"),          # solo suman, no bastan solos
    ("surprised", 3, r"😮|😲|🤯"),
    ("surprised", 2, r"\bwow\b|no manches|órale|increíble|no lo puedo creer"),
    ("surprised", 1, r"\bvaya\b|en serio\?"),
    ("thinking", 2, r"🤔|hmm+|déjame pensar|veamos|a ver\b|dame un segundo"),
    ("confused", 2, r"no entend|no estoy segur|a qué te refieres|no me queda claro|me confund|no sé si|puedes (repetir|aclarar|explicar)|\bperdona\?"),
    ("angry", 3, r"😠|😡|🤬"), ("angry", 2, r"qué coraje|me molesta|qué molesto|qué enojo"),
    ("excited", 3, r"🤩|🥳|🚀"), ("excited", 2, r"qué emoción|emocionad|vamos con todo|no puedo esperar"),
    ("sleepy", 3, r"😴"), ("sleepy", 2, r"buenas noches|descansa|tengo sueño"),
    ("happy", 3, r"😊|😄|😁|😀|🎉|✨|😎"),
    ("happy", 2, r"jaja|jeje|\bxd\b|genial|excelente|buen[ií]simo|perfecto|con gusto|de nada|claro que sí"),
    ("happy", 1, r"\blisto\b|\bclaro\b"),
]
EMOTION_THRESHOLD = 2


def emotion_from_text(text: str) -> str:
    """Adivina la emoción de una respuesta por puntos (emojis y palabras clave)."""
    t = text.lower()
    score = {}
    for emo, pts, pat in EMOTION_RULES:
        if re.search(pat, t):
            score[emo] = score.get(emo, 0) + pts
    if not score:
        return "neutral"
    best = max(score, key=score.get)
    return best if score[best] >= EMOTION_THRESHOLD else "neutral"

