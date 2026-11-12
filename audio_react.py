"""Orbi baila al ritmo de la música que suena en la PC (Spotify, YouTube, Discord, llamadas, lo que sea).

Todo se analiza LOCAL: se captura lo que sale por tus bocinas (WASAPI loopback, librería `soundcard`), se mide la energía de los
graves y se detectan los golpes de ritmo. No se graba nada, no se manda nada a Gemini y no gasta cuota.

Cómo decide «esto es música» (suene donde suene: YouTube, Spotify, un juego...): en los últimos segundos tiene que haber golpes
REGULARES (60-210 BPM), de graves o de ataques en todo el espectro (para música sin bombo fuerte), y el sonido NO debe parecer
habla. El habla (videos, clases, llamadas) se reconoce porque tiene muchas pausas cortas entre palabras y una envolvente que
«late» al ritmo de las sílabas (~4-6 veces por segundo); la música casi no tiene pausas. Además estima el tempo (BPM) y elige
un estilo de baile (`estilo`: suave, balanceo, grave, pop, fiesta, intenso).

RITMO ESTABLE: los golpes sueltos (bombo, caja, platillos, rellenos de batería) ya NO mueven a Orbi uno por uno, porque así daba
saltos a lo loco. Se mide el TEMPO de la canción (autocorrelación de la «fuerza de ataque» de los últimos ~8 s, con preferencia por
tempos razonables para no confundir el doble o la mitad) y Orbi baila con un metrónomo propio a ese tempo, que se engancha con
suavidad a los golpes reales. Si el tempo cambia se tarda ~2 s en seguirlo (no brinca con un solo relleno), y por encima de ~150 BPM
baila a la mitad de velocidad. Si la música no tiene un pulso claro, vuelve al método de antes (un movimiento por golpe).
"""
import math, threading, time
from collections import deque

RATE = 48000                       # lo entrega la captura compartida (loopback_hub.py); antes 44100
BLOCK = 1024                       # ~23 ms por bloque que se analiza
BUFFER = 16384                     # ~370 ms de colchón de WASAPI. soundcard usa blocksize/samplerate como duración del buffer:
                                   # con 1024 eran 23 ms y cualquier tironcito de la CPU perdía audio («data discontinuity»)
BASS = (30.0, 195.0)               # banda donde viven el bombo y el bajo (a 48 kHz cada bin de FFT es ~9 % más ancho: 195 Hz deja los mismos 4 bins que 180 Hz a 44.1 kHz)
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
        self._acc = None; self._t0 = time.monotonic(); self._frames = 0
        self._reset()

    # ------------------------------------------------------------------ control
    def start(self):
        """Se suscribe a la captura loopback COMPARTIDA (loopback_hub.py): ya no abre su propio recorder."""
        from loopback_hub import hub
        if hub().is_subscribed(self._NOMBRE):
            return
        self._reset()
        self._acc = None
        self._t0, self._frames = time.monotonic(), 0
        hub().subscribe(self._NOMBRE, self._on_raw, RATE, self._hub_error)

    def stop(self):
        from loopback_hub import hub
        hub().unsubscribe(self._NOMBRE)
        self._apagar_baile()

    _NOMBRE = "audio-react"

    def _apagar_baile(self):
        if self.dancing:
            self.dancing = False; self.on_dance(False)

    def _hub_error(self, msg):
        self.on_error(msg)
        self._apagar_baile()

    def _on_raw(self, x):
        """Recibe bloques de 960 muestras (48 kHz) de la captura compartida y los junta en bloques de BLOCK para analizarlos."""
        import numpy as np
        self._acc = x if self._acc is None else np.concatenate((self._acc, x))
        while len(self._acc) >= BLOCK:
            blk, self._acc = self._acc[:BLOCK], self._acc[BLOCK:]
            self._frames += BLOCK
            # reloj por muestras: si el hilo se atrasa y recupera de golpe, los golpes no se «apelotonan»
            self.process(blk, now=self._t0 + self._frames / RATE)

    # ------------------------------------------------------------------ análisis (se puede probar sin soundcard)
    LEAD_S = 0.055                             # la detección llega ~60 ms tarde: el metrónomo se adelanta ese poco
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
        # --- tempo estable + metrónomo
        self._ons = deque(maxlen=400)             # fuerza de ataque por bloque (~9 s)
        self._ons_t = deque(maxlen=400)
        self._prev_bass = 0.0
        self._ons_avg = 1.0                       # promedio móvil de la fuerza de ataque (para detectar picos)
        self._tempo_bpm = 0.0                         # BPM estable (70-180) mientras hay pulso claro
        self._conf = 0.0                          # qué tan periódico es el sonido (0..1)
        self._locked = False                      # ¿hay pulso claro? entonces el metrónomo manda
        self._weak = 0; self._cand = None
        self._t_est = 0.0
        self._next = None; self._realign = False  # próximo golpe del metrónomo
        self._peak = 0.0; self._ev_t = -9.0
        self.clock_beats = 0
        self._quiet_since = None                  # desde cuándo hay silencio seguido
        self._fast = False                        # recién le dieron play: empieza a bailar con menos golpes
        self._now = 0.0
        self.total_beats = 0                      # (para diag_audio.py)
        self.dancing = False
        self._last_music = 0.0
        self._since = None                        # desde cuándo «parece música» sin interrupción
        self._frac_avg, self._rms_avg = 0.0, 0.0
        self.bpm, self.estilo = 0.0, ""
        self.speechy = False
        self.bloqueado = False                    # lo pone live_orb.py: lo que suena es un VIDEO (no música): no baila aunque haya ritmo

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

        self._now = now
        if rms > SILENCE_RMS:
            self._quiet_since = None
        elif self._quiet_since is None:
            self._quiet_since = now
        if self.dancing and self._quiet_since is not None and now - self._quiet_since > self.QUIET_STOP_S:   # pausaron: no esperar los ~4 s de antes
            self._para(now, "silencio")
            return
        self._onset(now, bass, avg, flux, fm, rms)
        bass_beat = (avg > 0 and bass > avg * self.ratio and bass > 0.0003 and frac > 0.03)
        flux_beat = (len(self._flux_hist) > 20 and flux > fm + 1.5 * max(fsd, 0.02 * fm) and flux > fm * 1.6 and flux > 1.0)
        if rms > SILENCE_RMS and bass_beat and now - self._last_bass > 0.24:
            self._last_bass = now
            self._bbeats.append(now)
        if rms > SILENCE_RMS and (bass_beat or flux_beat) and now - self._last_beat > 0.24:
            self._last_beat = now
            self.total_beats += 1
            self._beats.append(now)
            if self.dancing and not self._locked:           # sin pulso claro: un movimiento por golpe, como antes
                self.on_beat(min(1.0, max(bass / (avg * 3.0 + 1e-9), flux / (fm * 3.0 + 1e-9))))

        self._habla(now)
        if self.bloqueado:                                  # el título/la app dicen que es un video: nada de bailar (ni empezar a medir el ritmo)
            if self.dancing:
                self._para(now, "es un video, no música")
            self._since = None
            return
        if self.dancing and self._locked:
            self._clock(now)
        music = self._keep_dancing(now) if self.dancing else self._is_music(now)
        if music:
            self._last_music = now
        if not self.dancing:
            if not music:
                self._since = None
            else:
                if self._since is None:
                    self._since = now
                if now - self._since >= (min(self.hold, 1.0) if self._fast else self.hold):   # tiene que parecer música varios segundos seguidos
                    self.dancing = True; self._fast = False; self.on_dance(True)
                    self._estilo(now, forzar=True)
                    if self.debug: print(f"[baile] empieza ({self.bpm:.0f} BPM, estilo {self.estilo})")
        elif now - self._last_music > 1.5:
            self.dancing = False; self._since = None; self.on_dance(False)
            if self.debug: print(f"[baile] para (sonido={sum(self._loud)}/{len(self._loud)} bloques, golpes 10 s={sum(1 for t in self._beats if now - t <= 10.0)}, "
                                 f"habla={self.speechy} pausas/s={self._pause_rate(now):.2f} mod={self._mod:.2f})")
        elif self.dancing:
            self._estilo(now)

    # --- eventos de música (los manda live_orb.py desde media_events.py) --------------------------------------------
    QUIET_STOP_S = 0.6                            # silencio seguido que corta el baile (un break de EDM casi nunca dura tanto)

    def _para(self, now, motivo: str) -> None:
        if self.dancing:
            self.dancing = False; self._since = None; self.on_dance(False)
            if self.debug: print(f"[baile] para ({motivo})")
        self._beats.clear(); self._bbeats.clear()
        self.reset_ritmo()

    def media_state(self, playing) -> None:
        """Pausa → deja de bailar al instante (una sola vez). NO bloquea nada más: para empezar a bailar no hace falta ningún evento de
        «play», basta con que el audio suene como música. Un «play» solo acelera el arranque un poquito."""
        if playing is False:
            self._para(self._now, "pausa")
            self._fast = True                   # si el audio sigue (otra app), vuelve a bailar rápido; si de verdad se calló, no hay nada que detectar
        elif playing:
            self._fast = True

    def bloquear(self, si: bool) -> None:
        """True: lo que suena es un video (película, tutorial, gameplay...), no música → no baila. False: vuelve a decidir por el audio."""
        si = bool(si)
        if si != self.bloqueado:
            self.bloqueado = si
            if si:
                self._para(self._now, "es un video, no música")
            if self.debug: print(f"[baile] {'bloqueado: es un video' if si else 'desbloqueado'}")

    def reset_ritmo(self) -> None:
        """Canción nueva: olvida el tempo y la fase para volver a medirlos (si no, se tarda en soltar el de la canción anterior)."""
        self._tempo_bpm, self._locked, self._next, self._cand, self._weak = 0.0, False, None, None, 0
        self._ons.clear(); self._ons_t.clear()

    # --- tempo estable y metrónomo ---------------------------------------------------------------------------------
    def _onset(self, now, bass, avg, flux, fm, rms):
        """Guarda la «fuerza de ataque» de este bloque (subida de graves + subida del espectro) y cada ~0.5 s re-estima el tempo."""
        pb = max(0.0, bass - self._prev_bass) / (avg + 1e-6) if avg > 0 else 0.0
        self._prev_bass = bass
        pf = flux / (fm + 1e-6) if fm > 0 else 0.0
        o = (min(6.0, pb) + 0.5 * min(6.0, pf)) if rms > SILENCE_RMS else 0.0
        self._ons.append(o); self._ons_t.append(now)
        self._ons_avg = self._ons_avg * 0.97 + o * 0.03
        self._peak = max(self._peak, o)
        if o > max(1.2, self._ons_avg * 2.2) and now - self._ev_t > 0.12:      # ataque claro: sirve para engancharse al ritmo
            self._ev_t = now
            self._pll(now)
        if now - self._t_est >= 0.5 and len(self._ons) >= 150:
            self._t_est = now
            try:
                self._estima_tempo(now)
            except Exception:                                  # noqa: BLE001
                pass

    def _estima_tempo(self, now):
        import numpy as np
        x = np.asarray(self._ons, dtype="float64")
        n = len(x)
        dt = (self._ons_t[-1] - self._ons_t[0]) / max(1, n - 1)
        if dt <= 0 or float(x.std()) < 1e-6:
            return self._track(now, 0.0, 0.0)
        fps = 1.0 / dt
        if float(np.percentile(x, 99)) < 2.0:                  # no hay ataques de verdad (pad, ruido, silencio): no hay pulso que seguir
            return self._track(now, 0.0, 0.0)
        x = x - x.mean()
        f = np.fft.rfft(x, 2 * n)
        ac = np.fft.irfft(f * np.conj(f))[:n]
        ac = ac / (ac[0] + 1e-12) * (n / np.maximum(1.0, n - np.arange(n)))       # normalizada y sin sesgo por la ventana corta
        lmin, lmax = int(fps * 60.0 / 180.0), int(fps * 60.0 / 70.0) + 1          # 180 BPM ... 70 BPM
        best, best_l = 0.0, 0
        for l in range(max(2, lmin), lmax + 1):
            sc = ac[l] + (0.5 * ac[2 * l] if 2 * l < n else 0.0) + (0.25 * ac[4 * l] if 4 * l < n else 0.0)   # el pulso real se repite en 2x y 4x
            bpm = 60.0 * fps / l
            w = math.exp(-0.5 * (math.log2(bpm / 105.0) / 0.75) ** 2)              # prefiere tempos «normales» (evita el doble o la mitad)
            if sc * w > best:
                best, best_l = sc * w, l
        if not best_l:
            return self._track(now, 0.0, 0.0)
        l = float(best_l)                                                          # afinar entre muestras (interpolación parabólica)
        if 2 <= best_l < n - 1:
            y0, y1, y2 = ac[best_l - 1], ac[best_l], ac[best_l + 1]
            den = y0 - 2 * y1 + y2
            if den < 0:
                l += max(-0.5, min(0.5, 0.5 * (y0 - y2) / den))
        self._conf = float(ac[best_l])
        self._track(now, 60.0 * fps / l, self._conf)

    def _track(self, now, bpm, conf):
        """Sigue el tempo con calma: ajustes chicos se suavizan; un cambio grande solo se acepta si se repite ~2 s; el doble o la mitad se ignoran."""
        if conf < 0.16 or bpm <= 0:
            self._weak += 1
            if self._weak >= 10 and self._locked:                  # ~5 s sin pulso claro: vuelve al método por golpes
                self._locked, self._tempo_bpm, self._next = False, 0.0, None
                if self.debug: print("[baile] sin pulso claro: un movimiento por golpe")
            return
        self._weak = 0
        cur = self._tempo_bpm
        if not cur:
            self._tempo_bpm, self._locked, self._realign, self._cand = bpm, True, True, None
            if self.debug: print(f"[baile] tempo {bpm:.0f} BPM (pulso {conf:.2f})")
            return
        r = bpm / cur
        if abs(r - 1.0) < 0.04:
            self._tempo_bpm = cur * 0.85 + bpm * 0.15
            self._cand = None
        elif 0.47 < r < 0.53 or 1.9 < r < 2.1 or 0.65 < r < 0.69 or 1.45 < r < 1.52:    # doble/mitad/3:2: no cuenta como cambio de tempo
            return
        else:
            if self._cand and abs(bpm / self._cand[0] - 1.0) < 0.04:
                self._cand = ((self._cand[0] + bpm) / 2.0, self._cand[1] + 1)
            else:
                self._cand = (bpm, 1)
            if self._cand[1] >= 4:                                  # ~2 s seguidos con otro tempo
                if self.debug: print(f"[baile] tempo {cur:.0f} -> {self._cand[0]:.0f} BPM")
                self._tempo_bpm, self._realign, self._cand = self._cand[0], True, None

    def _periodo(self) -> float:
        per = 60.0 / max(60.0, self._tempo_bpm)
        return per * 2.0 if self._tempo_bpm > 150.0 else per        # muy rápido: baila a la mitad (si no, parece que tiembla)

    def _fase(self, now, per) -> float:
        """Próximo instante de golpe, alineado con donde caen los ataques de los últimos ~4 s."""
        import numpy as np
        k = min(len(self._ons), int(4.0 / (BLOCK / RATE)))      # ~4 s de bloques (antes fijo en 0.0232 s = 1024 a 44.1 kHz)
        ts = np.fromiter(list(self._ons_t)[-k:], dtype="float64")
        os_ = np.fromiter(list(self._ons)[-k:], dtype="float64")
        phis = np.linspace(0.0, per, 48, endpoint=False)
        m = (ts[:, None] - phis[None, :]) % per
        d = np.minimum(m, per - m)
        score = (os_[:, None] * np.exp(-0.5 * (d / 0.05) ** 2)).sum(axis=0)
        phi = float(phis[int(score.argmax())])
        return now + ((phi - now) % per)

    def _pll(self, now):
        """Un ataque claro cerca del golpe esperado: mueve el metrónomo un poquito hacia él (se mantiene enganchado sin brincar)."""
        if not (self._locked and self._next):
            return
        per = self._periodo()
        e = ((now - self._next) + per / 2.0) % per - per / 2.0
        if abs(e) < 0.25 * per:
            self._next += 0.12 * e

    def _clock(self, now):
        """Metrónomo: un on_beat por cada golpe del tempo estable, no por cada golpe que se oye."""
        per = self._periodo()
        if self._realign or self._next is None:
            self._next, self._realign = self._fase(now, per), False
        if now >= self._next - self.LEAD_S:
            self.clock_beats += 1
            fuerza = max(0.5, min(1.0, 0.5 + 0.5 * self._peak / 4.0))
            self._peak = 0.0
            self._next += per
            if self._next < now:                                     # se atrasó mucho (CPU): reiniciar la cuenta
                self._next = now + per
            self.on_beat(fuerza)

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
        if len(recent) < (4 if self._fast else self.min_golpes) or sum(self._loud) < len(self._loud) * (0.3 if self._fast else 0.5):
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
