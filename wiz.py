"""Luces WiZ directo por red local (UDP, puerto 38899). Sin Home Assistant, sin cuenta, sin librerías extra.

Cómo funciona: las luces WiZ contestan comandos JSON por UDP en tu red WiFi. Orbi las descubre mandando un
"getPilot" por broadcast y guarda los nombres que le des en wiz_nombres.json (ej. «cuarto», «sala»).
Requisito: en la app WiZ activa «Permitir control local» (Ajustes > Privacidad/Seguridad) y estar en la misma red.
Opcional en config.json:  "wiz": {"cuarto": "192.168.1.50", "sala": "192.168.1.51"}  (IPs fijas, si el broadcast falla)
"""
import json, socket, time, unicodedata
from pathlib import Path

PORT = 38899
NAMES_PATH = Path(__file__).parent / "wiz_nombres.json"

COLORS = {"rojo": (255, 0, 0), "verde": (0, 200, 0), "azul": (0, 90, 255), "amarillo": (255, 210, 0),
          "naranja": (255, 120, 0), "morado": (150, 0, 255), "rosa": (255, 60, 160), "blanco": (255, 255, 255),
          "celeste": (80, 200, 255), "cian": (0, 220, 220)}
KELVIN = {"calido": 2700, "neutro": 4000, "frio": 6500}
SCENES = {"oceano": 1, "romantico": 2, "atardecer": 3, "fiesta": 4, "chimenea": 5, "acogedor": 6, "bosque": 7,
          "relajante": 16, "relax": 16, "enfoque": 15, "tv": 18, "noche": 14, "vela": 29}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).lower().strip())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _load_names() -> dict:
    try:
        return json.loads(NAMES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_names(d: dict):
    try:
        NAMES_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def _udp(ip: str, msg: dict, timeout: float = 1.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(json.dumps(msg).encode(), (ip, PORT))
        data, _ = s.recvfrom(2048)
        return json.loads(data.decode())
    except Exception:
        return None
    finally:
        s.close()


class Wiz:
    def __init__(self, fixed: dict | None = None):
        self.fixed = {_norm(k): v for k, v in (fixed or {}).items()}      # nombre -> ip (de config.json)
        self.bulbs = {}                                                    # ip -> {"mac": ..., "state": ...}
        self.last_scan = 0.0

    def discover(self, wait: float = 1.6) -> dict:
        """Broadcast getPilot y junta las respuestas."""
        found = {}
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.4)
        try:
            for _ in range(2):
                s.sendto(b'{"method":"getPilot","params":{}}', ("255.255.255.255", PORT))
            t0 = time.time()
            while time.time() - t0 < wait:
                try:
                    data, (ip, _p) = s.recvfrom(2048)
                    r = json.loads(data.decode()).get("result", {})
                    found[ip] = {"mac": r.get("mac", ip), "state": r.get("state")}
                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            s.close()
        for ip in self.fixed.values():                                    # IPs fijas que no contestaron al broadcast
            if ip not in found:
                r = _udp(ip, {"method": "getPilot", "params": {}})
                if r:
                    found[ip] = {"mac": r.get("result", {}).get("mac", ip), "state": r.get("result", {}).get("state")}
        self.bulbs, self.last_scan = found, time.time()
        return found

    def _ensure(self):
        if not self.bulbs or time.time() - self.last_scan > 600:
            self.discover()

    def listing(self) -> list:
        """[(nombre, ip, encendida)] — foco sin nombre = 'foco N'."""
        self._ensure()
        names = _load_names()
        by_ip = {ip: n for n, ip in self.fixed.items()}
        out = []
        for i, (ip, b) in enumerate(sorted(self.bulbs.items()), 1):
            out.append((by_ip.get(ip) or names.get(b["mac"]) or f"foco {i}", ip, b.get("state")))
        return out

    def rename(self, quien: str, nuevo: str) -> bool:
        self._ensure()
        found = self.find(quien)
        if len(found) != 1 or not nuevo.strip():
            return False
        ip = found[0][1]
        names = _load_names()
        names[self.bulbs[ip]["mac"]] = nuevo.strip()[:40]
        _save_names(names)
        return True

    def find(self, nombre: str) -> list:
        lst = self.listing()
        q = _norm(nombre)
        if q in ("", "todas", "todos", "luces", "focos"):
            return lst
        exact = [x for x in lst if _norm(x[0]) == q]
        return exact or [x for x in lst if q in _norm(x[0]) or _norm(x[0]) in q]

    def control(self, ips: list, accion: str, valor=None) -> str:
        accion, v = _norm(accion), _norm(valor or "")
        if accion in ("encender", "prender"):
            msg = {"method": "setPilot", "params": {"state": True}}
        elif accion == "apagar":
            msg = {"method": "setPilot", "params": {"state": False}}
        elif accion == "brillo":
            try:
                pct = max(10, min(100, int(float(v.strip("%")))))
            except ValueError:
                return "El brillo debe ser un número de 1 a 100."
            msg = {"method": "setPilot", "params": {"state": True, "dimming": pct}}
        elif accion == "color":
            if v in COLORS:
                r, g, b = COLORS[v]
                msg = {"method": "setPilot", "params": {"state": True, "r": r, "g": g, "b": b, "dimming": 100}}
            elif v in KELVIN:
                msg = {"method": "setPilot", "params": {"state": True, "temp": KELVIN[v]}}
            else:
                return f"No conozco el color «{valor}». Tengo: {', '.join(COLORS)}, cálido, neutro, frío."
        elif accion == "temperatura":
            try:
                k = max(2200, min(6500, int(float(v))))
            except ValueError:
                k = KELVIN.get(v)
                if not k:
                    return "Dime cálido, neutro, frío o un número en kelvin (2200-6500)."
            msg = {"method": "setPilot", "params": {"state": True, "temp": k}}
        elif accion == "escena":
            sid = SCENES.get(v)
            if not sid:
                return f"No conozco esa escena. Tengo: {', '.join(SCENES)}."
            msg = {"method": "setPilot", "params": {"state": True, "sceneId": sid}}
        else:
            return "Acción inválida (encender, apagar, brillo, color, temperatura, escena)."
        ok = sum(1 for ip in ips if _udp(ip, msg))
        return "ok" if ok == len(ips) else (f"Solo contestaron {ok} de {len(ips)} focos (¿están en la misma red?)." if ok
                                            else "Ningún foco contestó. ¿Activaste «control local» en la app WiZ y estás en su misma red WiFi?")
