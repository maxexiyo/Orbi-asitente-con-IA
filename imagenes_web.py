"""Imágenes para presentaciones y documentos: BUSCAR en internet (con su licencia y crédito), DESCARGAR con seguridad y GUARDAR las generadas con IA.

  buscar_y_guardar(consulta)        -> {ruta, credito, titulo, fuente, ancho, alto}   (Wikimedia Commons primero, luego Openverse)
  descargar_y_guardar(url, nombre)  -> igual, para un enlace directo a una imagen
  guardar_bytes(datos, nombre)      -> {ruta, ...}  guarda una imagen ya hecha (la que generó la IA)
Todo lo que baja queda en  Imágenes/Orbi  (una carpeta que Orbi ya puede leer) y NUNCA pisa un archivo existente.
Lanza ImgError con un mensaje claro si algo falla.

Seguridad: solo https, nada que apunte a tu red local (IPs privadas), tope de 8 MB, y se comprueba con Pillow que de verdad sea una imagen.
Las fotos de internet traen autor y licencia (CC): se devuelven en `credito` para ponerlas en la diapositiva.
"""
import html, io, ipaddress, re, socket, unicodedata
from pathlib import Path
from urllib.parse import urlparse, urljoin

import archivos_ops as AO
from archivos_ops import OpError

UA = "OrbiAsistente/1.0 (asistente personal de escritorio; uso escolar)"
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
CARPETA = "Imágenes/Orbi"
MAX_BYTES = 8_000_000
MIN_ANCHO = 800
MAX_LADO = 2000
PERMITIR_LOCAL = False                       # solo para pruebas (servidores falsos en 127.0.0.1)
_MIME_OK = ("image/jpeg", "image/png", "image/webp")


class ImgError(Exception):
    pass


# --------------------------------------------------------------------------- red segura
def _host_publico(host: str) -> bool:
    if PERMITIR_LOCAL:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for i in infos:
        ip = ipaddress.ip_address(i[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return bool(infos)


def _url_ok(url: str) -> None:
    u = urlparse(url)
    if u.scheme != "https" and not (PERMITIR_LOCAL and u.scheme == "http"):
        raise ImgError("Solo descargo imágenes de enlaces https.")
    if not u.hostname or not _host_publico(u.hostname):
        raise ImgError("Ese enlace apunta a un lugar que no puedo abrir por seguridad.")


def _json(url: str, params: dict) -> dict:
    import httpx
    _url_ok(url)
    r = httpx.get(url, params=params, headers={"User-Agent": UA}, timeout=15, follow_redirects=False)
    if r.status_code != 200:
        raise ImgError(f"El buscador de imágenes respondió {r.status_code}.")
    return r.json()


def _descargar(url: str) -> bytes:
    import httpx
    for _ in range(4):                                   # sigue redirecciones a mano para revisar cada destino
        _url_ok(url)
        with httpx.stream("GET", url, headers={"User-Agent": UA, "Accept": "image/*"}, timeout=25, follow_redirects=False) as r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            if r.status_code != 200:
                raise ImgError(f"La descarga respondió {r.status_code}.")
            if not r.headers.get("content-type", "").lower().startswith("image/"):
                raise ImgError("Ese enlace no es una imagen.")
            if int(r.headers.get("content-length") or 0) > MAX_BYTES:
                raise ImgError("La imagen es demasiado pesada (más de 8 MB).")
            buf = bytearray()
            for chunk in r.iter_bytes(65536):
                buf += chunk
                if len(buf) > MAX_BYTES:
                    raise ImgError("La imagen es demasiado pesada (más de 8 MB).")
            return bytes(buf)
    raise ImgError("Demasiadas redirecciones.")


# --------------------------------------------------------------------------- validar y guardar
def _slug(t: str, defecto: str = "imagen") -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()[:48]
    return t or defecto


def _procesar(datos: bytes, min_ancho: int = 0):
    """-> (bytes listos para guardar, extensión, ancho, alto). Comprueba con Pillow que sea imagen, la achica si es enorme."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(datos))
        im.load()
    except Exception:                                    # noqa: BLE001
        raise ImgError("El archivo no es una imagen válida.")
    w, h = im.size
    if w < min_ancho:
        raise ImgError(f"La imagen es muy chica ({w} px de ancho).")
    if not (0.4 <= w / max(h, 1) <= 3.2):
        raise ImgError("La imagen tiene una forma muy rara (muy larga o muy angosta).")
    if max(w, h) > MAX_LADO:
        im.thumbnail((MAX_LADO, MAX_LADO))
        w, h = im.size
    tiene_alfa = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    out = io.BytesIO()
    if tiene_alfa:
        im.convert("RGBA").save(out, "PNG", optimize=True)
        return out.getvalue(), ".png", w, h
    im.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue(), ".jpg", w, h


def _guardar(datos: bytes, ext: str, nombre: str) -> Path:
    try:
        destino = AO._destino_nuevo(f"{CARPETA}/{_slug(nombre)}{ext}", ext)
    except OpError as e:
        raise ImgError(str(e))
    destino.write_bytes(datos)
    return destino


def guardar_bytes(datos: bytes, nombre: str = "imagen", credito: str = "", titulo: str = "", fuente: str = "") -> dict:
    """Guarda una imagen ya hecha (p. ej. la generada con IA) en Imágenes/Orbi."""
    b, ext, w, h = _procesar(datos)
    p = _guardar(b, ext, nombre)
    return {"ruta": str(p), "credito": credito, "titulo": titulo or nombre, "fuente": fuente, "ancho": w, "alto": h}


def descargar_y_guardar(url: str, nombre: str = "imagen", credito: str = "", titulo: str = "", fuente: str = "") -> dict:
    b, ext, w, h = _procesar(_descargar(url), MIN_ANCHO // 2)
    p = _guardar(b, ext, nombre)
    return {"ruta": str(p), "credito": credito, "titulo": titulo or nombre, "fuente": fuente or (urlparse(url).hostname or ""), "ancho": w, "alto": h}


# --------------------------------------------------------------------------- buscadores
def _texto(h) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(h or "")))).strip()


def _wikimedia(consulta: str, n: int = 15) -> list:
    d = _json(WIKIMEDIA_API, {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": n,
                              "gsrsearch": f"{consulta} filetype:bitmap", "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
                              "iiurlwidth": 1600})
    out = []
    pages = sorted((d.get("query", {}).get("pages") or {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        titulo = re.sub(r"^File:|\.[A-Za-z]{3,4}$", "", p.get("title", ""))
        if ii.get("mime") not in _MIME_OK or int(ii.get("width") or 0) < MIN_ANCHO:
            continue
        if re.search(r"\b(logo|icon|icono|flag of|coat of arms|signature|stamp)\b", titulo, re.I):
            continue
        em = ii.get("extmetadata") or {}
        autor = _texto((em.get("Artist") or {}).get("value"))[:60]
        lic = _texto((em.get("LicenseShortName") or {}).get("value"))
        cred = " · ".join(x for x in (f"Foto: {autor}" if autor else "", lic, "Wikimedia Commons") if x)
        out.append({"url": ii.get("thumburl") or ii.get("url"), "titulo": titulo, "credito": cred, "fuente": "Wikimedia Commons"})
    return out


def _openverse(consulta: str, n: int = 15) -> list:
    d = _json(OPENVERSE_API, {"q": consulta, "page_size": n, "license_type": "commercial,modification", "extension": "jpg,jpeg,png"})
    out = []
    for r in d.get("results") or []:
        if int(r.get("width") or 0) < MIN_ANCHO:
            continue
        lic = f"CC {str(r.get('license', '')).upper()} {r.get('license_version', '')}".strip()
        cred = " · ".join(x for x in (f"Foto: {_texto(r.get('creator'))[:60]}" if r.get("creator") else "", lic, r.get("source") or "Openverse") if x)
        for u in (r.get("url"), r.get("thumbnail")):
            if u:
                out.append({"url": u, "titulo": _texto(r.get("title")) or consulta, "credito": cred, "fuente": "Openverse"})
    return out


def buscar_y_guardar(consulta: str, nombre: str = "") -> dict:
    """Busca una foto en internet, baja la primera buena y la guarda en Imágenes/Orbi. Devuelve ruta + crédito/licencia."""
    consulta = re.sub(r"\s+", " ", str(consulta or "")).strip()[:120]
    if not consulta:
        raise ImgError("¿Qué imagen busco?")
    errores, intentos = [], 0
    for fuente in (_wikimedia, _openverse):
        try:
            cand = fuente(consulta)
        except Exception as e:                           # noqa: BLE001
            errores.append(f"{fuente.__name__}: {str(e)[:80]}")
            continue
        for c in cand:
            if intentos >= 6:
                break
            intentos += 1
            try:
                return descargar_y_guardar(c["url"], nombre or consulta, c["credito"], c["titulo"], c["fuente"])
            except ImgError as e:
                errores.append(str(e)[:80])
            except Exception as e:                       # noqa: BLE001
                errores.append(f"{type(e).__name__}")
    raise ImgError(f"No encontré una buena imagen de «{consulta}»" + (f" ({errores[-1]})" if errores else "") + ".")
