"""Orbi: la bolita. La clase Orb junta el estado, el ratón y los menús; el dibujo vive en orb_dibujo.py, el cuerpo controlado por la IA en
orb_cuerpo.py, los gestos predefinidos en orb_gestos.py, las ventanitas en orb_widgets.py y las tablas en orb_consts.py."""
import json, math, os, random, re, sys, time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, QPropertyAnimation, QEasingCurve, QPoint, QRect
from PySide6.QtGui import QPainter, QRadialGradient, QLinearGradient, QColor, QBrush, QPen, QPainterPath, QFont, QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QLabel, QVBoxLayout
import orb_dodge
import cuerpo as _cu
from orb_consts import *                       # (re-exporta las tablas: otros módulos hacen `from orb import FACES, R0…`)
from orb_consts import _cfg_val, _cfg_value, _mix
from orb_gestos import *
from orb_gestos import _env, _hold, _G0, _LOOK_DIR
from orb_widgets import Bubble, Pointer
from orb_cuerpo import CuerpoMixin
from orb_dibujo import DibujoMixin


class Orb(CuerpoMixin, DibujoMixin, QWidget):
    clicked = Signal()
    petted = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(W, H)
        self.setMouseTracking(True)                     # para detectar caricias (pasar el mouse por encima sin clic)
        self.halo_clickthrough = bool(_cfg_val("halo_clickthrough", True))   # el brillo de alrededor deja pasar los clics a lo que hay debajo
        self._hit_clickthrough = None
        self._hit_t = 0.0                               # última vez que se cambió entre sólida y transparente (anti-parpadeo del puntero, #47)
        self._hit_timer = QTimer(self); self._hit_timer.timeout.connect(self._hit_tick); self._hit_timer.start(30)

        self.state = "idle"
        self.emotion = "neutral"
        self._emotion_until = None
        self.level = 0.0; self._level_target = 0.0
        self.t = 0.0
        self.blink = 0.0; self._next_blink = 3.0
        self._eye_wander = [0.0, 0.0]; self._next_wander = 2.0
        self.last_active = time.time()
        self.keep_awake = lambda: False                 # la app lo reemplaza: no dormirse si hay tarea/observador
        self.sleep_lock = False                         # modo dormir manual: nada la despierta (eventos, clics, caricias) hasta que se desactive
        self.on_dormir = None                           # la app lo reemplaza: alterna el modo dormir (menú «Dormir / Despertar»)
        self._hint_t = 0.0
        self.standby = False                            # esperando la palabra clave (se ve un poco más apagada)
        self.ripples = []; self._last_ripple = 0.0
        self._look = None; self._look_until = 0.0       # (lx, ly) hacia dónde mira (al señalar algo)
        self.hearts = []                                # corazones flotando tras una caricia: (nacimiento, desplazamiento)
        self.dancing = False; self._beat = 0.0; self._dance_dir = 1   # bailar con la música (lo activa live_orb)
        self._bv = 0.0; self._omega = 12.0; self._beat_t = 0.0; self._dir_s = 1.0   # rebote con resorte (estilo Animal Crossing)
        self.dance_style = "pop"                        # cómo baila (DANCE_STYLES)
        self._hx = self._hy = self._rot = 0.0           # cabeza: la carita se corre, cabecea y se inclina al bailar
        self._dface = "excited"; self._dface_next = 0.0  # cara de baile actual y cuándo cambia
        self.trabajando_hasta = 0.0                      # mientras sea futuro está CHAMBEANDO: el baile no le cambia la cara (solo brinca)
        self._dx = 0.0; self._dy = 0.0
        self._g = dict(_G0); self._gestos = []          # lenguaje corporal libre: desplazamientos de los gestos activos [(t0, dur, nombre, k)]
        self._seq_id = 0                                # cada secuencia nueva de la IA cancela los pasos pendientes de la anterior
        # rig: cada parámetro es un resorte [valor, velocidad] hacia un objetivo que fija la IA (pose); vuelve solo a 0 al vencer su tiempo
        self._rig = {n: [_cu.POSE_DEFAULTS.get(n, 0.0), 0.0] for n in _cu.POSE_PARAMS}
        self._rig_obj = {n: _cu.POSE_DEFAULTS.get(n, 0.0) for n in _cu.POSE_PARAMS}; self._rig_hasta = {n: 0.0 for n in _cu.POSE_PARAMS}
        self._rig_vel = {n: 1.0 for n in _cu.POSE_PARAMS}
        self._jel = [0.0, 0.0, 0.0, 0.0]                # gelatina: [estiramiento x, velocidad, estiramiento y, velocidad] (resortes sueltos)
        self._pos_ant = None; self._vc = [0.0, 0.0]     # posición anterior y velocidad suavizada del cuerpo (px/s) para la gelatina
        self._sq = (1.0, 1.0)                           # escala final del cuerpo (aplastar + gelatina)
        self._rodar = None                              # (t0, duración, grados totales): al rodar por la pantalla la carita da vueltas
        self._salto_id = 0                              # cada «saltar» nuevo cancela los brincos pendientes del anterior
        self._lip_t = [0.0, 0.0]; self._lip = [0.0, 0.0]   # boca al hablar: [abierta, forma] (forma: -1 redonda «o/u» … 1 ancha «e/i»), objetivo y suavizado
        self.ia_control = True                          # el cuerpo lo maneja SOLO la IA: sin mirada que divaga al azar (interruptor de Ajustes > Funciones)
        # --- VIDA CONTINUA (siempre en local, sin IA ni avisos): deriva suave de cabeza/cuerpo/mirada, asentir mientras le hablas
        self._vida_voz = 0.0; self._vida_pausa = 0.0; self._vida_nod_t = 0.0
        self._intro_t0 = None                           # animación de aparecer (play_intro)
        self._outro_t0 = None; self._outro_done = False  # animación de despedirse (quit_animated)
        self._pet_acc = 0.0; self._pet_last = None; self._pet_t = 0.0; self._pet_cool = 0.0
        self.pointer = Pointer()
        self._move_anim = QPropertyAnimation(self, b"pos", self)
        self._move_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._move_anim.valueChanged.connect(lambda _v: self.bubble.isVisible() and self.bubble.place(self._center_global(), R0))

        self.mood = 0.0                                 # ánimo -1..1 (cómo ha ido todo últimamente); se apaga solo
        self._face_nm = "neutral"                       # carita base actual (para saltar al instante cuando cambia)
        self._prop_name = None; self._prop_k = 0.0; self._prop_t0 = 0.0; self._prop_force = None   # objeto en «mano»
        self.last_pet = 0.0
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

        try:                                            # "orb_fps": 60 por defecto; 30 repinta la bolita la mitad de veces (prueba contra parpadeos)
            _ms = max(16, int(1000 / max(15, min(60, int(_cfg_val("orb_fps", 60))))))
        except (TypeError, ValueError):
            _ms = 16
        t = QTimer(self); t.timeout.connect(self._tick); t.start(_ms)
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
        if self.sleep_lock and s != "sleeping": return      # en modo dormir ningún evento le cambia el estado
        if s == "listening" and self.state != "listening" and self.emotion == "curious":
            self.emotion = "neutral"; self._emotion_until = None      # le estás contestando: ya no hace falta la cara de pregunta
        self.state = s
        if s != "idle": self.last_active = time.time()

    def nudge_mood(self, d):
        """Sube o baja el ánimo (-1..1): lo usan las caricias, los regaños, etc. Se apaga solo con el tiempo."""
        self.mood = max(-0.8, min(0.8, self.mood + float(d)))

    def set_prop(self, name):
        """Fuerza el objeto que sostiene («pen», «lupa», «gear», «folder», «hourglass», «question») o None = el que toque por su emoción."""
        self._prop_force = name if name in ("pen", "lupa", "gear", "folder", "hourglass", "question", "nube") else None

    def set_emotion(self, name, hold=4.0):
        if self.sleep_lock: return
        name = EMO_ALIAS.get(str(name).lower().strip(), str(name).lower().strip())
        nuevo = name if name in FACES else "neutral"
        if nuevo != self.emotion:
            self.nudge_mood(MOOD_VALENCE.get(nuevo, 0.0))            # una emoción NUEVA mueve el ánimo (repetir la misma no suma)
        self.emotion = nuevo
        self._emotion_until = time.time() + hold if (hold and self.emotion != "neutral") else None
        self.last_active = time.time()

    def set_level(self, x):
        self._level_target = max(0.0, min(1.0, x))

    def _dance_emote(self, snap=False):
        """Cara de baile. Si está chambeando se queda la cara de chamba: el baile solo la hace brincar con la música (antes se peleaban y la cara
        cambiaba al azar entre baile y trabajo)."""
        if time.time() < self.trabajando_hasta:
            return
        self.set_emotion(self._dface, 3.0)
        if snap:
            self._snap_face()

    def set_dancing(self, on):
        """Empieza/termina el baile (la música se detecta en audio_react.py)."""
        if self.sleep_lock: on = False
        self.dancing = bool(on)
        if self.dancing:
            self.last_active = time.time()
            if self.state == "idle": self._dance_emote(True)

    def _snap_face(self):
        """Pone la carita (ojos, cejas, boca, mejillas) en la objetivo AL INSTANTE, sin pasar por caras intermedias."""
        if not FACE_SNAP:
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
                self._dance_emote(True)

    def beat(self, strength=1.0):
        """Un golpe de ritmo: rebote hacia arriba y se carga al otro lado."""
        if not self.dancing: return
        # REBOTE BLANDO: el golpe no «teletransporta» a Orbi, le da un empujón de velocidad a un resorte que lo sube, lo pasa un poquito
        # y lo regresa (boing, como los saltitos de Animal Crossing). El resorte rebota al ritmo de la canción (su periodo ≈ el
        # tiempo entre golpes), y ya no se corta de golpe si llega otro golpe en pleno salto.
        now = time.time()
        iv = now - self._beat_t; self._beat_t = now
        if 0.25 < iv < 1.6:
            self._omega = max(7.0, min(16.0, 0.75 * self._omega + 0.25 * (6.283 / iv)))
        peak = (0.45 + 0.55 * max(0.0, min(1.0, float(strength)))) * (1.0 - 0.30 * DANCE_SMOOTH)
        self._bv = peak * self._omega / 0.55          # velocidad inicial: con amortiguación ~0.5 el pico llega a ≈ `peak`
        self._dance_dir = -self._dance_dir
        self.last_active = time.time()
        if self.state in ("idle", "listening"): self._dance_emote(False)

    def say(self, text, seconds=None, force=False):
        if self.sleep_lock and not force: return          # dormida: ni burbujas (force=True solo para sus propios avisos de dormir/despertar)
        self.last_active = time.time()
        self.bubble.show_text(text, self._center_global(), R0, seconds)

    # Lo único que sale en el clic derecho (el resto de las funciones está en Ajustes -> Funciones). Se compara con «empieza con».
    MENU_BASICO = ("Silenciar micro", "Hablar ahora", "Detener tarea", "Traer a Orbi", "Ajustes")

    def add_menu_action(self, text, callback, checkable=False, checked=None, menu=None):
        """checked: función que devuelve si la casilla está marcada (para acciones checkable).
        menu: True = sale en el clic derecho · False = solo en Ajustes -> Funciones · None = según MENU_BASICO."""
        show = text.startswith(self.MENU_BASICO) if menu is None else bool(menu)
        self._menu_actions.append((text, callback, checkable, checked, show))

    def menu_items(self) -> list:
        """Todas las funciones registradas (también las que no salen en el clic derecho), para la ventana de Ajustes."""
        return [dict(text=t, cb=cb, checkable=c, checked=chk, en_menu=show) for t, cb, c, chk, show in self._menu_actions]

    def wake(self):
        if self.sleep_lock: return                       # en modo dormir solo despierta el usuario (menú o Ctrl+Alt+Espacio)
        if self.state == "sleeping":
            self.state = "idle"
        self.last_active = time.time()

    def _dormida_pista(self):
        if time.time() - self._hint_t > 4.0:
            self._hint_t = time.time()
            self.say("Estoy dormida 😴 (clic derecho → Despertar)", 3, force=True)

    def summon(self):
        """Trae la bolita de vuelta (si se perdió detrás de otra ventana o fuera de la pantalla)."""
        if not self._on_a_screen():
            self._to_safe_place()
        self.show(); self.raise_()
        self._force_top()
        self.wake(); self.reveal()
        self.set_emotion("happy", 2); self.say("¡Aquí estoy! 👋", 2.5)

    def _on_a_screen(self):
        """¿Se ve al menos un pedacito de la bolita en alguna pantalla? (Antes se miraba solo el CENTRO de la ventana: al acurrucarse en el borde el centro
        queda FUERA de la pantalla a propósito, así que el «cuidador» creía que se había perdido y la teletransportaba a la esquina.)"""
        if self.edge or self._drag is not None or self._anim.state() == QPropertyAnimation.Running or self._move_anim.state() == QPropertyAnimation.Running:
            return True                                  # acurrucada en el borde, arrastrándola o caminando: no se toca
        c = self._center_global()
        r = QRect(c.x() - R0, c.y() - R0, 2 * R0, 2 * R0)
        for sc in QGuiApplication.screens():
            i = sc.geometry().intersected(r)
            if i.width() >= 12 and i.height() >= 12:
                return True
        return False

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
    def _face_name(self):
        """Nombre de la carita base que toca ahora (cambia de golpe cuando cambia la emoción o el estado)."""
        if self.state == "sleeping": return "sleepy"
        if self.emotion == "neutral":
            if self.state == "thinking": return "thinking"
            if self.state == "listening": return "attentive"
        return self.emotion

    def _mood_face(self, base):
        """La cara neutral teñida por el ánimo: sonrisita y mejillas si todo ha ido bien, más seria y mirada baja si ha ido mal."""
        m = max(-1.0, min(1.0, self.mood))
        f = dict(base)
        f["curve"] = base["curve"] + m * 0.55
        f["blush"] = base["blush"] + max(0.0, m - 0.35) * 0.5
        f["brow"] = base["brow"] + max(0.0, -m) * 0.25
        f["eye_h"] = base["eye_h"] * (1 - max(0.0, -m) * 0.12)
        f["ly"] = base["ly"] + max(0.0, -m) * 0.25
        return f

    def _face_target(self):
        nm = self._face_name()
        base = FACES[nm]
        if nm != "sleepy" and self._look and time.time() < self._look_until:
            return {**FACES[self.emotion if self.emotion != "neutral" else "attentive"], "lx": self._look[0], "ly": self._look[1]}
        if nm in WORK_MOTION:                                                      # cada tipo de chamba mueve los ojos distinto
            return {**base, **WORK_MOTION[nm](self.t)}
        if nm == "neutral" and abs(self.mood) > 0.08:
            return self._mood_face(base)
        return base

    # ------------------------------------------------------------------ VIDA CONTINUA
    @staticmethod
    def _ruido(t: float, semilla: float) -> float:
        """Ruido suave y continuo en [-1, 1] (suma de senos con frecuencias que no coinciden: no se repite nunca de forma visible)."""
        return (math.sin(t * 0.37 + semilla * 1.7) + 0.6 * math.sin(t * 0.91 + semilla * 4.3) + 0.35 * math.sin(t * 1.73 + semilla * 7.1)) / 1.95

    def _vida_paso(self, dt: float, now: float, g: dict) -> None:
        """Capa de vida PROCEDURAL: movimiento continuo y suave (nunca a ratos) que se SUMA a los gestos y a la pose de la IA. Local, sin cuota.
        Config: `vida_continua` (true), `vida_amp` (1.0 = normal; 0.5 más discreta), `vida_asentir` (true)."""
        if not _cfg_val("vida_continua", True) or self.sleep_lock or self.state == "sleeping" or self.dancing or self.edge:
            return
        t = self.t
        amp = float(_cfg_val("vida_amp", 1.0))
        en = {"speaking": 1.25, "listening": 1.1, "thinking": 0.9}.get(self.state, 1.0) * (0.78 + 0.22 * self._ruido(t * 0.2, 9.0))   # energía que sube y baja sola
        a = amp * en
        rn = self._ruido
        g["ghx"] += a * 0.050 * R0 * rn(t, 1.0); g["ghy"] += a * 0.040 * R0 * rn(t, 2.0); g["grot"] += a * 2.2 * rn(t, 3.0)       # cabeza
        g["gdx"] += a * 0.040 * R0 * rn(t * 0.8, 4.0); g["gdy"] += a * 0.035 * R0 * rn(t * 0.7, 5.0); g["gsc"] += a * 0.010 * rn(t * 0.6, 6.0)   # flota
        lx, ly = 0.40 * rn(t * 1.2, 7.0), 0.22 * rn(t * 1.1, 8.0)                                                               # mirada que divaga
        g["glx"] += lx; g["gly"] += ly
        # asentir mientras le hablas: cuando haces una pausa después de hablar un rato, a veces cabecea («te sigo»)
        if _cfg_val("vida_asentir", True):
            if self.state == "listening" and self.level > 0.12:
                self._vida_voz += dt; self._vida_pausa = 0.0
            elif self._vida_voz > 0:
                self._vida_pausa += dt
                if self._vida_pausa > 0.35:
                    if self._vida_voz > 1.5 and now - self._vida_nod_t > 6.0 and random.random() < 0.6 and "asentir" in GESTO_FN:
                        self._gestos.append((now, 1.1, "asentir", 0.7)); self._vida_nod_t = now
                    self._vida_voz = 0.0

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
            nxt = EMO_AFTER.get(self.emotion)                       # la emoción se apaga por etapas (feliz → contento → neutral)
            if nxt:
                self.emotion = nxt; self._emotion_until = now + EMO_AFTER_S
            else:
                self.emotion = "neutral"; self._emotion_until = None
        self.mood *= 0.5 ** (dt / MOOD_HALF_S)

        # nivel de voz suavizado
        self.level += (self._level_target - self.level) * 0.35
        self._level_target *= 0.90

        # parpadeo (con el control total es una perilla de la IA: `parpadeo_auto`; si la apaga, parpadea ella)
        if self.t >= self._next_blink and (not self.ia_control or self._rig["parpadeo_auto"][0] > 0.5):
            self.blink = min(1.0, self.blink + 0.4)
            if self.blink >= 1.0: self._next_blink = self.t + (random.uniform(0.16, 0.30) if random.random() < 0.14 else random.uniform(2.2, 6.2))   # a veces parpadea doble
        else:
            self.blink = max(0.0, self.blink - 0.25)

        # mirada que divaga un poquito
        if self.t >= self._next_wander:
            self._eye_wander = [random.uniform(-0.5, 0.5), random.uniform(-0.3, 0.3)]
            self._next_wander = self.t + random.uniform(2.0, 5.0)

        # suavizado hacia la cara objetivo
        nm = self._face_name()
        if nm != self._face_nm:
            if "sleepy" not in (nm, self._face_nm):                 # dormirse/despertar sí es gradual; el resto de las caras cambian al instante
                self._snap_face()
            self._face_nm = nm
        target = self._face_target()
        for k in LERP_KEYS:                                         # la forma de la carita sigue el objetivo; el COLOR se funde más despacio
            self.p[k] += (target[k] - self.p[k]) * (COLOR_LERP if k in COLOR_KEYS else 0.14)
        self._prop_update(dt)
        base = STANDBY_COLOR if (self.standby and self.state == "idle") else STATE_COLORS[self.state]
        for i in range(3):
            self.col[i] += (base[i] - self.col[i]) * 0.10

        # ondas al hablar/escuchar
        if self.state in ("listening", "speaking") and self.level > 0.25 and self.t - self._last_ripple > 0.45:
            self.ripples.append(self.t); self._last_ripple = self.t
        self.ripples = [b for b in self.ripples if self.t - b < 1.3]

        # baile: rebota en cada golpe de ritmo y se mece entre golpes (solo si no está hablando ni escondida en el borde)
        ds = DANCE_STYLES.get(self.dance_style, DANCE_STYLES["pop"])
        # resorte amortiguado: más «flotante» en estilos con decay alto (suave/bachata), más seco en los de decay bajo (metal/rock)
        w = self._omega; z = max(0.42, min(0.8, 0.7 - (ds["decay"] - 0.80) * 1.8)); z = min(0.95, z + 0.22 * DANCE_SMOOTH)   # más amortiguado = menos «boing»
        self._bv += (-w * w * self._beat - 2.0 * z * w * self._bv) * 0.016
        self._beat = max(-0.3, min(1.3, self._beat + self._bv * 0.016))        # por debajo de 0 = se agacha un poquito (rebote)
        if not self.dancing:
            self._beat *= 0.85; self._bv *= 0.85
        sm = 1.0 - 0.5 * DANCE_SMOOTH                                          # suavidad: los filtros de movimiento se hacen más lentos
        G = DANCE_GAIN                                                         # y los movimientos más chicos
        self._dir_s += (self._dance_dir - self._dir_s) * 0.14 * (1.0 - 0.4 * DANCE_SMOOTH)   # el lado al que se inclina cambia suave, no de golpe
        active = self.dancing and self.state in ("idle", "listening") and not self.edge
        tx = (self._dir_s * ds["dx"] * self._beat + math.sin(self.t * ds["sw"]) * ds["sway"]) * G if active else 0.0
        ty = (ds["dy"] * self._beat) * G if active else 0.0
        self._dx += (tx - self._dx) * 0.22 * sm
        self._dy += (ty - self._dy) * 0.30 * sm
        hx = (self._dir_s * ds["hx"] * self._beat + math.sin(self.t * ds["sw"]) * ds["hsway"]) * R0 * G if active else 0.0
        hy = ds["nod"] * self._beat * R0 * G if active else 0.0
        rt = (self._dir_s * ds["tilt"] * self._beat + math.sin(self.t * ds["sw"] * 0.5) * ds["tsway"]) * G if active else 0.0
        self._hx += (hx - self._hx) * 0.26 * sm; self._hy += (hy - self._hy) * 0.30 * sm; self._rot += (rt - self._rot) * 0.22 * sm
        if active and now >= self._dface_next:                      # cada 4-8 s cambia de expresión (dentro de las del estilo)
            opciones = [x for x in ds["caras"] if x != self._dface] or list(ds["caras"])
            self._dface = random.choice(opciones); self._dface_next = now + random.uniform(4.0, 8.0)
            self._dance_emote(True)

        # lenguaje corporal libre: suma los gestos que la IA tiene en marcha (cada tick se arma de cero; nada se mueve solo)
        g = dict(_G0)
        if self.sleep_lock or self.state == "sleeping":
            self._gestos = []
        elif self._gestos:
            keep = []
            for (t0, dur, nm, k) in self._gestos:
                u = (now - t0) / dur
                if u >= 1.0:
                    continue
                keep.append((t0, dur, nm, k))
                for kk, v in GESTO_FN[nm](u, k).items():
                    g[kk] += v
            self._gestos = keep
        self._vida_paso(dt, now, g)                                 # vida continua (suma a lo de la IA; no depende de ningún reloj de avisos)
        aplastar = 0.0
        if self.sleep_lock or self.state == "sleeping" or not self.ia_control:
            for n, st in self._rig.items():
                st[0] = self._rig_obj[n] = _cu.POSE_DEFAULTS.get(n, 0.0); st[1] = 0.0
        else:                                                       # rig: las perillas de la pose libre se SUMAN a los gestos
            self._rig_paso(dt, now)
            R = {n: st[0] for n, st in self._rig.items()}
            g["ghx"] += R["cabeza_x"] * R0 * 0.45; g["ghy"] -= R["cabeza_y"] * R0 * 0.35; g["grot"] += R["cabeza_giro"] * 30
            g["gdx"] += R["cuerpo_x"] * R0 * 0.60; g["gdy"] -= R["cuerpo_y"] * R0 * 0.60; g["gsc"] += R["tamano"] * 0.22
            g["gel"] += R["ojo_izq"]; g["ger"] += R["ojo_der"]; g["gpup"] += R["pupila"]
            g["gbl"] += R["ceja_izq"]; g["gbr"] += R["ceja_der"]
            g["glx"] += R["mirada_x"] * 1.6; g["gly"] -= R["mirada_y"] * 1.0
            g["gmo"] += R["boca_abierta"]; g["gsm"] += R["sonrisa"]; g["gmw"] += R["boca_ancho"]
            g["grub"] += R["rubor"]; g["gglow"] += R["brillo"]
            g["gancho"] += R["ancho"]; g["galto"] += R["alto"]; g["garc"] += R["ojos_arco"]
            aplastar = R["aplastar"]
        if self._rodar:                                             # rodando: la carita gira (vueltas completas, así no «salta» al terminar)
            t0r, dur_r, tot = self._rodar
            u_r = (now - t0r) / dur_r
            if u_r >= 1.0:
                self._rodar = None
            else:
                g["grot"] += tot * (u_r * u_r * (3 - 2 * u_r))
        self._g = g
        self._gelatina_paso(dt, aplastar)
        tl = self._lip_t if self.state == "speaking" else (0.0, 0.0)              # boca: sigue el audio mientras habla
        self._lip[0] += (tl[0] - self._lip[0]) * 0.55; self._lip[1] += (tl[1] - self._lip[1]) * 0.35

        self.update()

    # ----------------------------------------------------------------- dibujo
    def _hit_tick(self):
        """La ventana de Orbi es grande (el brillo ocupa mucho) y un clic en el brillo se lo quedaba ella sin hacer nada.
        Solo la bolita es «sólida»: con el mouse fuera de ella la ventana se vuelve transparente a los clics y, en cuanto el mouse entra en la
        bolita, vuelve a recibirlos (clic, arrastre, caricias).

        Se hace con el mecanismo de Qt (`Qt.WindowTransparentForInput` sobre la ventana nativa), NO escribiendo a mano el estilo de Windows: Qt
        guarda su propia copia de las banderas y la reescribe cuando re-muestra la ventana o re-afirma «siempre encima», y eso borraba el bit
        manual dejando el brillo bloqueando clics. Cada tick compara con lo que Qt tiene y solo cambia si hace falta (no más de ~8 por segundo:
        cada cambio hace que Windows revise el cursor)."""
        if sys.platform != "win32" or not self.halo_clickthrough or not self.isVisible():
            return
        try:
            from PySide6.QtGui import QCursor
            wh = self.windowHandle()
            if wh is None:
                return
            g = self._g
            cx = W / 2 + self._dx + g["gdx"] + (self.width() - W) / 2        # centro REAL del cuerpo (con sus desplazamientos)
            cy = H / 2 + self._dy + g["gdy"] + (self.height() - H) / 2
            esc = max(self._sq[0], self._sq[1], 1.0) * (1 + max(0.0, g["gsc"]))
            p = self.mapFromGlobal(QCursor.pos())
            dentro = ((p.x() - cx) ** 2 + (p.y() - cy) ** 2) ** 0.5 <= R0 * 1.15 * esc + 6 or self._drag is not None
            through = not dentro
            self._estorba_tick(p, dentro, esc)
            actual = self._ex_transparent()                         # estado REAL de la ventana de Windows (la copia de Qt puede mentir si Windows/Qt le borran el bit)
            self._hit_clickthrough = actual
            if actual == through:
                return
            ahora = time.time()
            if through and ahora - self._hit_t < 0.12:      # el anti-parpadeo solo frena volverse transparente; sólida es al instante para poder agarrarla
                return
            self._hit_t = ahora
            wh.setFlag(Qt.WindowTransparentForInput, through)       # que Qt también lo sepa
            if self._ex_transparent() != through:                   # Qt no lo aplicó (o lo reescribió): se pone directo en la ventana
                self._ex_transparent(through)
            self._hit_clickthrough = self._ex_transparent()
            if getattr(self, "_hit_log", 0) < 4:                    # unas pocas líneas de diagnóstico para saber qué hace esta PC
                self._hit_log = getattr(self, "_hit_log", 0) + 1
                print(f"[halo] clic a través del brillo: quería {through}, quedó {self._hit_clickthrough}")
        except Exception as e:                                      # noqa: BLE001
            print(f"[halo] clic a través del brillo desactivado: {type(e).__name__}: {e}")
            self.halo_clickthrough = False                          # algo no cuadra en esta PC: se apaga y queda como antes

    def _estorba_tick(self, p, dentro, esc):
        """Detecta que Orbi le tapa algo al mouse y se aparta: el mouse se queda quieto ~1 s en el brillo cerca de la bolita
        (sin haber estado sobre ella hace poco: eso sería querer agarrarla)."""
        now = time.time()
        cx = W / 2 + self._dx + self._g["gdx"] + (self.width() - W) / 2
        cy = H / 2 + self._dy + self._g["gdy"] + (self.height() - H) / 2
        d = ((p.x() - cx) ** 2 + (p.y() - cy) ** 2) ** 0.5
        en_halo = (not dentro and self._drag is None and self.state != "sleeping"
                   and 0 <= p.x() < self.width() and 0 <= p.y() < self.height() and d <= R0 * 2.8 * esc)
        if dentro:
            self._ultimo_dentro = now
        if not en_halo or now - getattr(self, "_ultimo_dentro", 0.0) < 1.5:
            self._est_t = None; return
        gp = QCursor.pos()
        ref = getattr(self, "_est_ref", None)
        if getattr(self, "_est_t", None) is None or ref is None or abs(gp.x() - ref.x()) + abs(gp.y() - ref.y()) > 40:
            self._est_t = now; self._est_ref = gp; return
        if now - self._est_t > 1.0:
            self._est_t = None
            self._apartarse(gp)

    def _apartarse(self, gp):
        """Se mueve a otro lugar para dejar libre la zona donde está el mouse."""
        m = int(R0 * 1.2)
        self.dodge((gp.x() - m, gp.y() - m, gp.x() + m, gp.y() + m), force=True)

    def _ex_transparent(self, through=None):
        """Lee (o pone, si `through` no es None) el bit WS_EX_TRANSPARENT directo en la ventana de Windows. Devuelve cómo quedó."""
        import ctypes
        u = ctypes.windll.user32
        u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]; u.GetWindowLongW.restype = ctypes.c_long
        u.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]; u.SetWindowLongW.restype = ctypes.c_long
        hwnd = int(self.winId())
        ex = u.GetWindowLongW(hwnd, -20) & 0xFFFFFFFF
        if through is not None:
            nuevo = (ex | 0x20 | 0x80000) if through else (ex & ~0x20)
            if nuevo != ex:
                u.SetWindowLongW(hwnd, -20, ctypes.c_long(nuevo - (1 << 32) if nuevo >= (1 << 31) else nuevo).value)
                ex = u.GetWindowLongW(hwnd, -20) & 0xFFFFFFFF
        return bool(ex & 0x20)

    # --------------------------------------------------------------- ratón
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            g = self._g                                     # mismo centro REAL del cuerpo que usa _hit_tick (con sus desplazamientos)
            cx = W / 2 + self._dx + g["gdx"] + (self.width() - W) / 2
            cy = H / 2 + self._dy + g["gdy"] + (self.height() - H) / 2
            esc = max(self._sq[0], self._sq[1], 1.0) * (1 + max(0.0, g["gsc"]))
            dx, dy = e.position().x() - cx, e.position().y() - cy
            dist = (dx * dx + dy * dy) ** 0.5
            if dist > R0 * 1.15 * esc + 6:                  # clic en el halo (el brillo de alrededor): se ignora
                self._drag = None; e.ignore()
                if dist > R0 * 1.5 * esc + 20:              # claramente fuera de la bolita: el clic era para lo de abajo, se aparta
                    self._apartarse(e.globalPosition().toPoint())
                return
            self._anim.stop()
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_pos = e.globalPosition().toPoint(); self._moved = False
            self.edge = None; self.revealed = False
            if self.sleep_lock:
                self._dormida_pista()
            else:
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
        if self._pet_acc > 140 * SCALE and self.emotion not in ("love", "dreamy"):
            self.set_emotion("dreamy", 2.5)                                    # ya lo siente: cierra los ojitos antes de que salgan los corazones
        if self._pet_acc > 450 * SCALE:
            self._pet_acc = 0.0; self._pet_last = None; self._pet_cool = now + 6.0
            self.last_pet = now; self.nudge_mood(0.25)
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
        if self.sleep_lock: return
        if self.state == "sleeping": self.state = "idle"
        self.last_active = time.time()
        self._move_anim.setDuration(ms)
        self._move_anim.setStartValue(self.pos())
        self._move_anim.setEndValue(QPoint(cx - W // 2, cy - H // 2))
        self._move_anim.start()

    def dodge(self, danger, force=False) -> bool:
        """Se aparta (esquina o borde) si estorba en la zona `danger` (x0,y0,x1,y1 globales); no se mueve si no hace falta."""
        now = time.time()
        if danger is None or self.state == "sleeping" or self.edge or self._drag is not None:
            return False
        if now < getattr(self, "_no_dodge_until", 0.0) or now - getattr(self, "_last_dodge", 0.0) < (1.0 if force else 3.0):
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

    # ------------------------------------------------------------------ lenguaje corporal libre (lo dispara la IA, cuerpo.py)
    def wander(self):
        """Se pasea a otro lugar de la pantalla (esquinas o mitad de los bordes), lejos de donde está ahora."""
        if self.sleep_lock: return
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
        if self.sleep_lock: return
        """Se pone junto al punto, lo mira y le dibuja un anillo pulsante."""
        screen = QGuiApplication.screenAt(QPoint(int(gx), int(gy))) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        side = -1 if gx > g.center().x() else 1                    # donde haya más espacio
        ox, oy = int(gx + side * (R0 * 2.4 + 60)), int(gy - R0 * 0.6)
        self._no_dodge_until = time.time() + seconds + 1.5          # señalando: aquí SÍ tiene que estar cerca
        self.move_to_global(ox, oy, 650)
        self._look = (-side * 1.6, max(-1.0, min(1.0, (gy - oy) / 200.0))); self._look_until = time.time() + seconds + 1.0
        self.set_emotion("attentive" if "attentive" in FACES else "happy", seconds)
        QTimer.singleShot(450, lambda: self.pointer.show_at(gx, gy, seconds))
        if text:
            QTimer.singleShot(700, lambda: self.say(text, max(4.0, seconds)))

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
        if self.on_dormir:
            m.addAction("Despertar" if self.sleep_lock else "Dormir", lambda checked=False: self.on_dormir())
        else:
            m.addAction("Dormir", lambda checked=False: setattr(self, "state", "sleeping"))
        for text, cb, checkable, is_checked, show in self._menu_actions:
            if not show:
                continue
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
