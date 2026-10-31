"""Prueba un modelo LOCAL (Ollama) con tareas parecidas a las de Orbi, para saber si te sirve como «plan B sin internet».

Mide tres cosas:
  1. ¿Escoge la herramienta correcta (y los datos correctos) cuando se lo pides en español normal?
  2. ¿Contesta sin herramienta cuando NO hace falta (un chiste, una duda)?
  3. ¿Qué tan rápido va en TU compu y cuánta RAM usa?

Cómo usarlo (no necesita nada de Orbi, solo Python y `pip install httpx`):
  1) Instala Ollama (ollama.com/download) y deja que corra.
  2) ollama pull qwen3.5:4b
  3) python probar_modelo_local.py --modelo qwen3.5:4b
  Repite con otros modelos (phi4-mini, gemma4:e2b ...) y compara la tabla final.
"""
import argparse, json, sys, time

import httpx

# Herramientas de ejemplo, con la forma de las de Orbi (nombre, para qué sirve, parámetros)
def _t(nombre, desc, props, req=()):
    return {"type": "function", "function": {"name": nombre, "description": desc,
            "parameters": {"type": "object", "properties": {k: {"type": v[0], "description": v[1]} for k, v in props.items()}, "required": list(req)}}}


TOOLS = [
    _t("abrir_app", "Abre una aplicación instalada o la pone al frente.", {"nombre": ("string", "Nombre de la app")}, ["nombre"]),
    _t("cerrar_ventana", "Cierra una ventana o aplicación abierta.", {"titulo": ("string", "Parte del título de la ventana")}, ["titulo"]),
    _t("listar_ventanas", "Lista las ventanas que hay abiertas ahora.", {}),
    _t("buscar_archivos", "Busca archivos en la PC por nombre.", {"consulta": ("string", "Nombre o parte del nombre")}, ["consulta"]),
    _t("leer_archivo", "Lee el contenido de un archivo de texto, Word o PDF.", {"ruta": ("string", "Nombre o ruta del archivo")}, ["ruta"]),
    _t("crear_alarma", "Programa una alarma o recordatorio.", {"hora": ("string", "Hora, ej. 07:00"), "mensaje": ("string", "Texto del aviso")}, ["hora"]),
    _t("poner_volumen", "Cambia el volumen del sistema de 0 a 100.", {"nivel": ("integer", "Volumen 0-100")}, ["nivel"]),
    _t("crear_presentacion", "Crea una presentación de PowerPoint completa sobre un tema.", {"archivo": ("string", "Nombre del archivo"),
       "instrucciones": ("string", "De qué trata y cuántas diapositivas")}, ["archivo", "instrucciones"]),
    _t("crear_hoja_excel", "Crea una hoja de cálculo de Excel con datos y fórmulas.", {"archivo": ("string", "Nombre del archivo"),
       "instrucciones": ("string", "Qué columnas y qué calcular")}, ["archivo", "instrucciones"]),
    _t("casa_luz", "Prende o apaga la luz de un cuarto de la casa.", {"cuarto": ("string", "Cuarto"), "accion": ("string", "prender o apagar")}, ["cuarto", "accion"]),
]

SISTEMA = ("Eres Orbi, el asistente de escritorio de Max. Hablas en español mexicano, corto y natural. Cuando te pidan hacer algo en la "
           "computadora, USA la herramienta adecuada; si solo es conversación o una duda, contesta directo sin herramientas.")

# (lo que dice el usuario, herramienta esperada o None, texto que debe aparecer en los argumentos)
CASOS = [
    ("abre la calculadora", "abrir_app", "calculadora"),
    ("ponme una alarma a las 7 de la mañana para levantarme", "crear_alarma", "7"),
    ("bájale el volumen a 30", "poner_volumen", "30"),
    ("qué ventanas tengo abiertas", "listar_ventanas", ""),
    ("hazme una presentación sobre el sistema solar", "crear_presentacion", "sistema solar"),
    ("busca mi tarea de probabilidad", "buscar_archivos", "probabilidad"),
    ("prende la luz de la sala", "casa_luz", "sala"),
    ("cierra chrome por favor", "cerrar_ventana", "chrome"),
    ("hazme un excel de mis gastos del mes con total", "crear_hoja_excel", "gastos"),
    ("léeme el archivo notas.txt", "leer_archivo", "notas"),
    ("cuéntame un chiste corto", None, ""),
    ("qué es una interrupción en arduino", None, ""),
]


def chat(cli, host, modelo, msgs, ctx, think):
    cuerpo = {"model": modelo, "messages": msgs, "tools": TOOLS, "stream": False, "keep_alive": "10m",
              "options": {"temperature": 0.2, "num_ctx": ctx}}
    if think is not None:
        cuerpo["think"] = think
    r = cli.post(f"{host}/api/chat", json=cuerpo)
    if r.status_code == 400 and think is not None and "think" in r.text.lower():
        cuerpo.pop("think")
        r = cli.post(f"{host}/api/chat", json=cuerpo)
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default="qwen3.5:4b")
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--ctx", type=int, default=4096, help="contexto; menos = menos RAM")
    ap.add_argument("--pensar", action="store_true", help="dejar que el modelo «piense» (más lento; por defecto se apaga)")
    a = ap.parse_args()
    cli = httpx.Client(timeout=300)
    try:
        tags = cli.get(f"{a.host}/api/tags").json()
    except Exception as e:                           # noqa: BLE001
        print(f"❌ No encuentro Ollama en {a.host} ({type(e).__name__}). ¿Está instalado y abierto? -> ollama.com/download")
        return 1
    nombres = [m.get("name", "") for m in tags.get("models", [])]
    if not any(n == a.modelo or n.split(":")[0] == a.modelo for n in nombres):
        print(f"❌ El modelo «{a.modelo}» no está instalado. Instálalo con:  ollama pull {a.modelo}")
        print("   Instalados:", ", ".join(nombres) or "(ninguno)")
        return 1
    think = True if a.pensar else False
    print(f"Modelo: {a.modelo} · contexto {a.ctx} · pensar={'sí' if a.pensar else 'no'}\n")
    t0 = time.time()
    chat(cli, a.host, a.modelo, [{"role": "user", "content": "hola"}], a.ctx, think)       # calentamiento: carga el modelo a la RAM
    print(f"Carga del modelo en memoria: {time.time() - t0:.1f} s (solo pasa la primera vez)\n")
    buenos, tiempos, toks = 0, [], []
    print(f"{'Lo que dices':<52} {'Herramienta elegida':<26} {'Seg':>5}  Resultado")
    for dicho, esperada, clave in CASOS:
        t = time.time()
        try:
            r = chat(cli, a.host, a.modelo, [{"role": "system", "content": SISTEMA}, {"role": "user", "content": dicho}], a.ctx, think)
        except Exception as e:                       # noqa: BLE001
            print(f"{dicho:<52} {'(error)':<26} {'-':>5}  ❌ {type(e).__name__}: {str(e)[:60]}")
            continue
        dt = time.time() - t
        msg = r.get("message", {})
        llamadas = msg.get("tool_calls") or []
        elegida = llamadas[0]["function"]["name"] if llamadas else None
        args = json.dumps(llamadas[0]["function"].get("arguments", {}), ensure_ascii=False).lower() if llamadas else ""
        if esperada is None:
            bien, motivo = elegida is None, "contestó sin herramienta" if elegida is None else f"usó {elegida} sin necesidad"
        elif elegida != esperada:
            bien, motivo = False, "no usó herramienta" if elegida is None else f"esperaba {esperada}"
        elif clave and clave.lower() not in args:
            bien, motivo = False, f"herramienta bien, pero faltó «{clave}» en los datos: {args[:40]}"
        else:
            bien, motivo = True, "ok"
        buenos += bien
        tiempos.append(dt)
        if r.get("eval_count") and r.get("eval_duration"):
            toks.append(r["eval_count"] / (r["eval_duration"] / 1e9))
        print(f"{dicho:<52} {(elegida or '(texto)'):<26} {dt:>5.1f}  {'✅' if bien else '❌'} {motivo}")
    ps = {}
    try:
        for m in cli.get(f"{a.host}/api/ps").json().get("models", []):
            if m.get("name", "").split(":")[0] == a.modelo.split(":")[0]:
                ps = m
    except Exception:                                # noqa: BLE001
        pass
    n = len(CASOS)
    print(f"\nAciertos: {buenos}/{n}  ({100 * buenos // n}%)")
    if tiempos:
        print(f"Tiempo por petición: promedio {sum(tiempos) / len(tiempos):.1f} s · velocidad al escribir ≈ {sum(toks) / max(len(toks), 1):.0f} tokens/s")
    if ps.get("size"):
        print(f"Memoria que ocupa el modelo: {ps['size'] / 1e9:.1f} GB (en GPU: {ps.get('size_vram', 0) / 1e9:.1f} GB)")
    print("\nCómo leerlo: ≥ 10/12 y menos de ~8 s por petición = te sirve como plan B. Entre 7 y 9 = sirve para tareas simples. Menos = busca otro modelo.")
    print("Tip: cierra Chrome y otras apps pesadas mientras lo pruebas; con 8 GB de RAM cada GB cuenta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
