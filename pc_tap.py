"""Orbi: oír lo que suena en la PC (la voz de tus amigos en una llamada) y mezclarlo con el micrófono.

El micrófono solo oye TU voz (y la limpieza de audio_clean.py quita lo que sale por las bocinas). Para que Orbi también oiga a los demás en una llamada
(Discord, Meet...) se captura lo que suena en la PC (WASAPI loopback, igual que audio_clean.py) y se suma al trozo de micrófono justo antes de
la palabra clave y de Gemini. Se llama desde live_client.py: `data = tap.mezclar(data, descartar=...)`.

Mientras Orbi habla NO se mezcla (su propia voz sale por las bocinas y se oiría a sí misma): en ese rato solo vale el micrófono."""
from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np

RATE = 16000
BLOCK = 320                    # 20 ms


class PCTap:
    def __init__(self, on_error=None, ganancia: float = 1.0):
        self.on_error = on_error or (lambda m: print(f"[pc_tap] {m}"))
        self.ganancia = float(ganancia)
        self._buf = deque(); self._n = 0; self._t = 0.0; self._lock = threading.Lock()
        # quién habla: el micrófono (ya sin el audio de la PC) es el usuario; lo que suena en la PC es un amigo. No es «reconocer voces»: son dos fuentes distintas
        # PRIORIDAD AL USUARIO: cuando hablas tú, el audio de la llamada se corta del flujo hacia Gemini (así tu frase queda limpia y Gemini detecta cuándo
        # terminaste, aunque tus amigos sigan hablando) y se queda cortado mientras Orbi te va a contestar, para que sus voces no la interrumpan.
        self.prioridad_usuario = True
        self.retener_s = 1.2                                          # tras tu última palabra, sigue cortado este rato (para que el silencio cierre tu turno)
        self.umbral_mic = 0.012                                       # volumen (RMS) del micro limpio que cuenta como «hablas tú»
        self.en_conversacion = None                                   # () -> bool: ¿hay ventana de conversación con Orbi abierta? (entonces espera su respuesta)
        self._res = 0.008                                             # restos de la voz de tus amigos que se cuelan al micro (aprendido): tu voz tiene que superarlos
        self._user_run = 0; self._user_t = -99.0; self._espera_hasta = 0.0
        self.on_hablante = None                                       # callback(q) con q = "usuario" | "amigo", al cambiar de quien habla
        self.umbral_voz = 0.012
        self._hab = None; self._cand = None; self._cand_t = 0.0; self._ult_voz = 0.0

    _NOMBRE = "pc-tap"

    @property
    def activo(self) -> bool:
        from loopback_hub import hub
        return hub().is_subscribed(self._NOMBRE)

    def start(self) -> None:
        """Se suscribe a la captura loopback COMPARTIDA (loopback_hub.py): ya no abre su propio recorder."""
        if self.activo:
            return
        from loopback_hub import hub
        with self._lock:
            self._buf.clear(); self._n = 0
        hub().subscribe(self._NOMBRE, self._push, 16000, self.on_error)

    def stop(self) -> None:
        from loopback_hub import hub
        hub().unsubscribe(self._NOMBRE)
        with self._lock:
            self._buf.clear(); self._n = 0

    # ------------------------------------------------------------------ captura
    def _push(self, x: np.ndarray) -> None:
        x = np.clip(np.asarray(x, dtype=np.float64) * 32768.0, -32768, 32767).astype(np.int16)
        with self._lock:
            self._buf.append(x); self._n += len(x); self._t = time.monotonic()
            if self._n > RATE * 0.3:                          # se atrasó: quedarse con lo más reciente
                allx = np.concatenate(self._buf)[-int(RATE * 0.1):]
                self._buf.clear(); self._buf.append(allx); self._n = len(allx)

    def _take(self, n: int) -> np.ndarray:
        with self._lock:
            if self._n == 0 or time.monotonic() - self._t > 0.5:      # la PC está en silencio
                self._buf.clear(); self._n = 0
                return np.zeros(n, dtype=np.int16)
            allx = np.concatenate(self._buf)
            out, rest = allx[:n], allx[n:]
            self._buf.clear()
            if len(rest):
                self._buf.append(rest)
            self._n = len(rest)
        if len(out) < n:
            out = np.concatenate([out, np.zeros(n - len(out), dtype=np.int16)])
        return out

    def _quien(self, mic: np.ndarray, pc: np.ndarray):
        m = float(np.sqrt(np.mean((mic.astype(np.float64) / 32768.0) ** 2))) if len(mic) else 0.0
        p = float(np.sqrt(np.mean((pc.astype(np.float64) / 32768.0) ** 2))) if len(pc) else 0.0
        if p > self.umbral_voz and p > m * 1.3:
            return "amigo"
        if m > self.umbral_voz and m >= p * 0.8:
            return "usuario"
        return None

    def _marcar(self, q) -> None:
        """Avisa solo cuando CAMBIA quien habla y lleva ~0.5 s hablando (así un ruidito no cuenta)."""
        now = time.monotonic()
        if q is None:
            if self._cand is not None and now - self._cand_t > 1.5:
                self._cand = None
            if self._hab is not None and now - self._ult_voz > 4.0:
                self._hab = None                                      # silencio largo: la siguiente voz se vuelve a anunciar
            return
        self._ult_voz = now
        if q == self._hab:
            self._cand = None
            return
        if q != self._cand:
            self._cand, self._cand_t = q, now
            return
        if now - self._cand_t >= 0.5:
            self._hab, self._cand = q, None
            cb = self.on_hablante
            if cb:
                try:
                    cb(q)
                except Exception:                                     # noqa: BLE001
                    pass

    def _usuario_habla(self, mic: np.ndarray, pc: np.ndarray, descartar: bool) -> bool:
        """¿Hablas tú ahora? (micrófono ya sin el audio de la PC, por encima de los restos aprendidos). Actualiza el estado de prioridad."""
        now = time.monotonic()
        if descartar:                                                 # Orbi está hablando: ya te contestó, se acaba la espera
            self._espera_hasta = 0.0; self._user_run = 0
            return False
        m = float(np.sqrt(np.mean((mic.astype(np.float64) / 32768.0) ** 2))) if len(mic) else 0.0
        p = float(np.sqrt(np.mean((pc.astype(np.float64) / 32768.0) ** 2))) if len(pc) else 0.0
        if m > max(self.umbral_mic, 2.0 * self._res):
            self._user_run += 1
        else:
            self._user_run = 0
            if p > self.umbral_voz:                                   # solo suena la llamada: lo que se cuela al micro son restos de ella
                self._res = 0.98 * self._res + 0.02 * min(m, 0.05)
        if self._user_run >= 2:                                       # ~130 ms seguidos: no es un clic ni un ruidito
            self._user_t = now
            try:
                conv = bool(self.en_conversacion()) if self.en_conversacion else False
            except Exception:                                         # noqa: BLE001
                conv = False
            self._espera_hasta = now + 8.0 if conv else 0.0           # si le hablas a Orbi, sus respuestas van primero (máx. 8 s)
            return True
        return False

    def mezclar(self, pcm: bytes, descartar: bool = False) -> bytes:
        """Suma el audio de la PC al trozo de micro (int16 mono 16 kHz). Con `descartar` solo avanza el reloj y devuelve el micro tal cual."""
        try:
            n = len(pcm) // 2
            pc = self._take(n)
            if not self.activo:
                return pcm
            mic = np.frombuffer(pcm, dtype="<i2")
            if not descartar:
                self._marcar(self._quien(mic, pc))
            hablas = self._usuario_habla(mic, pc, descartar)
            now = time.monotonic()
            silenciar = self.prioridad_usuario and (hablas or now - self._user_t < self.retener_s or now < self._espera_hasta)
            if descartar or silenciar or not pc.any():
                return pcm
            return np.clip(mic.astype(np.int32) + (pc.astype(np.int32) * self.ganancia).astype(np.int32), -32768, 32767).astype("<i2").tobytes()
        except Exception as e:                                        # noqa: BLE001
            self.on_error(f"no pude mezclar el audio de la PC ({type(e).__name__}); paso solo el micrófono")
            return pcm
