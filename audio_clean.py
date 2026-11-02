"""Orbi: limpieza del micrófono ANTES de mandarlo a Gemini Live.

Quita de lo que oye el micrófono (1) el sonido que sale por las bocinas de la PC (música, videos, la propia voz de Orbi)
con un cancelador de eco (AEC) y (2) el ruido de fondo (ventilador, teclado) con RNNoise, que es opcional.

Cómo funciona el AEC: se captura lo que la PC está reproduciendo (WASAPI loopback, `soundcard`, igual que audio_react.py)
y un filtro adaptativo (PBFDAF, solo numpy) aprende cómo llega ese sonido al micrófono (retraso + rebote del cuarto)
y lo resta en vivo. No es «invertir la fase»: el retraso y el cuarto lo hacen imposible, por eso el filtro se adapta solo.

Uso (desde live_client.py, sobre cada trozo de micrófono PCM int16 / 16 kHz / mono):
    pcm = cleaner.process(pcm)

Si algo falla, el audio pasa tal cual: la limpieza nunca debe dejar a Orbi sordo.
"""
from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np

RATE = 16000              # lo que pide Gemini Live
N = 256                   # bloque de proceso: 16 ms
REF_BLOCK = 320           # bloque del loopback: 20 ms (menos llamadas = menos CPU)


class _PBFDAF:
    """Filtro adaptativo en frecuencia por particiones (overlap-save). `parts * N` muestras de filtro."""

    def __init__(self, parts: int, mu: float = 0.5):
        self.P, self.mu = parts, mu
        self.W = np.zeros((parts, N + 1), dtype=np.complex128)
        self.X = np.zeros((parts, N + 1), dtype=np.complex128)
        self.xprev = np.zeros(N)

    def run(self, ref: np.ndarray, mic: np.ndarray, adapt: bool) -> np.ndarray:
        x = np.concatenate([self.xprev, ref])
        self.xprev = ref.copy()
        Xf = np.fft.rfft(x)
        self.X = np.roll(self.X, 1, axis=0)
        self.X[0] = Xf
        y = np.fft.irfft((self.W * self.X).sum(axis=0))[N:]
        e = mic - y
        if adapt:
            E = np.fft.rfft(np.concatenate([np.zeros(N), e]))
            norm = (np.abs(self.X) ** 2).sum(axis=0) + 1e-3 * N
            G = self.mu * E / norm
            g = np.fft.irfft(np.conj(self.X) * G[None, :], axis=1)
            g[:, N:] = 0.0                                   # restricción: cada partición solo tiene N taps
            self.W += np.fft.rfft(g, axis=1)
        return e

    def retraso_ms(self) -> float:
        """Dónde está la energía del filtro = retraso bocina→micrófono que encontró."""
        en = (np.abs(self.W) ** 2).sum(axis=1)
        return float(np.argmax(en) * N * 1000.0 / RATE) if en.max() > 0 else 0.0


class MicCleaner:
    def __init__(self, aec: bool = True, ruido: bool = True, filtro_ms: float = 512,
                 eco_residual_db: float = 0, debug: bool = False, on_error=None):
        self.aec_on, self.debug = aec, debug
        self.on_error = on_error or (lambda m: print(f"[audio_clean] {m}"))
        self.res_gain = 10 ** (-abs(eco_residual_db) / 20.0)
        self.aec = _PBFDAF(max(4, int(round(filtro_ms * RATE / 1000.0 / N))))
        self._inbuf = np.zeros(0)
        self._ref = deque(); self._ref_n = 0; self._lock = threading.Lock(); self._ref_t = 0.0
        self._floor, self._gain, self._warm = None, 1.0, 0
        self._st = [0.0, 0.0, 0]                                         # energía mic, energía salida, bloques (para el debug)
        self._t_dbg = time.monotonic()
        self._rn = None
        self._tm = [0.0, 0.0, 0, 0.0]                                    # tiempo de proceso: suma, máx, trozos, EMA de carga (proceso/audio)
        self._lento = 0
        self._t_tm = time.monotonic()
        if ruido:
            try:
                from pyrnnoise import RNNoise
                self._rn = RNNoise(sample_rate=RATE)
            except Exception as e:                                       # noqa: BLE001
                self.on_error(f"Sin reducción de ruido ({type(e).__name__}): instala con  python -m pip install -U pyrnnoise")
        self._cap = None

    # ------------------------------------------------------------------ referencia (lo que suena en la PC)
    def push_ref(self, x: np.ndarray) -> None:
        with self._lock:
            self._ref.append(np.asarray(x, dtype=np.float64)); self._ref_n += len(x); self._ref_t = time.monotonic()
            if self._ref_n > RATE * 0.3:                                 # se atrasó (reloj distinto): quedarse con lo más reciente
                allx = np.concatenate(self._ref)[-int(RATE * 0.1):]
                self._ref.clear(); self._ref.append(allx); self._ref_n = len(allx)

    def _take_ref(self, n: int) -> np.ndarray:
        with self._lock:
            if self._ref_n == 0 or time.monotonic() - self._ref_t > 0.5:   # la PC está en silencio (el loopback no manda nada)
                self._ref.clear(); self._ref_n = 0
                return np.zeros(n)
            allx = np.concatenate(self._ref)
            out, rest = allx[:n], allx[n:]
            self._ref.clear()
            if len(rest):
                self._ref.append(rest)
            self._ref_n = len(rest)
        if len(out) < n:
            out = np.concatenate([out, np.zeros(n - len(out))])
        return out

    def start(self) -> None:
        if not self.aec_on or self._cap is not None:
            return
        self._cap = _RefCapture(self.push_ref, self.on_error)
        self._cap.start()

    def stop(self) -> None:
        if self._cap is not None:
            self._cap.stop(); self._cap = None

    # ------------------------------------------------------------------ micrófono
    def process(self, pcm: bytes) -> bytes:
        t0 = time.perf_counter()
        try:
            x = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
            y = self.process_f(x)
            out = np.clip(y * 32768.0, -32768, 32767).astype("<i2")
            if self._rn is not None:
                out = self._ruido(out)
            res = out.tobytes()
        except Exception as e:                                           # noqa: BLE001
            self.on_error(f"falló la limpieza ({type(e).__name__}: {e}); paso el audio sin limpiar")
            self.aec_on = False; self._rn = None
            return pcm
        self._medir(time.perf_counter() - t0, len(pcm) / 2 / RATE)
        return res

    def _medir(self, dt: float, audio_s: float) -> None:
        """Mide cuánto tarda la limpieza. Si la PC va tan justa que no alcanza a tiempo (antivirus, CPU al tope), apaga primero el ruido
        y luego el eco, avisando: un micro sin limpiar es mejor que una voz de Orbi entrecortada."""
        tm = self._tm
        tm[0] += dt; tm[1] = max(tm[1], dt); tm[2] += 1
        tm[3] = 0.9 * tm[3] + 0.1 * (dt / max(audio_s, 1e-3))
        if tm[3] > 0.6:
            self._lento += 1
        else:
            self._lento = 0
        if self._lento >= 30:                                            # ~2 s seguidos usando más del 60 % del tiempo real
            self._lento = 0; tm[3] = 0.0
            if self._rn is not None:
                self._rn = None
                self.on_error("Tu PC va muy justa de CPU: apago la reducción de ruido del micrófono para que la voz de Orbi no se corte.")
            elif self.aec_on:
                self.aec_on = False
                self.on_error("Tu PC va muy justa de CPU: apago el cancelador de eco para que la voz de Orbi no se corte.")
        if self.debug and time.monotonic() - self._t_tm > 3 and tm[2]:
            print(f"[audio_clean] proceso medio {tm[0] / tm[2] * 1000:.1f} ms, máx {tm[1] * 1000:.1f} ms por trozo | carga {tm[3] * 100:.0f} % del tiempo real")
            self._tm = [0.0, 0.0, 0, tm[3]]; self._t_tm = time.monotonic()

    def process_f(self, x: np.ndarray) -> np.ndarray:
        """float [-1, 1] mono 16 kHz → float. Acumula hasta tener bloques de N; la sobra espera al siguiente trozo."""
        if not self.aec_on:
            return x
        buf = np.concatenate([self._inbuf, x])
        nb = len(buf) // N
        self._inbuf = buf[nb * N:]
        outs = [self._bloque(buf[i * N:(i + 1) * N]) for i in range(nb)]
        return np.concatenate(outs) if outs else np.zeros(0)

    def _bloque(self, mic: np.ndarray) -> np.ndarray:
        ref = self._take_ref(N)
        ref_on = float(np.sqrt(np.mean(ref ** 2))) > 0.002
        near = self._floor_near(None)
        e = self.aec.run(ref, mic, adapt=ref_on and not near)
        if ref_on:
            e_rms = float(np.sqrt(np.mean(e ** 2)))
            near = self._floor_near(e_rms, float(np.sqrt(np.mean(ref ** 2))))
        g_t = self.res_gain if (ref_on and not near) else 1.0            # solo eco: baja el residuo; si hablas, no toca
        g0 = self._gain
        self._gain = g0 + (g_t - g0) * (0.5 if g_t < g0 else 0.8)
        e = e * np.linspace(g0, self._gain, N)
        if self.debug and ref_on:
            self._st[0] += float(np.sum(mic ** 2)); self._st[1] += float(np.sum(e ** 2)); self._st[2] += 1
            if time.monotonic() - self._t_dbg > 3 and self._st[2]:
                erle = 10 * np.log10((self._st[0] + 1e-12) / (self._st[1] + 1e-12))
                print(f"[audio_clean] eco quitado ≈ {erle:4.1f} dB | retraso bocina→mic ≈ {self.aec.retraso_ms():.0f} ms | habla tuya: {'sí' if near else 'no'}")
                self._st = [0.0, 0.0, 0]; self._t_dbg = time.monotonic()
        return e

    def _floor_near(self, e_rms, ref_rms=0.0):
        """¿hablas tú mientras suena la PC? El eco que sobra es proporcional al volumen de la PC (e/ref); si ese cociente
        se dispara por encima de su mínimo reciente, es otra cosa (tu voz). Así los cambios de volumen de la música no cuentan."""
        if e_rms is None:
            return getattr(self, "_near", False)
        r = e_rms / (ref_rms + 1e-6)
        self._warm += 1
        if self._floor is None or r < self._floor:
            self._floor = r if self._floor is None else 0.9 * self._floor + 0.1 * r
        else:
            self._floor *= 1.002
        self._near = self._warm > 150 and r > 2.5 * self._floor and e_rms > 0.004     # los primeros ~2 s siempre aprende
        return self._near

    def _ruido(self, pcm16: np.ndarray) -> np.ndarray:
        frames = [np.asarray(f).reshape(-1) for _, f in self._rn.denoise_chunk(pcm16, partial=False)]
        return np.concatenate(frames).astype("<i2") if frames else np.zeros(0, dtype="<i2")


class _RefCapture(threading.Thread):
    """Escucha lo que sale por las bocinas (loopback WASAPI) a 16 kHz mono y se lo pasa al AEC."""

    def __init__(self, push, on_error):
        super().__init__(daemon=True, name="orbi-aec-ref")
        self.push, self.on_error, self._stop_ev = push, on_error, threading.Event()

    def stop(self) -> None:
        self._stop_ev.set()

    def run(self) -> None:
        import warnings
        warnings.filterwarnings("ignore", message="data discontinuity in recording")
        errores = 0
        while not self._stop_ev.is_set():
            try:
                import soundcard as sc
                from pc_audio import loopback_mic
                spk = sc.default_speaker()
                mic = loopback_mic(sc)
                rec_cm = mic.recorder(samplerate=RATE, channels=1, blocksize=RATE // 2)
                rec = rec_cm.__enter__()
                try:
                    errores, t_chk = 0, time.monotonic()
                    while not self._stop_ev.is_set():
                        d = rec.record(numframes=REF_BLOCK)
                        self.push(d[:, 0] if getattr(d, "ndim", 1) > 1 else d)
                        if time.monotonic() - t_chk > 5.0:               # ¿cambiaste de bocinas/audífonos? reabrir
                            t_chk = time.monotonic()
                            if sc.default_speaker().id != spk.id:
                                break
                finally:
                    try:
                        rec_cm.__exit__(None, None, None)
                    except Exception:                                    # noqa: BLE001
                        pass                                             # S_FALSE al cerrar un flujo ya detenido: no es un fallo real
            except Exception as e:                                       # noqa: BLE001
                errores += 1
                if errores == 1:
                    self.on_error(f"No pude escuchar el audio de la PC para cancelar el eco ({type(e).__name__}: {str(e)[:100]}).")
                if errores >= 3:
                    self.on_error("Dejo el cancelador de eco apagado (el micrófono sigue normal).")
                    return
                self._stop_ev.wait(2.0 * errores)


def crear_limpiador(cfg: dict, headphones: bool = False, on_error=None) -> MicCleaner | None:
    """Arma el limpiador según config.json. Con audífonos no hay eco que quitar: solo ruido. None si todo está apagado."""
    if not cfg.get("limpiar_mic", True):
        return None
    aec = bool(cfg.get("limpiar_eco", True)) and not headphones
    ruido = bool(cfg.get("limpiar_ruido", False))          # RNNoise: opcional (gasta CPU y puede comerse el inicio de una palabra corta como «Orbi»)
    if not aec and not ruido:
        return None
    return MicCleaner(aec=aec, ruido=ruido, filtro_ms=float(cfg.get("aec_filtro_ms", 512)),
                      eco_residual_db=float(cfg.get("aec_residuo_db", 0)), debug=bool(cfg.get("aec_debug", False)),
                      on_error=on_error)
