"""Tools de prueba para Gemini Live (function calling). Agrega aquí las tuyas."""
import subprocess, sys
from datetime import datetime

APPS = {  # lista blanca: nombre que dice la IA -> ejecutable de Windows
    "calculadora": "calc.exe",
    "bloc de notas": "notepad.exe",
    "paint": "mspaint.exe",
    "explorador": "explorer.exe",
}

DECLARATIONS = [
    {
        "name": "obtener_hora",
        "description": "Devuelve la fecha y hora actuales del equipo del usuario.",
    },
    {
        "name": "abrir_app",
        "description": "Abre una aplicación de Windows. Apps disponibles: " + ", ".join(APPS),
        "parameters": {
            "type": "OBJECT",
            "properties": {"nombre": {"type": "STRING", "description": "Nombre de la app"}},
            "required": ["nombre"],
        },
    },
    {
        "name": "set_emotion",
        "description": "Cambia la expresión de la bolita para reflejar tu emoción al responder.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"emocion": {"type": "STRING",
                                       "enum": ["neutral", "happy", "love", "sad", "surprised", "thinking", "sleepy"]}},
            "required": ["emocion"],
        },
    },
]
TOOLS = [{"function_declarations": DECLARATIONS}]


def run_tool(name: str, args: dict, emit=lambda *a: None) -> dict:
    if name == "obtener_hora":
        n = datetime.now()
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                 "septiembre", "octubre", "noviembre", "diciembre"]
        return {"resultado": f"{dias[n.weekday()]} {n.day} de {meses[n.month - 1]} de {n.year}, {n:%H:%M}"}
    if name == "abrir_app":
        app = str(args.get("nombre", "")).lower().strip()
        exe = APPS.get(app)
        if not exe:
            return {"error": f"No conozco la app '{app}'. Disponibles: {', '.join(APPS)}"}
        if sys.platform != "win32":
            return {"resultado": f"(simulado, no es Windows) abriría {exe}"}
        subprocess.Popen(exe)
        return {"resultado": f"Abrí {app}"}
    if name == "set_emotion":
        emit("emotion", args.get("emocion", "neutral"))
        return {"resultado": "ok"}
    return {"error": f"Tool desconocida: {name}"}
