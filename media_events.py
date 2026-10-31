"""Eventos de música de Windows: reproducir, pausar, cambiar de canción. Se leen del control multimedia del sistema (el mismo de las teclas
multimedia y del panel de volumen), que Spotify, YouTube en Chrome/Edge, el reproductor de Windows, etc. rellenan solos.
Es LOCAL: no escucha ni sube nada; solo pregunta «¿qué está sonando / en pausa?» unas 2 veces por segundo.

Necesita UNA de estas librerías (si no está, Orbi sigue bailando con el método de siempre, solo que tarda más en notar las pausas):
    pip install winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections
    (o, alternativa vieja:  pip install winsdk)

MediaWatcher(on_state, on_track).start()
  on_state(playing)  -> True: algo está sonando · False: hay reproductores pero todos en pausa/detenidos · None: no hay ninguno (no se sabe)
  on_track(titulo, artista) -> cambió la canción
"""
import asyncio
import threading
import time

PLAYING = 4          # GlobalSystemMediaTransportControlsSessionPlaybackStatus.Playing (0 Closed, 1 Opened, 2 Changing, 3 Stopped, 4 Playing, 5 Paused)


def _manager_cls():
    for mod in ("winsdk.windows.media.control", "winrt.windows.media.control"):
        try:
            m = __import__(mod, fromlist=["GlobalSystemMediaTransportControlsSessionManager"])
            return m.GlobalSystemMediaTransportControlsSessionManager
        except Exception:                                      # noqa: BLE001
            continue
    return None


class MediaWatcher:
    def __init__(self, on_state, on_track, interval: float = 0.4, debug: bool = False):
        self.on_state, self.on_track, self.interval, self.debug = on_state, on_track, interval, debug
        self._stop = threading.Event()
        self._th = None

    def start(self) -> bool:
        """False si no está la librería de Windows (entonces no hay eventos de música)."""
        cls = _manager_cls()
        if cls is None:
            return False
        self._th = threading.Thread(target=lambda: asyncio.run(self._loop(cls)), daemon=True, name="media-events")
        self._th.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    async def _loop(self, cls) -> None:
        mgr, errores, estado, track, t_props = None, 0, "?", None, 0.0
        while not self._stop.is_set():
            try:
                if mgr is None:
                    mgr = await cls.request_async()
                sesiones = list(mgr.get_sessions())
                sonando = [s for s in sesiones if int(s.get_playback_info().playback_status) == PLAYING]
                nuevo = None if not sesiones else bool(sonando)
                if nuevo != estado:
                    estado = nuevo
                    if self.debug:
                        print(f"[música] {'sonando' if nuevo else 'en pausa' if nuevo is False else 'sin reproductor'}")
                    self.on_state(nuevo)
                if sonando and time.time() - t_props > 1.0:
                    t_props = time.time()
                    p = await sonando[0].try_get_media_properties_async()
                    cur = ((p.title or "").strip(), (p.artist or "").strip())
                    if cur[0] and cur != track:
                        track = cur
                        if self.debug:
                            print(f"[música] canción: {cur[1]} - {cur[0]}")
                        self.on_track(*cur)
                errores = 0
            except Exception as e:                             # noqa: BLE001
                errores += 1
                mgr = None                                     # vuelve a pedir el administrador (a veces se invalida al cambiar de dispositivo)
                if self.debug and errores in (1, 20):
                    print(f"[música] error leyendo el control multimedia: {type(e).__name__}: {str(e)[:80]}")
            await asyncio.sleep(self.interval if errores < 5 else 3.0)
