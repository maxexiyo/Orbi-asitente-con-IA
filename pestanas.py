"""Pestañas del navegador: Orbi las ve y las organiza mediante una EXTENSIÓN pequeña (Chrome / Edge / Brave).

Cómo funciona: Orbi abre un servidor SOLO local (127.0.0.1:8765) y la extensión (carpeta `extension_pestanas/`) le manda la lista de
pestañas y le pregunta si hay órdenes (cerrar, agrupar, ordenar, activar, abrir). Lleva un token aleatorio: otras webs o programas
no pueden mandarle órdenes. Instalación: chrome://extensions (o edge://extensions) > Modo desarrollador > Cargar descomprimida >
elegir la carpeta `extension_pestanas`. Orbi escribe el token en `extension_pestanas/config.js` al arrancar (recarga la extensión
una vez si lo cambió).
"""
import json, queue, secrets, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).parent
EXT = ROOT / "extension_pestanas"
PORT = 8765

_st = {"server": None, "token": "", "tabs": {}, "visto": {}, "cola": {}, "res": {}, "ultimo": ""}
_lock = threading.Lock()


def _token() -> str:
    p = ROOT / "orbi_pestanas_token.txt"
    try:
        if p.exists() and p.read_text().strip():
            return p.read_text().strip()
        t = secrets.token_urlsafe(24)
        p.write_text(t)
        return t
    except Exception:                                      # noqa: BLE001
        return secrets.token_urlsafe(24)


def _q(b: str) -> queue.Queue:
    with _lock:
        return _st["cola"].setdefault(b, queue.Queue())


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):                             # silencio
        pass

    def _ok(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self) -> bool:
        if self.headers.get("X-Orbi-Token") != _st["token"] or not (self.headers.get("Origin") or "").startswith(
                ("chrome-extension://", "moz-extension://", "")):
            self._ok({"error": "no autorizado"}, 403)
            return False
        return True

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:                                  # noqa: BLE001
            return {}

    def do_GET(self):                                      # noqa: N802
        if not self._auth():
            return
        u = urlparse(self.path)
        b = (parse_qs(u.query).get("b") or ["chrome"])[0]
        if u.path == "/poll":
            with _lock:
                _st["visto"][b] = time.time()
            try:
                self._ok(_q(b).get(timeout=20))
            except queue.Empty:
                self._ok({})
        else:
            self._ok({"error": "?"}, 404)

    def do_POST(self):                                     # noqa: N802
        if not self._auth():
            return
        u = urlparse(self.path)
        b = (parse_qs(u.query).get("b") or ["chrome"])[0]
        data = self._body()
        if u.path == "/tabs":
            with _lock:
                _st["tabs"][b] = data.get("tabs") or []
                _st["visto"][b] = time.time()
                _st["ultimo"] = b
            self._ok({"ok": 1})
        elif u.path == "/result":
            with _lock:
                _st["res"][data.get("id")] = data.get("result")
            self._ok({"ok": 1})
        else:
            self._ok({"error": "?"}, 404)


def start() -> bool:
    """Arranca el servidor local y deja listo el token para la extensión. False si el puerto está ocupado."""
    if _st["server"]:
        return True
    _st["token"] = _token()
    try:
        EXT.mkdir(exist_ok=True)
        (EXT / "config.js").write_text(f'const ORBI_TOKEN = "{_st["token"]}";\nconst ORBI_PORT = {PORT};\n', encoding="utf-8")
    except Exception as e:                                 # noqa: BLE001
        print("[pestanas] no pude escribir config.js:", e)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), _H)
    except OSError as e:
        print("[pestanas] puerto ocupado:", e)
        return False
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="orbi-pestanas", daemon=True).start()
    _st["server"] = srv
    return True


def stop():
    s = _st.pop("server", None)
    _st["server"] = None
    if s:
        s.shutdown()


def conectado() -> list:
    """Navegadores con la extensión activa (vista hace menos de 40 s)."""
    now = time.time()
    return [b for b, t in _st["visto"].items() if now - t < 40]


def _navegador(n: str = "") -> str:
    con = conectado()
    n = (n or "").lower().strip()
    for b in con:
        if n and n in b:
            return b
    return (_st["ultimo"] if _st["ultimo"] in con else (con[0] if con else ""))


def listar(navegador: str = "") -> tuple:
    """-> (navegador, [tabs]) o ("", [])"""
    b = _navegador(navegador)
    return b, list(_st["tabs"].get(b, []))


def comando(op: str, args: dict, navegador: str = "", timeout: float = 10.0) -> dict:
    b = _navegador(navegador)
    if not b:
        return {"error": "No hay ninguna extensión de Orbi conectada. Instálala desde la carpeta extension_pestanas "
                         "(chrome://extensions > Modo desarrollador > Cargar descomprimida)."}
    cid = uuid.uuid4().hex
    _q(b).put({"id": cid, "op": op, "args": args})
    t0 = time.time()
    while time.time() - t0 < timeout:
        with _lock:
            if cid in _st["res"]:
                return _st["res"].pop(cid) or {}
        time.sleep(0.1)
    return {"error": "El navegador no respondió a tiempo."}


def dominio(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:                                      # noqa: BLE001
        return ""


def duplicadas(tabs: list) -> list:
    """Pestañas repetidas (misma URL sin #fragmento): devuelve las SOBRANTES (deja la activa o la primera)."""
    vistos, sobran = {}, []
    for t in sorted(tabs, key=lambda t: (not t.get("active"), t.get("id", 0))):
        k = (t.get("url") or "").split("#")[0]
        if not k or k.startswith(("chrome://", "edge://", "about:")):
            continue
        if k in vistos:
            sobran.append(t)
        else:
            vistos[k] = t
    return sobran


def buscar(tabs: list, texto: str) -> list:
    q = (texto or "").lower().strip()
    return [t for t in tabs if q and (q in (t.get("title") or "").lower() or q in (t.get("url") or "").lower())]
