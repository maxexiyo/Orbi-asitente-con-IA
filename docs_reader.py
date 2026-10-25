"""Leer y buscar archivos SIN abrirlos (como hace Claude Code), solo en tus carpetas de usuario.

  extract(path)            -> (texto, tipo)   docx, pptx, xlsx, pdf y casi cualquier archivo de texto/código
  search_name(q)           -> archivos cuyo nombre contiene todas las palabras de q (los más recientes primero)
  search_content(q)        -> archivos cuyo CONTENIDO contiene q, con un fragmento
  find_open_document(title)-> el archivo que corresponde al título de la ventana activa (Word, Chrome, VS Code...)

docx/pptx se leen con zipfile (sin dependencias). xlsx necesita openpyxl y pdf necesita pypdf (opcionales).
"""
import html, os, re, time, zipfile
from datetime import datetime
from pathlib import Path

TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".log", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css",
            ".sql", ".php", ".kt", ".java", ".c", ".cpp", ".h", ".cs", ".ino", ".xml", ".yaml", ".yml", ".ini",
            ".cfg", ".toml", ".env.example", ".bat", ".sh", ".ps1", ".vbs", ".gradle", ".properties", ".srt", ".tex"}
CODE_EXT = TEXT_EXT - {".txt", ".md", ".csv", ".tsv", ".log", ".srt", ".tex"}
DOC_EXT = {".docx", ".pptx", ".xlsx", ".pdf"} | TEXT_EXT
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "AppData", ".venv", "venv", "site-packages", ".gradle", "build"}
MAX_CHARS = 900_000          # tope de texto que se extrae de un archivo
MAX_BYTES = 40_000_000       # no se lee nada más grande que esto


class ReadError(Exception):
    pass


# ------------------------------------------------------------------ carpetas permitidas
EXTERNAL_DRIVES = True       # incluir USB, discos externos y otras unidades (live_orb lo lee de config.json -> "unidades_externas")


def external_drives() -> list:
    """Raíces de unidades que NO son la del sistema: USB / discos externos (tipo 2) y discos fijos extra (tipo 3).
    Solo las que están conectadas en este momento. Sin CD/DVD ni unidades de red."""
    if os.name != "nt":
        return []
    try:
        import ctypes
        k = ctypes.windll.kernel32
        mask = k.GetLogicalDrives()
        sysdrive = (os.environ.get("SystemDrive") or "C:").upper()[:2]
        out = []
        for i in range(26):
            if not mask & (1 << i):
                continue
            letter = f"{chr(65 + i)}:"
            if letter == sysdrive:
                continue
            if k.GetDriveTypeW(letter + "\\") not in (2, 3):
                continue
            p = Path(letter + "\\")
            try:
                if p.is_dir():
                    out.append(p)
            except OSError:
                pass
        return out
    except Exception:                                      # noqa: BLE001
        return []


def file_roots() -> list:
    """Documentos, Escritorio, Descargas, Imágenes (incluye «Capturas de pantalla»), Videos y Música, y sus versiones en
    OneDrive / en español. Las de documentos van primero para que las búsquedas las revisen antes que las fotos."""
    home = Path.home()
    bases = [home, home / "OneDrive"]
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):      # OneDrive con otro nombre («OneDrive - Personal»…)
        v = os.environ.get(var)
        if v:
            bases.append(Path(v))
    try:
        bases += [d for d in home.iterdir() if d.is_dir() and d.name.lower().startswith("onedrive")]
    except OSError:
        pass
    roots = []
    for name in ("Desktop", "Documents", "Downloads", "Escritorio", "Documentos", "Descargas",
                 "Pictures", "Imágenes", "Imagenes", "Videos", "Vídeos", "Music", "Música", "Musica"):
        for base in bases:
            p = base / name
            try:
                if p.is_dir() and p.resolve() not in roots:
                    roots.append(p.resolve())
            except OSError:
                pass
    if EXTERNAL_DRIVES:                                    # al final: las búsquedas revisan primero tus carpetas de siempre
        for d in external_drives():
            try:
                if d.resolve() not in roots:
                    roots.append(d.resolve())
            except OSError:
                pass
    return roots


def inside_roots(path: Path) -> bool:
    try:
        rp = path.resolve()
    except Exception:
        return False
    for root in file_roots():
        try:
            rp.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def walk_files(roots=None, max_depth=5, max_scan=80_000):
    roots = roots or file_roots()
    scanned = 0
    for root in roots:
        base_depth = len(root.parts)
        for dirpath, dirnames, files in os.walk(root):
            if len(Path(dirpath).parts) - base_depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith((".", "$")) and d != "System Volume Information"]
            for f in files:
                scanned += 1
                if scanned > max_scan:
                    return
                yield Path(dirpath) / f


# ------------------------------------------------------------------ extracción
def _xml_text(xml: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    out, n = [], 0
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        para = re.sub(r"<w:tab\s*/>", "\t", para)
        para = re.sub(r"<w:br[^>]*/>", "\n", para)
        txt = "".join(html.unescape(t) for t in re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, flags=re.S)) \
            if "<w:t" in para else ""
        txt = txt.strip()
        if not txt:
            continue
        n += 1
        style = re.search(r'<w:pStyle w:val="([^"]+)"', para)
        head = bool(style and re.match(r"(?i)(heading|t[ií]tulo|title)", style.group(1)))
        out.append(f"[¶{n}] {'# ' if head else ''}{txt}")
    return "\n".join(out)


def _pptx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[-1]))
        out = []
        for i, n in enumerate(names, 1):
            xml = z.read(n).decode("utf-8", "replace")
            texts = [html.unescape(t) for t in re.findall(r"<a:t>(.*?)</a:t>", xml, flags=re.S)]
            out.append(f"--- diapositiva {i} ---\n" + "\n".join(t for t in texts if t.strip()))
    return "\n".join(out)


def _xlsx(path: Path) -> str:
    try:
        import openpyxl
    except ImportError:
        raise ReadError("Para leer Excel instala openpyxl:  pip install openpyxl")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"--- hoja {ws.title} ---")
        for r, row in enumerate(ws.iter_rows(values_only=True), 1):
            if r > 5000:
                out.append("(… más filas omitidas)")
                break
            cells = ["" if c is None else str(c) for c in row]
            if any(cells):
                out.append(" | ".join(cells).rstrip(" |"))
    return "\n".join(out)


def _pdf(path: Path, limit: int = MAX_CHARS) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ReadError("Para leer PDF instala pypdf:  pip install pypdf")
    rd = PdfReader(str(path))
    out = []
    for i, page in enumerate(rd.pages, 1):
        out.append(f"--- página {i} ---\n" + (page.extract_text() or ""))
        if sum(len(x) for x in out) > limit:
            break
    text = "\n".join(out)
    if len(text.strip()) < 40:
        raise ReadError("Este PDF parece escaneado (sin texto seleccionable); no puedo leerlo sin OCR.")
    return text


def _plain(path: Path) -> str:
    raw = path.read_bytes()[:MAX_BYTES]
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if path.suffix.lower() in CODE_EXT:
        text = "\n".join(f"{i}: {l}" for i, l in enumerate(text.splitlines(), 1))
    return text


def extract(path, limit: int = None) -> tuple:
    """(texto, tipo). Lanza ReadError con un mensaje claro si no se puede."""
    p = Path(path)
    if not p.is_file():
        raise ReadError("Ese archivo no existe.")
    if p.stat().st_size > MAX_BYTES:
        raise ReadError("Archivo demasiado grande (más de 40 MB).")
    ext = p.suffix.lower()
    try:
        if ext == ".docx":
            text, kind = _docx(p), "Word"
        elif ext == ".pptx":
            text, kind = _pptx(p), "PowerPoint"
        elif ext == ".xlsx":
            text, kind = _xlsx(p), "Excel"
        elif ext == ".pdf":
            text, kind = _pdf(p, limit or MAX_CHARS), "PDF"
        elif ext in TEXT_EXT or ext == "":
            text, kind = _plain(p), "texto"
        else:
            raise ReadError(f"No sé leer archivos {ext or 'sin extensión'}.")
    except ReadError:
        raise
    except zipfile.BadZipFile:
        raise ReadError("El archivo está dañado o protegido con contraseña.")
    except Exception as e:                                 # noqa: BLE001
        raise ReadError(f"No pude leerlo: {type(e).__name__}: {e}")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[… recortado]"
    return text, kind


def chunk(text: str, desde: int = 0, size: int = 6000) -> dict:
    """Trozo de `size` caracteres desde la posición `desde` (corta en salto de línea)."""
    desde = max(0, int(desde or 0))
    end = min(len(text), desde + size)
    if end < len(text):
        nl = text.rfind("\n", desde, end)
        if nl > desde + size // 2:
            end = nl + 1
    d = dict(texto=text[desde:end], desde=desde, hasta=end, total=len(text))
    if end < len(text):
        d["siguiente_desde"] = end
    return d


# ------------------------------------------------------------------ búsqueda
def _tokens(q: str) -> list:
    return [t for t in re.split(r"\W+", q.lower()) if t]


def search_name(query: str, limit: int = 8, roots=None) -> list:
    toks = _tokens(query)
    if not toks:
        return []
    hits = []
    for f in walk_files(roots):
        name = f.name.lower()
        if all(t in name for t in toks):
            try:
                hits.append((f.stem.lower() == " ".join(toks) or name == query.lower().strip(), f.stat().st_mtime, f))
            except OSError:
                pass
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    return [h[2] for h in hits[:limit]]


ROOT_ALIASES = {"escritorio": "desktop", "desktop": "desktop", "documentos": "documents", "documents": "documents",
                "descargas": "downloads", "downloads": "downloads",
                "imagenes": "pictures", "imágenes": "pictures", "pictures": "pictures", "fotos": "pictures",
                "videos": "videos", "vídeos": "videos", "musica": "music", "música": "music", "music": "music"}


def resolve_dir(ref: str, limit: int = 6) -> tuple:
    """Carpeta dentro de las permitidas a partir de una ruta o un nombre. -> (Path|None, candidatos).
    Acepta «Descargas», «escritorio», «CETI», «Documentos/CETI/sprint 3» o una ruta completa."""
    ref = (ref or "").strip().strip('"')
    if not ref:
        return None, []
    p = Path(ref)
    if p.is_dir():
        return (p, []) if inside_roots(p) else (None, [])
    roots = file_roots()
    parts = [x for x in re.split(r"[\\/]+", ref) if x]
    # ruta relativa a una carpeta raíz: «Documentos/CETI»
    first = ROOT_ALIASES.get(parts[0].lower(), parts[0].lower()) if parts else ""
    for root in roots:
        if root.name.lower() in (first, parts[0].lower() if parts else ""):
            cand = root.joinpath(*parts[1:]) if len(parts) > 1 else root
            if cand.is_dir() and inside_roots(cand):
                return cand, []
    # por nombre (todas las palabras dentro del nombre de la carpeta)
    toks = _tokens(ref)
    found = []
    for root in roots:
        base_depth = len(root.parts)
        for dirpath, dirnames, _files in os.walk(root):
            if len(Path(dirpath).parts) - base_depth >= 5:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for d in dirnames:
                low = d.lower()
                if toks and all(t in low for t in toks):
                    q = Path(dirpath) / d
                    try:
                        found.append((low == ref.lower(), q.stat().st_mtime, q))
                    except OSError:
                        pass
    found.sort(key=lambda h: (h[0], h[1]), reverse=True)
    cands = [h[2] for h in found[:limit]]
    exact = [h[2] for h in found if h[0]]
    if len(cands) == 1 or len(exact) == 1:
        return (exact or cands)[0], cands
    return None, cands


def list_dir(path: Path, limit: int = 40) -> dict:
    """Contenido de una carpeta (carpetas primero). Solo nombres, tipos y fechas: no abre ni lee nada."""
    items = []
    try:
        for e in path.iterdir():
            if e.name.startswith(".") or e.name in SKIP_DIRS:
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            items.append((e.is_file(), e.name.lower(), e, st))
    except OSError as ex:
        return {"error": f"No pude leer la carpeta: {ex}"}
    items.sort(key=lambda t: (t[0], t[1]))
    out = []
    for is_file, _n, e, st in items[:limit]:
        kb = f", {max(1, st.st_size // 1024)} KB" if is_file else ""
        out.append(f"{'📄' if is_file else '📁'} {e.name}  ({datetime.fromtimestamp(st.st_mtime):%d/%m/%Y}{kb})")
    res = {"carpeta": str(path), "contenido": out or "(vacía)"}
    if len(items) > limit:
        res["nota"] = f"Hay {len(items) - limit} elementos más; pide una subcarpeta o busca por nombre."
    return res


# --- búsqueda por contenido: índice que se va llenando (sobrevive entre búsquedas y reinicios) ------------------------------
import gzip, json, math, unicodedata

INDEX_CHARS = 20_000          # cuánto texto de cada archivo se guarda en el índice (el inicio: título, índice, primeras páginas)
INDEX_MAX = 2_000             # archivos máximos en el índice (se tiran los más viejos)
STOPWORDS = {"de", "la", "el", "en", "y", "a", "los", "las", "un", "una", "que", "del", "se", "por", "con", "para", "al", "lo",
             "su", "es", "mi", "como", "mas", "o", "pero", "sus", "le", "ya", "este", "esta", "ese", "esa", "unos", "unas", "sobre",
             "archivo", "documento", "word", "pdf", "donde", "dice", "tiene", "habla", "hay", "tengo", "mis", "me", "te"}
LAST_INFO = {}                # resumen de la última búsqueda (completa o no, qué faltó) para que Orbi se lo diga al dueño


# --- SEGURIDAD: archivos con secretos NUNCA entran al índice (ni se buscan por contenido) ----------------------------------------
_NOMBRE_SENSIBLE = re.compile(r"(token|secret|credential|credencial|password|passwd|contrase|claves\b|\.env|keystore|_keys?\b|apikey|api_key|private|"
                              r"id_rsa|\.pem$|\.key$|\.pfx$|\.p12$|\.kdbx$|wallet|seed|config\.json$|orbi_.*\.json$|\.log$)", re.I)
_DIR_SENSIBLE = {".ssh", ".aws", ".gnupg", ".kube", "AppData"}
_CONTENIDO_SECRETO = re.compile(r"(AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|xox[bpa]-[A-Za-z0-9-]{10,}|"
                                r"refresh_token|client_secret|-----BEGIN [A-Z ]*PRIVATE KEY|\"private_key\"|aws_secret_access_key)", re.I)


def es_sensible(path) -> bool:
    """¿Es un archivo con claves, tokens, contraseñas o datos internos de Orbi? Esos no se leen para el índice."""
    p = Path(path)
    return bool(_NOMBRE_SENSIBLE.search(p.name)) or any(part in _DIR_SENSIBLE for part in p.parts)


class _Fold(dict):
    """Minúsculas y sin acentos, un carácter por carácter (así las posiciones coinciden con el texto original)."""
    def __missing__(self, k):
        v = ord(unicodedata.normalize("NFD", chr(k).lower())[0])
        self[k] = v
        return v


_FOLD = _Fold()


def fold(t: str) -> str:
    return t.translate(_FOLD)


def _stem(t: str) -> str:
    if len(t) > 5 and t.endswith("es"):
        return t[:-2]
    if len(t) > 4 and t.endswith("s"):
        return t[:-1]
    return t


def _query_tokens(q: str) -> list:
    out = []
    for t in re.split(r"\W+", fold(q)):
        if t and t not in STOPWORDS and (len(t) > 1 or t.isdigit()):
            st = _stem(t)
            if st not in out:
                out.append(st)
    return out


_idx = {"loaded": False, "data": {}, "dirty": False}


def _index_path() -> Path:
    try:
        from paths import APP_DIR
        base = Path(APP_DIR)
    except Exception:                                      # noqa: BLE001
        base = Path(__file__).parent
    try:
        (base / "orbi_indice_docs.json.gz").unlink()       # índice viejo (v1): pudo guardar texto de archivos con secretos
    except OSError:
        pass
    return base / "orbi_indice_docs_v2.json.gz"


def _index_load() -> dict:
    if not _idx["loaded"]:
        _idx["loaded"] = True
        try:
            with gzip.open(_index_path(), "rt", encoding="utf-8") as fh:
                _idx["data"] = json.load(fh)
        except Exception:                                  # noqa: BLE001
            _idx["data"] = {}
    return _idx["data"]


def _index_save():
    if not _idx["dirty"]:
        return
    d = _idx["data"]
    if len(d) > INDEX_MAX:
        for k, _v in sorted(d.items(), key=lambda kv: kv[1][0])[: len(d) - INDEX_MAX]:
            d.pop(k, None)
    try:
        tmp = _index_path().with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False)
        tmp.replace(_index_path())
        _idx["dirty"] = False
    except Exception:                                      # noqa: BLE001
        pass


def index_clear():
    _idx.update(loaded=True, data={}, dirty=True)
    _index_save()


def _content_exts() -> tuple:
    exts, faltan = set(TEXT_EXT) | {".docx", ".pptx"}, []
    for mod, ext, pipname in (("pypdf", ".pdf", "pypdf"), ("openpyxl", ".xlsx", "openpyxl")):
        try:
            __import__(mod)
            exts.add(ext)
        except ImportError:
            faltan.append(pipname)
    return exts, faltan


def search_content(query: str, limit: int = 6, budget_s: float = 15.0, roots=None) -> list:
    """[(ruta, fragmento)] de los archivos cuyo CONTENIDO se parece más a `query` (Word, PowerPoint, PDF, Excel, texto, código).

    - No hace falta acordarse de las palabras exactas: puntúa cuántas de las palabras (sin acentos ni plurales) aparecen,
      más el nombre del archivo, y devuelve los mejores. Pide al menos el 60 % de las palabras.
    - Revisa primero lo MÁS RECIENTE y guarda lo leído en un índice: si no alcanza el tiempo, la siguiente búsqueda sigue donde
      se quedó (y las repetidas son casi instantáneas).
    Deja en LAST_INFO: completo (revisó todo), revisados, pendientes, faltan (librerías), escaneados (PDF sin texto).
    """
    toks = _query_tokens(query)
    LAST_INFO.clear()
    if not toks:
        return []
    exts, faltan = _content_exts()
    data = _index_load()
    cand = []
    for f in walk_files(roots):
        if f.suffix.lower() in exts and not es_sensible(f):
            try:
                st = f.stat()
            except OSError:
                continue
            if st.st_size <= (30_000_000 if f.suffix.lower() == ".pdf" else 8_000_000):
                cand.append((st.st_mtime, st.st_size, f))
    cand.sort(key=lambda c: c[0], reverse=True)
    t0, hits, pendientes, escaneados, revisados = time.time(), [], 0, 0, 0
    need = max(1, math.ceil(0.6 * len(toks)))
    for mtime, size, f in cand:
        key = str(f)
        ent = data.get(key)
        if not ent or ent[0] != mtime or ent[1] != size:                 # no está indexado (o cambió): léelo ahora
            if time.time() - t0 > budget_s:
                pendientes += 1
                continue
            try:
                text, _ = extract(f, limit=INDEX_CHARS * 2)
                ent = [mtime, size, "" if _CONTENIDO_SECRETO.search(text[:INDEX_CHARS * 2]) else fold(text[:INDEX_CHARS]), 0]
            except ReadError as e:
                ent = [mtime, size, "", 1 if "escaneado" in str(e) else 0]
            except Exception:                                            # noqa: BLE001
                ent = [mtime, size, "", 0]
            data[key] = ent
            _idx["dirty"] = True
        revisados += 1
        if ent[3]:
            escaneados += 1
        name = fold(f.stem)
        body = ent[2]
        got = [t for t in toks if t in body or t in name]
        if len(got) >= need:
            score = len(got) / len(toks) + 0.3 * sum(1 for t in toks if t in name) / len(toks)
            hits.append((score, mtime, f, got, body))
    _index_save()
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)
    out = []
    for score, _m, f, got, body in hits[:limit]:
        frag = ""
        try:                                                             # fragmento con el texto original (con acentos y mayúsculas)
            text, _ = extract(f, limit=INDEX_CHARS * 2)
            pos = [body.find(t) for t in got if body.find(t) >= 0]
            i = min(pos) if pos else 0
            frag = " ".join(text[max(0, i - 80): i + 200].split())
        except Exception:                                                # noqa: BLE001
            pass
        out.append((f, f"[{len(got)}/{len(toks)} palabras] " + frag))
    LAST_INFO.update(completo=pendientes == 0, revisados=revisados, pendientes=pendientes, faltan=faltan, escaneados=escaneados)
    return out


# ------------------------------------------------------------------ documento abierto
APP_SUFFIXES = ("microsoft word", "word", "microsoft excel", "excel", "microsoft powerpoint", "powerpoint",
                "google chrome", "microsoft edge", "mozilla firefox", "firefox", "brave", "visual studio code",
                "notepad", "bloc de notas", "notepad++", "adobe acrobat", "acrobat reader", "adobe acrobat reader",
                "libreoffice writer", "libreoffice calc", "wps writer", "sumatrapdf", "foxit reader", "obsidian",
                "windows photo viewer", "cursor", "pycharm", "sublime text", "documentos", "modo de compatibilidad")


def title_candidates(title: str) -> list:
    """Posibles nombres de archivo a partir del título de la ventana."""
    t = re.sub(r"^[\*\u25cf\u2022\s]+", "", title or "").strip()
    parts = [p.strip() for p in re.split(r"\s[-\u2013\u2014|]\s", t) if p.strip()]
    cands = []
    for p in parts:
        p = re.sub(r"\[(?:modo de compatibilidad|solo lectura|read-only|compatibility mode)\]", "", p, flags=re.I)
        p = re.sub(r"\s*(?:\*|\u25cf)$", "", p).strip(" .")
        if p and p.lower() not in APP_SUFFIXES:
            cands.append(p)
    return cands


def find_open_document(title: str):
    """Ruta del archivo que corresponde al título de la ventana, o None (documento sin guardar, página web, etc.)."""
    cands = title_candidates(title)
    if not cands:
        return None
    files = list(walk_files())
    best = None
    for cand in cands:
        low = cand.lower()
        for f in files:
            if f.suffix.lower() not in DOC_EXT:
                continue
            if f.name.lower() == low or f.stem.lower() == low:
                try:
                    m = f.stat().st_mtime
                except OSError:
                    continue
                if best is None or m > best[0]:
                    best = (m, f)
        if best:
            break
    return best[1] if best else None
