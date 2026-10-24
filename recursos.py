"""Monitor de recursos de la PC: CPU y RAM, avisa si algo se pone pesado y (solo con tu OK) cierra o baja la prioridad de un proceso.

Todo local con `psutil` (pip install psutil). No manda nada a Gemini ni gasta cuota.
  estado()                -> dict con CPU %, RAM %, y los procesos que más consumen
  Monitor(on_alert).start -> hilo que avisa si CPU/RAM pasan el umbral varias revisiones seguidas (con enfriamiento)
  cerrar(nombre) / bajar_prioridad(nombre) -> actúan sobre TODOS los procesos con ese nombre (pc_tools pide el OK antes)
"""
import os, threading, time
from collections import defaultdict

# Nunca se tocan: sistema, Orbi mismo y cosas que dejarían la PC inservible
PROTEGIDOS = {"system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
              "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe", "memcompression",
              "taskmgr.exe", "python.exe", "pythonw.exe", "py.exe", "orbi.exe", "msmpeng.exe", "sihost.exe", "ctfmon.exe"}


def _ps():
    import psutil
    return psutil


def _agrupa(por: str, n: int):
    ps = _ps()
    acc = defaultdict(lambda: [0.0, 0, 0])             # nombre -> [cpu%, rss_bytes, cuántos]
    for p in ps.process_iter(["name", "cpu_percent", "memory_info"]):
        try:
            i = p.info
            nombre = (i["name"] or "?")
            a = acc[nombre]
            a[0] += i["cpu_percent"] or 0.0
            a[1] += (i["memory_info"].rss if i["memory_info"] else 0)
            a[2] += 1
        except Exception:                                  # noqa: BLE001
            continue
    key = (lambda kv: kv[1][0]) if por == "cpu" else (lambda kv: kv[1][1])
    ncpu = ps.cpu_count() or 1
    return [dict(nombre=k, cpu=round(v[0] / ncpu, 1), ram_mb=round(v[1] / 1048576), procesos=v[2])
            for k, v in sorted(acc.items(), key=key, reverse=True)[:n]]


def estado(top: int = 5) -> dict:
    ps = _ps()
    ps.cpu_percent(None)
    for p in ps.process_iter():                            # primera lectura (cpu_percent necesita dos)
        try:
            p.cpu_percent(None)
        except Exception:                                  # noqa: BLE001
            pass
    time.sleep(0.6)
    vm = ps.virtual_memory()
    return dict(cpu=round(ps.cpu_percent(None), 1), ram=round(vm.percent, 1),
                ram_usada_gb=round((vm.total - vm.available) / 2**30, 1), ram_total_gb=round(vm.total / 2**30, 1),
                top_cpu=_agrupa("cpu", top), top_ram=_agrupa("ram", top))


def resumen(e: dict) -> str:
    c = ", ".join(f"{p['nombre']} {p['cpu']}%" for p in e["top_cpu"][:3])
    r = ", ".join(f"{p['nombre']} {p['ram_mb']} MB" for p in e["top_ram"][:3])
    return f"CPU {e['cpu']}% · RAM {e['ram']}% ({e['ram_usada_gb']}/{e['ram_total_gb']} GB). Más CPU: {c}. Más RAM: {r}."


def _coincide(nombre: str):
    ps = _ps()
    q = nombre.lower().strip()
    if q and not q.endswith(".exe"):
        q2 = q + ".exe"
    else:
        q2 = q
    out = []
    for p in ps.process_iter(["name", "pid"]):
        try:
            n = (p.info["name"] or "").lower()
            if n in (q, q2) or (len(q) >= 4 and q in n):
                out.append(p)
        except Exception:                                  # noqa: BLE001
            continue
    return out


def validar(nombre: str):
    """-> (procesos, error). Rechaza protegidos y a Orbi mismo."""
    procs = _coincide(nombre)
    if not procs:
        return [], f"No encontré ningún proceso que se llame «{nombre}»."
    mios = {os.getpid(), os.getppid()}
    bien = []
    for p in procs:
        n = (p.info["name"] or "").lower()
        if n in PROTEGIDOS or p.info["pid"] in mios:
            return [], f"«{p.info['name']}» es un proceso del sistema o de Orbi; no lo toco."
        bien.append(p)
    return bien, ""


def cerrar(nombre: str) -> dict:
    procs, err = validar(nombre)
    if err:
        return {"error": err}
    ok = 0
    for p in procs:
        try:
            p.terminate(); ok += 1
        except Exception:                                  # noqa: BLE001
            pass
    time.sleep(0.8)
    _ps().wait_procs(procs, timeout=2)
    return {"resultado": f"Cerré {ok} proceso(s) de «{nombre}»."} if ok else {"error": "No pude cerrarlo (¿permisos?)."}


def bajar_prioridad(nombre: str) -> dict:
    procs, err = validar(nombre)
    if err:
        return {"error": err}
    ps = _ps()
    nivel = getattr(ps, "BELOW_NORMAL_PRIORITY_CLASS", 10)
    ok = 0
    for p in procs:
        try:
            p.nice(nivel); ok += 1
        except Exception:                                  # noqa: BLE001
            pass
    return {"resultado": f"Bajé la prioridad de {ok} proceso(s) de «{nombre}»."} if ok else {"error": "No pude cambiar la prioridad."}


class Monitor:
    """Avisa (on_alert(texto)) si CPU o RAM pasan el umbral `seguidas` revisiones seguidas. Enfriamiento: no repite en `espera_s`."""

    def __init__(self, on_alert, cpu=90.0, ram=90.0, cada_s=15.0, seguidas=4, espera_s=900.0, activo=lambda: True):
        self.on_alert, self.cpu, self.ram = on_alert, cpu, ram
        self.cada_s, self.seguidas, self.espera_s, self.activo = cada_s, seguidas, espera_s, activo
        self._stop = threading.Event(); self._th = None
        self._n = {"cpu": 0, "ram": 0}; self._ultimo = 0.0

    def start(self):
        if self._th and self._th.is_alive():
            return
        try:
            _ps()
        except ImportError:
            print("[recursos] falta psutil (pip install psutil): monitor apagado")
            return
        self._stop.clear()
        self._th = threading.Thread(target=self._run, name="orbi-recursos", daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        ps = _ps()
        ps.cpu_percent(None)
        while not self._stop.wait(self.cada_s):
            try:
                if not self.activo():
                    self._n = {"cpu": 0, "ram": 0}
                    continue
                c, r = ps.cpu_percent(None), ps.virtual_memory().percent
                self._n["cpu"] = self._n["cpu"] + 1 if c >= self.cpu else 0
                self._n["ram"] = self._n["ram"] + 1 if r >= self.ram else 0
                if (self._n["cpu"] >= self.seguidas or self._n["ram"] >= self.seguidas) and time.time() - self._ultimo > self.espera_s:
                    self._ultimo = time.time()
                    self._n = {"cpu": 0, "ram": 0}
                    e = estado(3)
                    causa = "CPU" if c >= self.cpu else "RAM"
                    self.on_alert(f"La {causa} está muy cargada. " + resumen(e))
            except Exception as ex:                          # noqa: BLE001
                print("[recursos]", ex)
