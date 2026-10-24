"""Imágenes dentro de documentos (PDF, Word, PowerPoint, Excel): detectarlas, describirlas y poder buscarlas después.

Alcance: solo los documentos que Orbi ABRE o LEE (leer_archivo, analizar_documento, abrir_archivo). Al hacerlo, en un hilo de
fondo se sacan sus imágenes, un modelo con visión describe cada una UNA sola vez y la descripción se guarda en un JSON.
Después `buscar_en_imagenes` encuentra documentos por lo que se VE en ellas, y `leer_archivo` avisa cuántas imágenes tiene.

Frenos de cuota: se salta íconos y logos chicos, máximo MAX_IMGS_DOC por documento y MAX_PER_DAY descripciones por día.
"""
import io, json, os, re, threading, time, zipfile
from datetime import date
from pathlib import Path

DOC_EXTS = {".pdf", ".docx", ".pptx", ".xlsx"}
MIN_BYTES = 8_000          # imágenes más chicas suelen ser íconos / líneas / logos
MIN_SIDE = 120             # px
MAX_IMGS_DOC = 25
MAX_PER_DAY = 150
MAX_SIDE_SEND = 1280

_lock = threading.Lock()
_busy: set = set()
_state = {"loaded": False, "data": {}, "dia": "", "n": 0}

PROMPT = ("Esta imagen está dentro de un documento. Descríbela en español en 1 o 2 frases pensadas para BUSCARLA después "
          "(qué se ve: personas, animales, objetos, lugar, colores; y si es foto, gráfica, diagrama, captura o dibujo). "
          "Si hay texto legible, cópialo literal (máx. 40 palabras). Si es solo un ícono, logo decorativo, línea, "
          "fondo o adorno sin contenido, responde exactamente: DECORATIVA")


def _path() -> Path:
    try:
        from paths import APP_DIR
        return Path(APP_DIR) / "orbi_imagenes_docs.json"
    except Exception:                                      # noqa: BLE001
        return Path(__file__).parent / "orbi_imagenes_docs.json"


def _load() -> dict:
    if not _state["loaded"]:
        _state["loaded"] = True
        try:
            raw = json.loads(_path().read_text(encoding="utf-8"))
            _state["data"] = raw.get("docs", {})
            if raw.get("dia") == date.today().isoformat():
                _state["dia"], _state["n"] = raw["dia"], int(raw.get("n", 0))
        except Exception:                                  # noqa: BLE001
            _state["data"] = {}
    return _state["data"]


def _save() -> None:
    try:
        tmp = _path().with_suffix(".tmp")
        tmp.write_text(json.dumps({"docs": _state["data"], "dia": _state["dia"], "n": _state["n"]}, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, _path())
    except OSError:
        pass


# ------------------------------------------------------------------ extracción
def _jpeg(raw: bytes):
    """bytes de imagen -> JPEG reducido, o None si es chica / no se puede abrir (EMF/WMF, etc.)."""
    if len(raw) < MIN_BYTES:
        return None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        if min(im.size) < MIN_SIDE:
            return None
        im = im.convert("RGB")
        s = min(1.0, MAX_SIDE_SEND / max(im.size))
        if s < 1.0:
            im = im.resize((round(im.width * s), round(im.height * s)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return buf.getvalue()
    except Exception:                                      # noqa: BLE001
        return None


def _zip_media(path: Path, prefix: str, where_fn=None):
    out = []
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if n.startswith(prefix) and not n.endswith("/"))
        slide_of = where_fn(z) if where_fn else {}
        for n in names:
            out.append((slide_of.get(n, "en el documento"), lambda n=n: z.read(n), n))
        return [(w, rd(), n) for w, rd, n in out]


def _pptx_slides(z) -> dict:
    """media -> «diapositiva N» leyendo los .rels de cada diapositiva."""
    m = {}
    for n in z.namelist():
        mm = re.match(r"ppt/slides/_rels/slide(\d+)\.xml\.rels$", n)
        if mm:
            for tgt in re.findall(r'Target="\.\./media/([^"]+)"', z.read(n).decode("utf-8", "replace")):
                m.setdefault("ppt/media/" + tgt, f"diapositiva {int(mm.group(1))}")
    return m


def raw_images(path: Path) -> list:
    """[(dónde, bytes, nombre)] de las imágenes embebidas, sin filtrar."""
    ext = path.suffix.lower()
    if ext == ".docx":
        return _zip_media(path, "word/media/")
    if ext == ".pptx":
        return _zip_media(path, "ppt/media/", _pptx_slides)
    if ext == ".xlsx":
        return _zip_media(path, "xl/media/")
    if ext == ".pdf":
        from pypdf import PdfReader
        out = []
        for i, page in enumerate(PdfReader(str(path)).pages, 1):
            if i > 300:
                break
            try:
                for im in page.images:
                    out.append((f"página {i}", im.data, im.name))
            except Exception:                              # noqa: BLE001
                continue
        return out
    return []


def count_images(path: Path) -> int:
    try:
        return len([1 for _w, raw, _n in raw_images(path) if len(raw) >= MIN_BYTES])
    except Exception:                                      # noqa: BLE001
        return 0


# ------------------------------------------------------------------ indexado en segundo plano
def _work(path: Path, describe, mt: float) -> None:
    key = str(path)
    items = []
    try:
        imgs = raw_images(path)
        n_total = 0
        for where, raw, _name in imgs:
            jpg = _jpeg(raw)
            if jpg is None:
                continue
            n_total += 1
            if len(items) >= MAX_IMGS_DOC:
                continue
            with _lock:
                hoy = date.today().isoformat()
                if _state["dia"] != hoy:
                    _state["dia"], _state["n"] = hoy, 0
                if _state["n"] >= MAX_PER_DAY:
                    break
                _state["n"] += 1
            try:
                d = (describe(jpg) or "").strip()
            except Exception:                              # noqa: BLE001
                d = ""
            if d and d.upper().rstrip(".") != "DECORATIVA":
                items.append(dict(where=where, desc=d[:400]))
        with _lock:
            _load()[key] = dict(mt=mt, n=n_total, items=items, t=time.time())
            _save()
    except Exception as e:                                 # noqa: BLE001
        print(f"[imágenes] {path.name}: {type(e).__name__}: {str(e)[:100]}")
    finally:
        with _lock:
            _busy.discard(key)


def on_read(path, describe) -> dict:
    """Se llama cuando Orbi lee o abre un documento. Devuelve info para el modelo ({} si no hay imágenes o no aplica)."""
    p = Path(path)
    if p.suffix.lower() not in DOC_EXTS or describe is None:
        return {}
    try:
        mt = p.stat().st_mtime
    except OSError:
        return {}
    key = str(p)
    with _lock:
        rec = _load().get(key)
        if rec and abs(rec.get("mt", 0) - mt) < 1:
            n = rec.get("n", 0)
            return ({"imagenes_en_documento": n, "imagenes_indexadas": True} if n else {})
        if key in _busy:
            return {"imagenes_en_documento": "hay (describiéndolas ahora)", "imagenes_indexadas": False}
    n = count_images(p)
    if n == 0:
        with _lock:
            _load()[key] = dict(mt=mt, n=0, items=[], t=time.time())
            _save()
        return {}
    with _lock:
        _busy.add(key)
    threading.Thread(target=_work, args=(p, describe, mt), daemon=True).start()
    return {"imagenes_en_documento": n, "imagenes_indexadas": False,
            "nota_imagenes": (f"El documento tiene {n} imágenes (no las veo al leer el texto). Las estoy describiendo en segundo "
                              "plano; en un rato `buscar_en_imagenes` podrá encontrar este documento por lo que se ve en ellas.")}


# ------------------------------------------------------------------ búsqueda
def _fold(t: str) -> str:
    try:
        import docs_reader as DR
        return DR.fold(str(t).lower())
    except Exception:                                      # noqa: BLE001
        return str(t).lower()


def _toks(q: str) -> set:
    return {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in re.findall(r"[a-z0-9ñ]+", _fold(q)) if len(w) > 2}


def search(query: str, limit: int = 6) -> tuple:
    """-> (resultados, cuántos documentos hay indexados). resultados = [(ruta, dónde, descripción)] mejores primero."""
    qt = _toks(query)
    with _lock:
        data = dict(_load())
    hits = []
    for path, rec in data.items():
        if not Path(path).exists():
            continue
        for it in rec.get("items", []):
            dt = _toks(it["desc"])
            sc = len(qt & dt) / max(1, len(qt))
            if sc > 0:
                hits.append((sc, rec.get("t", 0), path, it["where"], it["desc"]))
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    return [(p, w, d) for _s, _t, p, w, d in hits[:limit] if _s >= 0.34], len([1 for r in data.values() if r.get("items")])
