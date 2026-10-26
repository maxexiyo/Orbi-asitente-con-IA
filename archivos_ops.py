"""Operaciones de archivos SIN pantalla (como leer_archivo, pero para organizar y escribir).

  crear_carpeta · mover · copiar · renombrar · escribir_texto_archivo · escribir_docx · organizar · deshacer

Reglas de seguridad (a propósito):
  - Solo dentro de Documentos, Escritorio y Descargas (y sus subcarpetas). Nunca las carpetas raíz mismas.
  - NUNCA borra y NUNCA sobrescribe: si el nombre ya existe, el nuevo lleva « (2)», « (3)»...
  - Nada de crear ejecutables ni scripts de Windows aquí (BLOCKED_EXT); el código normal (.js, .py...) sí. Scripts de Windows: archivos_edicion, con OK.
  - Cada movimiento queda en `organizacion_log.json` (junto a Orbi) para poder DESHACERLO.
  - Archivos abiertos en otro programa (Word, etc.) se saltan y se reportan: Windows no deja moverlos.

El .docx se escribe con zipfile (sin python-docx), así que también funciona en el .exe.
"""
import io, json, os, random, re, shutil, time, uuid, zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import docs_reader as DR
from paths import APP_DIR

LOG_PATH = APP_DIR / "organizacion_log.json"
LOG_MAX_BATCHES = 30
# Ejecutables y scripts de WINDOWS: aquí no se crean. Los scripts de texto (.bat, .ps1, .vbs...) se crean/editan con
# archivos_edicion (crear_script_windows), que muestra el código y pide el OK del dueño. El código normal (.js, .py, .sh...) sí se permite.
BLOCKED_EXT = {".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".ps1", ".vbs", ".vbe", ".jse",
               ".wsf", ".lnk", ".jar", ".reg", ".dll", ".hta", ".cpl", ".apk"}
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
        raise OpError("Los scripts de Windows (.bat, .ps1, .vbs...) se crean con crear_script_windows, que te pide OK con vista previa. "
                      "Los ejecutables (.exe, .dll...) no los creo.")
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


def _runs(texto: str, negrita: bool = False) -> str:
    """**negrita** y *cursiva* -> runs de Word. `negrita=True` pone todo en negrita (encabezados de tabla)."""
    out = []
    for parte in re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)", texto):
        if not parte:
            continue
        rpr = "<w:rPr><w:b/></w:rPr>" if negrita else ""
        if parte.startswith("**") and parte.endswith("**") and len(parte) > 4:
            parte, rpr = parte[2:-2], "<w:rPr><w:b/></w:rPr>"
        elif parte.startswith("*") and parte.endswith("*") and len(parte) > 2:
            parte, rpr = parte[1:-1], ("<w:rPr><w:b/><w:i/></w:rPr>" if negrita else "<w:rPr><w:i/></w:rPr>")
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(parte)}</w:t></w:r>')
    return "".join(out)


_NS_IMG = {"wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
           "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
           "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
           "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
_IMG_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_IMG_RE = re.compile(r"^\s*!\[([^\]]*)\]\((.+)\)\s*$")
_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
IMG_MAX_ANCHO_IN, IMG_MAX_ALTO_IN = 6.0, 8.0   # la página tiene 6.5" útiles


def _imagen_xml(ref: str, alt: str, medios: list) -> str:
    """![descripción](ruta) -> párrafo centrado con la imagen incrustada. `medios` acumula lo que hay que meter al .docx."""
    from PIL import Image
    p = resolver_archivo(ref.strip().strip('"'))
    if p.is_dir():
        raise OpError(f"«{ref}» es una carpeta, no una imagen.")
    try:
        im = Image.open(p)
        im.load()
    except Exception:  # noqa: BLE001
        raise OpError(f"No pude abrir la imagen «{p.name}» (¿es png, jpg, gif, bmp o webp?).")
    ext = p.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
        data = p.read_bytes()
        ext = ".jpg" if ext == ".jpeg" else ext
    else:                                   # webp, tiff...: Word los abre mal -> a PNG
        buf = io.BytesIO()
        (im if im.mode in ("RGB", "RGBA", "L", "LA", "P") else im.convert("RGBA")).save(buf, "PNG")
        data, ext = buf.getvalue(), ".png"
    w_px, h_px = im.size
    try:
        dpi = float((im.info.get("dpi") or (96, 96))[0]) or 96.0
    except (TypeError, ValueError):
        dpi = 96.0
    dpi = min(max(dpi, 72.0), 600.0)
    w_in, h_in = w_px / dpi, h_px / dpi
    k = min(1.0, IMG_MAX_ANCHO_IN / w_in, IMG_MAX_ALTO_IN / h_in)
    cx, cy = max(1, int(w_in * k * 914400)), max(1, int(h_in * k * 914400))
    uid = uuid.uuid4().hex[:10]
    rid, parte = f"rIdOrbi{uid}", f"orbi_{uid}{ext}"
    medios.append({"rid": rid, "parte": parte, "datos": data, "ext": ext.lstrip(".")})
    n = random.randint(1000, 2_000_000_000)
    alt_x = escape(alt or p.stem, {'"': "&quot;"})
    ns = _NS_IMG
    return (f'<w:p><w:pPr><w:keepNext/><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
            f'<wp:inline distT="0" distB="0" distL="0" distR="0" xmlns:wp="{ns["wp"]}">'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{n}" name="Imagen {n}" descr="{alt_x}"/>'
            f'<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="{ns["a"]}" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            f'<a:graphic xmlns:a="{ns["a"]}"><a:graphicData uri="{ns["pic"]}">'
            f'<pic:pic xmlns:pic="{ns["pic"]}"><pic:nvPicPr><pic:cNvPr id="0" name="{escape(parte)}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}" xmlns:r="{ns["r"]}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            f'</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


def _celdas(linea: str) -> list:
    t = linea.strip().replace("\\|", "\x00")
    if t.startswith("|"):
        t = t[1:]
    if t.endswith("|"):
        t = t[:-1]
    return [c.replace("\x00", "|").strip() for c in t.split("|")]


def _tabla_xml(filas: list, alin: list) -> str:
    """Tabla de Word: primera fila = encabezado (negrita y fondo azul claro). Ocupa todo el ancho útil."""
    ncol = max(len(f) for f in filas)
    ancho = 9360 // ncol
    borde = "".join(f'<w:{l} w:val="single" w:sz="4" w:space="0" w:color="A6A6A6"/>'
                    for l in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join('<w:gridCol w:w="%d"/>' % ancho for _ in range(ncol))
    xml = [f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{borde}</w:tblBorders><w:tblLayout w:type="autofit"/>'
           f'<w:tblCellMar><w:left w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr>'
           f'<w:tblGrid>{grid}</w:tblGrid>']
    for i, fila in enumerate(filas):
        fila = fila + [""] * (ncol - len(fila))
        xml.append("<w:tr>" + ("<w:trPr><w:tblHeader/></w:trPr>" if i == 0 else ""))
        for j, c in enumerate(fila):
            sh = '<w:shd w:val="clear" w:color="auto" w:fill="D9E2F3"/>' if i == 0 else ""
            jc = {"c": "center", "r": "right"}.get(alin[j] if j < len(alin) else "l", "left")
            xml.append(f'<w:tc><w:tcPr><w:tcW w:w="{ancho}" w:type="dxa"/>{sh}</w:tcPr>'
                       f'<w:p><w:pPr><w:spacing w:before="40" w:after="40"/><w:jc w:val="{jc}"/></w:pPr>{_runs(c, negrita=(i == 0))}</w:p></w:tc>')
        xml.append("</w:tr>")
    xml.append('</w:tbl><w:p><w:pPr><w:spacing w:after="0"/></w:pPr></w:p>')   # Word pide un párrafo después de la tabla
    return "".join(xml)


def _parrafos_xml(contenido: str, medios: list = None) -> str:
    """Markdown simple -> párrafos: # título, ## y ### encabezados, - o * viñetas, 1. numeradas, **negrita**, tablas con | y
    ![descripción](ruta) para imágenes (las incrusta; se acumulan en `medios`)."""
    medios = medios if medios is not None else []
    lineas = [x.rstrip() for x in str(contenido).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    xml, primero, i = [], True, 0
    while i < len(lineas):
        ln = lineas[i]
        if not ln.strip():
            i += 1
            continue
        mi = _IMG_RE.match(ln)
        if mi:
            xml.append(_imagen_xml(mi.group(2), mi.group(1).strip(), medios))
            primero, i = False, i + 1
            continue
        if "|" in ln and i + 1 < len(lineas) and "|" in lineas[i + 1] and _SEP_RE.match(lineas[i + 1]):
            enc = _celdas(ln)
            alin = ["c" if c.startswith(":") and c.endswith(":") else "r" if c.endswith(":") else "l"
                    for c in (x.replace(" ", "") for x in _celdas(lineas[i + 1]))]
            filas, i = [enc], i + 2
            while i < len(lineas) and lineas[i].strip() and "|" in lineas[i]:
                filas.append(_celdas(lineas[i]))
                i += 1
            xml.append(_tabla_xml(filas, alin))
            primero = False
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
        primero, i = False, i + 1
    return "".join(xml)


_IMG_CT = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp"}


def _ct_con_imagenes(ct: str, medios: list) -> str:
    """Declara en [Content_Types].xml las extensiones de imagen que faltan."""
    for ext in sorted({m["ext"] for m in medios}):
        if not re.search(rf'Extension="{ext}"', ct, re.I):
            ct = ct.replace("</Types>", f'<Default Extension="{ext}" ContentType="{_IMG_CT.get(ext, "image/png")}"/></Types>')
    return ct


def _rels_con_imagenes(rels: str, medios: list) -> str:
    add = "".join(f'<Relationship Id="{m["rid"]}" Type="{_IMG_REL}" Target="media/{m["parte"]}"/>' for m in medios)
    return rels.replace("</Relationships>", add + "</Relationships>")


def _escribir_docx(path: Path, contenido: str) -> None:
    medios = []
    body = _parrafos_xml(contenido, medios)
    sect = '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {_NS}><w:body>{body}{sect}</w:body></w:document>'
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _ct_con_imagenes(_CT, medios))
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/_rels/document.xml.rels", _rels_con_imagenes(_DOC_RELS, medios))
        for m in medios:
            z.writestr(f"word/media/{m['parte']}", m["datos"])
    os.replace(tmp, path)


def _agregar_docx(path: Path, contenido: str) -> None:
    """Agrega párrafos al final de un .docx existente (antes de sectPr). Falla con PermissionError si está abierto."""
    with zipfile.ZipFile(path) as z:
        items = {n: z.read(n) for n in z.namelist()}
    xml = items["word/document.xml"].decode("utf-8")
    medios = []
    nuevo = _parrafos_xml(contenido, medios)
    i = xml.rfind("<w:sectPr")
    if i < 0:
        i = xml.rfind("</w:body>")
    if i < 0:
        raise OpError("No pude entender la estructura de ese .docx.")
    items["word/document.xml"] = (xml[:i] + nuevo + xml[i:]).encode("utf-8")
    if medios:
        if "word/_rels/document.xml.rels" not in items or "[Content_Types].xml" not in items:
            raise OpError("Ese .docx no tiene la estructura que necesito para meterle imágenes.")
        items["[Content_Types].xml"] = _ct_con_imagenes(items["[Content_Types].xml"].decode("utf-8"), medios).encode("utf-8")
        items["word/_rels/document.xml.rels"] = _rels_con_imagenes(items["word/_rels/document.xml.rels"].decode("utf-8"), medios).encode("utf-8")
        for m in medios:
            items[f"word/media/{m['parte']}"] = m["datos"]
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
