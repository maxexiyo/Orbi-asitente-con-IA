"""Escucha continua del audio de la PC (#81): Orbi oye lo que suena en la computadora SIN que se lo pidan.

No es streaming puro: cada `cada_s` segundos graba un trocito (`seg`), lo analiza el modelo de análisis y, si había algo (voz, llamada, video,
aviso sonoro), se lo pasa a Orbi en silencio como contexto. Ella decide si lo comenta o no. Nada se guarda en disco.
Se salta los trozos en los que Orbi estaba hablando (para no escucharse a sí misma) y los silencios (no gasta cuota)."""
import threading
import time


class EscuchaPC:
    def __init__(self, analizar, emit, puede, seg=8.0, cada_s=25.0, max_por_hora=90):
        self.analizar = analizar          # analizar(seg) -> texto | None | "" (hilo de fondo; puede tardar)
        self.emit = emit                  # emit("audio_pc", texto)
        self.puede = puede                # () -> bool: ¿se puede escuchar ahora? (conectada, despierta, sin hablar...)
        self.seg = float(seg); self.cada_s = float(cada_s); self.max_por_hora = int(max_por_hora)
        self._hilo = None
        self._stop = threading.Event()
        self._ultimo = ""
        self._horas = []                  # marcas de tiempo de los análisis (tope por hora, cuida la cuota)

    @property
    def activo(self):
        return self._hilo is not None and self._hilo.is_alive() and not self._stop.is_set()

    def start(self):
        if self.activo:
            return
        if self._hilo is not None and self._hilo.is_alive():     # se pidió parar hace nada: se espera a que termine antes de arrancar otra vez
            self._hilo.join(2.0)
        self._stop.clear()
        self._hilo = threading.Thread(target=self._loop, name="escucha_pc", daemon=True)
        self._hilo.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self.cada_s):
            try:
                if not self.puede():
                    continue
                ahora = time.time()
                self._horas = [t for t in self._horas if ahora - t < 3600]
                if len(self._horas) >= self.max_por_hora:
                    continue
                texto = self.analizar(self.seg)
                if self._stop.is_set() or not self.puede():       # se durmió o empezó a hablar mientras tanto: se descarta
                    continue
                self._horas.append(time.time())
                texto = (texto or "").strip()
                if not texto or texto == self._ultimo:
                    continue
                self._ultimo = texto
                self.emit("audio_pc", texto)
            except Exception as e:                                # noqa: BLE001
                print(f"[escucha_pc] {type(e).__name__}: {str(e)[:120]}")
                self._stop.wait(30)
