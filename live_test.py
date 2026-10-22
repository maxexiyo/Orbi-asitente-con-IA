"""Prueba mínima de Gemini Live con tu micro, en consola (sin interfaz).

  python live_test.py              -> platica por voz (usa audífonos si puedes)
  python live_test.py --tools      -> además prueba function calling (hora, abrir calculadora...)
  python live_test.py --models     -> lista los modelos de tu cuenta que soportan Live
  python live_test.py --devices    -> lista tus micros/bocinas
  python live_test.py --model X    -> usa otro modelo (si no, el de config.json)
"""
import argparse, asyncio, functools, sys, time

from google import genai

from config import load_config, gemini_keys
from live_client import LiveSession
from demo_tools import TOOLS, run_tool

COLORS = {"user": "\033[96m", "model": "\033[92m", "dim": "\033[90m", "err": "\033[91m", "tool": "\033[93m", "end": "\033[0m"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model"); ap.add_argument("--tools", action="store_true")
    ap.add_argument("--models", action="store_true"); ap.add_argument("--devices", action="store_true")
    ap.add_argument("--headphones", action="store_true", help="dejar el micro abierto mientras la IA habla")
    ap.add_argument("--input-device", type=int); ap.add_argument("--output-device", type=int)
    a = ap.parse_args()

    if a.devices:
        import sounddevice as sd
        print(sd.query_devices()); return

    cfg = load_config(); keys = gemini_keys(cfg)

    if a.models:
        client = genai.Client(api_key=keys[0])
        print("Modelos con soporte Live (bidiGenerateContent) en tu cuenta:")
        for m in client.models.list():
            if "bidiGenerateContent" in (getattr(m, "supported_actions", None) or []):
                print("  ", m.name)
        return

    model = a.model or cfg.get("live_model", "gemini-3.1-flash-live-preview")
    print(f"Keys de Gemini: {len(keys)} (variables: {', '.join(cfg['_key_vars']['gemini']) or 'config.json'})")
    print(f"Modelo: {model} | keys: {len(keys)} | tools: {'sí' if a.tools else 'no'} | "
          f"audífonos: {'sí' if (a.headphones or cfg.get('headphones')) else 'no (micro se calla mientras habla la IA)'}")
    print("Habla cuando veas 'Conectado'. Ctrl+C para salir.\n")

    last = {"kind": None}

    def emit(kind, data):
        c = COLORS
        if kind == "connected":
            print(f"{c['dim']}[conectado a {data}]{c['end']}")
        elif kind == "state":
            print(f"\n{c['dim']}[{data}]{c['end']}", end="", flush=True); last["kind"] = None
        elif kind in ("user_text", "model_text"):
            if last["kind"] != kind:
                print(f"\n{c['user' if kind == 'user_text' else 'model']}{'Tú' if kind == 'user_text' else 'Orbi'}: ", end="")
            print(f"{c['user' if kind == 'user_text' else 'model']}{data}{c['end']}", end="", flush=True)
            last["kind"] = kind
        elif kind == "tool":
            print(f"\n{c['tool']}[tool] {data[0]}({data[1]}){c['end']}")
        elif kind in ("error", "fatal", "info"):
            print(f"\n{c['err']}[{kind}] {data}{c['end']}")
        elif kind == "interrupted":
            print(f"\n{c['dim']}[interrumpido]{c['end']}")

    session = LiveSession(
        keys, model, emit,
        tools=TOOLS if a.tools else None,
        tool_runner=functools.partial(run_tool, emit=emit),
        voice=cfg.get("live_voice"),
        headphones=a.headphones or cfg.get("headphones", False),
        input_device=a.input_device, output_device=a.output_device,
    )
    try:
        asyncio.run(session.run())
    except KeyboardInterrupt:
        print("\nAdiós!")


if __name__ == "__main__":
    main()
