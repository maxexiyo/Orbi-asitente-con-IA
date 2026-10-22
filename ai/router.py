"""Router de IA (modo texto): rota keys y modelos y cae al siguiente proveedor si falla.

Se usa cuando Gemini Live no está conectado. Los errores se clasifican (cuota / key inválida / modelo malo / red) y cada
key descansa solo lo que corresponde, así una racha de fallas ya no deja a Orbi "sin cerebros" hasta reiniciar.
"""
import hashlib, json, sys, time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import load_config

ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}
ORDER = ["groq", "gemini", "openrouter"]


class AIRouter:
    def __init__(self, providers):
        self.providers = providers          # [{name,url,model(s),keys}]
        self.cooldowns = {}                 # (key, modelo|"") -> timestamp hasta cuando descansa
        self.bad_models = set()
        self.cache = {}
        self.client = httpx.Client(timeout=30)

    @classmethod
    def from_config(cls, cfg=None):
        cfg = cfg or load_config()
        models = cfg.get("text_models", {})
        providers = []
        for name in ORDER:
            keys = [k for k in cfg.get(f"{name}_keys", []) if k]
            if keys and name in models:
                providers.append(dict(name=name, url=ENDPOINTS[name], model=models[name], keys=keys))
        return cls(providers)

    def _free(self, key, model):
        now = time.time()
        return self.cooldowns.get((key, ""), 0) < now and self.cooldowns.get((key, model), 0) < now

    def _cool(self, key, seconds, model=""):
        self.cooldowns[(key, model)] = time.time() + seconds

    @staticmethod
    def _retry_after(r, default=60.0):
        try:
            return min(300.0, max(5.0, float(r.headers.get("retry-after", default))))
        except (TypeError, ValueError):
            return default

    def chat(self, messages, use_cache=True):
        ck = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()
        if use_cache and ck in self.cache:
            return self.cache[ck]
        errors = []
        for p in self.providers:
            models = p["model"] if isinstance(p["model"], list) else [p["model"]]
            for model in models:
                if model in self.bad_models:
                    continue
                for key in [k for k in p["keys"] if self._free(k, model)]:
                    try:
                        r = self.client.post(p["url"], headers={"Authorization": f"Bearer {key}"},
                                             json={"model": model, "messages": messages})
                    except httpx.HTTPError as e:
                        self._cool(key, 10.0)
                        errors.append(f"{p['name']}: red ({type(e).__name__})")
                        continue
                    if r.status_code == 429:
                        self._cool(key, self._retry_after(r), model)           # cuota: por modelo
                        errors.append(f"{p['name']}/{model}: sin cuota")
                        continue
                    if r.status_code in (401, 403):
                        self._cool(key, 900.0)
                        errors.append(f"{p['name']}: key inválida")
                        continue
                    if r.status_code in (400, 404):
                        self.bad_models.add(model)                              # el modelo no existe/no sirve: sigue con otro
                        errors.append(f"{p['name']}/{model}: {r.status_code}")
                        break
                    if r.status_code >= 500:
                        self._cool(key, 10.0)
                        errors.append(f"{p['name']}: servidor {r.status_code}")
                        continue
                    try:
                        text = r.json()["choices"][0]["message"]["content"]
                    except Exception:                                           # noqa: BLE001
                        errors.append(f"{p['name']}/{model}: respuesta rara")
                        continue
                    self.cache[ck] = text
                    return text
        why = "; ".join(dict.fromkeys(errors[-4:])) or "no hay proveedores con keys"
        print("[router] sin respuesta:", why)
        return f"Ups, no pude contestar ahora ({why}). Intenta en un minuto."


if __name__ == "__main__":
    router = AIRouter.from_config()
    print(router.chat([{"role": "user", "content": "Di hola en una frase."}]))
