"""¿Cuándo le estás hablando a Orbi? (para que no conteste cuando hablas solo o con otras personas)

Tres modos de escucha (menú de la bolita o asistente de configuración):
  palabra  (recomendado)  Orbi solo manda tu voz a Gemini después de oír «Orbi» (detector LOCAL, tu audio no sale de la PC
                          mientras esté en espera). Abre una VENTANA DE CONVERSACIÓN de ~25 s que se renueva mientras
                          platican; si te despides ("gracias, es todo") o pasa el tiempo en silencio, vuelve a la espera.
  atajo                   Igual, pero la ventana se abre con Ctrl+Alt+Espacio (o clic derecho > "Hablar ahora").
  siempre                 Como antes: siempre escuchando (Gemini decide si le hablas; con gemini-3.8-live ya filtra mejor).

El detector de palabra clave usa Vosk (reconocimiento offline, modelo pequeño en español ~40 MB que se descarga solo la
primera vez). Si Vosk o el modelo no están, Orbi avisa y se queda en modo "atajo"/"siempre" sin romperse.
"""
import difflib, json, os, queue, re, threading, time, unicodedata, urllib.request, zipfile
from pathlib import Path

from paths import APP_DIR as ROOT  # carpeta de Orbi (o del .exe)
MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip"
MODEL_DIR = ROOT / "models"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z ]", "", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def matches_wake(text: str, word: str = "orbi", aliases=(), threshold: float = 0.74) -> bool:
    """¿`text` (lo que oyó el reconocedor) contiene la palabra clave, aunque la haya transcrito imperfecta?"""
    targets = {_norm(word), *(_norm(a) for a in aliases)} - {""}
    toks = _norm(text).split()
    if not toks or not targets:
        return False
    cands = list(toks) + ["".join(toks[i:i + 2]) for i in range(len(toks) - 1)]        # "or bi" -> "orbi"
    for c in cands:
        for t in targets:
            if c == t or (len(t) >= 4 and difflib.SequenceMatcher(None, c, t).ratio() >= threshold):
                return True
    return False


class Attention:
    """Compuerta del micro: abierta en 'siempre', o durante una ventana de conversación en 'palabra'/'atajo'."""

    def __init__(self, mode: str = "siempre", window: float = 25.0, now=time.time):
        self.mode, self.window, self.now = mode, float(window), now
        self._until = 0.0

    def is_open(self) -> bool:
        return self.mode == "siempre" or self.now() < self._until

    def open(self, seconds=None):
        self._until = max(self._until, self.now() + (seconds or self.window))

    def extend(self, seconds=None):
        """Hay actividad (hablas, Orbi habla, corre una tarea): renueva la ventana si estaba abierta."""
        if self.mode != "siempre" and self.now() < self._until:
            self._until = self.now() + (seconds or self.window)

    def close(self):
        self._until = 0.0

    def set_mode(self, mode: str):
        self.mode = mode if mode in ("siempre", "palabra", "atajo") else "siempre"
        if self.mode == "siempre":
            self._until = 0.0

    @property
    def standby(self) -> bool:
        return self.mode != "siempre" and not self.is_open()


class WakeWord:
    """Detector de palabra clave offline con Vosk. `feed()` recibe los trozos de micro (16 kHz, int16)."""

    def __init__(self, on_wake, emit=lambda k, d: None, word="orbi", aliases=("orvi", "orbe", "horbi", "horvi", "orby"),
                 threshold=0.74, model_url=MODEL_URL):
        self.on_wake, self.emit = on_wake, emit
        self.word, self.aliases, self.threshold, self.model_url = word, aliases, threshold, model_url
        self.status = "apagado"          # apagado | descargando | cargando | listo | error
        self.error = ""
        self._q = queue.Queue(maxsize=80)
        self._stop = threading.Event()
        self._thread = None
        self._last_wake = 0.0
        self.enabled = False             # solo escucha mientras Orbi está en espera (ahorra CPU)

    # ------------------------------------------------------------ ciclo de vida
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def feed(self, data: bytes):
        if not self.enabled or self.status != "listo":
            return
        try:
            self._q.put_nowait(data)
        except queue.Full:
            pass

    # ------------------------------------------------------------ modelo
    def _find_model(self):
        if MODEL_DIR.is_dir():
            for d in sorted(MODEL_DIR.iterdir()):
                if d.is_dir() and (d / "am").exists() or (d.is_dir() and (d / "conf").exists()):
                    return d
        return None

    def _download(self):
        MODEL_DIR.mkdir(exist_ok=True)
        zpath = MODEL_DIR / "model.zip"
        self.status = "descargando"
        self.emit("wake_status", "Descargando el oído para «Orbi» (una sola vez, ~40 MB)…")

        def hook(blocks, size, total):
            if total > 0 and blocks % 200 == 0:
                self.emit("info", f"[palabra clave] descargando… {min(100, blocks * size * 100 // total)}%")
        urllib.request.urlretrieve(self.model_url, zpath, hook)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(MODEL_DIR)
        zpath.unlink(missing_ok=True)

    def _run(self):
        try:
            import vosk
        except ImportError:
            self.status, self.error = "error", "Falta instalar vosk (pip install vosk)."
            self.emit("wake_status", self.error)
            return
        try:
            model_dir = self._find_model()
            if model_dir is None:
                self._download()
                model_dir = self._find_model()
            if model_dir is None:
                raise RuntimeError("No encontré el modelo después de descargarlo.")
            self.status = "cargando"
            vosk.SetLogLevel(-1)
            model = vosk.Model(str(model_dir))
            rec = vosk.KaldiRecognizer(model, 16000)
        except Exception as e:                                   # noqa: BLE001
            self.status, self.error = "error", f"{type(e).__name__}: {e}"
            self.emit("wake_status", f"No pude preparar la palabra clave: {self.error[:140]}")
            return
        self.status = "listo"
        self.emit("wake_status", "listo")
        while not self._stop.is_set():
            try:
                data = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "")
                else:
                    text = json.loads(rec.PartialResult()).get("partial", "")
            except Exception:
                continue
            if text and matches_wake(text, self.word, self.aliases, self.threshold):
                now = time.time()
                if now - self._last_wake > 2.0:
                    self._last_wake = now
                    rec.Reset()
                    self.on_wake(text)
