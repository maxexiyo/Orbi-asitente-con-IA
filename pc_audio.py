"""Audio de la PC (lo que SUENA en tus bocinas: video, llamada, música) para que Orbi lo escuche a pedido.

Usa WASAPI loopback por la librería `soundcard` (solo Windows). Graba unos segundos y devuelve un WAV mono de 16 kHz;
quien lo llama se lo manda a Gemini para transcribir, resumir o traducir. Nada se graba en disco ni se guarda.
Permiso «audio_pc» (apagado por defecto: en llamadas o videos privados puede oírse a otras personas).
"""
import io, wave


class AudioError(Exception):
    pass


def loopback_mic(sc=None):
    """Micrófono «loopback» de la bocina por defecto (lo que suena en la PC). Por id (más exacto que por nombre)."""
    if sc is None:
        import soundcard as sc
    spk = sc.default_speaker()
    try:
        return sc.get_microphone(id=str(spk.id), include_loopback=True)
    except Exception:                                        # noqa: BLE001
        return sc.get_microphone(id=str(spk.name), include_loopback=True)


def record_wav(seconds: float = 10.0, rate: int = 16000):
    """-> (bytes_wav, info{segundos, silencio}). Bloquea `seconds` s (3 a 30): llamarlo desde un hilo de tool."""
    try:
        seconds = max(3.0, min(30.0, float(seconds or 10)))
    except (TypeError, ValueError):
        seconds = 10.0
    try:
        import numpy as np
        import soundcard as sc
    except ImportError:
        raise AudioError("Falta instalar la librería 'soundcard' (pip install soundcard) para oír el audio de la PC.")
    try:
        mic = loopback_mic(sc)
        with mic.recorder(samplerate=rate, channels=1) as rec:
            data = rec.record(numframes=int(rate * seconds))
    except Exception as e:                                   # noqa: BLE001
        raise AudioError(f"No pude capturar el audio de la PC ({type(e).__name__}: {str(e)[:100]}).")
    mono = data[:, 0] if getattr(data, "ndim", 1) > 1 else data
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    pcm = (np.clip(mono, -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue(), {"segundos": seconds, "silencio": peak < 0.005}
