"""Demo: la bolita recorre estados y emociones. Clic derecho = probar emociones / salir."""
import math, sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from orb import Orb, emotion_from_text

SCRIPT = [
    ("idle", "Hola Max, soy tu bolita 💙 ¡arrástrame a un borde de la pantalla y me escondo!"),
    ("listening", None),
    ("thinking", "Hmm, déjame pensar..."),
    ("speaking", "¡Listo! Ya abrí la calculadora ✨"),
    ("speaking", "Uy, lo siento, no pude encontrar ese archivo 😔"),
    ("speaking", "¡Wow, no manches, eso sí que es increíble!"),
    ("speaking", "Te quiero mucho, gracias por programarme ❤"),
    ("idle", "Buenas noches, descansa 😴"),
]

app = QApplication(sys.argv)
orb = Orb()
orb.move(300, 300)
orb.show()
step = [0]

def next_step():
    state, text = SCRIPT[step[0] % len(SCRIPT)]
    orb.set_state(state)
    if text:
        orb.say(text)
        orb.set_emotion(emotion_from_text(text), 3.5)
    step[0] += 1

def fake_voice():                               # simula el volumen de la voz
    if orb.state in ("listening", "speaking"):
        import time
        orb.set_level(0.5 + 0.5 * math.sin(time.time() * 9) * math.sin(time.time() * 3.1))

QTimer(app, interval=3800, timeout=next_step).start()
QTimer(app, interval=50, timeout=fake_voice).start()
next_step()
sys.exit(app.exec())
