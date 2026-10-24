"""Operaciones de archivos SIN pantalla (como leer_archivo, pero para organizar y escribir).

  crear_carpeta · mover · copiar · renombrar · escribir_texto_archivo · escribir_docx · organizar · deshacer

Reglas de seguridad (a propósito):
  - Solo dentro de Documentos, Escritorio y Descargas (y sus subcarpetas). Nunca las carpetas raíz mismas.
  - NUNCA borra y NUNCA sobrescribe: si el nombre ya existe, el nuevo lleva « (2)», « (3)»...
  - Nada de crear archivos ejecutables/scripts (mismos BLOCKED_EXT de pc_tools).
  - Cada movimiento queda en `organizacion_log.json` (junto a Orbi) para poder DESHACERLO.
  - Archivos abiertos en otro programa (Word, etc.) se saltan y se reportan: Windows no deja moverlos.

El .docx se escribe con zipfile (sin python-docx), así que también funciona en el .exe.
"""
import json, os, re, shutil, time, zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import docs_reader as DR
from paths import APP_DIR

LOG_PATH = APP_DIR / "organizacion_log.json"
LOG_MAX_BATCHES = 30
BLOCKED_EXT = {".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".ps1", ".vbs", ".vbe", ".js", ".jse",
               ".wsf", ".lnk", ".jar", ".reg", ".dll", ".py", ".pyw", ".hta", ".cpl", ".sh", ".apk"}
SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}
RECIENTE_S = 20          # un archivo tocado hace menos de esto probablemente se está escribiendo: se salta al organizar

# categoría -> extensiones (carpetas que crea `organizar` con criterio «tipo»)
TIPOS = {
    "Documentos": {".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pdf", ".tex"},
    "Hojas de cálculo": {".xls", ".xlsx", ".csv", ".ods", ".tsv"},
    "Presentaciones": {".ppt", ".pptx", ".odp", ".key"},
    "Imágenes": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".heic", ".ico", ".tiff"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv"},
    "Música": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Comprimidos": {".zip", ".rar", ".7z", ".tar", ".gz", ".iso"},
    "Programas": {".exe", ".msi", ".apk", ".dmg"},
    "Código": {".py", ".js", ".ts", ".html", ".css", ".php", ".java", ".kt", ".c", ".cpp", ".cs", ".ino", ".json",
               ".xml", ".sql", ".sh", ".bat", ".yml", ".yaml"},
}
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]


class OpError(Exception):
    """Mensaje claro para el dueño (se devuelve tal cual como error de la tool)."""


# --------------------------------------------------------------------------- rutas
def _permitida(p: Path) -> bool:
    """Dentro de las carpetas permitidas y que no sea una carpeta raíz."""
    if not DR.inside_roots(p):
        return False
    try:
        return p.resolve() not in DR.file_roots()
    except OSError:
        return False


def _limpio(nombre: str) -> str:
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(nombre or "")).strip().strip(".")
    return re.sub(r"\s{2,}", " ", n)[:120]


def _libre(p: Path) -> Path:
    """Si `p` existe, devuelve «nombre (2).ext», «nombre (3).ext»... Nunca pisa nada."""
    if not p.exists():
        return p
    for i in range(2, 500):
        q = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not q.exists():
            return q
    raise OpError("Hay demasiados archivos con ese nombre.")


def carpeta_destino(ref: str, crear: bool = False) -> Path:
    """Carpeta permitida a partir de «Documentos/CETI/Prácticas», «Descargas» o una ruta. Con crear=True la crea."""
    ref = (ref or "").strip().strip('"')
    if not ref:
        raise OpError("Dime la carpeta.")
    d, cands = DR.resolve_dir(ref)
    if d is not None:
        return d
    if cands and not crear:
        raise OpError("Hay varias carpetas con ese nombre; dime cuál: " + "; ".join(str(c) for c in cands[:5]))
    parts = [x for x in re.split(r"[\\/]+", ref) if x]
    roots = DR.file_roots()
    if Path(ref).is_absolute():
        cand = Path(ref)
    else:
        first = DR.ROOT_ALIASES.get(parts[0].lower(), parts[0].lower()) if parts else ""
        base = next((r for r in roots if r.name.lower() in (first, parts[0].lower())), None)
        if base is None:                                   # sin raíz explícita: cuelga de Documentos
            base = next((r for r in roots if r.name.lower() in ("documents", "documentos")), roots[0] if roots else None)
            sub = parts
        else:
            sub = parts[1:]
        if base is None:
            raise OpError("No encontré Documentos, Escritorio, Descargas, Imágenes, Videos ni Música en esta PC.")
        cand = base.joinpath(*[_limpio(x) for x in sub]) if sub else base
    if not crear:
        raise OpError(f"No encontré la carpeta «{ref}» dentro de Documentos, Escritorio, Descargas, Imágenes, Videos, Música o una unidad externa conectada.")
    if not DR.inside_roots(cand):
        raise OpError("Solo puedo crear carpetas dentro de Documentos, Escritorio, Descargas, Imágenes, Videos, Música o una unidad externa conectada.")
    cand.mkdir(parents=True, exist_ok=True)
    return cand


def resolver_archivo(ref: str) -> Path:
    """Archivo (o carpeta) permitido a partir de una ruta o solo el nombre."""
    ref = (ref or "").strip().strip('"')
    if not ref:
        raise OpError("Dime qué archivo.")
    p = Path(ref)
    if p.exists():
        if not _permitida(p):
            raise OpError("Solo toco archivos dentro de Documentos, Escritorio, Descargas, Imágenes, Videos, Música o una unidad externa conectada.")
        return p
    found = DR.search_name(ref, limit=6)
    exact = [f for f in found if f.name.lower() == ref.lower() or f.stem.lower() == ref.lower()]
    if len(found) == 1 or len(exact) == 1:
        return (exact or found)[0]
    if found:
        raise OpError("Hay varios archivos con ese nombre; dime cuál: " + "; ".join(str(f) for f in found[:5]))
    d, cands = DR.resolve_dir(ref)
    if d is not None and _permitida(d):
        return d
    raise OpError(f"No encontré «{ref}» en Documentos, Escritorio o Descargas.")


# --------------------------------------------------------------------------- registro para deshacer
def _log_load() -> list:
    try:
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except Exception:                                      # noqa: BLE001
        return []


def _log_batch(titulo: str, movs: list) -> None:
    """movs: [(origen, destino)]. Se guarda para deshacer."""
    if not movs:
        return
    data = _log_load()
    data.append({"cuando": datetime.now().isoformat(timespec="seconds"), "titulo": titulo[:100],
                 "movs": [[str(a), str(b)] for a, b in movs]})
    try:
        LOG_PATH.write_text(json.dumps(data[-LOG_MAX_BATCHES:], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def deshacer() -> dict:
    """Regresa el último lote de movimientos/renombres a donde estaban. No borra nada."""
    data = _log_load()
    if not data:
        return {"error": "No tengo ningún movimiento reciente que deshacer."}
    lote = data[-1]
    ok, fallos = 0, []
    for a, b in reversed(lote["movs"]):
        src, dst = Path(b), Path(a)
        try:
            if not src.exists():
                fallos.append(f"{src.name}: ya no está ahí")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(_libre(dst)))
            ok += 1
        except OSError as e:
            fallos.append(f"{src.name}: {str(e)[:60]}")
    data.pop()
    try:
        LOG_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    out = {"resultado": f"Deshice «{lote['titulo']}»: regresé {ok} archivo(s) a su lugar."}
    if fallos:
        out["no_se_pudo"] = fallos[:8]
    return out


# --------------------------------------------------------------------------- operaciones sueltas
def crear_carpeta(ref: str) -> dict:
    existia = False
    try:
        d, _c = DR.resolve_dir(ref)
        existia = d is not None
        d = carpeta_destino(ref, crear=True)
    except OpError as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"No pude crear la carpeta: {e}"}
    return {"resultado": (f"La carpeta ya existía: {d}" if existia else f"Carpeta creada: {d}")}


def mover(origen: str, destino: str, nuevo_nombre: str = "") -> dict:
    try:
        src = resolver_archivo(origen)
        if not _permitida(src):
            raise OpError("Esa ruta no se puede mover.")
        d = carpeta_destino(destino, crear=True)
        nombre = _limpio(nuevo_nombre) or src.name
        if nuevo_nombre and src.is_file() and not Path(nombre).suffix:
            nombre += src.suffix
        dst = _libre(d / nombre)
        if src.is_dir():
            try:
                dst.resolve().relative_to(src.resolve())
                raise OpError("No puedo meter una carpeta dentro de sí misma.")
            except ValueError:
                pass
        shutil.move(str(src), str(dst))
    except OpError as e:
        return {"error": str(e)}
    except PermissionError:
        return {"error": f"«{Path(origen).name}» está abierto en otro programa; ciérralo y lo muevo."}
    except OSError as e:
        return {"error": f"No pude moverlo: {e}"}
    _log_batch(f"mover {src.name}", [(src, dst)])
    return {"resultado": f"Moví «{src.name}» a {dst.parent}" + (f" como «{dst.name}»." if dst.name != src.name else ".")}


def copiar(origen: str, destino: str, nuevo_nombre: str = "") -> dict:
    try:
        src = resolver_archivo(origen)
        d = carpeta_destino(destino, crear=True)
        dst = _libre(d / (_limpio(nuevo_nombre) or src.name))
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    except OpError as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"No pude copiarlo: {e}"}
    return {"resultado": f"Copié «{src.name}» a {dst}."}


def renombrar(ref: str, nuevo_nombre: str) -> dict:
    try:
        src = resolver_archivo(ref)
        if not _permitida(src):
            raise OpError("Esa ruta no se puede renombrar.")
        nombre = _limpio(nuevo_nombre)
        if not nombre:
            raise OpError("Dime el nombre nuevo.")
        if src.is_file() and not Path(nombre).suffix:
            nombre += src.suffix                              # «reporte» -> «reporte.docx» (no pierde la extensión)
        dst = src.with_name(nombre)
        if dst.suffix.lower() in BLOCKED_EXT and dst.suffix.lower() != src.suffix.lower():
            raise OpError("Por seguridad no cambio un archivo a ese tipo de extensión.")
        dst = _libre(dst) if dst != src else dst
        src.rename(dst)
    except OpError as e:
        return {"error": str(e)}
    except PermissionError:
        return {"error": "Está abierto en otro programa; ciérralo y lo renombro."}
    except OSError as e:
        return {"error": f"No pude renombrarlo: {e}"}
    _log_batch(f"renombrar {src.name}", [(src, dst)])
    return {"resultado": f"Listo: «{src.name}» ahora se llama «{dst.name}»."}


# --------------------------------------------------------------------------- escribir archivos
def _destino_nuevo(ruta: str, ext_defecto: str) -> Path:
    """Ruta de un archivo NUEVO: acepta ruta completa, «Documentos/CETI/tarea.docx» o solo un nombre (va a Documentos)."""
    ruta = (ruta or "").strip().strip('"')
    if not ruta:
        raise OpError("Dime cómo se llama el archivo.")
    parts = [x for x in re.split(r"[\\/]+", ruta) if x]
    nombre = _limpio(parts[-1])
    if not nombre:
        raise OpError("Ese nombre de archivo no sirve.")
    if not Path(nombre).suffix:
        nombre += ext_defecto
    if Path(nombre).suffix.lower() in BLOCKED_EXT:
        raise OpError("Por seguridad no creo programas ni scripts (.exe, .bat, .py...).")
    if len(parts) == 1 and not Path(ruta).is_absolute():
        base = next((r for r in DR.file_roots() if r.name.lower() in ("documents", "documentos")), None)
        if base is None:
            raise OpError("No encontré tu carpeta Documentos.")
        return _libre(base / nombre)
    carpeta = carpeta_destino("/".join(parts[:-1]) if not Path(ruta).is_absolute() else str(Path(ruta).parent), crear=True)
    return _libre(carpeta / nombre)


def escribir_archivo(ruta: str, contenido: str, agregar: bool = False) -> dict:
    """Crea un archivo de texto (.txt, .md, .csv...). Con agregar=True añade al final de uno que ya existe."""
    contenido = str(contenido or "")
    if not contenido.strip():
        return {"error": "No hay nada que escribir."}
    try:
        if agregar:
            p = resolver_archivo(ruta)
            if p.is_dir() or p.suffix.lower() in BLOCKED_EXT or p.suffix.lower() in {".docx", ".pptx", ".xlsx", ".pdf"}:
                raise OpError("A ese tipo de archivo no le puedo agregar texto así.")
            with open(p, "a", encoding="utf-8") as f:
                f.write(("\n" if p.stat().st_size else "") + contenido)
            return {"resultado": f"Agregué {len(contenido)} caracteres al final de «{p.name}».", "ruta": str(p)}
        p = _destino_nuevo(ruta, ".txt")
        if p.suffix.lower() in {".docx", ".pptx", ".xlsx", ".pdf"}:
            raise OpError("Para Word usa redactar_documento.")
        p.write_text(contenido, encoding="utf-8")
    except OpError as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"No pude escribir el archivo: {e}"}
    return {"resultado": f"Guardé «{p.name}» en {p.parent} ({len(contenido)} caracteres).", "ruta": str(p)}


# --- .docx mínimo (títulos, listas, negritas) sin librerías ----------------------------------------------------------
_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {_NS}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="24"/><w:lang w:val="es-MX"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="320" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:color w:val="1F3864"/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:color w:val="2F5496"/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="60"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:color w:val="2F5496"/><w:sz w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="60"/><w:ind w:left="720" w:hanging="360"/></w:pPr></w:style>
</w:styles>"""
_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def _runs(texto: str) -> str:
    """**negrita** y *cursiva* -> runs de Word."""
    out = []
    for parte in re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)", texto):
        if not parte:
            continue
        rpr = ""
        if parte.startswith("**") and parte.endswith("**") and len(parte) > 4:
            parte, rpr = parte[2:-2], "<w:rPr><w:b/></w:rPr>"
        elif parte.startswith("*") and parte.endswith("*") and len(parte) > 2:
            parte, rpr = parte[1:-1], "<w:rPr><w:i/></w:rPr>"
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(parte)}</w:t></w:r>')
    return "".join(out)


def _parrafos_xml(contenido: str) -> str:
    """Markdown simple -> párrafos: # título, ## y ### encabezados, - o * viñetas, 1. numeradas, **negrita**, líneas en blanco."""
    xml, primero = [], True
    for raw in str(contenido).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        ln = raw.rstrip()
        if not ln.strip():
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", ln)
        if m:
            nivel = len(m.group(1))
            estilo = "Title" if (nivel == 1 and primero) else f"Heading{min(3, nivel)}"
            xml.append(f'<w:p><w:pPr><w:pStyle w:val="{estilo}"/></w:pPr>{_runs(m.group(2).strip())}</w:p>')
        elif re.match(r"^\s*[-*•]\s+", ln):
            t = re.sub(r"^\s*[-*•]\s+", "", ln)
            xml.append(f'<w:p><w:pPr><w:pStyle w:val="ListParagraph"/></w:pPr>{_runs("• " + t)}</w:p>')
        elif re.match(r"^\s*\d+[.)]\s+", ln):
            n, t = re.match(r"^\s*(\d+)[.)]\s+(.*)$", ln).groups()
            xml.append(f'<w:p><w:pPr><w:pStyle w:val="ListParagraph"/></w:pPr>{_runs(n + ". " + t)}</w:p>')
        else:
            xml.append(f'<w:p><w:pPr><w:jc w:val="both"/></w:pPr>{_runs(ln.strip())}</w:p>')
        primero = False
    return "".join(xml)


def _escribir_docx(path: Path, contenido: str) -> None:
    body = _parrafos_xml(contenido)
    sect = '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {_NS}><w:body>{body}{sect}</w:body></w:document>'
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
    os.replace(tmp, path)


def _agregar_docx(path: Path, contenido: str) -> None:
    """Agrega párrafos al final de un .docx existente (antes de sectPr). Falla con PermissionError si está abierto."""
    with zipfile.ZipFile(path) as z:
        items = {n: z.read(n) for n in z.namelist()}
    xml = items["word/document.xml"].decode("utf-8")
    nuevo = _parrafos_xml(contenido)
    i = xml.rfind("<w:sectPr")
    if i < 0:
        i = xml.rfind("</w:body>")
    if i < 0:
        raise OpError("No pude entender la estructura de ese .docx.")
    items["word/document.xml"] = (xml[:i] + nuevo + xml[i:]).encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in items.items():
            z.writestr(n, data)
    os.replace(tmp, path)


def escribir_docx(ruta: str, contenido: str, agregar: bool = False) -> dict:
    """Crea un Word NUEVO (o agrega al final de uno existente que no esté abierto). `contenido` en markdown simple."""
    if not str(contenido or "").strip():
        return {"error": "No hay contenido para el documento."}
    try:
        if agregar:
            p = resolver_archivo(ruta)
            if p.suffix.lower() != ".docx":
                raise OpError("Solo puedo agregar a archivos .docx.")
            _agregar_docx(p, contenido)
            return {"resultado": f"Agregué el texto al final de «{p.name}».", "ruta": str(p)}
        p = _destino_nuevo(ruta, ".docx")
        if p.suffix.lower() != ".docx":
            p = p.with_suffix(".docx")
        _escribir_docx(p, contenido)
    except OpError as e:
        return {"error": str(e)}
    except PermissionError:
        return {"error": "Ese documento está abierto en Word y no lo puedo modificar por detrás. Ciérralo, o dime y lo escribo "
                         "directo en la ventana abierta."}
    except (OSError, zipfile.BadZipFile, KeyError) as e:
        return {"error": f"No pude escribir el documento: {e}"}
    return {"resultado": f"Guardé «{p.name}» en {p.parent}.", "ruta": str(p)}


# --------------------------------------------------------------------------- organizar una carpeta
def _categoria(p: Path, criterio: str) -> str:
    if criterio == "fecha":
        t = datetime.fromtimestamp(p.stat().st_mtime)
        return f"{t.year}/{t.month:02d} {_MESES[t.month - 1].capitalize()}"
    if criterio == "inicial":
        c = p.stem[:1].upper()
        return c if c.isalpha() else "#"
    ext = p.suffix.lower()
    for cat, exts in TIPOS.items():
        if ext in exts:
            return cat
    return "Otros"


def plan_organizar(carpeta: str, criterio: str = "tipo", solo_tipos=None) -> tuple:
    """-> (carpeta, [(archivo, subcarpeta_destino)], [saltados]). Solo archivos sueltos de ese nivel (no entra a subcarpetas)."""
    d = carpeta_destino(carpeta)
    criterio = {"type": "tipo", "tipos": "tipo", "date": "fecha", "meses": "fecha", "letra": "inicial"}.get(
        (criterio or "tipo").lower(), (criterio or "tipo").lower())
    if criterio not in ("tipo", "fecha", "inicial"):
        raise OpError("Puedo organizar por «tipo», «fecha» o «inicial» del nombre.")
    filtro = {("." + e.lower().lstrip(".")) for e in (solo_tipos or []) if str(e).strip()}
    plan, saltados, ahora = [], [], time.time()
    try:
        entradas = sorted(d.iterdir(), key=lambda x: x.name.lower())
    except OSError as e:
        raise OpError(f"No pude leer la carpeta: {e}")
    for e in entradas:
        if not e.is_file() or e.name.startswith((".", "~$")) or e.name.lower() in SKIP_NAMES:
            continue
        if filtro and e.suffix.lower() not in filtro:
            continue
        try:
            if ahora - e.stat().st_mtime < RECIENTE_S:
                saltados.append(f"{e.name} (se modificó hace segundos)")
                continue
        except OSError:
            continue
        plan.append((e, _categoria(e, criterio)))
    return d, plan, saltados


def resumen_plan(plan: list) -> list:
    por = {}
    for f, cat in plan:
        por.setdefault(cat, []).append(f.name)
    return [f"{cat}: {len(n)} archivo(s) — ej. {', '.join(n[:3])}" for cat, n in sorted(por.items())]


def aplicar_plan(d: Path, plan: list, titulo: str) -> dict:
    hechos, fallos = [], []
    for f, cat in plan:
        try:
            dest_dir = d.joinpath(*cat.split("/"))
            dest_dir.mkdir(parents=True, exist_ok=True)
            dst = _libre(dest_dir / f.name)
            shutil.move(str(f), str(dst))
            hechos.append((f, dst))
        except PermissionError:
            fallos.append(f"{f.name}: está abierto en otro programa")
        except OSError as e:
            fallos.append(f"{f.name}: {str(e)[:60]}")
    _log_batch(titulo, hechos)
    out = {"resultado": f"Organicé {len(hechos)} archivo(s) en «{d.name}»" + (f"; {len(fallos)} no se pudieron mover." if fallos else ".")
           + " Si no te gusta, dime «deshaz eso» y lo regreso todo."}
    if fallos:
        out["no_se_pudo"] = fallos[:8]
    return out
