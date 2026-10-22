"""Diagnóstico del audio de la PC para Orbi.  Uso (con la MISMA venv que usa Orbi):   python diag_audio.py
Pon música/un video y mira si los números se mueven. Si algo falla te dice dónde."""
import sys, time

print("Python:", sys.executable)
try:
    import numpy as np, soundcard as sc
except Exception as e:                                                       # noqa: BLE001
    print("✗ No se pudo importar numpy/soundcard en ESTE Python:", e)
    print("  → Instala con:  \"%s\" -m pip install -U soundcard numpy" % sys.executable); sys.exit(1)
import importlib.metadata as md
print("soundcard", md.version("soundcard"), "| numpy", np.__version__)

try:
    spk = sc.default_speaker()
    print("Bocina por defecto de Windows:", spk.name)
except Exception as e:                                                       # noqa: BLE001
    print("✗ No hay bocina por defecto:", e); sys.exit(1)
print("Dispositivos loopback visibles:")
for m in sc.all_microphones(include_loopback=True):
    if getattr(m, "isloopback", False):
        print("   ", "★" if m.id == spk.id else " ", m.name)

from pc_audio import loopback_mic
from audio_react import AudioReact, RATE, BLOCK
try:
    mic = loopback_mic(sc)
except Exception as e:                                                       # noqa: BLE001
    print("✗ No pude abrir el loopback:", type(e).__name__, e); sys.exit(1)
print("Escuchando por:", mic.name, "\n\n>>> PON MÚSICA AHORA (10 s). Columnas: volumen | graves | golpes\n")

ar = AudioReact(lambda s: None, lambda d: print("   >>>", "🕺 BAILA" if d else "😌 PARA"))
beats = 0; peak = 0.0; t_end = time.time() + 10; last = 0
with mic.recorder(samplerate=RATE, channels=1, blocksize=BLOCK) as rec:
    while time.time() < t_end:
        d = rec.record(numframes=BLOCK)[:, 0]
        ar.process(d); beats = ar.total_beats
        rms = float(np.sqrt(np.mean(d * d))); peak = max(peak, rms)
        if time.time() - last > 0.25:
            last = time.time()
            print(f"\r vol {'█' * int(min(rms * 120, 40)):<40} {rms:.3f}  golpes: {beats:<4}", end="", flush=True)
print("\n")
if peak < 0.003:
    print("✗ Todo en silencio: Windows no está mandando audio a la bocina por defecto.")
    print("  → ¿Spotify/Discord/el navegador tienen otra salida elegida? (Configuración > Sistema > Sonido > Mezclador de volumen)")
else:
    print("✓ Sí oigo audio. Pico de volumen:", round(peak, 3))
