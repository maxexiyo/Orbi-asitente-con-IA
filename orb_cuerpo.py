"""Cuerpo de Orbi controlado por la IA: gestos, mirada, pose libre (rig con resortes), gelatina, boca y movimiento por la pantalla."""
import math, time
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCursor, QGuiApplication
import cuerpo as _cu
from orb_consts import *
from orb_gestos import GESTO_FN, GESTO_DUR, _G0, _LOOK_DIR


class CuerpoMixin:
    """Métodos de Orb que mueven el cuerpo (se mezclan en la clase Orb de orb.py)."""

    def _cuerpo_libre_ok(self) -> bool:
        """Dormida (o en modo dormir) no hace gestos: ningún evento la despierta (#79)."""
        return not (self.sleep_lock or self.state == "sleeping")

    def gesto(self, nombre, k=1.0) -> bool:
        """Anima un gesto (asentir, ladear, brincar…). Se suma a lo que ya esté haciendo; no cambia su estado ni la despierta."""
        if nombre not in GESTO_FN or not self._cuerpo_libre_ok() or (self.edge and not self.revealed):
            return False
        k = max(0.3, min(1.6, float(k))) * random.uniform(0.92, 1.08)        # nunca dos iguales: un poquito de variación en fuerza y duración
        dur = GESTO_DUR[nombre] * random.uniform(0.94, 1.08)
        self._gestos = (self._gestos + [(time.time(), dur, nombre, k)])[-8:]
        if nombre == "parpadear":
            self.blink = 1.0
            QTimer.singleShot(280, lambda: setattr(self, "blink", 1.0))
        return True

    def mirar(self, hacia="", x=None, y=None, seconds=3.0) -> bool:
        """Mueve la mirada: izquierda/derecha/arriba/abajo/centro/cursor, o un punto de la pantalla (x, y de 0 a 1000)."""
        if not self._cuerpo_libre_ok():
            return False
        ctr = self._center_global()
        if hacia in _LOOK_DIR:
            look = _LOOK_DIR[hacia]
        else:
            if hacia == "cursor" or x in (None, "") or y in (None, ""):
                gx, gy = QCursor.pos().x(), QCursor.pos().y()
            else:
                g = (QGuiApplication.screenAt(ctr) or QGuiApplication.primaryScreen()).geometry()
                gx = g.x() + int(max(0.0, min(1000.0, float(x))) / 1000 * g.width())
                gy = g.y() + int(max(0.0, min(1000.0, float(y))) / 1000 * g.height())
            look = (max(-1.0, min(1.0, (gx - ctr.x()) / 200.0)) * 1.6, max(-1.0, min(1.0, (gy - ctr.y()) / 200.0)))
        self._look = look; self._look_until = time.time() + max(0.5, float(seconds))
        return True

    def acercarse_cursor(self) -> bool:
        """Se acerca al mouse (sin taparlo) y lo mira."""
        if not self._cuerpo_libre_ok() or self.sleep_lock:
            return False
        cur = QCursor.pos()
        screen = QGuiApplication.screenAt(cur) or QGuiApplication.primaryScreen()
        side = -1 if cur.x() > screen.availableGeometry().center().x() else 1
        self._no_dodge_until = time.time() + 3.0
        self.move_to_global(int(cur.x() + side * (R0 * 2.2 + 50)), int(cur.y() - R0 * 0.5), 900)
        self.mirar("cursor", seconds=3.5)
        return True

    def ir_a(self, x, y, estilo="deslizar", ms=None, cursor=False) -> bool:
        """Se mueve por la pantalla hasta (x, y) en milésimas de la pantalla donde está (0..1000). deslizar = camina suave; saltar = va a brincos
        (la gelatina se estira y se aplasta sola); rodar = se desliza mientras la carita da vueltas. Lo decide la IA, nada se mueve por su cuenta."""
        if not self._cuerpo_libre_ok() or self.sleep_lock:
            return False
        ctr = self._center_global()
        g = (QGuiApplication.screenAt(ctr) or QGuiApplication.primaryScreen()).availableGeometry()
        tx = g.x() + int(max(0.0, min(1000.0, float(x))) / 1000 * g.width())
        ty = g.y() + int(max(0.0, min(1000.0, float(y))) / 1000 * g.height())
        if cursor:                                                   # junto al mouse (sin taparlo)
            cur = QCursor.pos()
            lado = -1 if cur.x() > g.center().x() else 1
            tx, ty = int(cur.x() + lado * (R0 * 2.2 + 50)), int(cur.y() - R0 * 0.5)
        tx = max(g.x() + int(R0), min(g.x() + g.width() - int(R0), tx))      # el centro siempre queda dentro de la pantalla
        ty = max(g.y() + int(R0), min(g.y() + g.height() - int(R0), ty))
        dist = math.hypot(tx - ctr.x(), ty - ctr.y())
        self._no_dodge_until = time.time() + 2.5
        self._salto_id += 1
        if estilo == "saltar":
            n = max(1, min(6, int(dist / 240) + 1))
            sid = self._salto_id
            for i in range(n):
                px = ctr.x() + (tx - ctr.x()) * (i + 1) / n
                py = ctr.y() + (ty - ctr.y()) * (i + 1) / n
                QTimer.singleShot(int(i * 560), lambda px=px, py=py, sid=sid: self._brinco(px, py, sid))
        elif estilo == "rodar":
            ms = int(max(900, min(2600, dist * 2.2)))
            self.move_to_global(tx, ty, ms)
            vueltas = max(1, round(dist / (2 * math.pi * R0)))
            self._rodar = (time.time(), ms / 1000.0, (1.0 if tx >= ctr.x() else -1.0) * vueltas * 360.0)
        else:
            self.move_to_global(tx, ty, int(ms) if ms else int(max(600, min(2200, dist * 1.8))))
        return True

    def _brinco(self, px, py, sid):
        if sid != self._salto_id or not self._cuerpo_libre_ok():
            return
        self.move_to_global(px, py, 430)
        self.gesto("brincar", 0.8)

    def cuerpo(self, acciones) -> bool:
        """Ejecuta una secuencia ya validada (cuerpo.normalizar): cada acción a su momento. Una secuencia nueva cancela los pasos pendientes
        de la anterior. Si llevaba un buen rato quieta, esto NO cuenta como actividad (no le reinicia el sueño)."""
        if not acciones or not self._cuerpo_libre_ok():
            return False
        self._seq_id += 1
        sid = self._seq_id
        quieta = time.time() - self.last_active > 60.0
        antes = self.last_active
        for a in acciones:
            QTimer.singleShot(int(a["at"] * 1000), lambda a=a, sid=sid, q=quieta, ant=antes: self._cuerpo_paso(a, sid, q, ant))
        return True

    def _cuerpo_paso(self, a, sid, quieta, antes):
        if sid != self._seq_id or not self._cuerpo_libre_ok():
            return
        t = a.get("tipo")
        if t == "gesto":
            self.gesto(a["nombre"], a.get("k", 1.0))
        elif t == "pose":
            self.pose(a["valores"], a.get("segundos", 2.5), a.get("rapidez", 1.0))
        elif t == "emocion":
            self.set_emotion(a["nombre"], a.get("segundos", 4.0))
        elif t == "mirar":
            self.mirar(a.get("hacia", ""), a.get("x"), a.get("y"), a.get("segundos", 3.0))
        elif t == "ir_a":
            self.ir_a(a["x"], a["y"], a.get("estilo", "deslizar"), a.get("ms"), a.get("cursor", False))
        elif t == "mover":
            if a["nombre"] == "pasear":
                self.wander()
            elif a["nombre"] == "acercarse_cursor":
                self.acercarse_cursor()
        if quieta and self.state == "idle":
            self.last_active = antes                                  # un gesto por iniciativa propia no la mantiene despierta

    # ------------------------------------------------------------------ rig: pose libre y gelatina
    def pose(self, valores, seconds=2.5, rapidez=1.0) -> bool:
        """La IA fija el objetivo de varias «perillas» (cuerpo.POSE_PARAMS) a la vez; se mueven con resortes y vuelven solas a 0 en `seconds`."""
        if not valores or not self._cuerpo_libre_ok():
            return False
        now, hecho = time.time(), False
        for n, v in valores.items():
            if n in self._rig:
                lo, hi, _d = _cu.POSE_PARAMS[n]
                self._rig_obj[n] = max(lo, min(hi, float(v)))
                self._rig_hasta[n] = 1e18 if n in _cu.POSE_STICKY else now + max(0.3, float(seconds))     # (los automatismos se quedan como la IA los deja)
                self._rig_vel[n] = max(0.3, min(2.5, float(rapidez)))
                hecho = True
        return hecho

    def _rig_paso(self, dt, now):
        """Un paso de resorte por parámetro: aceleración = k·(objetivo − valor) − c·velocidad (con poco amortiguamiento: se pasa tantito y se asienta)."""
        for n, st in self._rig.items():
            if now >= self._rig_hasta[n]:
                self._rig_obj[n] = _cu.POSE_DEFAULTS.get(n, 0.0)
            tgt, x, v = self._rig_obj[n], st[0], st[1]
            if abs(x - tgt) < 1e-4 and abs(v) < 1e-3:
                st[0], st[1] = tgt, 0.0
                continue
            sp = self._rig_vel[n]
            k, c = 140.0 * sp * sp, 15.0 * sp
            h = dt / 2
            for _ in range(2):
                v += (k * (tgt - x) - c * v) * h
                x += v * h
            st[0], st[1] = x, v

    def set_viseme(self, abierta, forma):
        """Forma de la boca según el audio que está sonando (live_client la calcula): abierta 0..1, forma -1 redonda … 1 ancha."""
        self._lip_t = [max(0.0, min(1.0, float(abierta))), max(-1.0, min(1.0, float(forma)))]

    def _gelatina_paso(self, dt, aplastar):
        """El cuerpo es blandito: al moverse (arrastrarlo, brincar, bailar) se estira en la dirección del movimiento y, al frenar, rebota como
        gelatina. Solo reacciona al movimiento (nada se mueve por su cuenta). `aplastar` es la perilla de la IA (-1 alto y flaco, 1 ancho)."""
        if not self.ia_control:
            self._jel = [0.0, 0.0, 0.0, 0.0]; self._pos_ant = None; self._sq = (1.0, 1.0)
            return
        pos = (self.x() + self._dx + self._g["gdx"], self.y() + self._dy + self._g["gdy"])
        if self._pos_ant is None:
            self._pos_ant = pos
        vx, vy = (pos[0] - self._pos_ant[0]) / dt, (pos[1] - self._pos_ant[1]) / dt
        self._pos_ant = pos
        self._vc[0] = self._vc[0] * 0.65 + vx * 0.35; self._vc[1] = self._vc[1] * 0.65 + vy * 0.35
        speed = math.hypot(self._vc[0], self._vc[1])
        gel = max(0.0, min(1.0, self._rig["gelatina"][0]))          # «gelatina»: perilla de la IA (0 = cuerpo rígido, 1 = blandito)
        s = min(0.16, speed * 0.00018) * gel if speed > 25 else 0.0
        wx, wy = (abs(self._vc[0]) / speed, abs(self._vc[1]) / speed) if speed > 1e-6 else (0.0, 0.0)
        tx, ty = s * (wx - 0.6 * wy), s * (wy - 0.6 * wx)
        j = self._jel
        for i, tgt in ((0, tx), (2, ty)):
            j[i + 1] += (220.0 * (tgt - j[i]) - 9.0 * j[i + 1]) * dt
            j[i] += j[i + 1] * dt
        gg = self._g
        self._sq = (max(0.5, min(1.7, 1 + (j[0] * gel) + 0.28 * aplastar + 0.30 * gg["gancho"])),
                    max(0.5, min(1.7, 1 + (j[2] * gel) - 0.28 * aplastar + 0.30 * gg["galto"])))
