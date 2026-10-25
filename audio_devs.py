"""Dispositivos de audio de salida para Ajustes.

Problema: PortAudio (sounddevice) toma la lista de dispositivos UNA vez, al arrancar, y no se entera de los que conectas después
(audífonos Bluetooth, USB...). Reiniciarlo dentro de Orbi cerraría el micrófono y la bocina que están abiertos, así que la lista
«fresca» se pide a un proceso aparte (que arranca PortAudio de cero) y Orbi solo la muestra.

Para ABRIR un dispositivo hace falta que PortAudio de Orbi lo conozca: los que ya estaban al abrir Orbi se usan al momento;
uno nuevo se guarda y se usa al reiniciar Orbi (resolve_index lo dice con None).
"""
import json, subprocess, sys

_CODE = r"""
import json, sounddevice as sd
h = sd.query_hostapis(); d = sd.query_devices()
try:
    dflt = sd.default.device[1]
except Exception:
    dflt = -1
dh = d[dflt]["hostapi"] if isinstance(dflt, int) and 0 <= dflt < len(d) else (h and 0)
print(json.dumps({"dev": [{"name": x["name"], "out": x["max_output_channels"], "host": x["hostapi"]} for x in d],
                  "host": dh, "hostnames": [x["name"] for x in h]}))
"""


def _parse(raw: dict) -> list:
    names, seen = [], set()
    host = raw.get("host")
    for dv in raw.get("dev", []):
        if dv.get("out", 0) > 0 and (host is None or dv.get("host") == host):
            n = str(dv["name"]).strip()
            if n and n not in seen:
                seen.add(n)
                names.append(n)
    return names


def list_outputs(fresh: bool = True) -> list:
    """Nombres de las bocinas/audífonos disponibles AHORA. fresh=True usa un proceso aparte (ve lo recién conectado)."""
    if fresh and not getattr(sys, "frozen", False):
        try:
            r = subprocess.run([sys.executable, "-c", _CODE], capture_output=True, text=True, timeout=10,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0 and r.stdout.strip():
                return _parse(json.loads(r.stdout.strip().splitlines()[-1]))
        except Exception:                                   # noqa: BLE001
            pass
    try:
        import sounddevice as sd
        d, h = sd.query_devices(), sd.query_hostapis()
        dflt = sd.default.device[1]
        host = d[dflt]["hostapi"] if isinstance(dflt, int) and 0 <= dflt < len(d) else None
        return _parse({"dev": [{"name": x["name"], "out": x["max_output_channels"], "host": x["hostapi"]} for x in d], "host": host})
    except Exception:                                       # noqa: BLE001
        return []


def resolve_index(name: str):
    """Índice de PortAudio (el de este proceso) del dispositivo con ese nombre, o None si Orbi todavía no lo conoce."""
    if not name:
        return None
    try:
        import sounddevice as sd
        d = sd.query_devices()
        dflt = sd.default.device[1]
        host = d[dflt]["hostapi"] if isinstance(dflt, int) and 0 <= dflt < len(d) else None
        low = name.lower()
        for i, x in enumerate(d):
            if x["max_output_channels"] > 0 and (host is None or x["hostapi"] == host) and str(x["name"]).strip().lower() == low:
                return i
    except Exception:                                       # noqa: BLE001
        pass
    return None
