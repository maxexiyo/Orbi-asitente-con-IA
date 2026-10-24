"""La bolita: widget PySide6 con estados, emociones, burbuja y esconderse en el borde."""
import json, math, os, random, re, sys, time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, QPropertyAnimation, QEasingCurve, QPoint, QAbstractAnimation
from PySide6.QtGui import (QPainter, QRadialGradient, QLinearGradient, QColor, QBrush, QPen,
                           QPainterPath, QCursor, QFont, QGuiApplication)
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QLabel, QVBoxLayout
import orb_dodge

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
DANCE_FACE_SNAP = True      # True: al bailar, la carita cambia de golpe (el color de la emoción sí se funde); False: todo se funde suave

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
    "working":   dict(eye_h=0.8, eye_w=1.05, arc=0, curve=0.1, open=0, blush=0, brow=-0.35, lx=0, ly=0.55, tr=0, tg=18, tb=25),
    # caras por TIPO de chamba (las elige live_orb.py según la herramienta; el movimiento de los ojos está en WORK_MOTION)
    "writing":    dict(eye_h=0.75, eye_w=1.05, arc=0, curve=0.25, open=0, blush=0, brow=-0.15, lx=0, ly=0.7, tr=0, tg=0, tb=0),    # mirando el texto, siguiendo el renglón
    "searching":  dict(eye_h=1.4, eye_w=1.15, arc=0, curve=0.05, open=0, blush=0, brow=0.3, lx=0, ly=0, tr=0, tg=0, tb=0),         # ojotes: lupa que recorre la pantalla
    "waiting":    dict(eye_h=1.05, eye_w=1.0, arc=0, curve=0.0, open=0.2, blush=0, brow=0.25, lx=0, ly=-0.55, tr=0, tg=0, tb=0),  # mirando hacia arriba, esperando que cargue
    "organizing": dict(eye_h=0.95, eye_w=1.1, arc=0, curve=0.55, open=0, blush=0.15, brow=0.1, lx=0, ly=0.1, tr=0, tg=0, tb=0),    # sonrisita, ojos que reparten de lado a lado
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
EMO_ALIAS = {"curious": "attentive", "curioso": "attentive", "focused": "working", "concentrated": "working",
             "proud": "happy", "grateful": "love", "affectionate": "love", "tired": "sleepy", "bored": "sleepy",
             "worried": "sad", "disappointed": "sad", "confused": "thinking", "embarrassed": "surprised",
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
EMOTIONS = ["neutral", "happy", "love", "sad", "surprised", "thinking", "sleepy", "angry", "excited"]
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


class Bubble(QWidget):
    """Burbuja de texto que flota sobre la bolita."""
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(); self.label.setWordWrap(True); self.label.setMaximumWidth(340)
        self.label.setStyleSheet(
            "background: rgba(18,28,58,235); color: #eaf2ff; border: 1px solid rgba(120,170,255,120);"
            "border-radius: 16px; padding: 10px 14px; font-size: 14px; font-family: 'Segoe UI';")
        lay.addWidget(self.label)
        self.hide_timer = QTimer(self); self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

    def show_text(self, text, anchor: QPoint, orb_radius, seconds=None):
        self.label.setText(text)
        self.label.adjustSize(); self.adjustSize()
        self.place(anchor, orb_radius)
        self.show()
        seconds = seconds if seconds is not None else max(3.5, min(14, len(text) * 0.07))
        self.hide_timer.start(int(seconds * 1000))

    def place(self, anchor: QPoint, orb_radius):
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        x = anchor.x() - self.width() // 2
        y = anchor.y() - orb_radius - 18 - self.height()
        if y < g.top() + 4:                      # no cabe arriba -> abajo
            y = anchor.y() + orb_radius + 18
        x = max(g.left() + 4, min(x, g.right() - self.width() - 4))
        self.move(x, y)


class Pointer(QWidget):
    """Anillo pulsante transparente al ratón para SEÑALAR algo en la pantalla."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(170, 170)
        self._t0 = 0.0; self._until = 0.0
        self._timer = QTimer(self); self._timer.timeout.connect(self._tick)

    def show_at(self, gx, gy, seconds=5.0):
        self.move(int(gx - 85), int(gy - 85))
        self._t0 = time.time(); self._until = self._t0 + seconds
        self.show(); self.raise_(); self._timer.start(16)

    def _tick(self):
        if time.time() > self._until:
            self._timer.stop(); self.hide(); return
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        now = time.time(); t = now - self._t0
        fade = max(0.0, min(1.0, (self._until - now) / 0.6))
        c = QPointF(85, 85)
        for k in (0.0, 0.5):
            ph = (t * 1.2 + k) % 1.0
            col = QColor(255, 190, 60, int(230 * (1 - ph) * fade))
            p.setBrush(Qt.NoBrush); p.setPen(QPen(col, 4))
            rr = 14 + ph * 58
            p.drawEllipse(c, rr, rr)
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 120, 40, int(230 * fade)))
        p.drawEllipse(c, 6, 6)


class Orb(QWidget):
    clicked = Signal()
    petted = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(W, H)
        self.setMouseTracking(True)                     # para detectar caricias (pasar el mouse por encima sin clic)

        self.state = "idle"
        self.emotion = "neutral"
        self._emotion_until = None
        self.level = 0.0; self._level_target = 0.0
        self.t = 0.0
        self.blink = 0.0; self._next_blink = 3.0
        self._eye_wander = [0.0, 0.0]; self._next_wander = 2.0
        self.last_active = time.time()
        self.keep_awake = lambda: False                 # la app lo reemplaza: no dormirse si hay tarea/observador
        self.standby = False                            # esperando la palabra clave (se ve un poco más apagada)
        self.ripples = []; self._last_ripple = 0.0
        self._look = None; self._look_until = 0.0       # (lx, ly) hacia dónde mira (al señalar algo)
        self.hearts = []                                # corazones flotando tras una caricia: (nacimiento, desplazamiento)
        self.dancing = False; self._beat = 0.0; self._dance_dir = 1   # bailar con la música (lo activa live_orb)
        self.dance_style = "pop"                        # cómo baila (DANCE_STYLES)
        self._hx = self._hy = self._rot = 0.0           # cabeza: la carita se corre, cabecea y se inclina al bailar
        self._dface = "excited"; self._dface_next = 0.0  # cara de baile actual y cuándo cambia
        self._dx = 0.0; self._dy = 0.0
        self._intro_t0 = None                           # animación de aparecer (play_intro)
        self._outro_t0 = None; self._outro_done = False  # animación de despedirse (quit_animated)
        self._pet_acc = 0.0; self._pet_last = None; self._pet_t = 0.0; self._pet_cool = 0.0
        self.pointer = Pointer()
        self._move_anim = QPropertyAnimation(self, b"pos", self)
        self._move_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._move_anim.valueChanged.connect(lambda _v: self.bubble.isVisible() and self.bubble.place(self._center_global(), R0))

        self.p = dict(FACES["neutral"])                 # parámetros actuales (suavizados)
        self.col = list(STATE_COLORS["idle"])           # color actual (suavizado)

        self._drag = None; self._press_pos = None; self._moved = False
        self.edge = None                                # None | "left" | "right"
        self.revealed = False; self._leave_since = None
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(260); self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self.bubble = Bubble()
        self._menu_actions = []
        self._menu_groups = []

        t = QTimer(self); t.timeout.connect(self._tick); t.start(16)
        h = QTimer(self); h.timeout.connect(self._poll_edge); h.start(120)
        v = QTimer(self); v.timeout.connect(self._keep_visible); v.start(1500)

    # ------------------------------------------------------------------ aparecer / despedirse
    INTRO_S = 0.9
    OUTRO_S = 0.6

    def play_intro(self):
        """Aparece creciendo desde cero con un pequeño rebote y una onda de energía."""
        self._intro_t0 = time.time()
        self.ripples.append(self.t); self._last_ripple = self.t
        self.set_emotion("happy", 1.8)

    def quit_animated(self):
        """Se infla un poquito, se encoge hasta desaparecer y recién entonces cierra la app."""
        if self._outro_t0 is not None:
            return
        self.bubble.hide()
        self._outro_t0 = time.time()
        self.ripples.append(self.t); self._last_ripple = self.t
        self.set_emotion("happy", 1.0)
        QTimer.singleShot(int((self.OUTRO_S + 0.9) * 1000), QApplication.quit)    # respaldo por si algo traba el timer

    def _appear_factors(self, now):
        """-> (escala, opacidad) de la animación de entrada/salida (1, 1 si no hay ninguna)."""
        c1 = 1.70158; c3 = c1 + 1
        if self._outro_t0 is not None:
            x = max(0.0, min(1.0, (now - self._outro_t0) / self.OUTRO_S))
            ease = c3 * x ** 3 - c1 * x ** 2                   # easeInBack: primero se infla, luego cae a 0
            return max(0.0, 1.0 - ease), 1.0 - max(0.0, (x - 0.5) / 0.5)
        if self._intro_t0 is not None:
            x = (now - self._intro_t0) / self.INTRO_S
            if x >= 1.0:
                self._intro_t0 = None
                return 1.0, 1.0
            x = max(0.0, x)
            return max(0.0, 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2), min(1.0, x * 3.0)   # easeOutBack
        return 1.0, 1.0

    # ------------------------------------------------------------------ API
    def set_base_color(self, rgb):
        """Cambia el color base de Orbi (los demás estados se derivan de él). None = el azul de siempre."""
        rgb = tuple(int(max(0, min(255, v))) for v in (rgb or (70, 150, 255)))[:3]
        STATE_COLORS["idle"] = rgb
        STATE_COLORS["speaking"] = rgb
        STATE_COLORS["listening"] = _mix(rgb, (255, 255, 255), 0.30)
        STATE_COLORS["thinking"] = _mix(rgb, (140, 120, 255), 0.55)
        STATE_COLORS["sleeping"] = _mix(rgb, (20, 25, 45), 0.55)
        globals()["STANDBY_COLOR"] = _mix(rgb, (20, 25, 45), 0.18)

    def add_menu_group(self, title, options, on_pick, current=None):
        """Submenú con opciones excluyentes. options: [(etiqueta, valor)]; on_pick(valor); current(): valor marcado."""
        self._menu_groups.append((title, options, on_pick, current))

    def set_state(self, s):
        if s not in STATE_COLORS: return
        self.state = s
        if s != "idle": self.last_active = time.time()

    def set_emotion(self, name, hold=4.0):
        name = EMO_ALIAS.get(str(name).lower().strip(), str(name).lower().strip())
        self.emotion = name if name in FACES else "neutral"
        self._emotion_until = time.time() + hold if (hold and self.emotion != "neutral") else None
        self.last_active = time.time()

    def set_level(self, x):
        self._level_target = max(0.0, min(1.0, x))

    def set_dancing(self, on):
        """Empieza/termina el baile (la música se detecta en audio_react.py)."""
        self.dancing = bool(on)
        if self.dancing:
            self.last_active = time.time()
            if self.state == "idle": self.set_emotion(self._dface, 3.0); self._snap_face()

    def _snap_face(self):
        """Pone la carita (ojos, cejas, boca, mejillas) en la objetivo AL INSTANTE, sin pasar por caras intermedias."""
        if not DANCE_FACE_SNAP:
            return
        t = self._face_target()
        for k in LERP_KEYS:
            if k not in COLOR_KEYS:                  # el color de la emoción sí se funde suave; solo la carita salta
                self.p[k] = t[k]

    def set_dance_style(self, name):
        """Cambia cómo baila (salsa, cumbia, reggaeton, rock...). Si no existe, se queda como estaba."""
        if name in DANCE_STYLES and name != self.dance_style:
            self.dance_style = name
            self._dface = DANCE_STYLES[name]["caras"][0]; self._dface_next = time.time() + random.uniform(4.0, 8.0)
            if self.dancing and self.state in ("idle", "listening") and not self.edge:
                self.set_emotion(self._dface, 3.0); self._snap_face()

    def beat(self, strength=1.0):
        """Un golpe de ritmo: rebote hacia arriba y se carga al otro lado."""
        if not self.dancing: return
        self._beat = max(self._beat, 0.45 + 0.55 * max(0.0, min(1.0, float(strength))))
        self._dance_dir = -self._dance_dir
        self.last_active = time.time()
        if self.state in ("idle", "listening"): self.set_emotion(self._dface, 3.0)

    def say(self, text, seconds=None):
        self.last_active = time.time()
        self.bubble.show_text(text, self._center_global(), R0, seconds)

    def add_menu_action(self, text, callback, checkable=False, checked=None):
        """checked: función que devuelve si la casilla está marcada (para acciones checkable)."""
        self._menu_actions.append((text, callback, checkable, checked))

    def wake(self):
        if self.state == "sleeping":
            self.state = "idle"
        self.last_active = time.time()

    def summon(self):
        """Trae la bolita de vuelta (si se perdió detrás de otra ventana o fuera de la pantalla)."""
        if not self._on_a_screen():
            self._to_safe_place()
        self.show(); self.raise_()
        self._force_top()
        self.wake(); self.reveal()
        self.set_emotion("happy", 2); self.say("¡Aquí estoy! 👋", 2.5)

    def _on_a_screen(self):
        c = self._center_global()
        return any(sc.geometry().contains(c) for sc in QGuiApplication.screens())

    def _to_safe_place(self):
        g = QGuiApplication.primaryScreen().availableGeometry()
        cx, cy = g.right() - R0 - 30, g.top() + R0 + 90
        self.edge = None; self.revealed = False
        self.move(cx - W // 2, cy - H // 2)

    def _force_top(self):
        if sys.platform == "win32":
            try:
                from windows import force_topmost
                force_topmost(int(self.winId()))
                if self.bubble.isVisible():
                    force_topmost(int(self.bubble.winId()))
            except Exception:
                pass

    def _keep_visible(self):
        """Windows a veces pierde el "siempre encima" al abrir otras apps: se vuelve a afirmar cada 1.5 s."""
        try:
            if self.isMinimized():
                self.showNormal()
            if not self.isVisible():
                self.show()
            if not self._on_a_screen():
                self._to_safe_place()
            self._force_top()
        except Exception:
            pass

    def reveal(self):
        """Si está escondida en el borde, la saca."""
        if self.edge and not self.revealed:
            self.revealed = True; self._leave_since = None
            self._slide_to(self._edge_pos(self.edge, reveal=True))

    def anchor(self):
        return self._center_global()

    def _center_global(self):
        return self.mapToGlobal(QPoint(W // 2, H // 2))

    # --------------------------------------------------------------- lógica
    def _face_target(self):
        if self.state == "sleeping": return FACES["sleepy"]
        if self._look and time.time() < self._look_until:
            return {**FACES[self.emotion if self.emotion != "neutral" else "attentive"], "lx": self._look[0], "ly": self._look[1]}
        if self.emotion in WORK_MOTION:                                            # cada tipo de chamba mueve los ojos distinto
            return {**FACES[self.emotion], **WORK_MOTION[self.emotion](self.t)}
        if self.emotion == "neutral":
            if self.state == "thinking": return FACES["thinking"]
            if self.state == "listening": return FACES["attentive"]
        return FACES[self.emotion]

    def _tick(self):
        dt = 0.016
        self.t += dt
        now = time.time()

        if self._outro_t0 is not None and not self._outro_done and now - self._outro_t0 >= self.OUTRO_S + 0.05:
            self._outro_done = True
            QApplication.quit()
            return

        if SLEEP_AFTER and self.state == "idle" and now - self.last_active > SLEEP_AFTER and not self.keep_awake():
            self.state = "sleeping"
        if self._emotion_until and now > self._emotion_until:
            self.emotion = "neutral"; self._emotion_until = None

        # nivel de voz suavizado
        self.level += (self._level_target - self.level) * 0.35
        self._level_target *= 0.90

        # parpadeo
        if self.t >= self._next_blink:
            self.blink = min(1.0, self.blink + 0.4)
            if self.blink >= 1.0: self._next_blink = self.t + random.uniform(2.5, 5.5)
        else:
            self.blink = max(0.0, self.blink - 0.25)

        # mirada que divaga un poquito
        if self.t >= self._next_wander:
            self._eye_wander = [random.uniform(-0.5, 0.5), random.uniform(-0.3, 0.3)]
            self._next_wander = self.t + random.uniform(2.0, 5.0)

        # suavizado hacia la cara objetivo
        target = self._face_target()
        for k in LERP_KEYS:
            self.p[k] += (target[k] - self.p[k]) * 0.14
        base = STANDBY_COLOR if (self.standby and self.state == "idle") else STATE_COLORS[self.state]
        for i in range(3):
            self.col[i] += (base[i] - self.col[i]) * 0.10

        # ondas al hablar/escuchar
        if self.state in ("listening", "speaking") and self.level > 0.25 and self.t - self._last_ripple > 0.45:
            self.ripples.append(self.t); self._last_ripple = self.t
        self.ripples = [b for b in self.ripples if self.t - b < 1.3]

        # baile: rebota en cada golpe de ritmo y se mece entre golpes (solo si no está hablando ni escondida en el borde)
        ds = DANCE_STYLES.get(self.dance_style, DANCE_STYLES["pop"])
        self._beat *= ds["decay"]
        active = self.dancing and self.state in ("idle", "listening") and not self.edge
        tx = (self._dance_dir * ds["dx"] * self._beat + math.sin(self.t * ds["sw"]) * ds["sway"]) if active else 0.0
        ty = (ds["dy"] * self._beat) if active else 0.0
        self._dx += (tx - self._dx) * 0.30
        self._dy += (ty - self._dy) * 0.45
        hx = (self._dance_dir * ds["hx"] * self._beat + math.sin(self.t * ds["sw"]) * ds["hsway"]) * R0 if active else 0.0
        hy = ds["nod"] * self._beat * R0 if active else 0.0
        rt = (self._dance_dir * ds["tilt"] * self._beat + math.sin(self.t * ds["sw"] * 0.5) * ds["tsway"]) if active else 0.0
        self._hx += (hx - self._hx) * 0.35; self._hy += (hy - self._hy) * 0.45; self._rot += (rt - self._rot) * 0.30
        if active and now >= self._dface_next:                      # cada 4-8 s cambia de expresión (dentro de las del estilo)
            opciones = [x for x in ds["caras"] if x != self._dface] or list(ds["caras"])
            self._dface = random.choice(opciones); self._dface_next = now + random.uniform(4.0, 8.0)
            self.set_emotion(self._dface, 3.0); self._snap_face()

        self.update()

    # ----------------------------------------------------------------- dibujo
    def _color(self):
        w = max(0.0, min(1.0, self.p.get("ew", 0.0)))
        tgt = (self.p.get("er", 0), self.p.get("eg", 0), self.p.get("eb", 0))
        return QColor(*[int(max(0, min(255, self.col[i] + (tgt[i] - self.col[i]) * w))) for i in range(3)])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        _s, _o = self._appear_factors(time.time())
        if _s != 1.0 or _o != 1.0:                       # entrada/salida: escala y opacidad alrededor del centro
            p.translate(W / 2, H / 2); p.scale(_s, _s); p.translate(-W / 2, -H / 2)
            p.setOpacity(max(0.0, min(1.0, _o)))
        c = QPointF(W / 2 + self._dx, H / 2 + self._dy)
        pulse, speed = STATE_MOTION[self.state]
        r = R0 * (1 + pulse * math.sin(self.t * speed) + self.level * 0.16 + self._beat * DANCE_STYLES.get(self.dance_style, DANCE_STYLES["pop"])["pulse"])
        col = self._color()
        sleeping = self.state == "sleeping"

        # --- glow
        glow = QRadialGradient(c, r * 2.5)
        g0 = QColor(col); g0.setAlpha(int((70 if sleeping else 150) * (0.85 + self.level * 0.5)))
        g1 = QColor(col); g1.setAlpha(0)
        glow.setColorAt(0.30, g0); glow.setColorAt(1.0, g1)
        p.setPen(Qt.NoPen); p.setBrush(QBrush(glow))
        p.drawEllipse(c, r * 2.5, r * 2.5)

        # --- ondas
        for born in self.ripples:
            age = (self.t - born) / 1.3
            rc = QColor(col.lighter(150)); rc.setAlpha(int(130 * (1 - age)))
            p.setBrush(Qt.NoBrush); p.setPen(QPen(rc, 2))
            rr = r * (1.05 + age * 0.9)
            p.drawEllipse(c, rr, rr)

        # --- cuerpo
        body = QRadialGradient(c, r, QPointF(c.x() - r * 0.35, c.y() - r * 0.40))
        body.setColorAt(0.0, col.lighter(175)); body.setColorAt(0.55, col); body.setColorAt(1.0, col.darker(160))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(body))
        p.drawEllipse(c, r, r)

        # --- brillo interno que se mueve (recortado a la bolita)
        clip = QPainterPath(); clip.addEllipse(c, r, r)
        p.save(); p.setClipPath(clip)
        sc = QPointF(c.x() + math.cos(self.t * 0.7) * r * 0.35, c.y() + math.sin(self.t * 0.9) * r * 0.30 + r * 0.2)
        sh = QRadialGradient(sc, r * 0.8)
        s0 = QColor(255, 255, 255, 55); s1 = QColor(255, 255, 255, 0)
        sh.setColorAt(0, s0); sh.setColorAt(1, s1)
        p.setBrush(QBrush(sh)); p.drawEllipse(sc, r * 0.8, r * 0.8)
        p.restore()

        # --- borde tipo cristal + destello
        rim = QColor(255, 255, 255, 70)
        p.setBrush(Qt.NoBrush); p.setPen(QPen(rim, 1.6)); p.drawEllipse(c, r - 1, r - 1)
        p.save(); p.translate(c.x() - r * 0.32, c.y() - r * 0.50); p.rotate(-28)
        hl = QLinearGradient(0, -r * 0.1, 0, r * 0.1)
        hl.setColorAt(0, QColor(255, 255, 255, 190)); hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(hl)); p.drawEllipse(QPointF(0, 0), r * 0.26, r * 0.12)
        p.restore()

        self._draw_face(p, c, r)

        # --- pensando: puntitos orbitando
        if self.state == "thinking":
            for i in range(3):
                a = self.t * 3.2 + i * 2.094
                pos = QPointF(c.x() + math.cos(a) * r * 1.4, c.y() + math.sin(a) * r * 1.4 * 0.45 - r * 0.9)
                p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 220))
                p.drawEllipse(pos, 3.6, 3.6)

        # --- corazones de la caricia
        self.hearts = [h for h in self.hearts if self.t - h[0] < 1.6]
        if self.hearts:
            p.setFont(QFont("Segoe UI", max(9, round(14 * SCALE / 0.72)), QFont.Bold))
            for born, dx in self.hearts:
                age = (self.t - born) / 1.6
                p.setPen(QColor(255, 105, 150, int(230 * (1 - age))))
                p.drawText(QPointF(c.x() + dx * r, c.y() - r * (0.9 + age * 1.0)), "♥")

        # --- durmiendo: zzz
        if sleeping:
            f = QFont("Segoe UI", 14, QFont.Bold); p.setFont(f)
            for i in range(3):
                ph = (self.t * 0.5 + i / 3) % 1.0
                p.setPen(QColor(220, 235, 255, int(200 * (1 - ph))))
                p.drawText(QPointF(c.x() + r * (0.7 + ph * 0.4), c.y() - r * (0.5 + ph * 0.9)), "z")

    def _draw_face(self, p, c, r):
        p.save()
        if abs(self._rot) > 0.05:                                # cabeza inclinada: gira la carita alrededor del centro del cuerpo
            p.translate(c); p.rotate(self._rot); p.translate(-c)
        c = QPointF(c.x() + self._hx, c.y() + self._hy)          # y se corre / cabecea respecto al cuerpo
        f = self.p
        ink = QColor(14, 28, 70)
        lx = (f["lx"] + self._eye_wander[0] * (1 if self.state in ("idle", "listening") else 0.2)) * r * 0.10
        ly = (f["ly"] + self._eye_wander[1] * (1 if self.state in ("idle", "listening") else 0.2)) * r * 0.08
        if self.edge and not self.revealed:                      # asomada: mira hacia la pantalla
            lx += (-1 if self.edge == "right" else 1) * r * 0.12
        ey = c.y() - r * 0.08 + ly

        # mejillas
        if f["blush"] > 0.03:
            bc = QColor(255, 120, 150, int(120 * min(1, f["blush"])))
            p.setPen(Qt.NoPen); p.setBrush(bc)
            for dx in (-0.55, 0.55):
                p.drawEllipse(QPointF(c.x() + r * dx + lx * 0.5, c.y() + r * 0.22), r * 0.13, r * 0.075)

        for dx in (-0.33, 0.33):
            ex = c.x() + r * dx + lx
            # ojos redondos (se desvanecen cuando arc -> 1)
            a_round = 1 - max(0.0, min(1.0, f["arc"]))
            if a_round > 0.02:
                rx = r * 0.10 * f["eye_w"]
                ry = max(1.6, r * 0.20 * f["eye_h"] * (1 - self.blink * 0.92))
                col = QColor(ink); col.setAlpha(int(255 * a_round))
                p.setPen(Qt.NoPen); p.setBrush(col); p.drawEllipse(QPointF(ex, ey), rx, ry)
                if ry > 5:                                    # brillito en el ojo
                    wc = QColor(255, 255, 255, int(230 * a_round))
                    p.setBrush(wc); p.drawEllipse(QPointF(ex - rx * 0.3, ey - ry * 0.35), rx * 0.32, rx * 0.32)
            # ojos felices ^ ^
            if f["arc"] > 0.02:
                ac = QColor(ink); ac.setAlpha(int(255 * min(1, f["arc"])))
                p.setBrush(Qt.NoBrush); p.setPen(QPen(ac, 3.8, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(QRectF(ex - r * 0.14, ey - r * 0.08, r * 0.28, r * 0.22), 25 * 16, 130 * 16)

        # cejas
        if abs(f["brow"]) > 0.05:
            bc = QColor(ink); bc.setAlpha(int(200 * min(1, abs(f["brow"]))))
            p.setPen(QPen(bc, 3, Qt.SolidLine, Qt.RoundCap))
            by = ey - r * 0.28
            tilt = f["brow"] * r * 0.09
            for sign in (-1, 1):
                x0 = c.x() + sign * r * 0.33 + lx
                inner = x0 - sign * r * 0.10; outer = x0 + sign * r * 0.10
                p.drawLine(QPointF(inner, by - tilt), QPointF(outer, by + tilt))

        # boca
        my = c.y() + r * 0.36 + ly * 0.5
        mx = c.x() + lx * 0.6
        talk = self.level * 1.25 if self.state == "speaking" else 0.0
        opened = max(f["open"], min(1.0, talk))
        if opened > 0.06:
            p.setPen(Qt.NoPen); p.setBrush(ink)
            p.drawEllipse(QPointF(mx, my), r * (0.12 + 0.05 * opened), 2.5 + opened * r * 0.30)
        else:
            path = QPainterPath()
            w = r * 0.36
            path.moveTo(mx - w / 2, my)
            path.quadTo(mx, my + f["curve"] * r * 0.42, mx + w / 2, my)
            p.setBrush(Qt.NoBrush); p.setPen(QPen(ink, 3.2, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
        p.restore()

    # --------------------------------------------------------------- ratón
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            dx, dy = e.position().x() - W / 2, e.position().y() - H / 2
            if (dx * dx + dy * dy) ** 0.5 > R0 * 1.15:      # clic en el halo (el brillo de alrededor): se ignora
                self._drag = None; e.ignore(); return
            self._anim.stop()
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_pos = e.globalPosition().toPoint(); self._moved = False
            self.edge = None; self.revealed = False
            if self.state == "sleeping": self.state = "idle"
            self.last_active = time.time()

    def _pet(self, e):
        """Acariciar = pasar el mouse sobre la bolita (sin clic) de un lado a otro varias veces."""
        if self.state == "sleeping" or e.buttons():
            return
        now = time.time()
        dx, dy = e.position().x() - W / 2, e.position().y() - H / 2
        gp = e.globalPosition().toPoint()
        if (dx * dx + dy * dy) ** 0.5 > R0 * 1.1 or now < self._pet_cool:
            self._pet_last = None; self._pet_acc = 0.0
            return
        self._pet_acc *= max(0.0, 1.0 - (now - self._pet_t) * 1.2)     # se enfría si paras
        if self._pet_last is not None:
            self._pet_acc += (gp - self._pet_last).manhattanLength()
        self._pet_last, self._pet_t = gp, now
        if self._pet_acc > 450 * SCALE:
            self._pet_acc = 0.0; self._pet_last = None; self._pet_cool = now + 6.0
            self.set_emotion("love", 3.5)
            self.hearts += [(self.t + i * 0.18, random.uniform(-0.7, 0.7)) for i in range(4)]
            self.wake()
            self.petted.emit()

    def move_to_global(self, cx, cy, ms=700):
        """Camina la bolita (con animación) hasta que su centro quede en (cx, cy) de la pantalla."""
        screen = QGuiApplication.screenAt(QPoint(int(cx), int(cy))) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        m = int(R0 * 1.3)
        cx = max(g.left() + m, min(g.right() - m, int(cx))); cy = max(g.top() + m, min(g.bottom() - m, int(cy)))
        self._anim.stop(); self._move_anim.stop()
        self.edge = None; self.revealed = False
        if self.state == "sleeping": self.state = "idle"
        self.last_active = time.time()
        self._move_anim.setDuration(ms)
        self._move_anim.setStartValue(self.pos())
        self._move_anim.setEndValue(QPoint(cx - W // 2, cy - H // 2))
        self._move_anim.start()

    def dodge(self, danger) -> bool:
        """Se aparta (esquina o borde) si estorba en la zona `danger` (x0,y0,x1,y1 globales); no se mueve si no hace falta."""
        now = time.time()
        if danger is None or self.state == "sleeping" or self.edge or self._drag is not None:
            return False
        if now < getattr(self, "_no_dodge_until", 0.0) or now - getattr(self, "_last_dodge", 0.0) < 3.0:
            return False
        c = self._center_global()
        center = (c.x(), c.y())
        half = int(R0 * 1.6)
        bub = None
        if self.bubble.isVisible():
            g = self.bubble.frameGeometry()
            bub = (g.left(), g.top(), g.right(), g.bottom())
        if not orb_dodge.needs_dodge(center, half, bub, danger):
            return False
        screen = QGuiApplication.screenAt(c) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        m = int(R0 * 1.3) + 40
        xs = (g.left() + m, g.center().x(), g.right() - m)
        ys = (g.top() + m, g.center().y(), g.bottom() - m)
        spots = [(x, y) for x in xs for y in ys if not (x == xs[1] and y == ys[1])]
        sx, sy = orb_dodge.pick_spot(center, spots, half, bub, danger)
        self._last_dodge = now
        self.move_to_global(sx, sy, 800)
        return True

    def avoid_text(self, ratio: float = 1.0, mon=None) -> bool:
        """Si la bolita (o su burbuja) está encima de texto de la pantalla, se mueve al hueco más vacío. True si se movió.
        Detector local, sin IA (orb_cover): mira las franjas que rodean a la bolita y, si hay texto a ambos lados o arriba y abajo,
        busca entre ~15 lugares el que tenga menos texto. `ratio` = devicePixelRatio de Qt, `mon` = screen.primary_monitor()."""
        now = time.time()
        if mon is None or self.edge or self.state == "sleeping" or self._drag is not None or self.dancing \
                or not self.isVisible() or self.underMouse():
            return False
        if now < getattr(self, "_no_dodge_until", 0.0) or now - getattr(self, "_last_dodge", 0.0) < 6.0:
            return False
        if self._move_anim.state() == QAbstractAnimation.State.Running or self._anim.state() == QAbstractAnimation.State.Running:
            return False
        try:
            import orb_cover as oc
        except Exception:                                          # noqa: BLE001  (sin numpy/mss: simplemente no se aparta)
            return False
        c = self._center_global()
        pscr = QGuiApplication.primaryScreen()
        pgeo = pscr.geometry()
        if not pgeo.contains(c):
            return False                                           # solo se vigila la pantalla principal (la que ve Orbi)
        r = float(ratio) or 1.0

        def phys(x, y):                                            # coordenadas de Qt -> píxeles físicos de mss
            return mon["left"] + (x - pgeo.x()) * r, mon["top"] + (y - pgeo.y()) * r

        half = R0 * 1.2
        x0, y0 = phys(c.x() - half, c.y() - half)
        x1, y1 = phys(c.x() + half, c.y() + half)
        rect = [x0, y0, x1, y1]
        bub_rel = None
        if self.bubble.isVisible():                                # la burbuja con texto también tapa
            bg = self.bubble.frameGeometry()
            bx0, by0 = phys(bg.left(), bg.top())
            bx1, by1 = phys(bg.right(), bg.bottom())
            rect = [min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)]
            cpx, cpy = phys(c.x(), c.y())
            bub_rel = (bx0 - cpx, by0 - cpy, bx1 - cpx, by1 - cpy)
        bounds = (mon["left"], mon["top"], mon["left"] + mon["width"], mon["top"] + mon["height"])
        cov = oc.cover_score(rect, bounds)
        self._last_cover = cov
        if cov < oc.COVER_ON:
            return False
        g = oc.grab_gray(mon["left"], mon["top"], mon["width"], mon["height"])
        if g is None:
            return False
        ag = pscr.availableGeometry()
        m = int(R0 * 1.3) + 40
        xs = (ag.left() + m, ag.left() + ag.width() * 0.25, ag.center().x(), ag.left() + ag.width() * 0.75, ag.right() - m)
        ys = (ag.top() + m, ag.center().y(), ag.bottom() - m)
        spots = [phys(x, y) for x in xs for y in ys]
        best = oc.choose_spot(g, (mon["left"], mon["top"]), bounds, rect, spots, half * r, bub_rel, cov)
        if best is None:
            return False                                           # no hay un hueco vacío: mejor quedarse
        lx = pgeo.x() + (best[0] - mon["left"]) / r
        ly = pgeo.y() + (best[1] - mon["top"]) / r
        self._last_dodge = now
        self.move_to_global(int(lx), int(ly), 800)
        return True

    def wander(self):
        """Se pasea a otro lugar de la pantalla (esquinas o mitad de los bordes), lejos de donde está ahora."""
        c = self._center_global()
        screen = QGuiApplication.screenAt(c) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        m = int(R0 * 1.3) + 40
        xs = (g.left() + m, g.center().x(), g.right() - m)
        ys = (g.top() + m, g.center().y(), g.bottom() - m)
        spots = [(x, y) for x in xs for y in ys if not (x == xs[1] and y == ys[1])]          # sin el centro: taparía lo que haces
        far = [s for s in spots if math.hypot(s[0] - c.x(), s[1] - c.y()) > min(g.width(), g.height()) * 0.35]
        gx, gy = random.choice(far or spots)
        self.move_to_global(gx + random.randint(-30, 30), gy + random.randint(-30, 30), random.randint(900, 1400))

    def point_at(self, gx, gy, text="", seconds=5.0):
        """Se pone junto al punto, lo mira y le dibuja un anillo pulsante."""
        screen = QGuiApplication.screenAt(QPoint(int(gx), int(gy))) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        side = -1 if gx > g.center().x() else 1                    # donde haya más espacio
        ox, oy = int(gx + side * (R0 * 2.4 + 60)), int(gy - R0 * 0.6)
        self._no_dodge_until = time.time() + seconds + 1.5          # señalando: aquí SÍ tiene que estar cerca
        self.move_to_global(ox, oy, 520)
        self._look = (-side * 1.6, max(-1.0, min(1.0, (gy - oy) / 200.0))); self._look_until = time.time() + seconds + 1.0
        self.set_emotion("attentive" if "attentive" in FACES else "happy", seconds)
        self.pointer.show_at(gx, gy, seconds)                       # el anillo sale YA; la bolita camina hacia allá al mismo tiempo
        if text:
            QTimer.singleShot(250, lambda: self.say(text, max(4.0, seconds)))

    def mouseMoveEvent(self, e):
        if self._drag is None:
            self._pet(e)
            return
        if self._drag is not None:
            gp = e.globalPosition().toPoint()
            if (gp - self._press_pos).manhattanLength() > 4: self._moved = True
            self.move(gp - self._drag)
            if self.bubble.isVisible(): self.bubble.place(self._center_global(), R0)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._drag is None: return
        self._drag = None
        if not self._moved:
            self.clicked.emit(); return
        self._try_snap_to_edge()

    def build_menu(self):
        m = QMenu(self)
        emo = m.addMenu("Probar emoción")
        for name in EMOTIONS:
            emo.addAction(name, lambda checked=False, n=name: self.set_emotion(n, 5))
        for title, options, on_pick, current in self._menu_groups:
            sub = m.addMenu(title)
            cur = current() if current else None
            for label, value in options:
                a = sub.addAction(label)
                a.setCheckable(True)
                a.setChecked(value == cur)
                a.triggered.connect(lambda checked=False, f=on_pick, v=value: f(v))
        m.addAction("Dormir", lambda checked=False: setattr(self, "state", "sleeping"))
        for text, cb, checkable, is_checked in self._menu_actions:
            a = m.addAction(text)
            a.setCheckable(checkable)
            if checkable and is_checked:
                a.setChecked(bool(is_checked()))
            a.triggered.connect(lambda checked=False, f=cb: f())
        m.addSeparator()
        m.addAction("Salir", lambda checked=False: self.quit_animated())
        return m

    def contextMenuEvent(self, e):
        self.build_menu().exec(e.globalPos())

    # ------------------------------------------------------- borde de pantalla
    def _screen_geo(self):
        s = QGuiApplication.screenAt(self._center_global()) or QGuiApplication.primaryScreen()
        return s.availableGeometry()

    def _edge_pos(self, edge, reveal):
        g = self._screen_geo()
        left_in_win, right_in_win = W // 2 - R0, W // 2 + R0
        y = max(g.top() - (H // 2 - R0), min(self.y(), g.bottom() - (H // 2 + R0)))
        if edge == "right":
            x = g.right() - right_in_win - 10 if reveal else g.right() - left_in_win - VIS
        else:
            x = g.left() + 10 - left_in_win if reveal else g.left() + VIS - right_in_win
        return QPoint(x, y)

    def _slide_to(self, pos):
        self._anim.stop(); self._anim.setStartValue(self.pos()); self._anim.setEndValue(pos); self._anim.start()
        self._anim.finished.connect(self._after_slide, Qt.UniqueConnection)

    def _after_slide(self):
        if self.bubble.isVisible(): self.bubble.place(self._center_global(), R0)

    def _try_snap_to_edge(self):
        g = self._screen_geo(); cx = self._center_global().x()
        if cx - g.left() < EDGE_SNAP + R0:   edge = "left"
        elif g.right() - cx < EDGE_SNAP + R0: edge = "right"
        else: return
        self.edge = edge; self.revealed = False
        self._slide_to(self._edge_pos(edge, reveal=False))
        self.set_emotion("sleepy", 1.5)

    def _poll_edge(self):
        if not self.edge or self._drag is not None: return
        cur = QCursor.pos()
        orb = self._center_global()
        near = abs(cur.x() - orb.x()) < R0 + 28 and abs(cur.y() - orb.y()) < R0 + 28
        if not self.revealed and near:
            self.revealed = True; self._leave_since = None
            self._slide_to(self._edge_pos(self.edge, reveal=True))
            self.set_emotion("happy", 2.0)
        elif self.revealed:
            far = abs(cur.x() - orb.x()) > R0 + 70 or abs(cur.y() - orb.y()) > R0 + 70
            if far:
                self._leave_since = self._leave_since or time.time()
                if time.time() - self._leave_since > 1.4:
                    self.revealed = False; self._leave_since = None
                    self._slide_to(self._edge_pos(self.edge, reveal=False))
            else:
                self._leave_since = None
