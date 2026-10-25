"""Memoria de Orbi sobre su dueño, en archivos .md que el usuario puede abrir, leer y editar a mano.

Carpeta: <carpeta de datos de Orbi>/memoria/
    perfil.md            quién es: nombre, a qué se dedica, dónde vive...            (se carga siempre en el prompt)
    gustos.md            lo que le gusta / no le gusta
    preferencias.md      cómo quiere que Orbi se comporte con él
    areas/<tema>.md      un archivo por área o proyecto (escuela, trabajo, un proyecto...)
    personas/<nombre>.md un archivo por persona importante en su vida

Cada archivo: encabezado con name/description y una línea «- dato» por cada cosa que Orbi aprendió.
Orbi la escribe sola con `recordar(dato, categoria)` cuando el usuario cuenta algo duradero, y la consulta con `buscar_recuerdos`
y `leer_memoria`. Lo que edites o borres a mano se respeta: Orbi relee los archivos cada vez.

Nunca se guarda: contraseñas, números de tarjeta o cuenta, documentos de identidad, ni nada que el usuario no haya contado él.
"""
import os, re, threading, unicodedata
from datetime import datetime
from pathlib import Path

MAX_FILE = 20_000          # bytes por archivo: si se llena, hay que condensar
MAX_PROMPT_PERFIL = 1500   # caracteres del perfil.md que van siempre en el prompt
MAX_LISTING = 40
_lock = threading.Lock()

BASE = {
    "perfil": ("perfil", "Quién es el usuario: nombre, ocupación, lugar, datos estables"),
    "gustos": ("gustos", "Gustos, aficiones y cosas que no le gustan"),
    "preferencias": ("preferencias", "Cómo prefiere que Orbi se comporte con él (tono, formato, qué evitar)"),
}

_DESC_AREA = "Área o proyecto del usuario: contexto, decisiones y estado"
_DESC_PERSONA = "Persona importante en la vida del usuario y relación con él"


def root() -> Path:
    try:
        import perfil
        base = Path(perfil.ROOT)
    except Exception:                                      # noqa: BLE001
        base = Path(__file__).parent
    return base / "memoria"


def _fold(t: str) -> str:
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _slug(t: str) -> str:
    s = re.sub(r"[^a-z0-9ñ]+", "-", _fold(t)).strip("-")
    return s[:40] or "general"


def _target(categoria: str) -> tuple:
    """categoria libre -> (ruta relativa, descripción por defecto). «areas/escuela», «persona: Ana», «gustos», «perfil»..."""
    c = _fold(categoria).strip()
    for key, (stem, desc) in BASE.items():
        if c.startswith(key[:5]):
            return f"{stem}.md", desc
    if c.startswith(("person", "gente", "famil", "amig", "contacto")):
        nombre = re.split(r"[:/]", categoria, 1)[1] if re.search(r"[:/]", categoria) else "general"
        return f"personas/{_slug(nombre)}.md", _DESC_PERSONA
    nombre = re.split(r"[:/]", categoria, 1)[1] if re.search(r"[:/]", categoria) else categoria
    nombre = re.sub(r"^(areas?|proyectos?|temas?)\b", "", _fold(nombre)).strip(" :/-") or "general"
    return f"areas/{_slug(nombre)}.md", _DESC_AREA


def _safe(rel: str):
    p = (root() / rel).resolve()
    try:
        p.relative_to(root().resolve())
    except ValueError:
        return None
    return p if p.suffix == ".md" else None


def _split(text: str) -> tuple:
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, flags=re.S)
    return (m.group(1), m.group(2)) if m else ("", text)


def _desc(text: str) -> str:
    head, _ = _split(text)
    m = re.search(r"^description:\s*(.+)$", head, flags=re.M)
    return m.group(1).strip() if m else ""


def _facts(text: str) -> list:
    return [ln[2:].strip() for ln in _split(text)[1].splitlines() if ln.startswith("- ")]


# ------------------------------------------------------------------ escribir
def append(categoria: str, dato: str) -> dict:
    """Agrega un dato. -> {ok, archivo} | {error}. No repite lo que ya está."""
    dato = " ".join(str(dato or "").split())[:400]
    if len(dato) < 3:
        return {"error": "Dime qué dato guardar."}
    rel, desc = _target(categoria or "perfil")
    p = _safe(rel)
    if p is None:
        return {"error": "Categoría no válida."}
    with _lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            text = p.read_text(encoding="utf-8")
            if _fold(dato) in {_fold(f) for f in _facts(text)}:
                return {"ok": True, "archivo": rel, "nota": "ya estaba anotado"}
            if len(text.encode("utf-8")) > MAX_FILE:
                return {"error": f"{rel} está lleno: condensa su contenido (leer_memoria y reescribe lo importante) antes de agregar."}
            if not text.endswith("\n"):
                text += "\n"
            p.write_text(text + f"- {dato}\n", encoding="utf-8")
        else:
            name = p.stem
            p.write_text(f"---\nname: {name}\ndescription: {desc}\nsources: [orbi]\n---\n\n- {dato}\n", encoding="utf-8")
    return {"ok": True, "archivo": rel}


def migrar_notas(prof: dict) -> None:
    """Una sola vez: pasa las «notas» viejas del perfil a memoria/notas.md (para que el usuario también las vea)."""
    try:
        notas = prof.get("notas") or []
        p = root() / "notas.md"
        if not notas or p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"- ({n.get('fecha', '')}) {n.get('nota', '')}" for n in notas if n.get("nota")]
        p.write_text("---\nname: notas\ndescription: Notas anteriores de Orbi sobre el usuario (de antes de esta memoria)\n"
                     "sources: [orbi]\n---\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------------ leer
def files() -> list:
    r = root()
    if not r.is_dir():
        return []
    return sorted(p for p in r.rglob("*.md") if p.is_file())


def listing() -> list:
    out = []
    for p in files()[:MAX_LISTING]:
        try:
            out.append((p.relative_to(root()).as_posix(), _desc(p.read_text(encoding="utf-8")), p.stat().st_size))
        except OSError:
            pass
    return out


def read(rel: str, max_chars: int = 6000) -> dict:
    rel = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        li = listing()
        return {"resultado": [f"{r} — {d}" for r, d, _s in li]} if li else {"resultado": "Todavía no hay nada guardado en la memoria."}
    if not rel.endswith(".md"):
        rel += ".md"
    p = _safe(rel)
    if p is None or not p.is_file():
        li = [r for r, _d, _s in listing()]
        return {"error": f"No existe «{rel}».", "archivos": li}
    return {"resultado": p.read_text(encoding="utf-8")[:max_chars], "archivo": rel}


def search(consulta: str, limit: int = 8) -> list:
    toks = [t for t in re.findall(r"[a-z0-9ñ]+", _fold(consulta)) if len(t) > 2]
    if not toks:
        return []
    hits = []
    for p in files():
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = p.relative_to(root()).as_posix()
        for f in _facts(text):
            ft = _fold(f + " " + rel)
            sc = sum(1 for t in toks if t in ft)
            if sc:
                hits.append((sc, f"[{rel}] {f}"))
    hits.sort(key=lambda h: -h[0])
    return [h[1] for h in hits[:limit]]


def prompt_text() -> str:
    """Bloque para el prompt de la voz: perfil.md completo + índice del resto."""
    parts = []
    try:
        pf = root() / "perfil.md"
        if pf.is_file():
            facts = _facts(pf.read_text(encoding="utf-8"))
            if facts:
                parts.append("MEMORIA — perfil de tu dueño (lo escribiste tú o él, en perfil.md):\n"
                             + "\n".join("- " + f for f in facts)[:MAX_PROMPT_PERFIL])
        li = [(r, d) for r, d, _s in listing() if r != "perfil.md"]
        if li:
            parts.append("MEMORIA — otros archivos que tienes sobre tu dueño (léelos con `leer_memoria` o `buscar_recuerdos` "
                         "cuando el tema salga):\n" + "\n".join(f"- {r}: {d}" for r, d in li))
    except OSError:
        return ""
    return "\n\n".join(parts)


def open_folder() -> None:
    r = root()
    r.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(str(r))                                # noqa: S606  (Windows)
    except Exception:                                      # noqa: BLE001
        pass
