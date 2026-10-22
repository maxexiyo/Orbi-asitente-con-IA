"""Keys y modelos de Gemini compartidos por todo Orbi (Live, agente, observador, análisis de documentos).

Por qué existe: antes cada parte rotaba keys "a ciegas" y una racha de errores dejaba a Orbi sin respuesta hasta reiniciar.
Ahora:
  - cada key tiene su propio enfriamiento (por cuota 429 se respeta el "retry in Xs" que manda Google)
  - los errores se clasifican: cuota / key inválida / modelo inexistente / red / otro
  - si un modelo se queda sin cuota (la cuota es POR MODELO) se prueba el siguiente de la lista
  - nada se rinde para siempre: siempre se vuelve a intentar cuando pasa el enfriamiento
"""
import re, threading, time

QUOTA, AUTH, MODEL, TRANSIENT, OTHER = "quota", "auth", "model", "transient", "other"
SESSION = "session"      # el identificador de sesión de Live caducó o no sirve con esta key: hay que empezar de cero


def classify(err) -> tuple:
    """(tipo, segundos_de_espera) a partir de la excepción o del texto del error."""
    msg = str(err)
    low = msg.lower()
    m = re.search(r"retry(?:\s+in|delay['\"]?:?\s*['\"]?)\s*([\d.]+)\s*s", low)
    retry = float(m.group(1)) if m else None
    if any(s in low for s in ("429", "resource_exhausted", "quota", "rate limit", "rate_limit", "too many requests")):
        return QUOTA, min(max(retry or 60.0, 5.0), 600.0)
    # "1008 ... session not found": NO es un modelo inexistente (antes caía en "not found" -> MODEL y reintentaba con el mismo handle viejo)
    if "session" in low and any(s in low for s in ("not found", "invalid", "expired", "resum", "unknown", "1008")):
        return SESSION, 0.0
    if any(s in low for s in ("api key not valid", "api_key_invalid", "permission_denied", "401", "403",
                              "unauthenticated", "invalid api key", "api key expired")):
        return AUTH, 900.0
    if any(s in low for s in ("not found", "404", "not supported", "unsupported", "is not available",
                              "no longer available", "deprecated")):
        return MODEL, 0.0
    if any(s in low for s in ("timeout", "timed out", "connection", "503", "500", "502", "504", "unavailable",
                              "1011", "1006", "1008", "internal", "overloaded", "network", "reset by peer", "eof")):
        return TRANSIENT, 5.0
    return OTHER, 3.0


class KeyPool:
    """Keys con enfriamiento. Las de CUOTA se enfrían por (key, modelo); las demás, para toda la key."""

    def __init__(self, keys):
        self.keys = [k for k in dict.fromkeys(keys) if k]
        self.cool = {}                       # (key, modelo|"") -> hasta cuándo descansa
        self.last_error = {}                 # key -> (tipo, texto corto)
        self._i = 0
        self._lock = threading.Lock()

    def _free(self, key, scope, now):
        return self.cool.get((key, ""), 0) <= now and (not scope or self.cool.get((key, scope), 0) <= now)

    def available(self, scope=None):
        now = time.time()
        return [k for k in self.keys if self._free(k, scope, now)]

    def pick(self, scope=None):
        """Siguiente key disponible (round-robin) o None si todas están descansando."""
        with self._lock:
            av = self.available(scope)
            if not av:
                return None
            self._i += 1
            return av[self._i % len(av)]

    def penalize(self, key, seconds, kind=OTHER, text="", scope=None):
        with self._lock:
            k = (key, scope if (kind == QUOTA and scope) else "")
            self.cool[k] = max(self.cool.get(k, 0), time.time() + seconds)
            self.last_error[key] = (kind, str(text)[:160])

    def wait_seconds(self, scope=None) -> float:
        """Cuánto falta para que alguna key vuelva (0 si ya hay una libre)."""
        if not self.keys or self.available(scope):
            return 0.0
        now = time.time()
        waits = []
        for k in self.keys:
            w = max(self.cool.get((k, ""), 0), self.cool.get((k, scope or ""), 0)) - now
            waits.append(max(0.0, w))
        return min(waits)

    def describe(self) -> str:
        """Resumen legible de por qué no hay keys (para mostrárselo al usuario)."""
        if not self.keys:
            return "no hay keys de Gemini"
        kinds = {}
        for k in self.keys:
            t = self.last_error.get(k, ("?", ""))[0]
            kinds[t] = kinds.get(t, 0) + 1
        names = {QUOTA: "sin cuota (límite por minuto/día)", AUTH: "key inválida o sin permiso",
                 MODEL: "modelo no disponible", TRANSIENT: "fallas de red/servidor", OTHER: "error desconocido"}
        return ", ".join(f"{n}× {names.get(t, t)}" for t, n in kinds.items())


class AllBusy(Exception):
    pass


_CLIENTS: dict = {}
_CLIENTS_LOCK = threading.Lock()
_NO_THINK: set = set()
_ANNOUNCED: set = set()          # modelos que rechazaron el ajuste de thinking (se les deja el suyo)


def client_for(key):
    """Un cliente por key, reutilizado: antes se creaba uno nuevo (y una conexión TLS nueva) en CADA llamada."""
    from google import genai
    with _CLIENTS_LOCK:
        c = _CLIENTS.get(key)
        if c is None:
            c = _CLIENTS[key] = genai.Client(api_key=key)
        return c


def _thinking_for(model: str, mode):
    """ThinkingConfig que baja la latencia según la familia del modelo; None si no aplica.

    Gemini 3.x Flash: thinking_level="low" (en 3.8/3.7 \"minimal\" da error). Gemini 2.5 Flash: presupuesto 0 (apagado).
    Flash-Lite ya piensa lo mínimo por defecto, y los demás modelos se dejan como están.
    """
    if not mode or str(mode).lower() == "default":
        return None
    from google.genai import types
    m = model.lower()
    if "lite" in m or "image" in m:
        return None
    if "gemini-3" in m:
        return types.ThinkingConfig(thinking_level=str(mode).lower())
    if "gemini-2.5" in m and "flash" in m:
        return types.ThinkingConfig(thinking_budget=0)
    return None


def _with_thinking(config, tc):
    from google.genai import types
    if config is None:
        return types.GenerateContentConfig(thinking_config=tc)
    if getattr(config, "thinking_config", None) is not None:      # si ya traía el suyo, se respeta
        return config
    return config.model_copy(update={"thinking_config": tc})


def generate(pool: KeyPool, models, contents, config=None, retries_per_model=None, thinking=None):
    """generate_content con rotación de keys y fallback de modelos. Devuelve (respuesta, modelo_usado).

    models: un modelo o lista en orden de preferencia.
    thinking: None = no tocar · "low" = pensar poco (más rápido; para el agente). Si un modelo rechaza el ajuste, se reintenta sin él.
    Lanza AllBusy(texto) si nada funcionó (con el motivo), no se queda colgado.
    """
    models = [models] if isinstance(models, str) else list(models)
    bad_models = _BAD_MODELS
    last = None
    for model in models:
        if model in bad_models:
            continue
        tried = set()
        while True:
            key = pool.pick(model)
            if key is None or key in tried:
                break                                    # todas las keys de este modelo agotadas -> siguiente modelo
            tried.add(key)
            try:
                client = client_for(key)
                cfg = config
                if thinking and model not in _NO_THINK:
                    tc = _thinking_for(model, thinking)
                    if tc is not None:
                        cfg = _with_thinking(config, tc)
                        if model not in _ANNOUNCED:
                            _ANNOUNCED.add(model)
                            print(f"[llm] {model}: thinking ajustado a {thinking}")
                try:
                    r = client.models.generate_content(model=model, contents=contents, config=cfg)
                except Exception as e:                   # noqa: BLE001
                    if cfg is not config and "thinking" in str(e).lower():
                        _NO_THINK.add(model)             # este modelo no acepta el ajuste: reintenta igual, sin tocarlo
                        print(f"[llm] {model} rechazó el ajuste de thinking ({str(e)[:100]}); sigo con el suyo por defecto")
                        r = client.models.generate_content(model=model, contents=contents, config=config)
                    else:
                        raise
                return r, model
            except Exception as e:                       # noqa: BLE001
                kind, wait = classify(e)
                last = f"{model}: {str(e)[:160]}"
                if kind == MODEL:
                    bad_models.add(model)                # no insistas con un modelo que no existe
                    break
                if kind == QUOTA:
                    pool.penalize(key, wait, kind, e, scope=model)     # la cuota es por modelo
                    continue
                pool.penalize(key, wait, kind, e)
    raise AllBusy(last or pool.describe())


_BAD_MODELS: set = set()
