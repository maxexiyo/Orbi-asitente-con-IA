"""Casa inteligente con Home Assistant (API REST local).

¿Por qué Home Assistant y no "Alexa directo"? Alexa no tiene una API para que una app de PC prenda tus focos:
solo se puede desde el celular/Echo o con "skills" propias. Home Assistant (gratis, corre en una Raspberry Pi,
una PC vieja o Docker) integra Tuya/Smart Life, Philips Hue, TP-Link Kasa, WiZ, Shelly, Xiaomi, etc. y expone una API
local sencilla. Orbi habla con esa API. (Y desde Home Assistant también puedes exponer tus cosas a Alexa si quieres.)

Configuración (en tu .env o en config.json):
    HA_URL=http://homeassistant.local:8123
    HA_TOKEN=eyJ...        <- Perfil de tu usuario en Home Assistant > Seguridad > Tokens de acceso de larga duración
Seguridad: solo se exponen luces, enchufes/interruptores, ventiladores, persianas, escenas, clima y similares.
NO se exponen cerraduras ni alarmas, y abrir cocheras/portones SIEMPRE pide tu OK.
"""
import re, unicodedata

import httpx

SAFE_DOMAINS = ("light", "switch", "fan", "cover", "scene", "climate", "input_boolean", "humidifier", "vacuum",
                "media_player")
COLORS = {"rojo": [255, 0, 0], "verde": [0, 200, 0], "azul": [0, 90, 255], "amarillo": [255, 210, 0],
          "naranja": [255, 120, 0], "morado": [150, 0, 255], "rosa": [255, 60, 160], "blanco": [255, 255, 255],
          "celeste": [80, 200, 255], "cian": [0, 220, 220]}
KELVIN = {"cálido": 2700, "calido": 2700, "neutro": 4000, "frío": 6500, "frio": 6500}
STOP = {"luz", "luces", "foco", "focos", "lampara", "lamparas", "de", "del", "la", "el", "los", "las", "mi", "mis",
        "un", "una", "en", "al", "a"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


class HAError(Exception):
    pass


class HomeAssistant:
    def __init__(self, url: str, token: str, timeout: float = 6.0):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self.timeout = timeout
        self._cache = None

    # ---------------------------------------------------------------- bajo nivel
    def _req(self, method: str, path: str, json=None):
        try:
            r = httpx.request(method, self.url + path, headers=self.headers, json=json, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise HAError(f"No pude conectar con Home Assistant en {self.url} ({type(e).__name__}).")
        if r.status_code == 401:
            raise HAError("Home Assistant rechazó el token (HA_TOKEN inválido o vencido).")
        if r.status_code >= 400:
            raise HAError(f"Home Assistant respondió {r.status_code}: {r.text[:120]}")
        return r.json() if r.content else None

    def states(self, refresh: bool = False) -> list:
        if self._cache is None or refresh:
            self._cache = self._req("GET", "/api/states") or []
        return self._cache

    # ---------------------------------------------------------------- consulta
    def entities(self, domain: str = "", refresh: bool = False) -> list:
        out = []
        for s in self.states(refresh):
            eid = s["entity_id"]
            dom = eid.split(".", 1)[0]
            if dom not in SAFE_DOMAINS or (domain and dom != domain):
                continue
            a = s.get("attributes", {})
            out.append(dict(entity_id=eid, nombre=a.get("friendly_name", eid), dominio=dom, estado=s.get("state"),
                            clase=a.get("device_class"), attrs=a))
        return out

    def find(self, query: str, domain: str = "") -> list:
        """Entidades cuyo nombre contiene todas las palabras relevantes de `query` (sin acentos)."""
        q = _norm(query)
        if re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", q):
            hit = [e for e in self.entities(domain) if e["entity_id"] == q]
            if hit:
                return hit
        toks = [t for t in re.split(r"\W+", q) if t and t not in STOP] or [t for t in re.split(r"\W+", q) if t]
        scored = []
        for e in self.entities(domain):
            name = _norm(e["nombre"] + " " + e["entity_id"])
            if all(t in name for t in toks):
                scored.append((_norm(e["nombre"]) == q, -len(e["nombre"]), e))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [s[2] for s in scored]

    # ---------------------------------------------------------------- acciones
    def call(self, domain: str, service: str, data: dict):
        self._req("POST", f"/api/services/{domain}/{service}", json=data)
        self._cache = None

    def control(self, ent: dict, accion: str, valor=None) -> str:
        """Ejecuta la acción sobre una entidad. Devuelve texto de lo que hizo o lanza HAError."""
        eid, dom = ent["entity_id"], ent["dominio"]
        accion = _norm(accion or "")
        if accion in ("encender", "prender", "activar", "on"):
            if dom == "cover":
                self.call("cover", "open_cover", {"entity_id": eid}); return f"Abrí {ent['nombre']}"
            self.call(dom, "turn_on", {"entity_id": eid}); return f"Encendí {ent['nombre']}"
        if accion in ("apagar", "desactivar", "off"):
            if dom == "cover":
                self.call("cover", "close_cover", {"entity_id": eid}); return f"Cerré {ent['nombre']}"
            self.call(dom, "turn_off", {"entity_id": eid}); return f"Apagué {ent['nombre']}"
        if accion in ("alternar", "toggle", "cambiar"):
            self.call(dom, "toggle", {"entity_id": eid}); return f"Cambié el estado de {ent['nombre']}"
        if accion in ("abrir", "cerrar") and dom == "cover":
            self.call("cover", "open_cover" if accion == "abrir" else "close_cover", {"entity_id": eid})
            return f"{'Abrí' if accion == 'abrir' else 'Cerré'} {ent['nombre']}"
        if accion == "brillo" and dom == "light":
            try:
                pct = max(1, min(100, int(float(valor))))
            except (TypeError, ValueError):
                raise HAError("Dime el brillo de 1 a 100.")
            self.call("light", "turn_on", {"entity_id": eid, "brightness_pct": pct}); return f"Brillo de {ent['nombre']} al {pct}%"
        if accion == "color" and dom == "light":
            v = _norm(str(valor or ""))
            if v in KELVIN or str(valor).lower() in KELVIN:
                self.call("light", "turn_on", {"entity_id": eid, "color_temp_kelvin": KELVIN.get(v, KELVIN.get(str(valor).lower()))})
            elif v in COLORS:
                self.call("light", "turn_on", {"entity_id": eid, "rgb_color": COLORS[v]})
            else:
                raise HAError(f"No conozco el color «{valor}». Opciones: {', '.join(COLORS)}, cálido, frío.")
            return f"Cambié {ent['nombre']} a {valor}"
        if accion == "temperatura" and dom == "climate":
            try:
                t = float(valor)
            except (TypeError, ValueError):
                raise HAError("Dime a cuántos grados.")
            self.call("climate", "set_temperature", {"entity_id": eid, "temperature": t}); return f"{ent['nombre']} a {t:g}°"
        raise HAError(f"No puedo hacer «{accion}» con {ent['nombre']} ({dom}).")

    @staticmethod
    def needs_ok(ent: dict) -> bool:
        """Cocheras, portones y puertas siempre piden OK."""
        return ent["dominio"] == "cover" and (ent.get("clase") in ("garage", "gate", "door"))
