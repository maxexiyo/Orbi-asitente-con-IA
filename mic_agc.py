"""Orbi: control automático de ganancia (AGC) del micrófono, ANTES de mandarlo a Gemini y a la palabra clave.

Si hablas bajito o el micrófono es flojo, a Gemini (y a Vosk) les llega una voz débil y entienden mal: ni «sensibilidad» ni umbrales arreglan eso, porque solo
cambian cuándo la bolita «se da cuenta» de que hablas, no el volumen del audio que sale. Aquí se SUBE de verdad el volumen de la voz hasta un nivel cómodo
(objetivo), con un tope, y sin inflar el ruido de fondo (solo sube cuando hay voz). Rápido para bajar (no satura si gritas), lento para subir.
Se usa desde live_client.py:  data = agc.process(data)   (PCM int16 mono 16 kHz)
"""
from __future__ import annotations

import numpy as np


class MicAGC:
    def __init__(self, objetivo: float = 0.10, max_gain_db: float = 18.0, on_info=None):
        self.objetivo = float(objetivo)                      # nivel RMS al que se lleva la voz (0.10 ≈ -20 dBFS: cómodo para reconocer)
        self.max_gain = 10 ** (float(max_gain_db) / 20.0)
        self.gain = 1.0
        self.floor = 0.004                                   # ruido de fondo estimado (RMS)
        self._n = 0
        self.on_info = on_info

    def process(self, pcm: bytes) -> bytes:
        try:
            x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
            if x.size == 0:
                return pcm
            r = float(np.sqrt(np.mean(x * x)))
            voz = r > max(0.006, self.floor * 2.2)
            if not voz:
                self.floor = 0.98 * self.floor + 0.02 * r    # trozo de silencio: aprende el ruido de fondo
                g = min(self.gain, 1.5)                      # sin voz no se infla el ruido
            else:
                deseada = min(self.max_gain, max(1.0, self.objetivo / max(r, 1e-4)))
                if deseada < self.gain:
                    self.gain = 0.6 * self.gain + 0.4 * deseada      # bajar rápido (no saturar)
                else:
                    self.gain = 0.94 * self.gain + 0.06 * deseada    # subir despacio (sin bombeo)
                self.gain = min(self.gain, 0.5 / max(r, 1e-4))        # techo inmediato: una voz fuerte repentina nunca sale por encima de ~0.5 (sin saturar)
                g = self.gain
            if g <= 1.02:
                return pcm
            y = np.clip(x * g, -0.97, 0.97)
            return (y * 32767.0).astype("<i2").tobytes()
        except Exception as e:                               # noqa: BLE001
            if self.on_info:
                self.on_info(f"[agc] falló ({type(e).__name__}); paso el audio sin tocar")
            return pcm
