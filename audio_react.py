"""Orbi baila al ritmo de la música que suena en la PC (Spotify, YouTube, Discord, llamadas, lo que sea).

Todo se analiza LOCAL: se captura lo que sale por tus bocinas (WASAPI loopback, librería `soundcard`), se mide la energía de los
graves y se detectan los golpes de ritmo. No se graba nada, no se manda nada a Gemini y no gasta cuota.

Cómo decide «esto es música»: en los últimos segundos tiene que haber golpes de graves REGULARES (60-210 BPM). La voz de una
llamada tiene energía pero no ese pulso constante, así que no se pone a bailar con gente hablando.
"""
import threading, time
from collections import deque

RATE = 44100
BLOCK = 1024                       # ~23 ms por bloque que se analiza
BUFFER = 16384                     # ~370 ms de colchón de WASAPI. soundcard usa blocksize/samplerate como duración del buffer:
                                   # con 1024 eran 23 ms y cualquier tironcito de la CPU perdía audio («data discontinuity»)
BASS = (30.0, 180.0)               # banda donde viven el bombo y el bajo
SILENCE_RMS = 0.0015               # por debajo de esto no hay nada sonando


class AudioReact:
    CHECK_S = 5.0                      # cada cuánto revisa si cambiaste de bocinas/audífonos

    def __init__(self, on_beat, on_dance, on_error=None, sensibilidad: float = 1.7, debug: bool = False,
                 min_golpes: int = 8, mantener_s: float = 3.0):
        """on_beat(fuerza 0..1) por cada golpe de ritmo · on_dance(True/False) cuando empieza/termina la música.
        sensibilidad: cuántas veces tiene que superar el golpe al promedio de graves (más bajo = más sensible)."""
        self.on_beat, self.on_dance, self.on_error = on_beat, on_dance, on_error or (lambda m: None)
        self.ratio = max(1.1, float(sensibilidad)); self.debug = debug
        self.min_golpes = max(5, int(min_golpes)); self.hold = max(0.0, float(mantener_s))   # golpes mínimos y segundos seguidos de «parece música»
        self._stop = threading.Event(); self._th = None
        self._reset()

    # ------------------------------------------------------------------ control
    def start(self):
        if self._th and self._th.is_alive():
            return
        self._stop.clear()
        self._th = threading.Thread(target=self._run, name="orbi-audio-react", daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------ análisis (se puede probar sin soundcard)
    def _reset(self):
        self._win = None
        self._bass_hist = deque(maxlen=43)        # ~1 s de energía de graves
        self._beats = deque(maxlen=16)            # momentos (s) de los últimos golpes
        self._loud = deque(maxlen=130)            # ~3 s: ¿hubo sonido?
        self._last_beat = 0.0
        self.total_beats = 0                      # (para diag_audio.py)
        self.dancing = False
        self._last_music = 0.0
        self._since = None                        # desde cuándo «parece música» sin interrupción

    def process(self, mono, now=None):
        """Procesa un bloque (float32 mono, -1..1). Dispara on_beat/on_dance."""
        import numpy as np
        now = time.monotonic() if now is None else now
        n = len(mono)
        if n < 256:
            return
        if self._win is None or len(self._win) != n:
            self._win = np.hanning(n).astype("float32")
            f = np.fft.rfftfreq(n, 1.0 / RATE)
            self._band = (f >= BASS[0]) & (f <= BASS[1])
        rms = float(np.sqrt(np.mean(mono * mono)))
        self._loud.append(rms > SILENCE_RMS)
        spec = np.abs(np.fft.rfft(mono * self._win))
        bass = float(spec[self._band].sum()) / n
        frac = float(spec[self._band].sum()) / (float(spec.sum()) + 1e-9)   # qué tanto del sonido son graves
        avg = (sum(self._bass_hist) / len(self._bass_hist)) if self._bass_hist else 0.0
        self._bass_hist.append(bass)

        beat = (rms > SILENCE_RMS and avg > 0 and bass > avg * self.ratio
                and bass > 0.0008 and frac > 0.06 and now - self._last_beat > 0.26)
        if beat:
            self._last_beat = now
            self.total_beats += 1
            self._beats.append(now)
            if self.dancing:
                self.on_beat(min(1.0, bass / (avg * 3.0)))

        music = self._keep_dancing(now) if self.dancing else self._is_music(now)
        if music:
            self._last_music = now
        if not self.dancing:
            if not music:
                self._since = None
            else:
                if self._since is None:
                    self._since = now
                if now - self._since >= self.hold:          # tiene que parecer música varios segundos seguidos
                    self.dancing = True; self.on_dance(True)
                    if self.debug: print("[baile] empieza")
        elif now - self._last_music > 1.5:
            self.dancing = False; self._since = None; self.on_dance(False)
            if self.debug: print(f"[baile] para (sonido={sum(self._loud)}/{len(self._loud)} bloques, golpes 10 s={sum(1 for t in self._beats if now - t <= 10.0)})")

    def _keep_dancing(self, now) -> bool:
        """Ya bailando: sigue mientras haya sonido y al menos un par de golpes en los últimos 10 s (aguanta breaks y cortes)."""
        return sum(self._loud) >= 20 and sum(1 for t in self._beats if now - t <= 10.0) >= 3

    def _is_music(self, now) -> bool:
        recent = [t for t in self._beats if now - t <= 8.0]
        if len(recent) < self.min_golpes or sum(self._loud) < len(self._loud) * 0.6:
            return False
        iv = sorted(b - a for a, b in zip(recent, recent[1:]))
        med = iv[len(iv) // 2]
        if not 0.28 <= med <= 1.0:                           # 60-210 BPM
            return False
        ok = sum(1 for x in iv if any(abs(x - med * k) <= med * k * 0.12 for k in (1.0, 2.0)))
        return ok / len(iv) >= 0.8

    # ------------------------------------------------------------------ hilo de captura
    def _run(self):
        import warnings
        # Aviso inofensivo de soundcard (pierde unos paquetes) que, además, llenaba la consola y empeoraba el atasco
        warnings.filterwarnings("ignore", message="data discontinuity in recording")
        errores = 0
        while not self._stop.is_set():
            try:
                import soundcard as sc
                from pc_audio import loopback_mic
                spk = sc.default_speaker()
                mic = loopback_mic(sc)
                self._reset()
                chequeo = time.monotonic()
                rec_cm = mic.recorder(samplerate=RATE, channels=1, blocksize=BUFFER)
                rec = rec_cm.__enter__()
                try:
                    errores = 0
                    t0, frames = time.monotonic(), 0
                    while not self._stop.is_set():
                        data = rec.record(numframes=BLOCK)
                        frames += BLOCK
                        # reloj por muestras: si el hilo se atrasa y recupera de golpe, los golpes no se «apelotonan»
                        self.process(data[:, 0] if getattr(data, "ndim", 1) > 1 else data, now=t0 + frames / RATE)
                        if time.monotonic() - chequeo > self.CHECK_S:      # ¿cambiaste de bocinas/audífonos? reabrir
                            chequeo = time.monotonic()
                            if sc.default_speaker().id != spk.id:
                                break
                finally:
                    try:
                        rec_cm.__exit__(None, None, None)
                    except Exception:                                 # noqa: BLE001
                        # Stop() devuelve S_FALSE (=1) si el flujo ya estaba detenido (cambió el dispositivo) y soundcard
                        # lo toma por error: «Error 0x100000001». No es un fallo real, no cuenta.
                        pass
            except ImportError as e:
                import sys
                self.on_error(f"No se pudo importar ({e}). Orbi corre con: {sys.executable}  → instala ahí: "
                              f"\"{sys.executable.replace('pythonw', 'python')}\" -m pip install -U soundcard numpy cffi")
                return
            except Exception as e:                                # noqa: BLE001
                errores += 1
                if errores == 1:
                    self.on_error(f"No pude escuchar el audio de la PC ({type(e).__name__}: {str(e)[:120]}).")
                if errores >= 3:     # insistir abriendo el loopback una y otra vez puede estorbar al micrófono de Orbi: mejor rendirse
                    self.on_error("Apagué el baile tras varios fallos para no estorbar al micrófono. Vuelve a activarlo "
                                  "desde el menú cuando quieras.")
                    break
                self._stop.wait(2.0 * errores)
        if self.dancing:
            self.dancing = False; self.on_dance(False)
