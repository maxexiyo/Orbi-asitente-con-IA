"""¿Quién habla? Huella de voz LOCAL del dueño (para no hacerle caso a otras personas).

Usa el modelo de hablante de Vosk (vosk-model-spk, ~13 MB, se descarga solo la primera vez). Todo corre en tu PC:
la huella se guarda en orbi_voz.json (no sube a ningún lado) y el audio se analiza aquí, no en la nube.

Cómo funciona:
  1. «Aprender mi voz»: hablas ~20 s y Orbi guarda tu huella (un vector de 128 números por frase).
  2. Cada frase que oye el micro se compara con tu huella (distancia coseno). Si es muy distinta -> otra persona.
  3. live_orb.py cancela la respuesta de ese turno (voz, texto y herramientas), así que nadie más puede darle órdenes.

Las frases muy cortas (< ~1 s) no se juzgan: no hay voz suficiente para saber de quién es.
"""
import json, math, threading, queue, time, urllib.request, zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
MODEL_DIR = ROOT / "models"
SPK_URL = "https://alphacephei.com/vosk/models/vosk-model-spk-0.4.zip"
VOICE_PATH = ROOT / "orbi_voz.json"

UMBRAL_DEFAULT = 0.55      # distancia coseno máxima para considerar que eres tú (se calibra al aprender tu voz)
MIN_FRAMES = 90            # frames de 10 ms: ~0.9 s de voz como mínimo para opinar
MIN_FRAMES_APRENDER = 800  # ~8 s de voz en total para guardar la huella


def cosine_dist(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 1.0
    return 1.0 - dot / (na * nb)


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class VoiceID:
    """Hilo con Vosk que clasifica cada frase como «dueño» u «otra voz».

    on_verdict(owner: bool, dist: float, text: str, dur_s: float) se llama al terminar cada frase juzgable.
    feed(data) recibe los trozos de micro (16 kHz, int16), igual que WakeWord.feed.
    """

    def __init__(self, on_verdict, emit=lambda k, d: None, umbral=None, min_frames=MIN_FRAMES):
        self.on_verdict, self.emit = on_verdict, emit
        self.umbral_cfg = float(umbral) if umbral else None     # config.json "voz_umbral" manda sobre el calibrado
        self.min_frames = int(min_frames)
        self.status = "apagado"           # apagado | descargando | cargando | listo | error
        self.error = ""
        self.enabled = True               # «solo hacerle caso a mi voz»
        self.ref = None                   # huella del dueño (vector unitario) o None si aún no aprende
        self.umbral = UMBRAL_DEFAULT
        self._q = queue.Queue(maxsize=120)
        self._stop = threading.Event()
        self._thread = None
        self._enroll = None               # {"vecs": [(vec, frames)], "seconds", "t_end", "done"} mientras aprende
        self._enroll_req = None
        self.load()

    # ------------------------------------------------------------ huella guardada
    @property
    def enrolled(self) -> bool:
        return self.ref is not None

    @property
    def enrolling(self) -> bool:
        return self._enroll is not None or self._enroll_req is not None

    @property
    def active(self) -> bool:
        """¿Hay que alimentarlo con micro? (solo si ya tiene huella o está aprendiendo)"""
        return (self.enabled and self.enrolled) or self.enrolling

    def load(self):
        try:
            d = json.loads(VOICE_PATH.read_text(encoding="utf-8"))
            ref = d.get("ref")
            if isinstance(ref, list) and len(ref) >= 32:
                self.ref = _unit([float(x) for x in ref])
                self.umbral = float(d.get("umbral", UMBRAL_DEFAULT))
        except Exception:
            self.ref = None

    def clear(self):
        self.ref = None
        try:
            VOICE_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    def _save(self, vecs):
        tot = sum(f for _v, f in vecs) or 1
        dim = len(vecs[0][0])
        mean = [sum(v[i] * f for v, f in vecs) / tot for i in range(dim)]
        ref = _unit(mean)
        umbral = UMBRAL_DEFAULT
        if len(vecs) >= 3:     # calibra con qué tan parecidas son tus propias frases a tu huella
            ds = [cosine_dist(v, ref) for v, _f in vecs]
            umbral = min(0.65, max(0.45, max(ds) + 0.12))
        self.ref, self.umbral = ref, umbral
        VOICE_PATH.write_text(json.dumps({
            "ref": [round(x, 6) for x in ref], "umbral": round(umbral, 3), "frases": len(vecs),
            "creado": datetime.now().isoformat(timespec="seconds"),
        }), encoding="utf-8")

    @property
    def umbral_efectivo(self) -> float:
        return self.umbral_cfg if self.umbral_cfg else self.umbral

    # ------------------------------------------------------------ aprender
    def start_enroll(self, seconds=20.0, done=lambda ok, msg: None):
        """Pide aprender tu voz. El reloj empieza cuando el modelo está listo."""
        self._enroll_req = (float(seconds), done)
        self.start()

    def cancel_enroll(self):
        self._enroll = self._enroll_req = None

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
        if self.status != "listo" or not self.active:
            return
        try:
            self._q.put_nowait(data)
        except queue.Full:
            pass

    # ------------------------------------------------------------ modelos
    @staticmethod
    def _find_dir(pred):
        if MODEL_DIR.is_dir():
            for d in sorted(MODEL_DIR.iterdir()):
                if d.is_dir() and pred(d):
                    return d
        return None

    def _find_main(self):
        return self._find_dir(lambda d: "spk" not in d.name and ((d / "am").exists() or (d / "conf").exists()))

    def _find_spk(self):
        return self._find_dir(lambda d: "spk" in d.name or (d / "mean.vec").exists())

    def _download_spk(self):
        MODEL_DIR.mkdir(exist_ok=True)
        zpath = MODEL_DIR / "spk.zip"
        self.status = "descargando"
        self.emit("voz_status", "Descargando el oído para reconocer tu voz (una sola vez, ~13 MB)…")
        urllib.request.urlretrieve(SPK_URL, zpath)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(MODEL_DIR)
        zpath.unlink(missing_ok=True)

    def _run(self):
        try:
            import vosk
        except ImportError:
            self.status, self.error = "error", "Falta instalar vosk (pip install vosk)."
            self.emit("voz_status", self.error)
            return
        try:
            main_dir = self._find_main()
            if main_dir is None:
                raise RuntimeError("No encuentro el modelo de voz en español (models/). Abre Orbi con «solo si digo Orbi» "
                                   "una vez para que lo descargue.")
            spk_dir = self._find_spk()
            if spk_dir is None:
                self._download_spk()
                spk_dir = self._find_spk()
            if spk_dir is None:
                raise RuntimeError("No encontré el modelo de hablante después de descargarlo.")
            self.status = "cargando"
            vosk.SetLogLevel(-1)
            model = vosk.Model(str(main_dir))
            spk = vosk.SpkModel(str(spk_dir))
            rec = vosk.KaldiRecognizer(model, 16000)
            rec.SetSpkModel(spk)
        except Exception as e:                                   # noqa: BLE001
            self.status, self.error = "error", f"{type(e).__name__}: {e}"
            self.emit("voz_status", f"No pude preparar el reconocimiento de voz: {self.error[:140]}")
            return
        self.status = "listo"
        self.emit("voz_status", "listo")
        while not self._stop.is_set():
            if self._enroll_req and self._enroll is None:        # empieza el reloj de aprendizaje ya con el modelo listo
                secs, done = self._enroll_req
                self._enroll_req = None
                self._enroll = {"vecs": [], "t_end": time.time() + secs, "done": done}
                rec.Reset()
                self.emit("voz_status", "aprendiendo")
            try:
                data = self._q.get(timeout=0.5)
            except queue.Empty:
                self._check_enroll_end()
                continue
            try:
                final = rec.AcceptWaveform(data)
                res = json.loads(rec.Result()) if final else None
            except Exception:
                continue
            if res is not None:
                self._on_final(res)
            self._check_enroll_end()

    # ------------------------------------------------------------ resultados
    def _on_final(self, res: dict):
        spk, frames = res.get("spk"), int(res.get("spk_frames") or 0)
        text = (res.get("text") or "").strip()
        if not spk or not text or frames <= 0:
            return
        if self._enroll is not None:
            self._enroll["vecs"].append((_unit([float(x) for x in spk]), frames))
            return
        if not (self.enabled and self.ref is not None) or frames < self.min_frames:
            return                                               # sin huella o frase muy corta: no se juzga
        dist = cosine_dist([float(x) for x in spk], self.ref)
        try:
            self.on_verdict(dist <= self.umbral_efectivo, dist, text, frames / 100.0)
        except Exception:
            pass

    def _check_enroll_end(self):
        e = self._enroll
        if e is None or time.time() < e["t_end"]:
            return
        self._enroll = None
        vecs = e["vecs"]
        total = sum(f for _v, f in vecs)
        if total < MIN_FRAMES_APRENDER:
            msg = (f"Casi no te escuché ({total / 100:.0f} s de voz). Revisa el micro, habla más fuerte "
                   "o inténtalo otra vez.")
            e["done"](False, msg)
            return
        try:
            self._save(vecs)
        except Exception as ex:                                  # noqa: BLE001
            e["done"](False, f"No pude guardar tu huella: {ex}")
            return
        e["done"](True, f"Listo, ya reconozco tu voz ✅ ({total / 100:.0f} s, {len(vecs)} frases)")
