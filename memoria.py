"""Memoria larga de Orbi.

Antes olvidaba pronto porque: (1) solo guardaba 60 notas y mostraba las últimas 30, (2) la charla de la sesión solo se
recordaba 36 h y 10 turnos, (3) la voz en vivo comprime su ventana y suelta lo viejo.

Ahora hay tres capas (archivo `orbi_memoria.json`):
  - episodios: al cerrarse una conversación (silencio largo o al salir) se resume en 2-4 líneas con fecha.
  - resumen_general: cuando hay muchos episodios, los más viejos se funden en un resumen corrido (nunca se pierde lo importante).
  - búsqueda: la tool `buscar_recuerdos` encuentra cualquier nota/episodio/lección por palabras, sin inflar el prompt.

El prompt solo lleva: resumen_general + últimos episodios + notas recientes. Lo demás se consulta a pedido.
"""
import json, os, re, threading, unicodedata
from datetime import datetime
from pathlib import Path

PATH = Path(__file__).parent / "orbi_memoria.json"
MAX_EPISODIOS = 14            # al pasar de aquí, los más viejos se funden en el resumen general
RESUMEN_MAX = 2200            # caracteres del resumen general
_lock = threading.Lock()


def _load() -> dict:
    try:
        d = json.loads(PATH.read_text(encoding="utf-8"))
        d.setdefault("episodios", []); d.setdefault("resumen_general", "")
        return d
    except Exception:                                        # noqa: BLE001
        return {"episodios": [], "resumen_general": ""}


def _save(d: dict) -> None:
    try:
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, PATH)
    except Exception as e:                                   # noqa: BLE001
        print(f"[memoria] no pude guardar: {e}")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _words(s: str) -> set:
    return {w for w in re.findall(r"[a-z0-9ñ]{3,}", _norm(s))}


# ------------------------------------------------------------------ episodios
def _transcript(turns: list, max_chars: int = 5000) -> str:
    out = "\n".join(f"Tú: {t.get('tu', '')[:300]}\nOrbi: {t.get('orbi', '')[:300]}" for t in turns)
    return out[-max_chars:]


def close_episode(turns: list, summarize) -> bool:
    """Resume una conversación y la guarda. summarize(prompt) -> texto (usa el modelo de análisis). Seguro de llamar en un hilo."""
    turns = [t for t in turns if t.get("tu") and t.get("orbi")]
    if len(turns) < 3:                                       # saludos sueltos no valen la pena
        return False
    prompt = ("Resume esta conversación entre un usuario y su asistente Orbi en 2 a 4 líneas, en español, SOLO con lo que vale la pena "
              "recordar después: decisiones, datos personales o de proyectos, pendientes, preferencias, cosas que quedaron a medias. "
              "Sin saludos ni relleno, en tercera persona sobre «el usuario». Si no hay nada que valga la pena, responde exactamente: NADA.\n\n"
              + _transcript(turns))
    try:
        texto = " ".join((summarize(prompt) or "").split())
    except Exception as e:                                   # noqa: BLE001
        print(f"[memoria] no pude resumir: {str(e)[:100]}")
        return False
    if not texto or texto.upper().startswith("NADA"):
        return False
    with _lock:
        d = _load()
        d["episodios"].append({"fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "resumen": texto[:600]})
        _save(d)
    consolidate(summarize)
    return True


def consolidate(summarize) -> None:
    """Si hay demasiados episodios, los más viejos se funden en el resumen general."""
    with _lock:
        d = _load()
        if len(d["episodios"]) <= MAX_EPISODIOS:
            return
        viejos, d["episodios"] = d["episodios"][:-8], d["episodios"][-8:]
    base = d.get("resumen_general", "")
    prompt = ("Actualiza el RESUMEN GENERAL de lo que Orbi sabe de su usuario, fundiendo estos episodios viejos con el resumen actual. "
              f"Máximo {RESUMEN_MAX - 200} caracteres, en español, viñetas cortas agrupadas por tema (proyectos, escuela, gustos, "
              "pendientes). Conserva lo duradero, quita lo que ya caducó o se repite.\n\nRESUMEN ACTUAL:\n" + (base or "(vacío)") +
              "\n\nEPISODIOS VIEJOS:\n" + "\n".join(f"[{e['fecha']}] {e['resumen']}" for e in viejos))
    try:
        nuevo = (summarize(prompt) or "").strip()
    except Exception as e:                                   # noqa: BLE001
        print(f"[memoria] no pude consolidar ahora ({str(e)[:80]}); se intenta luego")
        nuevo = ""
    with _lock:
        cur = _load()
        if nuevo:                                            # ya están fundidos en el resumen: se quitan de la lista
            cur["resumen_general"] = nuevo[:RESUMEN_MAX]
            cur["episodios"] = cur["episodios"][len(viejos):]      # los viejos son siempre los primeros
        # sin red/cuota (nuevo vacío): se conservan todos y se vuelve a intentar en el próximo episodio
        _save(cur)


# ------------------------------------------------------------------ para el prompt
def prompt_text() -> str:
    d = _load()
    partes = []
    if d["resumen_general"]:
        partes.append("Resumen de lo que sabes de tu dueño por conversaciones pasadas:\n" + d["resumen_general"])
    if d["episodios"]:
        partes.append("Conversaciones recientes:\n" + "\n".join(f"- ({e['fecha'][:10]}) {e['resumen']}" for e in d["episodios"][-5:]))
    if partes:
        partes.append("Si te preguntan por algo del pasado que no ves aquí, usa `buscar_recuerdos` antes de decir que no lo sabes.")
    return "\n".join(partes)


# ------------------------------------------------------------------ búsqueda
def search(consulta: str, prof: dict | None = None, n: int = 6) -> list:
    """Busca en notas, lecciones, episodios y resumen. -> [texto]; ordenado por coincidencias (con acentos y sin ellos)."""
    q = _words(consulta)
    if not q:
        return []
    d = _load()
    items = []
    for nt in (prof or {}).get("notas", []):
        items.append((f"({nt.get('fecha', '')}) {nt.get('nota', '')}", nt.get("nota", "")))
    for l in (prof or {}).get("lecciones", []):
        items.append((f"Lección «{l.get('tema', '')}»: {l.get('leccion', '')}", f"{l.get('tema', '')} {l.get('leccion', '')}"))
    for e in d["episodios"]:
        items.append((f"({e['fecha'][:10]}) {e['resumen']}", e["resumen"]))
    for linea in d["resumen_general"].splitlines():
        if linea.strip():
            items.append((linea.strip(), linea))
    scored = []
    for texto, base in items:
        w = _words(base)
        hit = len(q & w) + 0.5 * sum(1 for a in q for b in w if a != b and (a in b or b in a))
        if hit >= 1:
            scored.append((hit, texto))
    scored.sort(key=lambda x: -x[0])
    return [t for _s, t in scored[:n]]
