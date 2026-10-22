"""Guarda tus keys de Gemini en esta PC, cifradas (orbi_keys.json, junto a Orbi).

En Windows se cifran con DPAPI: solo tu usuario de Windows en esta PC puede leerlas (el archivo copiado
a otra PC o a otro usuario no sirve). Si DPAPI no está disponible, se guardan en texto plano como respaldo.
Se suman a las que ya tengas en el .env.
"""
import base64, json, sys
from paths import APP_DIR

PATH = APP_DIR / "orbi_keys.json"


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = BLOB()
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("DPAPI falló")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def load_keys() -> list:
    try:
        d = json.loads(PATH.read_text(encoding="utf-8"))
        if d.get("dpapi"):
            raw = _dpapi(base64.b64decode(d["data"]), protect=False)
            keys = json.loads(raw.decode("utf-8"))
        else:
            keys = d.get("keys", [])
        return [k for k in keys if isinstance(k, str) and k]
    except FileNotFoundError:
        return []
    except Exception as e:
        print("[keystore] no pude leer orbi_keys.json:", e)
        return []


def save_keys(keys: list) -> None:
    keys = list(dict.fromkeys(k for k in keys if k))
    if not keys:
        try:
            PATH.unlink()
        except FileNotFoundError:
            pass
        return
    doc = None
    if sys.platform == "win32":
        try:
            enc = _dpapi(json.dumps(keys).encode("utf-8"), protect=True)
            doc = {"v": 1, "dpapi": True, "data": base64.b64encode(enc).decode("ascii")}
        except Exception as e:
            print("[keystore] DPAPI no disponible, guardo sin cifrar:", e)
    if doc is None:
        doc = {"v": 1, "dpapi": False, "keys": keys}
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc), encoding="utf-8")
    tmp.replace(PATH)
