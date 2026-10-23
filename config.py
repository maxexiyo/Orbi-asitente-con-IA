"""Carga las keys desde tu .env (y ajustes opcionales desde config.json).

Busca el .env en la carpeta del proyecto y, si no está, en la carpeta de arriba.
Detecta solo las variables, sin importar cómo las llamaste:
  Gemini:      GEMINI_API_KEY, GEMINI_API_KEY_1, GEMINI_KEY_2, GEMINI_API_KEYS=k1,k2, GOOGLE_API_KEY...
  Groq:        GROQ_API_KEY, GROQ_API_KEY_1, ...
  OpenRouter:  OPENROUTER_API_KEY, OPENROUTER_API_KEY_1, ...
Todas las keys pueden ir en UNA variable como arreglo: GEMINI_API_KEYS=["AIza...","AIza..."]
  (también sirve con comas, una por línea, o arreglo de varias líneas).
Si tu variable tiene otro nombre y no se detecta: ORBI_GEMINI_VAR=NOMBRE_DE_TU_VARIABLE
Opcionales en el .env:  LIVE_MODEL, LIVE_VOICE, HEADPHONES=true
"""
import json, os, re
from pathlib import Path

ROOT = Path(__file__).parent

DEFAULT_TEXT_MODELS = {
    "groq": "llama-3.3-70b-versatile",
    "gemini": ["gemini-3.8-flash", "gemini-2.5-flash"],
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
}
PROVIDER_PREFIXES = {
    "gemini": ("GEMINI", "GOOGLE_API", "GOOGLE_AI"),
    "groq": ("GROQ",),
    "openrouter": ("OPENROUTER",),
}


def _parse_env_file(path: Path) -> dict:
    env = {}
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:]
        k, v = line.split("=", 1)
        v = v.strip()
        # valor de varias líneas: arreglo [ ... ] o comillas que no se cierran
        while i < len(lines) and (
            (v.startswith("[") and "]" not in v)
            or (v[:1] in "\"'" and len(v) >= 1 and v.count(v[0]) % 2 == 1)
        ):
            v += "\n" + lines[i].strip()
            i += 1
        if v[:1] in "\"'" and v[-1:] == v[:1] and len(v) >= 2:
            v = v[1:-1]
        elif v[:1] not in "[{" and " #" in v:
            v = v.split(" #", 1)[0].strip()
        env[k.strip()] = v
    return env


def _natural(name: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


KEY_PATTERNS = {
    "gemini": re.compile(r"AIza[\w\-]{30,}"),
    "groq": re.compile(r"gsk_[\w]{20,}"),
    "openrouter": re.compile(r"sk-or-[\w\-]{20,}"),
}
# variables que tienen keys de Google pero NO son de Gemini
NOT_GEMINI = ("CSE", "SEARCH", "MAPS", "YOUTUBE", "TRANSLATE", "VISION", "FIREBASE", "FCM")


def _extract(value: str, pattern) -> list:
    """Saca las keys de un valor: arreglo JSON/Python, lista con comas, una por línea, etc."""
    found = pattern.findall(value)
    if found:
        return found
    parts = re.split(r"[,\s;]+", value.strip().strip("[]{}"))
    return [p.strip("\"'[]{}") for p in parts if len(p.strip("\"'[]{}")) >= 20]


def _collect_keys(env: dict, prov: str) -> tuple:
    prefixes = PROVIDER_PREFIXES[prov]
    pattern = KEY_PATTERNS[prov]
    keys, names = [], []

    def add(name):
        got = _extract(env[name], pattern)
        for k in got:
            if k not in keys:
                keys.append(k)
        if got and name not in names:
            names.append(name)

    forced = env.get(f"ORBI_{prov.upper()}_VAR")          # opcional: nombre exacto de tu variable
    if forced and forced in env:
        add(forced)
        return keys, names
    for name in sorted(env, key=_natural):
        up = name.upper()
        if up.startswith(prefixes) and "KEY" in up and "MODEL" not in up:
            add(name)
    if not keys:                                          # plan B: cualquier variable "KEY" con el patrón de la key
        for name in sorted(env, key=_natural):
            up = name.upper()
            if "KEY" in up and not any(w in up for w in NOT_GEMINI) and pattern.search(env[name]):
                add(name)
    return keys, names


def load_config() -> dict:
    cfg = {}
    jpath = ROOT / "config.json"
    if jpath.exists():                                   # opcional: solo ajustes
        cfg = json.loads(jpath.read_text(encoding="utf-8"))

    env = {}
    for p in (ROOT.parent / ".env", ROOT / ".env"):      # la del proyecto tiene prioridad
        if p.exists():
            env.update(_parse_env_file(p))
    env.update(os.environ)                               # las variables reales del sistema mandan

    cfg["_env_names"] = sorted(n for n in env if any(w in n.upper() for w in ("KEY", "GEMINI", "GROQ", "OPENROUTER")))
    cfg["_key_vars"] = {}
    for prov in PROVIDER_PREFIXES:
        keys, names = _collect_keys(env, prov)
        for k in cfg.get(f"{prov}_keys", []):            # keys sueltas en config.json (compatibilidad)
            if k and not k.startswith(("AIza_key", "gsk_key", "sk-or-key")) and k not in keys:
                keys.append(k)
        cfg[f"{prov}_keys"] = keys
        cfg["_key_vars"][prov] = names

    cfg["_agenda_env"] = {k: v for k, v in env.items() if k.upper().startswith(("ORBI_MAIL_PASS_", "ORBI_CAL_"))}
    cfg["text_models"] = {**DEFAULT_TEXT_MODELS, **cfg.get("text_models", {})}
    if env.get("LIVE_MODEL"):
        cfg["live_model"] = env["LIVE_MODEL"]
    if env.get("LIVE_VOICE"):
        cfg["live_voice"] = env["LIVE_VOICE"]
    if env.get("HEADPHONES"):
        cfg["headphones"] = env["HEADPHONES"].strip().lower() in ("1", "true", "yes", "si", "sí")
    cfg.setdefault("live_model", "gemini-3.8-live")
    # Modelos en orden de preferencia: si el primero se queda sin cuota (la cuota es POR MODELO) o no existe, se usa el siguiente.
    cfg["live_models"] = _unique([cfg["live_model"], "gemini-3.8-live", "gemini-3.1-flash-live-preview"])
    cfg["agent_models"] = _unique([cfg.get("agent_model"), "gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash"])
    cfg["analysis_models"] = _unique([cfg.get("analysis_model"), "gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash"])
    cfg["observer_models"] = _unique([cfg.get("observer_model"), "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-2.5-flash"])
    # Home Assistant (casa inteligente)
    ha = dict(cfg.get("home_assistant") or {})
    ha["url"] = env.get("HA_URL") or env.get("HOMEASSISTANT_URL") or ha.get("url") or ""
    ha["token"] = env.get("HA_TOKEN") or env.get("HOMEASSISTANT_TOKEN") or ha.get("token") or ""
    cfg["home_assistant"] = ha
    return cfg


def _unique(items):
    return [m for m in dict.fromkeys(i for i in items if i)]


def gemini_keys(cfg: dict) -> list:
    keys = cfg.get("gemini_keys", [])
    if not keys:
        vistas = ", ".join(cfg.get("_env_names", [])) or "(ninguna)"
        raise SystemExit(
            "No encontré keys de Gemini en tu .env.\n"
            f"Variables parecidas que sí vi: {vistas}\n"
            "Revisa que el .env esté en la carpeta del proyecto (o en la de arriba) y que la variable "
            "empiece con GEMINI y contenga KEY, por ejemplo GEMINI_API_KEY_1=AIza..."
        )
    return keys
