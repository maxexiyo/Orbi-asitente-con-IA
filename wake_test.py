"""Prueba de la palabra clave: habla al micro y mira qué entiende el reconocedor (para ajustar alias en config.json).

    python wake_test.py          (20 s)        ·  python wake_test.py 60   (60 s)
Muestra lo que oye y marca con ✅ cuando lo tomaría como «Orbi».
"""
import json, sys, time

from attention import MODEL_DIR, WakeWord, matches_wake


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20
    import sounddevice as sd, vosk
    ww = WakeWord(lambda t: None)
    d = ww._find_model()
    if d is None:
        print("Aún no hay modelo; abre Orbi una vez (se descarga solo) o ejecuta este script después.")
        return
    vosk.SetLogLevel(-1)
    rec = vosk.KaldiRecognizer(vosk.Model(str(d)), 16000)
    print(f"Escuchando {secs:.0f} s… di «Orbi», «oye Orbi», otras palabras, etc.\n")
    t0, last = time.time(), ""
    with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1024) as st:
        while time.time() - t0 < secs:
            data, _ = st.read(1024)
            data = bytes(data)
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "")
                if text:
                    print(("✅ " if matches_wake(text) else "   ") + text)
            else:
                part = json.loads(rec.PartialResult()).get("partial", "")
                if part and part != last and matches_wake(part):
                    print("✅ (parcial)", part)
                last = part


if __name__ == "__main__":
    main()
