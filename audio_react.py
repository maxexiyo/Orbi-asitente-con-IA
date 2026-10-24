"""Orbi baila al ritmo de la música que suena en la PC (Spotify, YouTube, Discord, llamadas, lo que sea).

Todo se analiza LOCAL: se captura lo que sale por tus bocinas (WASAPI loopback, librería `soundcard`), se mide la energía de los
graves y se detectan los golpes de ritmo. No se graba nada, no se manda nada a Gemini y no gasta cuota.

Cómo decide «esto es música» (suene donde suene: YouTube, Spotify, un juego...): en los últimos segundos tiene que haber golpes
REGULARES (60-210 BPM), de graves o de ataques en todo el espectro (para música sin bombo fuerte), y el sonido NO debe parecer
habla. El habla (videos, clases, llamadas) se reconoce porque tiene muchas pausas cortas entre palabras y una envolvente que
«late» al ritmo de las sílabas (~4-6 veces por segundo); la música casi no tiene pausas. Además estima el tempo (BPM) y elige
un estilo de baile (`estilo`: suave, balanceo, grave, pop, fiesta, intenso).
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
                 min_golpes: int = 8, mantener_s: float = 3.0, voz_pausas: float = 0.8, on_style=None):
        """on_beat(fuerza 0..1) por cada golpe de ritmo · on_dance(True/False) cuando empieza/termina la música ·
        on_style(estilo) cuando cambia el estilo de la música que suena (mientras baila).
        sensibilidad: cuántas veces tiene que superar el golpe al promedio de graves (más bajo = más sensible). Se aplica un
        factor 0.8 y se piden 2 golpes menos que antes (la versión anterior casi no bailaba), así que NO hace falta cambiar tu config.
        voz_pausas: pausas por segundo a partir de las cuales el sonido se considera habla (más bajo = descarta más habla)."""
        self.on_beat, self.on_dance, self.on_error = on_beat, on_dance, on_error or (lambda m: None)
        self.on_style = on_style or (lambda e: None)
        self.ratio = max(1.1, float(sensibilidad) * 0.8); self.debug = debug
        self.min_golpes = max(4, int(min_golpes) - 2); self.hold = max(0.0, float(mantener_s))   # golpes mínimos y segundos seguidos de «parece música»
        self.voz_pausas = max(0.2, float(voz_pausas))
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
    ENV_N = 128                                # bloques de envolvente que se miran para distinguir habla (~3 s)

    def _reset(self):
        self._win = None
        self._bass_hist = deque(maxlen=43)        # ~1 s de energía de graves
        self._flux_hist = deque(maxlen=43)        # ~1 s de «novedad» espectral (ataques en todo el espectro)
        self._prev_mag = None
        self._beats = deque(maxlen=20)            # momentos (s) de los últimos golpes (graves o ataques)
        self._bbeats = deque(maxlen=20)           # solo los golpes de graves (para estimar el tempo sin que lo dominen los platillos)
        self._last_bass = 0.0
        self._loud = deque(maxlen=130)            # ~3 s: ¿hubo sonido?
        self._env = deque(maxlen=self.ENV_N)      # energía por bloque (para pausas y ritmo de sílabas)
        self._pause_run = 0
        self._pauses = deque(maxlen=64)           # cuándo empezó cada pausa corta (≥ ~115 ms de casi-silencio)
        self._mod = 0.0                           # qué tanto «late» la envolvente al ritmo del habla (0..1)
        self._speech_since = None
        self._last_beat = 0.0
        self.total_beats = 0                      # (para diag_audio.py)
        self.dancing = False
        self._last_music = 0.0
        self._since = None                        # desde cuándo «parece música» sin interrupción
        self._frac_avg, self._rms_avg = 0.0, 0.0
        self.bpm, self.estilo = 0.0, ""
        self.speechy = False

    def process(self, mono, now=None):
        """Procesa un bloque (float32 mono, -1..1). Dispara on_beat/on_dance/on_style."""
        import numpy as np
        now = time.monotonic() if now is None else now
        n = len(mono)
        if n < 256:
            return
        if self._win is None or len(self._win) != n:
            self._win = np.hanning(n).astype("float32")
            f = np.fft.rfftfreq(n, 1.0 / RATE)
            self._band = (f >= BASS[0]) & (f <= BASS[1])
            self._fband = (f >= 100.0) & (f <= 4000.0)
        rms = float(np.sqrt(np.mean(mono * mono)))
        self._loud.append(rms > SILENCE_RMS)
        self._env.append(rms)
        spec = np.abs(np.fft.rfft(mono * self._win))
        bass = float(spec[self._band].sum()) / n
        frac = float(spec[self._band].sum()) / (float(spec.sum()) + 1e-9)   # qué tanto del sonido son graves
        avg = (sum(self._bass_hist) / len(self._bass_hist)) if self._bass_hist else 0.0
        self._bass_hist.append(bass)
        if rms > SILENCE_RMS:
            self._frac_avg = self._frac_avg * 0.98 + frac * 0.02
            self._rms_avg = self._rms_avg * 0.98 + rms * 0.02

        # ataques en todo el espectro (música sin bombo fuerte: guitarras, pop suave, lo-fi...)
        mag = np.log1p(spec[self._fband] * 40.0)
        flux = 0.0 if self._prev_mag is None else float(np.maximum(mag - self._prev_mag, 0.0).sum())
        self._prev_mag = mag
        fm = (sum(self._flux_hist) / len(self._flux_hist)) if self._flux_hist else 0.0
        fsd = (sum((x - fm) ** 2 for x in self._flux_hist) / len(self._flux_hist)) ** 0.5 if self._flux_hist else 0.0
        self._flux_hist.append(flux)

        bass_beat = (avg > 0 and bass > avg * self.ratio and bass > 0.0003 and frac > 0.03)
        flux_beat = (len(self._flux_hist) > 20 and flux > fm + 1.5 * max(fsd, 0.02 * fm) and flux > fm * 1.6 and flux > 1.0)
        if rms > SILENCE_RMS and bass_beat and now - self._last_bass > 0.24:
            self._last_bass = now
            self._bbeats.append(now)
        if rms > SILENCE_RMS and (bass_beat or flux_beat) and now - self._last_beat > 0.24:
            self._last_beat = now
            self.total_beats += 1
            self._beats.append(now)
            if self.dancing:
                self.on_beat(min(1.0, max(bass / (avg * 3.0 + 1e-9), flux / (fm * 3.0 + 1e-9))))

        self._habla(now)
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
                    self._estilo(now, forzar=True)
                    if self.debug: print(f"[baile] empieza ({self.bpm:.0f} BPM, estilo {self.estilo})")
        elif now - self._last_music > 1.5:
            self.dancing = False; self._since = None; self.on_dance(False)
            if self.debug: print(f"[baile] para (sonido={sum(self._loud)}/{len(self._loud)} bloques, golpes 10 s={sum(1 for t in self._beats if now - t <= 10.0)}, "
                                 f"habla={self.speechy} pausas/s={self._pause_rate(now):.2f} mod={self._mod:.2f})")
        elif self.dancing:
            self._estilo(now)

    # --- ¿es habla? (videos, clases, llamadas) -----------------------------------------------------------------
    def _pause_rate(self, now) -> float:
        return sum(1 for t in self._pauses if now - t <= 5.0) / 5.0

    def _habla(self, now):
        import numpy as np
        env = self._env
        if len(env) < 40:
            return
        arr = np.fromiter(env, dtype="float32")
        ref = float(np.percentile(arr, 90))
        if ref < SILENCE_RMS * 2:
            self._pause_run = 0
            return
        if arr[-1] < ref * 0.12:                            # casi silencio comparado con lo normal de esta ventana
            self._pause_run += 1
            if self._pause_run == 5:                        # pausa de ~115 ms: entre palabras. La música casi no tiene
                self._pauses.append(now)
        else:
            self._pause_run = 0
        self._nblk = getattr(self, "_nblk", 0) + 1
        if len(env) == self.ENV_N and self._nblk % 10 == 0:
            e = arr - arr.mean()
            p = np.abs(np.fft.rfft(e * np.hanning(len(e)))) ** 2
            f = np.fft.rfftfreq(len(e), 1.0 / 43.07)
            ps = float(p[(f >= 3.5) & (f <= 7.5)].sum())
            pb = float(p[(f >= 0.7) & (f < 3.5)].sum())
            self._mod = ps / (ps + pb + 1e-12)
        pr = self._pause_rate(now)
        self.speechy = pr >= self.voz_pausas or (self._mod > 0.7 and pr >= 0.3)
        if self.speechy:
            if self._speech_since is None:
                self._speech_since = now
        else:
            self._speech_since = None

    def _keep_dancing(self, now) -> bool:
        """Ya bailando: sigue mientras haya sonido y al menos un par de golpes en los últimos 10 s (aguanta breaks y cortes);
        se detiene si pasa a sonar habla varios segundos seguidos."""
        if self._speech_since is not None and now - self._speech_since > 4.0:
            return False
        return sum(self._loud) >= 20 and sum(1 for t in self._beats if now - t <= 10.0) >= 3

    def _is_music(self, now) -> bool:
        if self.speechy:
            return False
        recent = [t for t in self._beats if now - t <= 8.0]
        if len(recent) < self.min_golpes or sum(self._loud) < len(self._loud) * 0.5:
            return False
        iv = sorted(b - a for a, b in zip(recent, recent[1:]))
        med = iv[len(iv) // 2]
        if not 0.24 <= med <= 1.0:                           # 60-250 BPM (con medios y dobles tiempos)
            return False
        ok = sum(1 for x in iv if any(abs(x - med * k) <= med * k * 0.15 for k in (0.5, 1.0, 2.0)))
        if ok / len(iv) < 0.7:
            return False
        self.bpm = self._tempo(now) or self.bpm
        return True

    def _tempo(self, now) -> float:
        """BPM estimado (70-180). Usa los golpes de graves; si hay pocos, todos los golpes."""
        for lst in (self._bbeats, self._beats):
            recent = [t for t in lst if now - t <= 8.0]
            if len(recent) >= 4:
                iv = sorted(b - a for a, b in zip(recent, recent[1:]))
                bpm = 60.0 / max(0.2, iv[len(iv) // 2])
                while bpm < 70: bpm *= 2
                while bpm > 180: bpm /= 2
                return bpm
        return 0.0

    # --- estilo de baile según el tempo y lo grave/fuerte que suena ---------------------------------------------
    def _estilo(self, now, forzar=False):
        """Estima el estilo (cada ~2 s) y avisa si cambió. Es una aproximación por tempo y graves, no sabe el género real."""
        if not forzar and now - getattr(self, "_t_estilo", 0.0) < 2.0:
            return
        self._t_estilo = now
        self.bpm = self._tempo(now) or self.bpm
        bpm = self.bpm or 100.0
        if bpm < 85 and self._rms_avg < 0.03:
            est = "suave"
        elif bpm < 105 and self._frac_avg > 0.30:
            est = "grave"           # mucho bajo y tempo medio: reggaetón, hip-hop, trap
        elif bpm < 100:
            est = "balanceo"
        elif bpm < 128:
            est = "pop"
        elif bpm < 155:
            est = "fiesta"          # tempo de electrónica / dance
        else:
            est = "intenso"         # rock, metal, punk, drum & bass
        if est != self.estilo:
            self.estilo = est
            try:
                self.on_style(est)
            except Exception:                                   # noqa: BLE001
                pass
            if self.debug: print(f"[baile] estilo: {est} ({bpm:.0f} BPM, graves {self._frac_avg:.2f}, volumen {self._rms_avg:.3f})")

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
