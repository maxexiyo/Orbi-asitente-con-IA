"""Herramientas del cuerpo de Orbi (se registran al importar desde pc_tools.py).

  cuerpo_libre      · CONTROL TOTAL (opción de Ajustes prendida): la IA mueve las perillas del cuerpo y la cara paso a paso; no hay gestos ni emociones
                      prefabricados (cuerpo_libre.py).
  lenguaje_corporal · ANIMACIONES PROGRAMADAS (opción apagada): la IA elige gestos y emociones de un catálogo ya animado (cuerpo.py).
Solo una de las dos está declarada a la vez (flags «cuerpo» / «cuerpo_prog» en live_orb.py); cada una se niega si no es la del modo actual.
"""
import cuerpo as CU
import cuerpo_libre as CL
from pc_tools import _tool, N, S

_PASO_PROG = {
    "type": "OBJECT",
    "properties": dict(
        gesto={"type": "STRING", "enum": list(CU.GESTOS)},
        emocion={"type": "STRING", "enum": list(CU.EMOCIONES)},
        mirar={"type": "STRING", "enum": list(CU.DIRECCIONES), "description": "hacia dónde mira (o usa x,y)"},
        x=N("mirar: punto de la pantalla, 0 a 1000"), y=N("mirar: punto de la pantalla, 0 a 1000"),
        intensidad=N("0.3 (suave) a 1.6 (exagerado); 1 por defecto"),
        segundos=N("cuánto dura la emoción o la mirada (0.5 a 15)"),
        esperar=N("segundos hasta el siguiente paso (por defecto lo que dura el gesto); úsalo para repartir los gestos a lo largo de tu frase"),
        ir_x=N("moverte por la pantalla: punto de llegada, 0 (izquierda) a 1000 (derecha); va junto con ir_y"),
        ir_y=N("moverte por la pantalla: punto de llegada, 0 (arriba) a 1000 (abajo)"),
        estilo={"type": "STRING", "enum": list(CU.ESTILOS_MOV), "description": "cómo te mueves: deslizar, saltar (brincando) o rodar (girando)"}),
}
_tool("lenguaje_corporal", "Mueves tu cuerpo y gesticulas sin hablar eligiendo gestos y emociones del catálogo, una mirada o una secuencia corta en UNA llamada "
      "(`pasos`). Úsala en cada respuesta y en los avisos «[Cuerpo]». Es invisible y sin resultado que leer: no la comentes.",
      dict(**_PASO_PROG["properties"], pasos={"type": "ARRAY", "items": _PASO_PROG, "description": "Varios pasos en orden (máx 24, hasta ~90 s)"}),
      [], scopes=("live",), flag="cuerpo_prog")

_PASO_LIBRE = {
    "type": "OBJECT",
    "properties": dict(
        pose={"type": "OBJECT", "description": "objetivo de las perillas que nombres (resto sin cambio); se mantienen `segundos` y vuelven solas a reposo",
              "properties": {n: N(f"{d} ({lo:g} a {hi:g})") for n, (lo, hi, d) in CU.POSE_PARAMS.items()}},
        segundos=N("cuánto se mantiene esta pose antes de volver a reposo (0.2 a 120; por defecto 2.5)"),
        rapidez={"type": "STRING", "enum": list(CU.RAPIDEZ), "description": "qué tan rápido va hacia la pose: suave, normal o rapido"},
        esperar=N("segundos hasta el siguiente paso (por defecto 0.4): pasos cortos = movimientos rápidos"),
        mirar={"type": "STRING", "enum": list(CU.DIRECCIONES), "description": "a dónde miras"},
        mirar_x=N("mirar a un punto de la pantalla: 0 (izquierda) a 1000 (derecha); va junto con mirar_y"),
        mirar_y=N("mirar a un punto de la pantalla: 0 (arriba) a 1000 (abajo)"),
        mirar_segundos=N("cuánto mantienes la mirada (0.5 a 30)"),
        ir_x=N("moverte por la pantalla: punto de llegada, 0 (izquierda) a 1000 (derecha); va junto con ir_y"),
        ir_y=N("moverte por la pantalla: punto de llegada, 0 (arriba) a 1000 (abajo)"),
        ir_a={"type": "STRING", "enum": ["cursor"], "description": "ir junto al mouse"},
        ir_segundos=N("cuánto tardas en llegar (0.3 a 20; por defecto 1.5)")),
}
_tool("cuerpo_libre", "CONTROL TOTAL de tu cuerpo: mueves las perillas de tu carita y tu cuerpo (cabeza, ojos, cejas, boca, tamaño, rubor, brillo…) paso a paso, "
      "miras a un punto y te mueves por la pantalla. No hay gestos prefabricados: tú los compones. Úsala en cada respuesta, escuchando, pensando y en tus "
      "ratos de vida. Es invisible y sin resultado que leer: no la comentes.",
      dict(**_PASO_LIBRE["properties"],
           pasos={"type": "ARRAY", "items": _PASO_LIBRE, "description": f"Pasos en orden (máx {CL.MAX_PASOS_LIBRE}, hasta ~{int(CL.MAX_TOTAL_LIBRE_S)} s)"},
           volver_en=N("solo en tus momentos de vida: en cuántos segundos quieres el próximo (15 a 300)")),
      [], scopes=("live",), flag="cuerpo")


def manejar(name: str, args: dict, ctx) -> dict:
    """Valida lo que pidió la IA y se lo manda a la bolita (evento «cuerpo» → Orb.cuerpo)."""
    if name == "cuerpo_libre":
        if not CU.ACTIVO:
            return {"error": "Ahora tu cuerpo funciona con animaciones programadas: usa lenguaje_corporal."}
        acc = CL.normalizar_libre(args)
        if not acc:
            return {"error": "Pásame al menos una pose, una mirada o un destino válidos."}
        ctx.emit("cuerpo", {"acciones": acc, "volver_en": CU.volver_en(args)})
        return {"resultado": "ok"}
    if CU.ACTIVO:
        return {"error": "Ahora tienes control total de tu cuerpo: usa cuerpo_libre."}
    acc = CU.normalizar(args)
    if not acc:
        return {"error": "Pásame al menos un gesto, una emoción o una mirada válidos."}
    ctx.emit("cuerpo", {"acciones": acc, "volver_en": None})
    return {"resultado": "ok"}
