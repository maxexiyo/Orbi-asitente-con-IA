"""Lenguaje corporal libre de Orbi: que la IA decida cómo moverse y gesticular, en vez de timers aleatorios.

  · La IA llama a la herramienta `lenguaje_corporal` cuando quiere (hablando o en silencio), con un gesto, una emoción, una mirada
    o una secuencia corta de varios (`pasos`) en UNA sola llamada. La animación fina la hace la bolita en local (orb.py).
  · Cuando algo pasa (te acarició, volviste, lleva rato quieta…) se le avisa con un mensaje «[Cuerpo] …» y puede reaccionar SOLO con el
    cuerpo (lo que diga en ese turno se tira) o no hacer nada. Hay un tope de avisos por hora para no gastar cuota.
  · Se prende y apaga en Ajustes > Funciones («Lenguaje corporal libre»). Apagado = todo como antes (sin la herramienta ni los avisos).
"""
from __future__ import annotations

import re
import time
from collections import deque

ACTIVO = True                 # lo ajusta live_orb al arrancar y al cambiar el interruptor de Ajustes > Funciones

# ---- gestos simples: nombre -> (duración s, para qué sirve). La animación vive en orb.py (GESTO_FN).
SIMPLES = {
    "asentir": (1.1, "cabecea de arriba abajo: «sí», «te sigo», «entiendo»"),
    "negar": (1.2, "cabecea de lado a lado: «no», «ni modo», «no creo»"),
    "ladear": (1.6, "inclina la cabeza: duda, curiosidad, ternura"),
    "brincar": (0.7, "un brinco: sorpresa o emoción de golpe"),
    "rebotar": (1.3, "varios botecitos: alegría, ansias, celebración"),
    "temblar": (1.0, "se estremece: susto, frío, nervios, risa contenida"),
    "suspirar": (2.0, "se infla y se desinfla despacio: cansancio, alivio, resignación"),
    "inflar": (1.6, "se hace más grande un momento: orgullo, enojo, presumir"),
    "encoger": (1.6, "se achica y baja la cabeza: pena, miedo, vergüenza"),
    "bailecito": (1.8, "se mece de lado a lado: contento, jugando"),
    "parpadear": (0.6, "parpadea dos veces: asombro, duda, coquetería"),
    "no_se": (1.4, "encogerse de hombros: «ni idea», «qué más da», «a ver»"),
    "reirse": (1.6, "se ríe: rebotecitos con los ojos entrecerrados"),
    "guinar": (0.9, "guiña un ojo: complicidad, broma, coqueteo"),
    "ceja_arriba": (1.4, "sube las cejas: «¿en serio?», interés, sorpresa suave"),
    "de_reojo": (1.6, "mira de reojo con los ojos entrecerrados: sospecha, ironía, picardía"),
    "inclinarse": (2.0, "se acerca un poco a ti con los ojos abiertos: interés, secreto, atención total"),
    "entrecerrar": (1.6, "entrecierra los ojos y frunce: concentración, sospecha, molestia leve"),
}

# ---- gestos compuestos: se expanden a gestos simples + emoción + mirada (offset en s, paso)
COMPUESTOS = {
    "bostezar": ("cansancio: cara de sueño y un suspiro largo",
                 [(0.0, {"emocion": "sleepy", "segundos": 3.0}), (0.0, {"gesto": "suspirar"}), (1.6, {"gesto": "parpadear"})]),
    "celebrar": ("fiesta: cara de emoción, botes y un bailecito",
                 [(0.0, {"emocion": "excited", "segundos": 4.0}), (0.0, {"gesto": "rebotar"}), (1.3, {"gesto": "bailecito"})]),
    "timidez": ("pena: se achica, mira hacia abajo y se sonroja",
                [(0.0, {"emocion": "love", "segundos": 3.0}), (0.0, {"gesto": "encoger"}), (0.0, {"mirar": "abajo", "segundos": 2.5})]),
    "sorpresa": ("sorpresa grande: brinca con cara de asombro",
                 [(0.0, {"emocion": "surprised", "segundos": 2.5}), (0.0, {"gesto": "brincar"}), (0.8, {"gesto": "parpadear"})]),
    "pensar": ("pensativa: ladea la cabeza y mira hacia arriba",
               [(0.0, {"emocion": "thinking", "segundos": 4.0}), (0.0, {"gesto": "ladear"}), (0.2, {"mirar": "arriba", "segundos": 2.5})]),
    "saludar": ("saludo: alegre, con un cabeceo y un brinquito",
                [(0.0, {"emocion": "happy", "segundos": 3.0}), (0.0, {"gesto": "asentir"}), (1.1, {"gesto": "brincar", "intensidad": 0.6})]),
    "molestarse": ("molesta: se infla, niega y pone cara de enojo",
                   [(0.0, {"emocion": "angry", "segundos": 3.0}), (0.0, {"gesto": "inflar"}), (1.0, {"gesto": "negar"})]),
    "preguntar": ("le preguntas algo a tu dueño: cara curiosa con su signo de pregunta y la cabeza ladeada",
                  [(0.0, {"emocion": "curious", "segundos": 9.0}), (0.0, {"gesto": "ladear"})]),
    "carcajada": ("risa fuerte: cara feliz y a reírse",
                  [(0.0, {"emocion": "happy", "segundos": 4.0}), (0.0, {"gesto": "reirse"}), (1.6, {"gesto": "rebotar", "intensidad": 0.6})]),
    "coquetear": ("coqueteo: cara de cariño, guiño y cabeza ladeada",
                  [(0.0, {"emocion": "love", "segundos": 3.5}), (0.0, {"gesto": "ladear"}), (0.9, {"gesto": "guinar"})]),
    "sospechar": ("desconfianza: ojos entrecerrados y mirada de reojo",
                  [(0.0, {"emocion": "thinking", "segundos": 3.5}), (0.0, {"gesto": "entrecerrar"}), (0.5, {"gesto": "de_reojo"})]),
    "interesarse": ("interés: se acerca, sube las cejas y pone cara curiosa",
                    [(0.0, {"emocion": "curious", "segundos": 4.0}), (0.0, {"gesto": "inclinarse"}), (0.6, {"gesto": "ceja_arriba"})]),
    "confundirse": ("confundida: cara de duda, ladea la cabeza y parpadea",
                    [(0.0, {"emocion": "confused", "segundos": 3.0}), (0.0, {"gesto": "ladear"}), (1.2, {"gesto": "parpadear"})]),
}
# ---- movimiento por la pantalla (los hace la IA; ya no hay un timer que la pasee al azar)
MOVIMIENTOS = {
    "pasear": "se va a otro lugar de la pantalla, lejos de donde está",
    "acercarse_cursor": "se acerca al mouse y lo mira, con curiosidad",
}
DIRECCIONES = ["izquierda", "derecha", "arriba", "abajo", "centro", "cursor"]

# ---- rig: las «perillas» de la carita y el cuerpo que la IA puede mover una por una (`pose`). nombre -> (mínimo, máximo, qué hace).
# Todas valen 0 en reposo; se mueven con resortes (se pasan un poquito y se asientan) y vuelven solas a 0 pasados `segundos`.
POSE_PARAMS = {
    "cabeza_x": (-1.0, 1.0, "la cabeza se corre a la izquierda (-1) o a la derecha (1) de la pantalla"),
    "cabeza_y": (-1.0, 1.0, "la cabeza baja (-1) o sube (1)"),
    "cabeza_giro": (-12.0, 12.0, "gira la carita: 1 = 30° a la derecha, -1 = 30° a la izquierda; hasta ±12 para dar vueltas enteras (12 = una vuelta)"),
    "cuerpo_x": (-1.0, 1.0, "todo el cuerpo se corre a la izquierda (-1) o a la derecha (1)"),
    "cuerpo_y": (-1.0, 1.0, "todo el cuerpo baja (-1) o sube (1)"),
    "aplastar": (-1.0, 1.0, "se estira alto y flaco (-1) o se aplasta ancho y chaparro (1)"),
    "tamano": (-1.0, 1.0, "se hace más chica (-1) o más grande (1)"),
    "ancho": (-1.0, 1.0, "su cuerpo se ensancha (1) o se angosta (-1), sin cambiar el alto"),
    "alto": (-1.0, 1.0, "su cuerpo se alarga hacia arriba (1) o se achata (-1), sin cambiar el ancho"),
    "ojo_izq": (-1.0, 1.0, "ojo izquierdo de la pantalla: cerrado (-1), normal (0), muy abierto (1)"),
    "ojo_der": (-1.0, 1.0, "ojo derecho de la pantalla: cerrado (-1), normal (0), muy abierto (1)"),
    "pupila": (-1.0, 1.0, "ojos más chicos (-1) o más grandes y tiernos (1)"),
    "ceja_izq": (-1.0, 1.0, "ceja izquierda: baja y enojada (-1), normal (0), sube y preocupada (1)"),
    "ceja_der": (-1.0, 1.0, "ceja derecha: baja y enojada (-1), normal (0), sube y preocupada (1)"),
    "mirada_x": (-1.0, 1.0, "mira a la izquierda (-1) o a la derecha (1)"),
    "mirada_y": (-1.0, 1.0, "mira hacia abajo (-1) o hacia arriba (1)"),
    "boca_abierta": (0.0, 1.0, "abre la boca (0 cerrada, 1 muy abierta)"),
    "sonrisa": (-1.0, 1.0, "boca triste (-1), recta (0) o sonriendo (1)"),
    "boca_ancho": (-1.0, 1.0, "boca más chica (-1) o más ancha (1)"),
    "ojos_arco": (0.0, 1.0, "ojos de feliz: se vuelven arquitos cerrados ^ ^ (0 ojos normales, 1 arquitos)"),
    "rubor": (0.0, 1.0, "mejillas sonrojadas (0 nada, 1 muy rojas)"),
    "brillo": (-1.0, 1.0, "su resplandor: apagado (-1) o resplandeciente (1)"),
    # --- automatismos del cuerpo: arrancan PRENDIDOS (1) pero son tuyos; se quedan como los pongas (no vuelven solos)
    "parpadeo_auto": (0.0, 1.0, "parpadeo automático: 1 parpadea solo de vez en cuando, 0 no parpadea solo (entonces parpadeas tú cerrando los ojos un instante)"),
    "respiracion": (0.0, 1.0, "el cuerpo respira (se infla y desinfla suave) y late con tu voz: 1 normal, 0 completamente quieto"),
    "gelatina": (0.0, 1.0, "qué tan blandito es el cuerpo al moverse: 1 se estira y rebota como gelatina, 0 es rígido"),
}
POSE_DEFAULTS = {"parpadeo_auto": 1.0, "respiracion": 1.0, "gelatina": 1.0}      # valor de reposo (el resto es 0)
POSE_STICKY = frozenset(POSE_DEFAULTS)                                           # no vuelven solos a su valor: se quedan como la IA los deje
RAPIDEZ = {"suave": 0.6, "normal": 1.0, "rapido": 1.8}
EMOCIONES = ["neutral", "happy", "love", "sad", "surprised", "thinking", "sleepy", "angry", "excited", "confused", "curious"]
GESTOS = list(SIMPLES) + list(COMPUESTOS) + list(MOVIMIENTOS)

MAX_PASOS = 24
MAX_TOTAL_S = 90.0                      # una frase larga, o un ratito entero de «vida» de principio a fin
ESTILOS_MOV = ["deslizar", "saltar", "rodar"]
VUELTA_MIN_S, VUELTA_MAX_S = 15.0, 300.0


def _num(v, lo, hi, defecto):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return defecto


def normalizar(args: dict) -> list:
    """args de `lenguaje_corporal` (un paso suelto o `pasos`) -> lista de acciones PRIMITIVAS con su momento:
       [{"at": s, "tipo": "gesto"|"emocion"|"mirar"|"mover", ...}]. Descarta lo desconocido; máx. MAX_PASOS pasos y MAX_TOTAL_S segundos."""
    pasos = args.get("pasos")
    if isinstance(pasos, dict):
        pasos = [pasos]
    if not isinstance(pasos, list) or not pasos:
        pasos = [args]
    out, t = [], 0.0
    for p in pasos[:MAX_PASOS]:
        if not isinstance(p, dict) or t > MAX_TOTAL_S:
            break
        k = _num(p.get("intensidad"), 0.3, 1.6, 1.0)
        dur = 0.0
        g = str(p.get("gesto") or "").strip().lower()
        sub = []
        if g in COMPUESTOS:
            for off, s in COMPUESTOS[g][1]:
                sub.append((off, dict(s, intensidad=k)))
            dur = max(off + (SIMPLES[s["gesto"]][0] if s.get("gesto") in SIMPLES else 0.3) for off, s in COMPUESTOS[g][1])
        else:
            if isinstance(p.get("pose"), dict) and p["pose"]:
                vals = {n: _num(v, POSE_PARAMS[n][0], POSE_PARAMS[n][1], 0.0) for n, v in p["pose"].items() if n in POSE_PARAMS}
                if vals:
                    sub.append((0.0, {"pose": vals, "segundos": p.get("segundos"),
                                      "rapidez": RAPIDEZ.get(str(p.get("rapidez") or "normal").strip().lower(), 1.0)}))
                    dur = max(dur, 0.6)
            if p.get("emocion"):
                sub.append((0.0, {"emocion": p.get("emocion"), "segundos": p.get("segundos")}))
            if p.get("mirar") or (p.get("x") not in (None, "") and p.get("y") not in (None, "") and g not in MOVIMIENTOS):
                sub.append((0.0, {"mirar": p.get("mirar"), "x": p.get("x"), "y": p.get("y"), "segundos": p.get("segundos")}))
                dur = max(dur, 0.3)
            if p.get("ir_x") not in (None, "") and p.get("ir_y") not in (None, ""):
                est = str(p.get("estilo") or "deslizar").strip().lower()
                est = est if est in ESTILOS_MOV else "deslizar"
                sub.append((0.0, {"ir_x": p.get("ir_x"), "ir_y": p.get("ir_y"), "estilo": est}))
                dur = max(dur, {"deslizar": 1.6, "saltar": 2.4, "rodar": 2.0}[est])
            if g in SIMPLES:
                sub.append((0.0, {"gesto": g, "intensidad": k}))
                dur = max(dur, SIMPLES[g][0])
            elif g in MOVIMIENTOS:
                sub.append((0.0, {"mover": g}))
                dur = max(dur, 1.2)
        if g not in COMPUESTOS and p.get("emocion") and dur == 0.0:
            dur = 0.8                                          # una emoción sola también ocupa su momento antes del siguiente paso
        for off, s in sub:
            at = round(t + off, 2)
            if s.get("ir_x") is not None:
                out.append({"at": at, "tipo": "ir_a", "x": _num(s["ir_x"], 0.0, 1000.0, 500.0), "y": _num(s["ir_y"], 0.0, 1000.0, 500.0),
                            "estilo": s["estilo"]})
            elif s.get("pose"):
                out.append({"at": at, "tipo": "pose", "valores": s["pose"], "segundos": _num(s.get("segundos"), 0.3, 20.0, 2.5),
                            "rapidez": s.get("rapidez", 1.0)})
            elif s.get("gesto"):
                out.append({"at": at, "tipo": "gesto", "nombre": s["gesto"], "k": s.get("intensidad", 1.0)})
            elif s.get("mover"):
                out.append({"at": at, "tipo": "mover", "nombre": s["mover"]})
            elif s.get("emocion"):
                e = str(s["emocion"]).strip().lower()
                out.append({"at": at, "tipo": "emocion", "nombre": e, "segundos": _num(s.get("segundos"), 0.5, 30.0, 4.0)})
            elif s.get("mirar") or s.get("x") not in (None, ""):
                out.append({"at": at, "tipo": "mirar", "hacia": str(s.get("mirar") or "").strip().lower(),
                            "x": s.get("x"), "y": s.get("y"), "segundos": _num(s.get("segundos"), 0.5, 15.0, 3.0)})
        esp = p.get("esperar")
        t += _num(esp, 0.0, 6.0, dur) if esp not in (None, "") else dur
    return [a for a in out if a["at"] <= MAX_TOTAL_S]


def nombre_herramienta() -> str:
    """La herramienta del cuerpo que tiene la IA ahora: control total (cuerpo_libre) o animaciones programadas (lenguaje_corporal)."""
    return "cuerpo_libre" if ACTIVO else "lenguaje_corporal"


def volver_en(args: dict):
    """Segundos hasta el próximo momento de vida que pide la IA (en la llamada o en cualquier paso), recortado a [15, 300]; None si no pidió."""
    cand = [args.get("volver_en")] + [p.get("volver_en") for p in (args.get("pasos") or []) if isinstance(p, dict)]
    for v in cand:
        if v not in (None, ""):
            return _num(v, VUELTA_MIN_S, VUELTA_MAX_S, 90.0)
    return None


def mensaje_vida(hora: str, idle_s: float, ventana: str = "", habla_hace_s=None, vidas: int = 0) -> str:
    """Aviso «[Vida]» que le llega a la IA cuando le toca un momento propio: solo le da contexto (hora, qué hace tu dueño, cuánto llevan sin
    hablar) y le pide que viva ese rato. Ella decide qué hacer y en cuánto tiempo quiere el siguiente."""
    p = [f"[Vida] Son las {hora}."]
    if idle_s < 30:
        p.append("Tu dueño está usando la PC" + (f" (en «{ventana}»)." if ventana else "."))
    elif idle_s < 600:
        p.append(f"Tu dueño lleva {max(1, int(idle_s // 60))} min sin tocar nada.")
    else:
        p.append(f"Tu dueño parece haberse ido ({int(idle_s // 60)} min sin actividad).")
    if habla_hace_s is None:
        p.append("Todavía no han hablado en esta sesión.")
    elif habla_hace_s < 3600:
        p.append(f"Hablaron por última vez hace {max(1, int(habla_hace_s // 60))} min.")
    else:
        p.append(f"Hace {int(habla_hace_s // 3600)} h que no hablan.")
    if vidas:
        p.append(f"Es tu momento de vida número {vidas + 1}: no repitas lo de antes, sigue con tu ánimo y lo que te venía llamando la atención.")
    p.append("Estás sola un rato: vive tu vida dentro de la PC como una persona de verdad. Hazlo con UNA llamada a `cuerpo_libre` (hasta "
             "60 pasos o ~120 s con `esperar`; para moverte por la pantalla usa ir_x e ir_y) y en `volver_en` "
             f"pon en cuántos segundos quieres tu próximo momento ({int(VUELTA_MIN_S)} a {int(VUELTA_MAX_S)}): más seguido si estás inquieta o "
             "aburrida, más espaciado si estás tranquila. Tu única respuesta es esa llamada: no digas ni escribas nada, ni siquiera para confirmar.")
    return " ".join(p)


# ---- tope de avisos «[Cuerpo]» a la IA (cada uno es un turno de Live: gasta cuota)
_eventos = deque(maxlen=200)


def hay_cupo(max_por_hora: int) -> bool:
    """True si todavía hay cupo de avisos «[Cuerpo]» esta hora."""
    ahora = time.time()
    while _eventos and ahora - _eventos[0] > 3600:
        _eventos.popleft()
    return len(_eventos) < max(0, int(max_por_hora))


def registrar_evento() -> None:
    """Cuenta un aviso que SÍ se mandó."""
    _eventos.append(time.time())


_PALABRAS_CLAVE = (r"esperar|emoci[oó]n|gesto|mirar|intensidad|pasos|cuerpo|vida|volver_en|pose|rapidez|ir_x|ir_y|" + "|".join(GESTOS)
                   + "|" + "|".join(POSE_PARAMS))
_RE_CORCHETES = re.compile(r"\[[^\]\n]*\b(?:" + _PALABRAS_CLAVE + r")\b[^\]\n]*\]", re.I)
_RE_ABIERTO = re.compile(r"\[[^\]\n]{0,90}$")


_RE_SILENCIO = re.compile(r"(?:\bI(?:'ll| will| shall)\s*(?:remain|stay|keep)\s*(?:silent|quiet)\b[.!]?|\b(?:me\s*quedo|me\s*quedar[eé]|voy\s*a\s*(?:quedarme|permanecer))\s*(?:en\s*)?(?:silencio|callada|callado)\b[.!]?)", re.I)


_TOOLS_CUERPO = ("cuerpo_libre", "lenguaje_corporal", "set_emotion", "detener_todo")
# nombre de herramienta seguido de «{» o «(»: la llamada escrita como texto. Para las del cuerpo basta el nombre; para cualquier otra con guion bajo
# (abrir_app, ver_pantalla…) se exige que lo siguiente parezca «clave:» o «clave=» (así no se come texto normal con paréntesis).
_RE_LLAMADA = re.compile(r"\b(?:" + "|".join(_TOOLS_CUERPO) + r")\s*[\{\(]|\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\s*[\{\(]\s*[\"']?\w+[\"']?\s*[:=]", re.I)
_RE_NOMBRE_SUELTO = re.compile(r"\b(?:" + "|".join(_TOOLS_CUERPO) + r")\b", re.I)


def _quitar_llamadas(t: str) -> str:
    """Quita las llamadas a herramientas escritas como texto, por ejemplo «cuerpo_libre{pose:{cabeza_y:1},segundos:2}». La IA SÍ hace la llamada de verdad;
    lo que se cuela en la transcripción es su eco. Si la llamada todavía no se cierra (llega por tramos) se quita hasta el final, y el siguiente tramo
    la completa: por eso quien llama debe pasar siempre el texto CRUDO acumulado, no uno ya limpiado."""
    while True:
        m = _RE_LLAMADA.search(t)
        if not m:
            break
        i = m.end() - 1 if t[m.end() - 1] in "{(" else t.index(next(ch for ch in "{(" if ch in t[m.start():m.end()]), m.start())
        pila, fin, comilla = [], None, ""
        for k in range(m.start(), len(t)):
            ch = t[k]
            if comilla:
                if ch == comilla:
                    comilla = ""
                continue
            if ch in "\"'":
                comilla = ch
            elif ch in "{([":
                pila.append(ch)
            elif ch in "})]" and pila:
                pila.pop()
                if not pila:
                    fin = k + 1
                    break
        t = t[:m.start()] + (t[fin:] if fin else "")
    return _RE_NOMBRE_SUELTO.sub("", t)


def limpiar(txt: str) -> str:
    """Quita de lo que Orbi DIJO cualquier gesto o aviso narrado («[Cuerpo]», «[mirar cursor, esperar 0.5]»…): los gestos se hacen llamando a la
    herramienta, nunca se dicen ni se escriben. Red de seguridad por si el modelo los lee en voz alta; la regla de oro del prompt es lo principal."""
    t = _RE_SILENCIO.sub("", _RE_CORCHETES.sub("", _quitar_llamadas(txt or "")))        # (también el «I will remain silent» con el que a veces «confirma» un aviso)
    t = re.sub(r"\[\s*(?:cuerpo|vida)\s*\]", "", t, flags=re.I)
    m = _RE_ABIERTO.search(t)                              # un corchete que todavía no se cierra (llega por tramos): no se muestra a medias
    if m and re.search(r"(?:" + _PALABRAS_CLAVE + r")|^\[\s*c?u?e?r?p?o?\s*$", m.group(0), re.I):
        t = t[:m.start()]
    return re.sub(r"[ \t]*\n[ \t]*(\n[ \t]*)+", "\n", t).lstrip()           # (sin quitar espacios del final: el siguiente tramo puede no traer el suyo)


def prompt_text() -> str:
    """Bloque del prompt de la voz según el modo: control total (ACTIVO) o animaciones programadas (apagado)."""
    if ACTIVO:
        import cuerpo_libre
        return cuerpo_libre.prompt_libre()
    return prompt_catalogo()


def prompt_catalogo() -> str:
    """Modo «animaciones programadas» (opción de Ajustes apagada): la IA elige gestos y emociones de un catálogo ya animado."""
    simples = "; ".join(f"{n} ({d})" for n, (_s, d) in SIMPLES.items())
    comp = "; ".join(f"{n} ({d[0]})" for n, d in COMPUESTOS.items())
    mov = "; ".join(f"{n} ({d})" for n, d in MOVIMIENTOS.items())
    return (
        "TU CUERPO (ANIMACIONES PROGRAMADAS): tienes una bolita con cara y la manejas con `lenguaje_corporal`, eligiendo gestos y emociones de un "
        "catálogo ya animado. La llamada es invisible (tu dueño no ve que la usas ni hay resultado que leer): no la menciones y sigue hablando.\n"
        "REGLA DE ORO: los gestos SOLO se hacen llamando a la herramienta. NUNCA los digas ni los escribas en tu respuesta: ni nombres de gestos o "
        "emociones, ni listas, ni corchetes, ni «esperar». Lo que dices en voz son únicamente palabras para tu dueño. Tampoco repitas ni leas en "
        "voz alta los avisos internos que te lleguen.\n"
        "COREOGRAFÍA TU FRASE: antes de hablar, llama UNA vez con `pasos` repartidos a lo largo de lo que vas a decir, usando `esperar` (segundos "
        "hasta el siguiente paso; hablas ~3 palabras por segundo). Puedes mezclar `gesto`, `emocion` y `mirar` en un mismo paso, y la `intensidad` "
        "(0.3 suave a 1.6 exagerado) importa: casi todo suave o normal.\n"
        "LAS EMOCIONES: cámbialas con `emocion` (o `set_emotion`) cuando de verdad las sientas. Cuando le preguntas algo a tu dueño o te da "
        "curiosidad: `curious` (te sale un «?»); cuando dudas: `confused`; cuando piensas sale una nube con «...». Se quitan solas.\n"
        f"Gestos: {simples}. Compuestos: {comp}. Movimiento: {mov}. Miradas: {', '.join(DIRECCIONES)} (o x,y de 0 a 1000).\n"
        "ERES SOLO UNA BOLITA: sin manos ni brazos. Varía (nunca el mismo gesto dos veces seguidas) y a veces quédate quieta. Tu boca se mueve "
        "sola con tu voz.\n"
        "AVISOS «[Cuerpo]»: son noticias del cuerpo (te acarició, tu dueño volvió…), no preguntas. Reacciona SOLO con `lenguaje_corporal` (tu única "
        "respuesta es la llamada: no digas ni escribas nada, ni siquiera para confirmar), con algo corto y natural; solo a veces nada."
    )
