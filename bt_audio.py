"""Micrófono de Orbi vs. audífonos/bocinas Bluetooth.

POR QUÉ: casi todos los audífonos y bocinas Bluetooth traen micrófono. En cuanto UNA app abre ese micrófono, Windows cambia el
aparato del perfil de música (A2DP, estéreo bueno) al de llamadas (Manos libres / HFP, mono y de mala calidad), y en muchos modelos
(los TWS tipo OPPO Enco Buds y las bocinas nuevas) el audio de la PC se corta o suena horrible hasta que esa app cierra el micro.
Orbi abre el micrófono PREDETERMINADO de Windows; si ese es el del aparato Bluetooth, pasa justo eso.

QUÉ HACE: al arrancar, si el micrófono predeterminado parece Bluetooth, Orbi usa otro (el de la laptop / webcam / USB) y tus
audífonos se quedan solo como salida de audio. También puedes fijarlo a mano en config.json:
    "microfono": "Matriz de micrófonos"        (parte del nombre; se ve en Ajustes de sonido de Windows o en la consola de Orbi)
    "evitar_mic_bluetooth": false              (para volver a usar siempre el predeterminado)
    "mic_bluetooth_palabras": ["enco", "mi bocina"]   (palabras extra que identifican a un aparato Bluetooth por su nombre)
"""
import re

_BT = ("bluetooth", "hands-free", "hands free", "handsfree", "manos libres", "ag audio", "bthhf", "a2dp", "airpods", "buds", " tws")


def parece_bluetooth(nombre: str, extra=()) -> bool:
    n = " " + re.sub(r"\s+", " ", str(nombre).lower()) + " "
    return any(k in n for k in (*_BT, *(str(e).lower() for e in extra if e)))


def _entradas(sd):
    """[(indice, nombre)] de entradas de audio en el mismo «host API» que la predeterminada (para no listar el mismo micro 4 veces)."""
    d = sd.query_devices()
    dflt = sd.default.device[0]
    host = d[dflt]["hostapi"] if isinstance(dflt, int) and 0 <= dflt < len(d) else None
    return [(i, str(x["name"])) for i, x in enumerate(d)
            if x["max_input_channels"] > 0 and (host is None or x["hostapi"] == host)], dflt


def elegir_entrada(cfg: dict, log=print):
    """Índice de PortAudio del micrófono que debe usar Orbi, o None = el predeterminado de Windows."""
    try:
        import sounddevice as sd
        ins, dflt = _entradas(sd)
    except Exception as e:                                         # noqa: BLE001
        log(f"[audio] no pude revisar los micrófonos ({type(e).__name__}): uso el predeterminado")
        return None
    nombres = dict(ins)
    pedido = str(cfg.get("microfono") or "").strip().lower()
    if pedido:                                                     # lo fijaste a mano
        for i, n in ins:
            if pedido in n.lower():
                log(f"[audio] micrófono: «{n}» (config.json)")
                return i
        log(f"[audio] no encontré un micrófono que contenga «{pedido}»; uso el predeterminado. Disponibles: {', '.join(n for _, n in ins)}")
        return None
    actual = nombres.get(dflt, "")
    extra = cfg.get("mic_bluetooth_palabras") or ()
    if not bool(cfg.get("evitar_mic_bluetooth", True)) or not parece_bluetooth(actual, extra):
        log(f"[audio] micrófono: «{actual or 'predeterminado'}»")
        return None
    libres = [(i, n) for i, n in ins if not parece_bluetooth(n, extra) and not re.search(r"mezcla|stereo mix|what u hear|loopback|asignador|mapper", n, re.I)]
    pref = [x for x in libres if re.search(r"micr|mic|array|matriz|webcam|usb", x[1], re.I)]
    if (pref or libres):
        i, n = (pref or libres)[0]
        log(f"[audio] el micrófono predeterminado es Bluetooth («{actual}») y eso corta el audio de esos aparatos: uso «{n}» "
            f"(cámbialo con \"microfono\" en config.json, o desactiva esto con \"evitar_mic_bluetooth\": false)")
        return i
    log(f"[audio] el micrófono predeterminado es Bluetooth («{actual}») y no hay otro entrada disponible: si el audio de tus audífonos se corta "
        f"mientras Orbi está abierto, conecta/activa otro micrófono")
    return None
