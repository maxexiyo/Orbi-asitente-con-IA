"""Depuración de proyectos de código para Orbi.

Tres herramientas (se registran en pc_tools.py, permiso «archivos»):
  diagnosticar_proyecto  lee el front + rutas + controllers JUNTOS, hace comprobaciones automáticas (rutas que el front llama y el
                         back no define, routers sin montar, respuestas que no coinciden con lo que el front espera) y manda todo
                         a un modelo con un prompt de depuración (ctx.analyze). Nunca lee .env ni llaves.
  probar_endpoint        pide una URL de localhost (sin cookies, sin seguir redirecciones) y explica qué significa lo que respondió.
  probar_proyecto        «sintaxis» (node --check / php -l / ast de Python: no ejecuta nada) o «correr» un archivo unos segundos
                         y devolver lo que imprimió. «correr» SIEMPRE pide OK en pantalla mostrando el comando exacto.

Seguridad: solo carpetas dentro de las permitidas (docs_reader.inside_roots), sin shell (lista de argumentos), solo node/python/php,
con límite de tiempo, sin ventana, sin stdin y con las variables de entorno de Orbi (keys, tokens) QUITADAS del proceso hijo.
Para arreglar lo que se encuentre, Orbi usa editar_archivo (deja respaldo) y restaurar_archivo si no quedó bien.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import docs_reader as DR

_SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", "venv", ".venv", "env", ".idea", ".vscode", "vendor",
              "coverage", ".next", "uploads", "backups", "bin", "obj"}
_CODE_EXT = {".js", ".mjs", ".cjs", ".ts", ".html", ".htm", ".css", ".scss", ".php", ".py", ".sql", ".ejs", ".pug", ".kt", ".java"}
_SOLO_NOMBRE = {"package.json", "composer.json", "requirements.txt"}
_NUNCA = ("package-lock", "yarn.lock", "pnpm-lock", ".min.", "secret", "credential", "password", "id_rsa")
_MAX_ARCHIVO = 200_000          # bytes: más grande que esto no se lee (bundles, dumps)
_MAX_TEXTO = 70_000             # caracteres que se mandan al modelo
_MAX_POR_ARCHIVO = 14_000
_ENTRADAS = {"app.js", "server.js", "index.js", "main.js", "package.json", "app.py", "main.py", "index.php"}
_CARPETAS_BACK = ("router", "route", "controller", "middleware", "api", "model", "config")


# --------------------------------------------------------------------------- ayudas
def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode()
    return s.lower()


def _dentro(p: Path) -> bool:
    try:
        return bool(DR.inside_roots(p) or DR.inside_roots(p / "_"))
    except Exception:                                          # noqa: BLE001
        return False


def _bases() -> list:
    h = Path.home()
    nombres = ["Documents", "Documentos", "Desktop", "Escritorio", "Downloads", "Descargas"]
    bases = [h / n for n in nombres] + [h / "OneDrive" / n for n in nombres]
    return [b for b in bases if b.is_dir()]


def _resolver_carpeta(ref: str):
    """Carpeta del proyecto a partir de una ruta o un nombre. -> (Path|None, candidatos)."""
    ref = (ref or "").strip().strip('"')
    if not ref:
        return None, []
    p = Path(ref).expanduser()
    if p.is_dir():
        return (p, []) if _dentro(p) else (None, [])
    buscado = _norm(ref)
    hallados, vistos = [], 0
    for base in _bases():
        base_n = len(base.parts)
        for dp, dn, _ in os.walk(base):
            dn[:] = [d for d in dn if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
            vistos += 1
            if vistos > 20000 or len(hallados) >= 8:
                break
            if len(Path(dp).parts) - base_n >= 4:
                dn[:] = []
            for d in dn:
                if buscado in _norm(d):
                    hallados.append(Path(dp) / d)
    exactos = [h for h in hallados if _norm(h.name) == buscado]
    if len(exactos) == 1 or len(hallados) == 1:
        return (exactos or hallados)[0], hallados
    return None, hallados


def _leer(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _claves(texto: str) -> list:
    palabras = re.findall(r"[a-z0-9_]{4,}", _norm(texto))
    vacias = {"para", "pero", "como", "esta", "este", "esto", "algo", "porque", "cuando", "donde", "sirve", "funciona",
              "problema", "error", "proyecto", "pagina", "equipo", "algun", "alguna", "tiene", "hace"}
    return [w for w in dict.fromkeys(palabras) if w not in vacias][:12]


def _es_codigo(f: Path) -> bool:
    n = f.name.lower()
    if n.startswith(".env") or any(x in n for x in _NUNCA):
        return False
    return f.suffix.lower() in _CODE_EXT or n in _SOLO_NOMBRE


def _recolectar(raiz: Path, claves: list) -> list:
    """[(puntaje, Path, texto)] de los archivos de código del proyecto, los más relevantes primero."""
    out = []
    for dp, dn, fn in os.walk(raiz):
        dn[:] = [d for d in dn if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
        for f in fn:
            p = Path(dp) / f
            if not _es_codigo(p):
                continue
            try:
                if p.stat().st_size > _MAX_ARCHIVO:
                    continue
                texto = _leer(p)
            except OSError:
                continue
            rel = _norm(str(p.relative_to(raiz)))
            nt = _norm(texto)
            pts = 0
            if p.name.lower() in _ENTRADAS:
                pts += 5
            if any(c in rel for c in _CARPETAS_BACK):
                pts += 4
            pts += sum(3 for c in claves if c in rel)
            pts += sum(min(nt.count(c), 3) * 2 for c in claves)
            out.append((pts, p, texto))
    out.sort(key=lambda x: (-x[0], str(x[1])))
    return out


# --------------------------------------------------------------------------- comprobaciones automáticas (sin IA)
_RUTA_BACK = re.compile(r"""\b(?:router|app)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*(['"`])(/[^'"`]*)\2""")
_LITERAL_API = re.compile(r"""(['"`])(/api/[A-Za-z0-9_\-/.:]*)\1""")


def _linea(texto: str, pos: int) -> int:
    return texto.count("\n", 0, pos) + 1


def _hallazgos(raiz: Path, archivos: list) -> list:
    """Cosas que se pueden comprobar sin IA. Cada una dice archivo:línea para que se pueda verificar."""
    h = []
    rutas_back, llamadas_front, front_usa_ok = [], [], False
    res_json_directo = []
    for _, p, t in archivos:
        rel = str(p.relative_to(raiz)).replace("\\", "/")
        es_front = p.suffix.lower() in (".html", ".htm", ".js", ".mjs", ".ts") and (
            "fetch(" in t or "XMLHttpRequest" in t or "axios" in t)
        for m in _RUTA_BACK.finditer(t):
            rutas_back.append((m.group(1).upper(), m.group(3), rel, _linea(t, m.start())))
        if es_front:
            for m in _LITERAL_API.finditer(t):
                llamadas_front.append((m.group(2), rel, _linea(t, m.start())))
            if re.search(r"\.ok\b", t):
                front_usa_ok = True
        for m in re.finditer(r"res\s*\.\s*json\s*\(\s*([A-Za-z_]\w*)\s*\)", t):
            res_json_directo.append((m.group(1), rel, _linea(t, m.start())))

    def _patron(ruta):
        return re.compile("^" + re.sub(r":[A-Za-z_]\w*", "[^/]+", re.escape(ruta).replace("\\:", ":")) + "$")

    if rutas_back:
        for ruta, rel, ln in llamadas_front:
            base = ruta.rstrip("/")
            if base.endswith(".") or not base:
                continue
            exacta = any(_patron(r.rstrip("/")).match(base) for _, r, _, _ in rutas_back)
            if exacta:
                continue
            if any(r.startswith(base + "/") for _, r, _, _ in rutas_back):
                h.append(f"{rel}:{ln} POSIBLE: el front llama a «{ruta}», pero el servidor solo define subrutas que empiezan así "
                         f"(ej. {next(r for _, r, _, _ in rutas_back if r.startswith(base + '/'))}). Si el front pide exactamente esa URL, falta esa ruta.")
            else:
                h.append(f"{rel}:{ln} el front llama a «{ruta}» pero ninguna ruta del servidor la define (¿falta la ruta o está mal escrita?).")

    if front_usa_ok:
        for ident, rel, ln in res_json_directo[:6]:
            if ident not in ("ok", "true", "false", "null", "undefined"):
                h.append(f"{rel}:{ln} res.json({ident}) manda el valor directo. El front lee «.ok», así que si «{ident}» es un arreglo u objeto "
                         f"sin «ok», el front lo toma como error. Normalmente debe ser res.json({{ ok: true, ... }}).")

    # routers que existen pero no están montados
    nombres_montados = " ".join(t for _, p, t in archivos if p.name.lower() in ("app.js", "server.js", "index.js", "main.js"))
    if nombres_montados:
        for _, p, t in archivos:
            if p.suffix.lower() == ".js" and re.search(r"module\.exports\s*=\s*router\b", t):
                if p.stem not in nombres_montados:
                    rel = str(p.relative_to(raiz)).replace("\\", "/")
                    h.append(f"{rel}: es un router pero «{p.stem}» no aparece en app.js/server.js (¿falta require y app.use?).")
    return h


# --------------------------------------------------------------------------- diagnosticar_proyecto
_INSTRUCCION = (
    "Eres un depurador experto de aplicaciones web (Node/Express, PHP, Python, MySQL). Te paso el código de UN proyecto: front, "
    "rutas, controllers y, si hay, el esquema SQL. Busca por qué falla lo que describe el usuario.\n"
    "Método: (1) sigue el camino completo de una petición: front -> URL -> ruta montada en el servidor -> middleware -> controller -> SQL -> "
    "respuesta -> cómo la lee el front. (2) Compara el CONTRATO entre ambos lados: la forma exacta de la respuesta (¿objeto con «ok» o "
    "arreglo suelto?), nombres de campos, códigos de error y status HTTP. (3) Revisa que las rutas existan y estén montadas, que los "
    "require/imports apunten a archivos reales, que las tablas/columnas del SQL existan en el esquema, que no haya filas duplicadas por "
    "un JOIN y que un middleware de PÁGINAS no devuelva HTML a una petición de API. (4) Si el usuario pegó un error, explícalo con él.\n"
    "Responde en español, corto y concreto, SIN inventar: usa solo lo que ves en el código y los hallazgos automáticos. Formato:\n"
    "CAUSA MÁS PROBABLE: una o dos frases.\nEVIDENCIA: archivo:línea de cada lado.\nARREGLO: el cambio mínimo, con el código exacto a poner, "
    "y en qué archivo.\nOTROS RIESGOS: solo si son reales (máx. 3).\nSi con lo que ves no se puede saber, di exactamente qué archivo o "
    "qué dato falta (por ejemplo el status de la pestaña Network o el error de la terminal)."
)


def _diagnosticar(args: dict, ctx) -> dict:
    ref = str(args.get("carpeta", "")).strip()
    raiz, cands = _resolver_carpeta(ref)
    if raiz is None:
        if cands:
            return {"error": "Hay varias carpetas con ese nombre; dime cuál.", "candidatos": [str(c) for c in cands]}
        return {"error": "No encontré esa carpeta del proyecto en Documentos, Escritorio o Descargas (o está fuera de las carpetas "
                         "permitidas). Dame la ruta completa o copia el proyecto a Documentos."}
    problema = str(args.get("problema", "")).strip() or "No funciona."
    error = str(args.get("error", "") or "").strip()[:4000]
    claves = _claves(problema + " " + error)
    archivos = _recolectar(raiz, claves)
    if not archivos:
        return {"error": f"No encontré archivos de código en «{raiz.name}»."}
    hallazgos = _hallazgos(raiz, archivos)

    partes, usados, total = [], [], 0
    for _, p, t in archivos:
        if total >= _MAX_TEXTO:
            break
        rel = str(p.relative_to(raiz)).replace("\\", "/")
        t = t[:_MAX_POR_ARCHIVO]
        numerado = "\n".join(f"{i + 1:>4}| {ln}" for i, ln in enumerate(t.splitlines()))
        partes.append(f"=== {rel} ===\n{numerado}")
        usados.append(rel)
        total += len(numerado)

    cabecera = [f"PROYECTO: {raiz.name}", f"PROBLEMA QUE DESCRIBE EL USUARIO: {problema}"]
    if error:
        cabecera.append(f"ERROR O RESPUESTA REAL (terminal / Network):\n{error}")
    if hallazgos:
        cabecera.append("HALLAZGOS AUTOMÁTICOS (verificados con búsqueda de texto):\n- " + "\n- ".join(hallazgos))
    texto = "\n\n".join(cabecera) + "\n\nCÓDIGO:\n" + "\n\n".join(partes)
    informe = ctx.analyze(texto, _INSTRUCCION)
    return {
        "resultado": str(informe)[:6000],
        "archivos_leidos": usados,
        "hallazgos_automaticos": hallazgos,
        "siguiente_paso": ("Si propone un cambio: editar_archivo (deja respaldo) y luego verifica con probar_endpoint o probar_proyecto. "
                           "Si no quedó bien, restaurar_archivo regresa la versión anterior."),
    }


# --------------------------------------------------------------------------- probar_endpoint
class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):                       # noqa: D401
        return None


def _probar_endpoint(args: dict, ctx) -> dict:
    url = str(args.get("url", "")).strip()
    if not url:
        return {"error": "Falta la URL (ej. localhost:3000/api/admin/reportes)."}
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url.lstrip("/")
    u = urllib.parse.urlparse(url)
    if (u.hostname or "").lower() not in ("localhost", "127.0.0.1", "::1"):
        return {"error": "Solo pruebo servidores de tu propia PC (localhost). No hago peticiones a internet."}
    metodo = str(args.get("metodo", "") or "GET").upper()
    if metodo not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"):
        return {"error": "Método no válido (GET, HEAD, POST, PUT, PATCH o DELETE)."}
    cuerpo = args.get("cuerpo")
    if metodo not in ("GET", "HEAD"):
        if not ctx.confirm(f"Orbi quiere mandar un {metodo} a:\n{url}\n\nPuede CAMBIAR o BORRAR datos de tu base de datos."):
            return {"error": "El usuario no autorizó esa petición."}
    datos = None
    cab = {"Accept": "application/json", "User-Agent": "Orbi-depurar"}
    if cuerpo not in (None, ""):
        datos = (cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo)).encode("utf-8")
        cab["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=datos, method=metodo, headers=cab)
    abridor = urllib.request.build_opener(_SinRedireccion)
    estado, tipo, loc, texto = None, "", "", ""
    try:
        with abridor.open(req, timeout=8) as r:
            estado, tipo, texto = r.status, r.headers.get("Content-Type", ""), r.read(60000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        estado, tipo, loc = e.code, e.headers.get("Content-Type", ""), e.headers.get("Location", "")
        try:
            texto = e.read(60000).decode("utf-8", "replace")
        except Exception:                                      # noqa: BLE001
            texto = ""
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        motivo = str(getattr(e, "reason", e))
        return {"error": f"No hay respuesta de {u.netloc}: {motivo[:120]}. ¿El servidor está encendido en ese puerto?"}

    res = {"estado": estado, "tipo_contenido": tipo.split(";")[0], "vista_previa": texto[:700]}
    if loc:
        res["redirige_a"] = loc
    parsed, es_json = None, False
    try:
        parsed, es_json = json.loads(texto), True
    except ValueError:
        pass
    res["es_json"] = es_json
    if es_json:
        res["forma"] = (f"arreglo de {len(parsed)} elementos" if isinstance(parsed, list)
                        else "objeto con las llaves: " + ", ".join(list(parsed)[:12]) if isinstance(parsed, dict) else type(parsed).__name__)

    if estado in (301, 302, 303, 307, 308):
        res["diagnostico"] = (f"Redirige a {loc or 'otra página'}: casi seguro pide iniciar sesión. La ruta EXISTE, pero esta prueba no lleva tu "
                              "sesión; pruébala desde el navegador con tu cuenta. Ojo: si una ruta de API redirige a HTML en vez de dar 401 en JSON, el front "
                              "no puede leerla (el middleware es de páginas).")
    elif estado in (401, 403):
        res["diagnostico"] = "La ruta existe pero exige sesión o rol (esta prueba va sin sesión)."
    elif estado == 404:
        res["diagnostico"] = ("La ruta NO existe en el servidor (o no está montada). Revisa el app.use / require del router y que el servidor "
                              "se haya reiniciado después de agregarla.")
    elif estado and estado >= 500:
        res["diagnostico"] = "La ruta existe pero truena por dentro: mira el error que imprime la terminal donde corre el servidor (probablemente SQL o un campo undefined)."
    elif estado and 200 <= estado < 300:
        if not es_json:
            res["diagnostico"] = "Respondió bien pero NO es JSON; si el front hace .json() va a fallar."
        elif isinstance(parsed, list):
            res["diagnostico"] = "Responde un arreglo suelto. Si el front espera { ok, ... } no va a coincidir."
        elif isinstance(parsed, dict) and "ok" not in parsed:
            res["diagnostico"] = "Responde un objeto sin la llave «ok»; revisa si el front la necesita."
        else:
            res["diagnostico"] = "Respuesta con la forma esperada."
    return res


# --------------------------------------------------------------------------- probar_proyecto
_SECRETO = re.compile(r"(KEY|TOKEN|SECRET|PASS|PWD|CREDENTIAL|AUTH)", re.I)
_EXT_EJEC = {".js": "node", ".mjs": "node", ".cjs": "node", ".py": "python", ".php": "php"}


def _entorno_limpio() -> dict:
    return {k: v for k, v in os.environ.items() if not _SECRETO.search(k)}


def _exe(nombre: str):
    if nombre == "python":
        return shutil.which("python") or shutil.which("python3") or shutil.which("py")
    return shutil.which(nombre)


def _matar(p: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=8,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            p.kill()
    except Exception:                                          # noqa: BLE001
        pass


def _cmd_sintaxis(exe: str, nombre: str, f: Path) -> list:
    if nombre == "node":
        return [exe, "--check", str(f)]
    if nombre == "php":
        return [exe, "-l", str(f)]
    # Python: solo parsea (no importa nada, no deja __pycache__)
    return [exe, "-c", "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read(),sys.argv[1])", str(f)]


def _sintaxis(raiz: Path, archivo: str) -> dict:
    if archivo:
        f = Path(archivo) if Path(archivo).is_absolute() else raiz / archivo
        lista = [f]
    else:
        lista = []
        for dp, dn, fn in os.walk(raiz):
            dn[:] = [d for d in dn if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
            lista += [Path(dp) / x for x in fn if Path(x).suffix.lower() in _EXT_EJEC]
        lista = sorted(lista)[:60]
    errores, revisados, sin_herramienta = [], 0, set()
    for f in lista:
        nombre = _EXT_EJEC.get(f.suffix.lower())
        if not nombre or not f.is_file():
            continue
        exe = _exe(nombre)
        if not exe:
            sin_herramienta.add(nombre)
            continue
        try:
            r = subprocess.run(_cmd_sintaxis(exe, nombre, f), cwd=str(raiz), capture_output=True, text=True, timeout=15,
                               encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, env=_entorno_limpio(),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            errores.append({"archivo": str(f.relative_to(raiz)), "error": "se tardó más de 15 s"})
            continue
        revisados += 1
        if r.returncode != 0:
            errores.append({"archivo": str(f.relative_to(raiz)), "error": ((r.stderr or r.stdout) or "").strip()[:600]})
    res = {"revisados": revisados, "con_errores": errores}
    res["resultado"] = ("Sin errores de sintaxis." if not errores and revisados else
                        f"{len(errores)} archivo(s) con errores de sintaxis." if errores else "No había archivos que revisar.")
    if sin_herramienta:
        res["aviso"] = "No encontré instalado: " + ", ".join(sorted(sin_herramienta)) + " (no pude revisar esos archivos)."
    return res


def _correr(raiz: Path, archivo: str, segundos, ctx) -> dict:
    if not archivo:
        return {"error": "Dime qué archivo correr (ej. app.js)."}
    f = (Path(archivo) if Path(archivo).is_absolute() else raiz / archivo).resolve()
    try:
        f.relative_to(raiz.resolve())
    except ValueError:
        return {"error": "Solo corro archivos dentro de la carpeta del proyecto."}
    nombre = _EXT_EJEC.get(f.suffix.lower())
    if not nombre or not f.is_file():
        return {"error": "Solo corro archivos .js, .py o .php que existan."}
    exe = _exe(nombre)
    if not exe:
        return {"error": f"No tengo «{nombre}» instalado o en el PATH de esta PC."}
    try:
        seg = max(2.0, min(float(segundos or 6), 20.0))
    except (TypeError, ValueError):
        seg = 6.0
    cmd = [exe, str(f)]
    if not ctx.confirm(f"Orbi quiere CORRER tu código unos {int(seg)} s para ver qué imprime:\n\n{nombre} {f.name}\nCarpeta: {raiz}\n\n"
                       "Es tu propio proyecto, pero ejecuta lo que tenga el archivo (puede tocar tu base de datos)."):
        return {"error": "El usuario no autorizó correr el archivo."}
    salida, t0 = [], time.time()
    try:
        p = subprocess.Popen(cmd, cwd=str(raiz), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=_entorno_limpio(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        return {"error": f"No pude arrancarlo: {e}"}

    def _lee():
        for linea in iter(p.stdout.readline, b""):
            salida.append(linea.decode("utf-8", "replace"))

    th = threading.Thread(target=_lee, daemon=True)
    th.start()
    while p.poll() is None and time.time() - t0 < seg:
        if ctx.cancelled():
            break
        time.sleep(0.2)
    sigue = p.poll() is None
    if sigue:
        _matar(p)
    th.join(timeout=2)
    texto = "".join(salida)
    res = {"salida": texto[-3500:] if texto else "(no imprimió nada)", "sigue_corriendo_al_final": sigue,
           "codigo_salida": None if sigue else p.returncode}
    if sigue:
        res["resultado"] = f"Estuvo corriendo {int(seg)} s sin caerse (normal en un servidor) y lo cerré."
    elif p.returncode == 0:
        res["resultado"] = "Terminó sin errores."
    else:
        res["resultado"] = f"Terminó con error (código {p.returncode}). Lee «salida»."
    if re.search(r"EADDRINUSE|address already in use|Address already in use", texto):
        res["aviso"] = "Ese puerto ya está ocupado: seguramente tu servidor ya está encendido. Usa probar_endpoint en vez de correrlo otra vez."
    return res


def _probar_proyecto(args: dict, ctx) -> dict:
    raiz, cands = _resolver_carpeta(str(args.get("carpeta", "")))
    if raiz is None:
        return ({"error": "Hay varias carpetas con ese nombre; dime cuál.", "candidatos": [str(c) for c in cands]} if cands
                else {"error": "No encontré esa carpeta del proyecto dentro de Documentos, Escritorio o Descargas."})
    accion = str(args.get("accion", "") or "sintaxis").lower()
    archivo = str(args.get("archivo", "") or "").strip()
    if accion == "sintaxis":
        return _sintaxis(raiz, archivo)
    if accion == "correr":
        return _correr(raiz, archivo, args.get("segundos"), ctx)
    return {"error": "accion debe ser «sintaxis» o «correr»."}


# --------------------------------------------------------------------------- entrada desde pc_tools.run_tool
def ejecutar(name: str, args: dict, ctx) -> dict:
    if name == "diagnosticar_proyecto":
        return _diagnosticar(args, ctx)
    if name == "probar_endpoint":
        return _probar_endpoint(args, ctx)
    if name == "probar_proyecto":
        return _probar_proyecto(args, ctx)
    return {"error": f"Tool desconocida: {name}"}
