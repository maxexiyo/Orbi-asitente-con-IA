"""Editar imágenes SIN abrir programas (Pillow): recortar, redimensionar, rotar, filtros, texto...

Reglas (a propósito):
- NUNCA toca la imagen original: guarda una copia nueva («foto_editada.png», «foto_editada (2).png»...).
- Solo dentro de las carpetas permitidas de archivos_ops (Documentos, Escritorio, Descargas...).
- Las coordenadas van de 0 a 1000 sobre la imagen (0,0 = esquina superior izquierda), igual que en las demás herramientas.
- La imagen resultante se puede meter a un Word con redactar_documento usando ![descripción](nombre.png).
"""
from pathlib import Path

import archivos_ops as AO
from archivos_ops import OpError

LEIBLES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
FORMATOS = {"png": ".png", "jpg": ".jpg", "jpeg": ".jpg", "webp": ".webp", "bmp": ".bmp", "gif": ".gif"}
MAX_LADO = 8000
TIPOS = ["redimensionar", "recortar", "rotar", "voltear", "gris", "sepia", "invertir", "brillo", "contraste", "color",
         "nitidez", "desenfocar", "texto"]


def _num(v, nombre: str, defecto=None, lo=None, hi=None) -> float:
    if v in (None, ""):
        if defecto is None:
            raise OpError(f"Falta «{nombre}».")
        return defecto
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise OpError(f"«{nombre}» tiene que ser un número.")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise OpError(f"«{nombre}» tiene que estar entre {lo} y {hi}.")
    return v


def _color(v, defecto=(255, 255, 255)):
    from PIL import ImageColor
    if not v:
        return defecto
    try:
        return ImageColor.getrgb(str(v).strip())
    except ValueError:
        raise OpError(f"No entiendo el color «{v}» (usa un nombre en inglés como red o un código como #ff8800).")


def _fuente(px: int):
    from PIL import ImageFont
    for nombre in ("arial.ttf", "segoeui.ttf", "calibri.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(nombre, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def _aplicar(im, op: dict):
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
    t = str(op.get("tipo", "")).lower().strip()
    w, h = im.size
    if t == "redimensionar":
        if op.get("porcentaje") not in (None, ""):
            k = _num(op["porcentaje"], "porcentaje", lo=1, hi=1000) / 100
            nw, nh = round(w * k), round(h * k)
        else:
            a = _num(op.get("ancho"), "ancho", 0, 1, MAX_LADO)
            b = _num(op.get("alto"), "alto", 0, 1, MAX_LADO)
            if not a and not b:
                raise OpError("Para redimensionar dime ancho, alto (en píxeles) o un porcentaje.")
            nw = round(a) if a else round(w * b / h)
            nh = round(b) if b else round(h * a / w)
        if max(nw, nh) > MAX_LADO or min(nw, nh) < 1:
            raise OpError(f"Ese tamaño no es válido (máximo {MAX_LADO} px por lado).")
        return im.resize((nw, nh), Image.LANCZOS)
    if t == "recortar":
        x1, y1, x2, y2 = (_num(op.get(k), k, lo=0, hi=1000) for k in ("x1", "y1", "x2", "y2"))
        x1, x2, y1, y2 = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)
        box = (round(x1 / 1000 * w), round(y1 / 1000 * h), round(x2 / 1000 * w), round(y2 / 1000 * h))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            raise OpError("Esa zona de recorte es demasiado pequeña.")
        return im.crop(box)
    if t == "rotar":
        g = _num(op.get("grados"), "grados")
        fondo = (0, 0, 0, 0) if im.mode == "RGBA" else _color(op.get("color"), (255, 255, 255))
        return im.rotate(-g, expand=True, resample=Image.BICUBIC, fillcolor=fondo)   # grados en sentido del reloj
    if t == "voltear":
        d = str(op.get("direccion", "horizontal")).lower()
        return ImageOps.flip(im) if d.startswith("v") else ImageOps.mirror(im)
    if t in ("gris", "sepia", "invertir"):
        alpha = im.getchannel("A") if im.mode in ("RGBA", "LA") else None
        base = im.convert("RGB")
        if t == "invertir":
            out = ImageOps.invert(base)
        else:
            g = ImageOps.grayscale(base)
            out = g.convert("RGB") if t == "gris" else ImageOps.colorize(g, "#2b1b0a", "#f5e6c8")
        if alpha is not None:
            out = out.convert("RGBA")
            out.putalpha(alpha)
        return out
    if t in ("brillo", "contraste", "color", "nitidez"):
        f = _num(op.get("factor"), "factor", lo=0, hi=10)
        cls = {"brillo": ImageEnhance.Brightness, "contraste": ImageEnhance.Contrast,
               "color": ImageEnhance.Color, "nitidez": ImageEnhance.Sharpness}[t]
        return cls(im).enhance(f)
    if t == "desenfocar":
        return im.filter(ImageFilter.GaussianBlur(_num(op.get("radio"), "radio", 4, 0, 100)))
    if t == "texto":
        txt = str(op.get("texto", "") or "").strip()
        if not txt:
            raise OpError("Dime qué texto poner.")
        px = round(_num(op.get("tamano"), "tamano", max(12, h * 0.06), 6, MAX_LADO))
        x, y = _num(op.get("x"), "x", 500, 0, 1000), _num(op.get("y"), "y", 900, 0, 1000)
        col = _color(op.get("color"))
        out = im.convert("RGBA")
        d = ImageDraw.Draw(out)
        d.text((x / 1000 * w, y / 1000 * h), txt, font=_fuente(px), fill=col + (255,), anchor="mm",
               stroke_width=max(1, px // 14), stroke_fill=(0, 0, 0, 255) if sum(col) > 380 else (255, 255, 255, 255))
        return out
    raise OpError(f"No sé hacer «{t}». Puedo: {', '.join(TIPOS)}.")


def editar_imagen(ruta: str, operaciones, salida: str = "", formato: str = "") -> dict:
    """Aplica una lista de operaciones a una imagen y guarda una COPIA nueva. Devuelve la ruta para usarla en un documento."""
    if isinstance(operaciones, str):
        import json
        try:
            operaciones = json.loads(operaciones)
        except ValueError:
            return {"error": "`operaciones` debe ser una lista."}
    if isinstance(operaciones, dict):
        operaciones = [operaciones]
    if not operaciones:
        return {"error": "Dime qué quieres hacerle a la imagen."}
    try:
        from PIL import Image, ImageOps
        p = AO.resolver_archivo(ruta)
        if p.is_dir() or p.suffix.lower() not in LEIBLES:
            raise OpError("Eso no es una imagen que pueda editar (png, jpg, webp, bmp, gif).")
        try:
            im = Image.open(p)
            im = ImageOps.exif_transpose(im)
            im.load()
        except OpError:
            raise
        except Exception:  # noqa: BLE001
            raise OpError(f"No pude abrir «{p.name}».")
        if im.mode not in ("RGB", "RGBA", "L", "LA"):
            im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("P", "PA") else "RGB")
        hechas = []
        for op in operaciones:
            if not isinstance(op, dict):
                raise OpError("Cada operación debe llevar un `tipo`.")
            im = _aplicar(im, op)
            hechas.append(str(op.get("tipo", "")).lower())
        ext = FORMATOS.get(str(formato or "").lower().lstrip("."), "") or (Path(salida).suffix.lower() if salida else "") or p.suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        if ext not in FORMATOS.values():
            ext = ".png"
        nombre = AO._limpio(salida) or f"{p.stem}_editada"
        if Path(nombre).suffix.lower() != ext:
            nombre = Path(nombre).stem + ext if Path(nombre).suffix.lower() in LEIBLES else nombre + ext
        dst = AO._libre(p.with_name(nombre))
        if ext in (".jpg", ".bmp") and im.mode in ("RGBA", "LA"):     # sin transparencia: fondo blanco
            fondo = Image.new("RGB", im.size, (255, 255, 255))
            fondo.paste(im, mask=im.getchannel("A"))
            im = fondo
        elif ext in (".jpg", ".bmp") and im.mode != "RGB":
            im = im.convert("RGB")
        kw = {"quality": 92} if ext in (".jpg", ".webp") else {}
        im.save(dst, **kw)
    except OpError as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"No pude guardar la imagen: {e}"}
    return {"resultado": f"Listo: guardé «{dst.name}» ({im.size[0]}x{im.size[1]} px) en {dst.parent}. El original no se tocó. "
                         f"Hice: {', '.join(hechas)}. Para meterla a un Word usa ![descripción]({dst.name}) en redactar_documento.",
            "ruta": str(dst)}


def ejecutar(name: str, args: dict) -> dict:
    a = args or {}
    if name == "editar_imagen":
        return editar_imagen(str(a.get("ruta", "")), a.get("operaciones"), str(a.get("salida", "") or ""), str(a.get("formato", "") or ""))
    return {"error": f"Tool desconocida: {name}"}
