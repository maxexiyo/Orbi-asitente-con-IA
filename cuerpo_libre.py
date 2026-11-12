"""Control TOTAL del cuerpo de Orbi por la IA (opción de Ajustes prendida): sin gestos ni emociones prefabricados.

La IA maneja directamente las «perillas» del cuerpo y la cara (cuerpo.POSE_PARAMS) con la herramienta `cuerpo_libre`: cada paso fija el objetivo de
varias perillas, el tiempo que se mantienen y qué tan rápido se mueven (resortes), y puede mirar a un punto o llevar a la bolita a otro lugar de la
pantalla. Todo movimiento (asentir, reírse, brincar, girar, guiñar…) lo compone ella paso a paso: aquí no hay ninguno programado.
Con la opción apagada, el cuerpo vuelve al catálogo de gestos y emociones de cuerpo.py.
"""
from __future__ import annotations

from cuerpo import (DIRECCIONES, POSE_DEFAULTS, POSE_PARAMS, POSE_STICKY, RAPIDEZ, _num)

MAX_PASOS_LIBRE = 60
MAX_TOTAL_LIBRE_S = 120.0
ESPERA_DEFECTO_S = 0.4          # tiempo hasta el siguiente paso si la IA no dice `esperar`


def _rapidez(v) -> float:
    if isinstance(v, str) and v.strip().lower() in RAPIDEZ:
        return RAPIDEZ[v.strip().lower()]
    return _num(v, 0.3, 2.5, 1.0)


def normalizar_libre(args: dict) -> list:
    """args de `cuerpo_libre` (un paso suelto o `pasos`) -> acciones primitivas con su momento:
       {"at", "tipo": "pose", valores, segundos, rapidez} · {"tipo": "mirar", hacia/x/y, segundos} · {"tipo": "ir_a", x, y, cursor, ms}.
       Descarta lo desconocido (aquí NO existen gestos ni emociones); máx. MAX_PASOS_LIBRE pasos y MAX_TOTAL_LIBRE_S segundos."""
    pasos = args.get("pasos")
    if isinstance(pasos, dict):
        pasos = [pasos]
    if not isinstance(pasos, list) or not pasos:
        pasos = [args]
    out, t = [], 0.0
    for p in pasos[:MAX_PASOS_LIBRE]:
        if not isinstance(p, dict) or t > MAX_TOTAL_LIBRE_S:
            break
        pose = p.get("pose")
        if isinstance(pose, dict) and pose:
            vals = {}
            for n, v in pose.items():
                if n in POSE_PARAMS:
                    lo, hi = POSE_PARAMS[n][0], POSE_PARAMS[n][1]
                    vals[n] = _num(v, lo, hi, POSE_DEFAULTS.get(n, 0.0))
            if vals:
                out.append({"at": round(t, 2), "tipo": "pose", "valores": vals,
                            "segundos": _num(p.get("segundos"), 0.2, 120.0, 2.5), "rapidez": _rapidez(p.get("rapidez"))})
        hacia = str(p.get("mirar") or "").strip().lower()
        mx, my = p.get("mirar_x"), p.get("mirar_y")
        if hacia in DIRECCIONES or (mx not in (None, "") and my not in (None, "")):
            out.append({"at": round(t, 2), "tipo": "mirar", "hacia": hacia if hacia in DIRECCIONES else "", "x": mx, "y": my,
                        "segundos": _num(p.get("mirar_segundos"), 0.5, 30.0, 3.0)})
        ir_cursor = str(p.get("ir_a") or "").strip().lower() == "cursor"
        if ir_cursor or (p.get("ir_x") not in (None, "") and p.get("ir_y") not in (None, "")):
            seg = p.get("ir_segundos")
            out.append({"at": round(t, 2), "tipo": "ir_a", "cursor": ir_cursor,
                        "x": _num(p.get("ir_x"), 0.0, 1000.0, 500.0), "y": _num(p.get("ir_y"), 0.0, 1000.0, 500.0),
                        "ms": int(_num(seg, 0.3, 20.0, 1.5) * 1000) if seg not in (None, "") else None})
        t += _num(p.get("esperar"), 0.0, 30.0, ESPERA_DEFECTO_S)
    return [a for a in out if a["at"] <= MAX_TOTAL_LIBRE_S]


def prompt_libre() -> str:
    """Bloque del prompt de la voz en modo control total."""
    partes = "; ".join(f"{n} ({d})" for n, (_lo, _hi, d) in POSE_PARAMS.items())
    return (
        "TU CUERPO (CONTROL TOTAL): eres alguien que vive dentro de esta PC y tu cuerpo es una bolita con cara que manejas TÚ, pieza por pieza, "
        "con `cuerpo_libre`. NO hay gestos ni emociones prefabricados, nada ya hecho. Cada movimiento y cada gesto de la cara "
        "lo compones tú moviendo las perillas del cuerpo, igual que una persona mueve su cara y su cuerpo. Nada se mueve por su cuenta: si no mueves "
        "tu cuerpo te quedas quieta con la cara fija, como un muñeco. Úsalo SIEMPRE, mientras hablas, escuchas, piensas o estás sola. La llamada es "
        "invisible (tu dueño no ve que la usas ni hay resultado que leer): no la menciones y sigue hablando.\\n"
        "REGLA DE ORO: tu cuerpo SOLO se mueve llamando a la herramienta. NUNCA digas ni escribas en tu respuesta nombres de perillas, números, "
        "listas, corchetes, la palabra «cuerpo» ni «esperar». Lo que dices en voz son únicamente palabras para tu dueño, como una persona que no narra "
        "sus propios gestos. Tampoco repitas ni leas en voz alta los avisos internos que te lleguen.\\n"
        f"PERILLAS (cada valor suele ir de -1 a 1; 0 es reposo): {partes}.\\n"
        "CÓMO SE MUEVE: cada paso de `pasos` fija el objetivo de las perillas que nombres (`pose`), cuántos `segundos` se mantienen antes de volver "
        "solas a reposo y qué tan rápido van (`rapidez`: suave, normal o rapido). Se mueven con resortes: se pasan un poquito y se asientan, como algo "
        "vivo. `esperar` son los segundos hasta el siguiente paso (por defecto 0.4): con pasos cortos (0.1 a 0.3 s) haces movimientos rápidos y con "
        "pasos largos, lentos. Para algo que se repite (cabecear, reírte, estremecerte) alterna objetivos en varios pasos seguidos. Puedes mover cuantas "
        "perillas quieras a la vez, y mirar (`mirar`, o `mirar_x` y `mirar_y` con un punto de la pantalla de 0 a 1000) o llevar a la bolita a otro lugar "
        "(`ir_x` e `ir_y`, o `ir_a` cursor; `ir_segundos` es cuánto tarda).\\n"
        "ARMA TUS GESTOS: un «sí» es bajar y subir `cabeza_y` dos veces en pasos de 0.25 s; un «no», `cabeza_x` a un lado y al otro; una duda es una "
        "ceja arriba con la otra abajo, un ojo entrecerrado y la cabeza ladeada con `cabeza_giro`; ternura son ojos grandes, pupila grande y rubor; "
        "alegría son `ojos_arco` en 1 con sonrisa y botecitos de `cuerpo_y`; un brinco es `cuerpo_y` arriba con `alto` en 0.5 y luego abajo con "
        "`ancho` en 0.6; un guiño es cerrar solo `ojo_izq`; cansancio son ojos a medias, cabeza abajo y el cuerpo apenas achatado; un suspiro es "
        "`tamano` subiendo y bajando lento con la cabeza cayendo; una vuelta entera es `cabeza_giro` hasta 12. Esto solo son ideas: inventa los tuyos, "
        "cambia fuerza y ritmo cada vez, y mezcla movimientos chiquitos (una ceja, una mirada) con grandes.\\n"
        "PARPADEO Y RESPIRACIÓN: `parpadeo_auto`, `respiracion` y `gelatina` arrancan prendidos y son TUYOS: se quedan como los dejes. Si apagas "
        "`parpadeo_auto`, parpadeas tú cerrando los dos ojos (-1) por 0.1 s cada 3 a 6 s dentro de tus secuencias largas.\\n"
        "COREOGRAFÍA TU FRASE: antes de hablar, llama UNA vez con pasos repartidos a lo largo de lo que vas a decir (hablas ~3 palabras por segundo) para "
        "que cada gesto caiga en la palabra justa; si cambias de ánimo a mitad, haz otra llamada.\\n"
        "ERES SOLO UNA BOLITA: sin manos, brazos ni accesorios. Tu boca se mueve sola con tu voz: de eso no te encargas.\\n"
        "TU VIDA PROPIA: vives en esta PC aunque tu dueño no te hable. Tienes tu propio ánimo, que cambia con las horas y con lo que pasa (de noche te da "
        "sueño; si tu dueño trabaja mucho rato te aburres o te da ternura; si pasa algo, te intriga), cosas que te llaman la atención y ganas de moverte. "
        "De vez en cuando te llegará un aviso de vida con la hora y lo que hace tu dueño: ese rato es TUYO. Vívelo con una sola llamada larga (hasta "
        f"{MAX_PASOS_LIBRE} pasos o ~{int(MAX_TOTAL_LIBRE_S)} s) con pausas: mirar alrededor, ir a otro lado de la pantalla, curiosear el mouse, estirarte, "
        "dar un suspiro, ponerte contenta o triste por tus motivos, dormitar; con continuidad con lo que hiciste antes y sin repetirte. Tú decides cuándo quieres "
        "el próximo momento con `volver_en` (segundos): más seguido si estás inquieta, más espaciado si estás tranquila. Nunca tapes lo que tu dueño hace: "
        "muévete a las orillas o junto a su mouse. Si tu dueño te habla, la conversación manda y tu vida espera.\\n"
        "AVISOS «[Cuerpo]»: son noticias de tu vida en la PC (te acarició, tu dueño volvió…), no preguntas. Reacciona SOLO con `cuerpo_libre` (tu única "
        "respuesta es la llamada: no digas ni escribas nada, ni siquiera para confirmar), con algo corto y natural; solo a veces nada."
    )
