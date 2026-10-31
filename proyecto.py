"""Proyectos de código de varios archivos, hechos de principio a fin SIN detenerse a la mitad.

Por qué existe: la voz de Orbi (Gemini Live) contesta por turnos: hacía un pedazo, decía «ya terminé X» y esperaba a que le dijeras que siguiera.
Aquí el trabajo lo lleva un bucle propio que NO se detiene hasta acabar, con un modelo de texto normal:

  1. PLAN    un esquema con los archivos del proyecto, en orden (lo que otros archivos necesitan va primero).
  2. ARCHIVOS cada archivo se escribe por separado, viendo el plan y lo ya escrito (para que nombres, funciones e imports coincidan).
  3. REVISIÓN los .py se comprueban con compile() y los .json con json; si fallan se repara el archivo una vez.
  4. RESUMEN  qué se hizo, dónde quedó y cómo ejecutarlo.

Seguridad: solo escribe DENTRO de la carpeta del proyecto (rutas relativas, sin «..»), solo extensiones de código/texto, máximo 25 archivos
y 60 KB por archivo. NUNCA ejecuta el código que genera.
"""
import json, re, time, unicodedata
from pathlib import Path

EXT_OK = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".md", ".txt", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".sql",
          ".sh", ".bat", ".ps1", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".php", ".rb", ".kt", ".xml", ".csv", ".gitignore", ".env.example"}
MAX_FILES = 25
MAX_BYTES = 60_000
CTX_CHARS = 24_000          # cuánto de lo ya escrito se le muestra al modelo al escribir el siguiente archivo


def _slug(t: str) -> str:
    t = unicodedata.normalize("NFD", str(t or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "proyecto"


def _limpiar(txt: str) -> str:
    """Quita las cercas ``` si el modelo las puso."""
    t = (txt or "").strip()
    m = re.match(r"^```[a-zA-Z0-9_+.-]*\n(.*?)\n?```\s*$", t, flags=re.S)
    return (m.group(1) if m else t).rstrip() + "\n"


def _ruta_segura(base: Path, ruta: str):
    r = str(ruta or "").strip().replace("\\", "/").lstrip("/")
    if not r or ".." in r.split("/") or re.match(r"^[A-Za-z]:", r):
        return None
    p = (base / r).resolve()
    try:
        p.relative_to(base.resolve())
    except ValueError:
        return None
    suf = p.suffix.lower() if p.suffix else p.name.lower()
    if suf not in EXT_OK and p.name.lower() not in (".gitignore", "readme", "license", "requirements.txt", "dockerfile"):
        return None
    return p


def _json_de(txt: str):
    m = re.search(r"\{.*\}", txt or "", flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def generar(objetivo: str, base_dir: Path, gen, progress=lambda t: None, nombre: str = "", lenguaje: str = "") -> dict:
    """gen(prompt, tokens=16384, thinking=None) -> texto. progress(texto) informa cada paso. Devuelve dict con carpeta, archivos y avisos."""
    objetivo = str(objetivo or "").strip()
    if len(objetivo) < 10:
        return {"error": "Describe qué debe hacer el proyecto (al menos una frase)."}
    t0 = time.time()
    progress("Planeando el proyecto")
    plan = _json_de(gen(
        "Eres un ingeniero de software senior. Diseña un proyecto PEQUEÑO pero COMPLETO y funcional que cumpla lo pedido.\n"
        f"PEDIDO: {objetivo}\n" + (f"LENGUAJE/STACK: {lenguaje}\n" if lenguaje else "") +
        f"Responde SOLO un JSON: {{\"nombre\": \"nombre-corto\", \"resumen\": \"qué hace en 1-2 frases\", \"como_ejecutar\": \"comandos exactos\", "
        f"\"archivos\": [{{\"ruta\": \"ruta/relativa.ext\", \"descripcion\": \"qué contiene y qué expone (funciones/clases)\"}}]}}.\n"
        f"Reglas: máximo {MAX_FILES} archivos (menos es mejor); el orden importa: primero lo que otros archivos importan; incluye README.md y "
        "requirements.txt/package.json si hacen falta; rutas relativas; nada de binarios ni imágenes.", tokens=4096, thinking=None))
    archivos = [a for a in (plan or {}).get("archivos", []) if isinstance(a, dict) and a.get("ruta")][:MAX_FILES]
    if not archivos:
        return {"error": "No pude armar el plan del proyecto (el modelo no devolvió archivos). Intenta de nuevo o describe el proyecto con más detalle."}
    carpeta = Path(base_dir) / (_slug(nombre or plan.get("nombre") or objetivo[:30]))
    n = 2
    base_slug = carpeta
    while carpeta.exists():                                   # nunca pisar un proyecto anterior
        carpeta = Path(str(base_slug) + f"-{n}")
        n += 1
    carpeta.mkdir(parents=True, exist_ok=True)
    indice = "\n".join(f"- {a['ruta']}: {a.get('descripcion', '')}" for a in archivos)
    escritos, avisos, vistos = [], [], {}
    for i, a in enumerate(archivos, 1):
        p = _ruta_segura(carpeta, a["ruta"])
        if p is None:
            avisos.append(f"Omití «{a['ruta']}» (ruta o tipo de archivo no permitido).")
            continue
        progress(f"Escribiendo {a['ruta']} ({i}/{len(archivos)})")
        previos, usados = [], 0
        for r, c in vistos.items():
            seg = f"--- {r} ---\n{c}"
            if usados + len(seg) > CTX_CHARS:
                seg = f"--- {r} --- (resumen: primeras líneas)\n" + "\n".join(c.splitlines()[:25])
            previos.append(seg); usados += len(seg)
        prompt = (f"Estás construyendo este proyecto: {objetivo}\n\nPLAN COMPLETO (todos los archivos):\n{indice}\n\n"
                  + (("ARCHIVOS YA ESCRITOS (usa exactamente sus nombres de funciones, clases e imports):\n" + "\n".join(previos) + "\n\n") if previos else "")
                  + f"Escribe AHORA el archivo «{a['ruta']}»: {a.get('descripcion', '')}.\n"
                    "Debe ser código real, completo y funcional (nada de «aquí va tu código», «TODO» ni pedazos). Manejo de errores razonable y "
                    "comentarios breves en español. Responde ÚNICAMENTE con el contenido del archivo: sin explicaciones, sin cercas ```.")
        try:
            txt = _limpiar(gen(prompt, tokens=16384, thinking="low"))
        except Exception as e:                                # noqa: BLE001
            avisos.append(f"{a['ruta']}: no pude generarlo ({type(e).__name__}).")
            continue
        if len(txt.encode("utf-8")) > MAX_BYTES:
            avisos.append(f"{a['ruta']}: quedó muy grande ({len(txt) // 1000} mil caracteres); lo recorté.")
            txt = txt[:MAX_BYTES]
        # revisión: sintaxis
        err = None
        if p.suffix.lower() == ".py":
            try:
                compile(txt, str(p), "exec")
            except SyntaxError as e:
                err = f"SyntaxError línea {e.lineno}: {e.msg}"
        elif p.suffix.lower() == ".json":
            try:
                json.loads(txt)
            except ValueError as e:
                err = f"JSON inválido: {e}"
        if err:
            progress(f"Corrigiendo {a['ruta']}")
            try:
                fix = _limpiar(gen(f"El archivo «{a['ruta']}» tiene este error: {err}\nCorrígelo y responde ÚNICAMENTE con el archivo completo, "
                                   f"sin cercas ni explicaciones.\n\n{txt}", tokens=16384, thinking="low"))
                if p.suffix.lower() == ".py":
                    compile(fix, str(p), "exec")
                elif p.suffix.lower() == ".json":
                    json.loads(fix)
                txt, err = fix, None
            except Exception:                                  # noqa: BLE001
                pass
        if err:
            avisos.append(f"{a['ruta']}: quedó con un error sin resolver ({err}).")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
        vistos[a["ruta"]] = txt
        escritos.append(a["ruta"])
    if not escritos:
        return {"error": "No se pudo escribir ningún archivo.", "avisos": avisos}
    progress("Listo")
    return {"resultado": f"Proyecto «{carpeta.name}» listo con {len(escritos)} archivo(s) en {carpeta}.", "carpeta": str(carpeta),
            "archivos": escritos, "como_ejecutar": str(plan.get("como_ejecutar", ""))[:400], "resumen": str(plan.get("resumen", ""))[:300],
            "segundos": int(time.time() - t0), **({"avisos": avisos} if avisos else {}),
            "nota": "El código se escribió pero NO se ejecutó: pruébalo antes de confiar en él."}
