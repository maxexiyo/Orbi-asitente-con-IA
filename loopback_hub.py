"""Orbi: UNA sola captura WASAPI loopback (lo que suena en la PC) compartida por todos los que la necesitan.

Antes, cada función abría su propia captura con `soundcard`: el cancelador de eco (audio_clean.py), el baile (audio_react.py), el modo
llamada (pc_tap.py) y «escuchar la PC» (pc_audio.record_wav, que abría y cerraba una nueva cada ~25 s). Eran hasta 4 clientes de audio
COM abiertos a la vez, cada uno revisando cada 5 s si cambiaste de bocinas. Con las horas (y los cambios de dispositivo Bluetooth) eso
es justo lo que puede dejar clientes de audio colgados en el servicio de audio de Windows (audiodg.exe), que sigue lento aunque cierres
Orbi y solo se arregla reiniciando.

Ahora hay UN hilo y UN recorder. Quien necesita el audio se suscribe y recibe bloques ya listos:
    hub().subscribe("nombre", callback, rate=16000, on_error=fn)    # callback(x) con x = float32 mono -1..1 (NO modificarlo)
        rate=16000 -> bloques de 320 muestras (20 ms): eco, llamada, escuchar PC
        rate=48000 -> bloques de 960 muestras (20 ms): baile (audio_react.py)
    hub().unsubscribe("nombre")
    hub().capturar(segundos)        # bloquea y devuelve float32 mono 16 kHz (para record_wav)
Cuando nadie está suscrito la captura se cierra sola. Si el dispositivo de salida cambia, se reabre una sola vez para todos.
"""
from __future__ import annotations

import threading
import time
import warnings

import numpy as np

RATE_RAW = 48000                 # se captura a 48 kHz y de ahí salen las dos velocidades (48000 y 16000 = 48000 / 3, exacto)
RATE_VOZ = 16000
BLOCK_RAW = 960                  # 20 ms a 48 kHz  ->  320 muestras a 16 kHz
BUFFER = 16384                   # ~340 ms de colchón de WASAPI (soundcard usa blocksize/samplerate como duración del buffer)
CHECK_S = 5.0                    # cada cuánto revisa si cambiaste de bocinas/audífonos (UNA vez para todos)
_DEC = 3
_TAPS = 63


def _fir() -> np.ndarray:
    """Filtro pasa-bajas (sinc con ventana Hamming) para bajar de 48 kHz a 16 kHz sin que los agudos se «doblen» (aliasing)."""
    t = np.arange(_TAPS) - (_TAPS - 1) / 2.0
    h = np.sinc(2.0 * 7200.0 / RATE_RAW * t) * np.hamming(_TAPS)
    return (h / h.sum()).astype(np.float64)


_FIR = _fir()


class LoopbackHub:
    def __init__(self):
        self._lk = threading.Lock()
        self._subs: dict = {}                      # nombre -> (callback, rate, on_error)
        self._th = None
        self._tail = np.zeros(_TAPS - 1)
        self._n = 0
        self.abiertos = 0                          # recorders abiertos AHORA (debe ser 0 o 1; si ves más, hay una fuga)
        self.stats = dict(aperturas=0, cierres=0, cierres_con_error=0, errores=0, bloques=0, reaperturas_por_cambio=0)

    # ------------------------------------------------------------------ suscripción
    def subscribe(self, name: str, callback, rate: int = RATE_VOZ, on_error=None) -> None:
        if rate not in (RATE_VOZ, RATE_RAW):
            raise ValueError("rate debe ser 16000 o 48000")
        with self._lk:
            self._subs[name] = (callback, rate, on_error or (lambda m: print(f"[loopback] {m}")))
            if self._th is None:
                self._th = threading.Thread(target=self._run, daemon=True, name="orbi-loopback")
                self._th.start()

    def unsubscribe(self, name: str) -> None:
        with self._lk:
            self._subs.pop(name, None)

    def is_subscribed(self, name: str) -> bool:
        with self._lk:
            return name in self._subs

    def detener(self) -> None:
        """Al cerrar Orbi: suelta a todos; el hilo cierra el recorder (si no está esperando audio, lo hará en cuanto llegue)."""
        with self._lk:
            self._subs.clear()

    def resumen(self) -> str:
        s = self.stats
        return (f"loopback: abiertos {self.abiertos} · aperturas {s['aperturas']} · cierres {s['cierres']} "
                f"(con error {s['cierres_con_error']}) · errores {s['errores']} · cambios de bocina {s['reaperturas_por_cambio']}")

    def _hay_subs(self) -> bool:
        with self._lk:
            return bool(self._subs)

    # ------------------------------------------------------------------ captura puntual (escuchar la PC N segundos)
    def capturar(self, seconds: float, rate: int = RATE_VOZ) -> np.ndarray:
        """Bloquea ~`seconds` s y devuelve float32 mono con EXACTAMENTE seconds*rate muestras (si la PC estaba en silencio y el loopback no mandó
        nada, se rellena con ceros). Reutiliza la captura que ya esté abierta (no abre otra). Lanza RuntimeError si no se pudo escuchar."""
        n = int(rate * seconds)
        partes, tot, ev, err = [], [0], threading.Event(), []
        nombre = f"captura-{id(ev)}"

        def cb(x):
            if tot[0] >= n:
                return
            partes.append(np.array(x, dtype=np.float32))
            tot[0] += len(x)
            if tot[0] >= n:
                ev.set()

        def onerr(m):
            err.append(m); ev.set()

        self.subscribe(nombre, cb, rate, onerr)
        try:
            ev.wait(seconds + 4.0)
        finally:
            self.unsubscribe(nombre)
        if err and tot[0] == 0:
            raise RuntimeError(err[0])
        out = np.concatenate(partes) if partes else np.zeros(0, dtype=np.float32)
        if len(out) < n:
            out = np.concatenate([out, np.zeros(n - len(out), dtype=np.float32)])
        return out[:n]

    # ------------------------------------------------------------------ hilo de captura
    def _run(self) -> None:
        warnings.filterwarnings("ignore", message="data discontinuity in recording")
        try:
            self._bucle()
        finally:
            with self._lk:
                self._th = None
                if self._subs:                       # alguien se suscribió justo mientras el hilo se estaba yendo: arranca otro
                    self._th = threading.Thread(target=self._run, daemon=True, name="orbi-loopback")
                    self._th.start()

    def _avisar_y_soltar(self, msg: str) -> None:
        with self._lk:
            subs = list(self._subs.values())
            self._subs.clear()
        for _cb, _r, onerr in subs:
            try:
                onerr(msg)
            except Exception:                        # noqa: BLE001
                pass

    def _avisar(self, msg: str) -> None:
        with self._lk:
            subs = list(self._subs.values())
        for _cb, _r, onerr in subs:
            try:
                onerr(msg)
            except Exception:                        # noqa: BLE001
                pass

    def _dormir(self, s: float) -> None:
        t0 = time.monotonic()
        while time.monotonic() - t0 < s and self._hay_subs():
            time.sleep(0.1)

    def _bucle(self) -> None:
        errores = 0
        while self._hay_subs():
            rec_cm = None
            try:
                import soundcard as sc
                from pc_audio import loopback_mic
                spk = sc.default_speaker()
                mic = loopback_mic(sc)
                cm = mic.recorder(samplerate=RATE_RAW, channels=1, blocksize=BUFFER)
                rec = cm.__enter__()
                rec_cm = cm                          # solo se cierra lo que de verdad se abrió
                self.stats["aperturas"] += 1
                self.abiertos += 1
                self._tail = np.zeros(_TAPS - 1)
                t_chk = time.monotonic()
                primero = True
                while self._hay_subs():
                    d = rec.record(numframes=BLOCK_RAW)
                    if primero:                      # solo cuenta como «abrió bien» si de verdad entregó audio (si no, un fallo en bucle reiniciaba el conteo)
                        errores = 0; primero = False
                    x = np.asarray(d[:, 0] if getattr(d, "ndim", 1) > 1 else d, dtype=np.float32)
                    self.stats["bloques"] += 1
                    self._repartir(x)
                    if time.monotonic() - t_chk > CHECK_S:           # ¿cambiaste de bocinas/audífonos? reabrir (una vez para todos)
                        t_chk = time.monotonic()
                        if sc.default_speaker().id != spk.id:
                            self.stats["reaperturas_por_cambio"] += 1
                            break
            except ImportError as e:
                import sys
                self._avisar_y_soltar(f"No se pudo importar ({e}). Orbi corre con: {sys.executable}  → instala ahí: "
                                      f"\"{sys.executable.replace('pythonw', 'python')}\" -m pip install -U soundcard numpy cffi")
                return
            except Exception as e:                   # noqa: BLE001
                errores += 1
                self.stats["errores"] += 1
                if errores == 1:
                    self._avisar(f"No pude escuchar el audio de la PC ({type(e).__name__}: {str(e)[:100]}).")
                if errores >= 3:
                    self._avisar_y_soltar("Dejo de escuchar el audio de la PC tras varios fallos (el micrófono sigue normal).")
                    return
                self._dormir(min(30.0, 2.0 * errores))
            finally:
                if rec_cm is not None:
                    try:
                        rec_cm.__exit__(None, None, None)
                        self.stats["cierres"] += 1
                    except Exception:                # noqa: BLE001
                        # S_FALSE al cerrar un flujo ya detenido (cambió el dispositivo): no es un fallo real, pero se cuenta para el diagnóstico
                        self.stats["cierres_con_error"] += 1
                    self.abiertos = max(0, self.abiertos - 1)

    # ------------------------------------------------------------------ reparto
    def _decimar(self, x: np.ndarray) -> np.ndarray:
        m = len(x) - len(x) % _DEC
        if m != len(x):
            x = x[:m]
        ext = np.concatenate((self._tail, x))
        y = np.convolve(ext, _FIR, mode="valid")           # misma longitud que x
        self._tail = ext[-(_TAPS - 1):]
        return y[::_DEC].astype(np.float32)

    def _repartir(self, x: np.ndarray) -> None:
        with self._lk:
            subs = list(self._subs.items())
        if not subs:
            return
        y16 = self._decimar(x) if any(r == RATE_VOZ for _n, (_c, r, _e) in subs) else None
        for _name, (cb, rate, _onerr) in subs:
            try:
                cb(y16 if rate == RATE_VOZ else x)
            except Exception:                        # noqa: BLE001  (un suscriptor con fallo no tumba a los demás)
                pass


_HUB = None
_HUB_LK = threading.Lock()


def hub() -> LoopbackHub:
    global _HUB
    with _HUB_LK:
        if _HUB is None:
            _HUB = LoopbackHub()
        return _HUB


def detener() -> None:
    """Para conectarlo a app.aboutToQuit."""
    if _HUB is not None:
        _HUB.detener()
