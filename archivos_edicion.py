"""Editar archivos que YA EXISTEN, sin borrar nada (complemento de archivos_ops.py).

editar_archivo · reescribir_archivo · extraer_de_html · restaurar_archivo

Reglas (a propósito):
- Solo dentro de las carpetas permitidas de archivos_ops (Documentos, Escritorio, Descargas...).
- NO borra: antes de tocar un archivo guarda una copia en «orbi_respaldos» (junto a Orbi) y la anota en
  `edicion_log.json`, así `restaurar_archivo` lo regresa a como estaba.
- Solo archivos de texto/código UTF-8 (nada de .docx/.pdf/imágenes ni ejecutables).
- Respeta el salto de línea (CRLF/LF) y el BOM que ya tenía el archivo.
"""
import json, os, re, shutil, textwrap
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import archivos_ops as AO
from archivos_ops import OpError
from paths import APP_DIR

RESPALDOS = APP_DIR / "orbi_respaldos"
LOG_PATH = APP_DIR / "edicion_log.json"
LOG_MAX = 200
MAX_BYTES = 3_000_000

NO_EDITABLES = {".docx", ".pptx", ".xlsx", ".pdf", ".doc", ".xls", ".ppt", ".zip", ".rar", ".7z", ".gz", ".tar", ".iso",
                ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svgz", ".heic", ".mp3", ".wav", ".flac",
                ".mp4", ".mkv", ".avi", ".mov", ".exe", ".dll", ".msi", ".bin", ".db", ".sqlite",
                ".scr", ".com", ".lnk", ".jar", ".apk", ".cpl"}  # binarios: no se pueden escribir como texto

# Scripts de Windows (texto): se pueden crear/editar, pero SIEMPRE con vista previa y tu OK en pantalla.
SCRIPTS_WIN = {".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".jse", ".wsf", ".hta", ".reg"}
VISTA_MAX = 2000


# --------------------------------------------------------------------------- base
def _log_load() -> list:
    try:
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _log_add(ruta: Path, respaldo: Path) -> None:
    data = _log_load()
    data.append({"cuando": datetime.now().isoformat(timespec="seconds"), "ruta": str(ruta), "respaldo": str(respaldo)})
    try:
        LOG_PATH.write_text(json.dumps(data[-LOG_MAX:], ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _respaldar(p: Path) -> Path:
    RESPALDOS.mkdir(parents=True, exist_ok=True)
    base = RESPALDOS / f"{datetime.now():%Y%m%d-%H%M%S}_{p.name}"
    dst, i = base, 2
    while dst.exists():
        dst = base.with_name(f"{base.stem} ({i}){base.suffix}")
        i += 1
    shutil.copy2(p, dst)
    _log_add(p, dst)
    return dst


def _archivo_editable(ref: str) -> Path:
    p = AO.resolver_archivo(ref)
    if not p.is_file():
        raise OpError("Eso es una carpeta, no un archivo.")
    if not AO._permitida(p):
        raise OpError("Solo edito archivos dentro de Documentos, Escritorio, Descargas o carpetas permitidas.")
    ext = p.suffix.lower()
    if ext in NO_EDITABLES:
        raise OpError(f"No edito archivos «{ext}» así. Para Word usa redactar_documento (agregar_a).")
    try:
        if p.stat().st_size > MAX_BYTES:
            raise OpError("Ese archivo es demasiado grande para editarlo así.")
    except OSError as e:
        raise OpError(f"No pude leerlo: {e}")
    return p


def _leer(p: Path) -> tuple:
    """-> (texto, bom). No toca los saltos de línea."""
    try:
        data = p.read_bytes()
    except PermissionError:
        raise OpError("Está abierto en otro programa que no me deja leerlo; ciérralo e intento otra vez.")
    except OSError as e:
        raise OpError(f"No pude leerlo: {e}")
    if b"\x00" in data[:8192]:
        raise OpError("Parece un archivo binario, no de texto.")
    bom = data.startswith(b"\xef\xbb\xbf")
    try:
        return data.decode("utf-8-sig"), bom
    except UnicodeDecodeError:
        raise OpError("No está en UTF-8; no lo toco para no estropear los acentos.")


def _escribir(p: Path, texto: str, bom: bool) -> None:
    tmp = p.with_name(p.name + ".orbi.tmp")
    try:
        tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + texto.encode("utf-8"))
        os.replace(tmp, p)
    except PermissionError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise OpError("Está abierto en otro programa y no me deja guardarlo. Ciérralo (o guárdalo y ciérralo) y lo intento otra vez.")
    except OSError as e:
        raise OpError(f"No pude guardar los cambios: {e}")


def _eol(texto: str, como: str) -> str:
    """Ajusta los saltos de línea de `como` al estilo del archivo (CRLF o LF)."""
    if "\r\n" in texto:
        return como.replace("\r\n", "\n").replace("\n", "\r\n")
    return como.replace("\r\n", "\n")


def _es_script(p: Path) -> bool:
    return p.suffix.lower() in SCRIPTS_WIN


def _pedir_ok(ctx, p: Path, antes, despues: str, accion: str) -> None:
    """Scripts de Windows: muestra el código (o el diff) y espera tu OK. Nunca los ejecuta."""
    if ctx is None:
        raise OpError("Los scripts de Windows necesitan tu OK en pantalla y ahora no puedo pedirlo.")
    if antes is None:
        cuerpo, n = despues, len(despues.splitlines())
        titulo = f"Código completo ({n} líneas):"
    else:
        import difflib
        cuerpo = "".join(difflib.unified_diff(antes.splitlines(True), despues.splitlines(True), "antes", "después", n=2))
        n = cuerpo.count("\n") + 1
        titulo = "Cambios (- quita, + agrega):"
    if len(cuerpo) > VISTA_MAX:
        cuerpo = cuerpo[:VISTA_MAX] + f"\n… (recortado; son {n} líneas en total)"
    if not ctx.confirm(f"Orbi quiere {accion} un script de Windows: «{p.name}».\n"
                       f"Revísalo antes de aceptar. Solo se guarda, Orbi NO lo ejecuta.\n\n{titulo}\n{cuerpo}"):
        raise OpError("No autorizaste ese script; no cambié nada.")


# --------------------------------------------------------------------------- operaciones
def editar_archivo(ruta: str, buscar: str, reemplazo: str, todas: bool = False, ctx=None) -> dict:
    """Cambia un trozo de texto exacto dentro de un archivo existente (con respaldo)."""
    try:
        if not str(buscar or ""):
            raise OpError("Dime qué texto exacto quieres cambiar.")
        p = _archivo_editable(ruta)
        texto, bom = _leer(p)
        b, r = _eol(texto, str(buscar)), _eol(texto, str(reemplazo or ""))
        n = texto.count(b)
        if n == 0:
            raise OpError("No encontré ese texto exacto en el archivo (cuentan espacios y sangría). "
                          "Léelo con leer_archivo y copia el trozo tal cual.")
        if n > 1 and not todas:
            raise OpError(f"Ese texto aparece {n} veces. Agrega más líneas alrededor para que sea único, o usa todas=true.")
        nuevo = texto.replace(b, r) if todas else texto.replace(b, r, 1)
        if nuevo == texto:
            raise OpError("El cambio no modifica nada.")
        if _es_script(p):
            _pedir_ok(ctx, p, texto, nuevo, "EDITAR")
        _respaldar(p)
        _escribir(p, nuevo, bom)
    except OpError as e:
        return {"error": str(e)}
    hechos = n if todas else 1
    return {"resultado": f"Edité «{p.name}» ({hechos} cambio(s)). Dejé un respaldo; si no te gusta, dime «restaura ese archivo».",
            "ruta": str(p)}


def reescribir_archivo(ruta: str, contenido: str, ctx=None) -> dict:
    """Reemplaza TODO el contenido de un archivo existente (con respaldo). Úsalo solo si cambia casi todo."""
    try:
        if not str(contenido or "").strip():
            raise OpError("No hay contenido nuevo; no voy a vaciar el archivo.")
        p = _archivo_editable(ruta)
        texto, bom = _leer(p)
        nuevo = _eol(texto, str(contenido))
        if nuevo == texto:
            raise OpError("El contenido es idéntico al que ya tiene.")
        if _es_script(p):
            _pedir_ok(ctx, p, texto, nuevo, "REESCRIBIR")
        _respaldar(p)
        _escribir(p, nuevo, bom)
    except OpError as e:
        return {"error": str(e)}
    out = {"resultado": f"Reescribí «{p.name}». Dejé un respaldo; si no te gusta, dime «restaura ese archivo».", "ruta": str(p)}
    if len(texto) > 500 and len(nuevo) < len(texto) * 0.4:
        out["aviso"] = "El archivo quedó mucho más corto que antes; confírmale al usuario que era lo esperado."
    return out


_JS_TYPES = {"", "text/javascript", "application/javascript", "module"}


def extraer_de_html(ruta: str, tipo: str = "script", archivo: str = "", numero: int = 1) -> dict:
    """Saca un <script> o <style> que está DENTRO de un .html a su propio archivo (.js/.css) y lo enlaza en el html."""
    tipo = str(tipo or "script").lower().strip()
    if tipo in ("js", "javascript"):
        tipo = "script"
    if tipo in ("css", "estilo", "estilos"):
        tipo = "style"
    try:
        if tipo not in ("script", "style"):
            raise OpError("Puedo extraer «script» (a .js) o «style» (a .css).")
        p = _archivo_editable(ruta)
        if p.suffix.lower() not in (".html", ".htm", ".php", ".xhtml"):
            raise OpError("Eso no es un archivo HTML.")
        html, bom = _leer(p)
        pat = re.compile(rf"<{tipo}\b([^>]*)>(.*?)</{tipo}\s*>", re.S | re.I)
        cands = []
        for m in pat.finditer(html):
            attrs = m.group(1)
            if tipo == "script":
                if re.search(r"\bsrc\s*=", attrs, re.I):
                    continue
                t = re.search(r"\btype\s*=\s*[\"']?([^\"'\s>]+)", attrs, re.I)
                if (t.group(1).lower() if t else "") not in _JS_TYPES:
                    continue  # JSON-LD, importmap, plantillas...
            if "<?php" in m.group(2) or not m.group(2).strip():
                continue
            cands.append(m)
        if not cands:
            raise OpError(f"No encontré ningún <{tipo}> con código dentro de ese archivo.")
        try:
            k = int(numero or 1)
        except (TypeError, ValueError):
            k = 1
        if not 1 <= k <= len(cands):
            raise OpError(f"Hay {len(cands)} bloque(s) <{tipo}> con código; elige un número del 1 al {len(cands)}.")
        m = cands[k - 1]
        eol = "\r\n" if "\r\n" in html else "\n"
        crudo = m.group(2).replace("\r\n", "\n")
        codigo = textwrap.dedent(crudo).strip("\n").rstrip() + "\n"
        codigo = codigo.replace("\n", eol)
        ext = ".js" if tipo == "script" else ".css"
        nombre = AO._limpio(archivo) or (p.stem + ext)
        if Path(nombre).suffix.lower() != ext:
            nombre += ext
        dst = AO._libre(p.with_name(nombre))
        href = quote(dst.name)
        attrs = m.group(1)
        if tipo == "script":
            tipo_attr = ' type="module"' if re.search(r"\btype\s*=\s*[\"']?module", attrs, re.I) else ""
            tag = f'<script src="{href}"{tipo_attr}></script>'
        else:
            media = re.search(r"\bmedia\s*=\s*([\"'][^\"']*[\"'])", attrs, re.I)
            tag = f'<link rel="stylesheet" href="{href}"' + (f" media={media.group(1)}" if media else "") + ">"
        nuevo_html = html[:m.start()] + tag + html[m.end():]
        _respaldar(p)
        dst.write_bytes((b"\xef\xbb\xbf" if bom else b"") + codigo.encode("utf-8"))
        _escribir(p, nuevo_html, bom)
    except OpError as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"No pude escribir el archivo nuevo: {e}"}
    resto = len(cands) - 1
    msg = f"Listo: saqué el <{tipo}> de «{p.name}» a «{dst.name}» (misma carpeta) y dejé el enlace en el HTML. Respaldo del HTML guardado."
    if resto:
        msg += f" Quedan {resto} bloque(s) <{tipo}> más dentro del HTML."
    return {"resultado": msg, "ruta": str(dst)}


def restaurar_archivo(ruta: str = "", ctx=None) -> dict:
    """Regresa un archivo a su versión anterior (la del último respaldo). Sin `ruta`, el último archivo editado."""
    data = _log_load()
    if not data:
        return {"error": "No tengo ninguna edición reciente que restaurar."}
    ref = str(ruta or "").strip().strip('"').lower()
    cand = None
    for e in reversed(data):
        if not ref or ref in Path(e["ruta"]).name.lower() or ref == e["ruta"].lower():
            if Path(e["respaldo"]).exists():
                cand = e
                break
    if cand is None:
        return {"error": "No encontré un respaldo de ese archivo."}
    destino, resp = Path(cand["ruta"]), Path(cand["respaldo"])
    try:
        if not AO._permitida(destino):
            raise OpError("Esa ruta ya no está en una carpeta permitida.")
        if _es_script(destino):
            try:
                _pedir_ok(ctx, destino, _leer(destino)[0] if destino.exists() else "", _leer(resp)[0], "RESTAURAR (versión anterior de)")
            except OpError as e:
                if "No autorizaste" in str(e) or "necesitan tu OK" in str(e):
                    raise
        if destino.exists():
            _respaldar(destino)  # lo de ahora también queda guardado: restaurar se puede «des-restaurar»
        tmp = destino.with_name(destino.name + ".orbi.tmp")
        shutil.copy2(resp, tmp)
        os.replace(tmp, destino)
    except OpError as e:
        return {"error": str(e)}
    except PermissionError:
        return {"error": "Está abierto en otro programa; ciérralo y lo restauro."}
    except OSError as e:
        return {"error": f"No pude restaurarlo: {e}"}
    return {"resultado": f"Restauré «{destino.name}» a como estaba el {cand['cuando'].replace('T', ' ')}.", "ruta": str(destino)}


def crear_script_windows(ruta: str, contenido: str, ctx=None) -> dict:
    """Crea un script NUEVO de Windows (.bat, .ps1, .vbs...) solo si el dueño aprueba la vista previa. No lo ejecuta."""
    try:
        contenido = str(contenido or "")
        if not contenido.strip():
            raise OpError("No hay código que guardar.")
        partes = [x for x in re.split(r"[\\/]+", str(ruta or "").strip().strip('"')) if x]
        if not partes:
            raise OpError("Dime cómo se llama el script.")
        nombre = AO._limpio(partes[-1])
        ext = Path(nombre).suffix.lower()
        if ext not in SCRIPTS_WIN:
            raise OpError("Para ese tipo de archivo usa escribir_archivo; esto es solo para scripts de Windows (" + ", ".join(sorted(SCRIPTS_WIN)) + ").")
        if len(partes) == 1 and not Path(str(ruta)).is_absolute():
            base = next((r for r in AO.DR.file_roots() if r.name.lower() in ("documents", "documentos")), None)
            if base is None:
                raise OpError("No encontré tu carpeta Documentos.")
            carpeta = base
        else:
            carpeta = AO.carpeta_destino(str(Path(ruta).parent) if Path(str(ruta)).is_absolute() else "/".join(partes[:-1]), crear=False)
        dst = AO._libre(carpeta / nombre)
        _pedir_ok(ctx, dst, None, contenido, "CREAR")
        carpeta.mkdir(parents=True, exist_ok=True)
        datos = contenido.replace("\r\n", "\n").replace("\n", "\r\n")
        dst.write_bytes((b"\xef\xbb\xbf" if ext == ".ps1" else b"") + datos.encode("utf-8"))
    except OpError as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"No pude guardar el script: {e}"}
    return {"resultado": f"Guardé «{dst.name}» en {dst.parent}. No lo ejecuté.", "ruta": str(dst)}


# --------------------------------------------------------------------------- puente con pc_tools
def _bool(v) -> bool:
    return v is True or str(v).strip().lower() in ("true", "1", "si", "sí", "yes")


def ejecutar(name: str, args: dict, ctx=None) -> dict:
    a = args or {}
    if name == "editar_archivo":
        return editar_archivo(str(a.get("ruta", "")), a.get("buscar", ""), a.get("reemplazo", ""), _bool(a.get("todas")), ctx)
    if name == "reescribir_archivo":
        return reescribir_archivo(str(a.get("ruta", "")), a.get("contenido", ""), ctx)
    if name == "extraer_de_html":
        return extraer_de_html(str(a.get("ruta", "")), str(a.get("tipo", "script")), str(a.get("archivo", "") or ""), a.get("numero") or 1)
    if name == "restaurar_archivo":
        return restaurar_archivo(str(a.get("ruta", "") or ""), ctx)
    if name == "crear_script_windows":
        return crear_script_windows(str(a.get("ruta", "")), a.get("contenido", ""), ctx)
    return {"error": f"Tool desconocida: {name}"}
