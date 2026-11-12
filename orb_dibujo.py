"""Dibujo de Orbi: cuerpo, halo, carita, props (pluma, lupa, nube…) y su animación por cuadro."""
import math, time
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QRadialGradient, QLinearGradient, QColor, QBrush, QPen, QPainterPath, QFont
from orb_consts import *

HALO_ESCALA = 1.7        # tamaño del brillo alrededor de la bolita (antes 2.5): más chico = menos brillo que tape cosas


class DibujoMixin:
    """Métodos de Orb que pintan (se mezclan en la clase Orb de orb.py)."""

    def _color(self):
        w = max(0.0, min(1.0, self.p.get("ew", 0.0)))
        tgt = (self.p.get("er", 0), self.p.get("eg", 0), self.p.get("eb", 0))
        return QColor(*[int(max(0, min(255, self.col[i] + (tgt[i] - self.col[i]) * w))) for i in range(3)])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        _s, _o = self._appear_factors(time.time())
        if _s != 1.0 or _o != 1.0:                       # entrada/salida: escala y opacidad alrededor del centro
            p.translate(W / 2, H / 2); p.scale(_s, _s); p.translate(-W / 2, -H / 2)
            p.setOpacity(max(0.0, min(1.0, _o)))
        c = QPointF(W / 2 + self._dx + self._g["gdx"], H / 2 + self._dy + self._g["gdy"])
        pulse, speed = STATE_MOTION[self.state]
        resp = max(0.0, min(1.0, self._rig["respiracion"][0])) if self.ia_control else 1.0      # respiración y latido con la voz: perilla de la IA
        r = R0 * (1 + pulse * resp * math.sin(self.t * speed) + self.level * 0.16 * resp + self._beat * DANCE_GAIN * DANCE_STYLES.get(self.dance_style, DANCE_STYLES["pop"])["pulse"] + self._g["gsc"])
        col = self._color()
        sleeping = self.state == "sleeping"

        # --- glow
        glow = QRadialGradient(c, r * HALO_ESCALA)
        g0 = QColor(col); g0.setAlpha(max(0, min(255, int((70 if sleeping else 150) * (0.85 + self.level * 0.5) * max(0.2, 1 + 0.6 * self._g["gglow"])))))
        g1 = QColor(col); g1.setAlpha(0)
        glow.setColorAt(0.30, g0); glow.setColorAt(1.0, g1)
        p.setPen(Qt.NoPen); p.setBrush(QBrush(glow))
        p.drawEllipse(c, r * HALO_ESCALA, r * HALO_ESCALA)

        # --- ondas
        for born in self.ripples:
            age = (self.t - born) / 1.3
            rc = QColor(col.lighter(150)); rc.setAlpha(int(130 * (1 - age)))
            p.setBrush(Qt.NoBrush); p.setPen(QPen(rc, 2))
            rr = r * (1.05 + age * 0.9)
            p.drawEllipse(c, rr, rr)

        # --- escuchando: un aro que respira mientras la ventana de conversación está abierta (sin letreros: solo el gesto)
        if getattr(self, "escuchando", False) and not sleeping:
            k = 0.5 + 0.5 * math.sin(self.t * 3.0)
            ac = QColor(col.lighter(175)); ac.setAlpha(int(110 + 90 * k))
            p.setBrush(Qt.NoBrush); p.setPen(QPen(ac, 2.2))
            rr = r * (1.22 + 0.05 * k)
            p.drawEllipse(c, rr, rr)

        # --- cuerpo (blandito: se estira / aplasta con el movimiento y con la perilla «aplastar» de la IA)
        _sx, _sy = self._sq
        deform = abs(_sx - 1) > 0.002 or abs(_sy - 1) > 0.002
        if deform:
            p.save(); p.translate(c); p.scale(_sx, _sy); p.translate(-c)
        body = QRadialGradient(c, r, QPointF(c.x() - r * 0.35, c.y() - r * 0.40))
        body.setColorAt(0.0, col.lighter(175)); body.setColorAt(0.55, col); body.setColorAt(1.0, col.darker(160))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(body))
        p.drawEllipse(c, r, r)

        # --- brillo interno que se mueve (recortado a la bolita)
        clip = QPainterPath(); clip.addEllipse(c, r, r)
        p.save(); p.setClipPath(clip)
        sc = QPointF(c.x() + math.cos(self.t * 0.7) * r * 0.35, c.y() + math.sin(self.t * 0.9) * r * 0.30 + r * 0.2)
        sh = QRadialGradient(sc, r * 0.8)
        s0 = QColor(255, 255, 255, 55); s1 = QColor(255, 255, 255, 0)
        sh.setColorAt(0, s0); sh.setColorAt(1, s1)
        p.setBrush(QBrush(sh)); p.drawEllipse(sc, r * 0.8, r * 0.8)
        p.restore()

        # --- borde tipo cristal + destello
        rim = QColor(255, 255, 255, 70)
        p.setBrush(Qt.NoBrush); p.setPen(QPen(rim, 1.6)); p.drawEllipse(c, r - 1, r - 1)
        p.save(); p.translate(c.x() - r * 0.32, c.y() - r * 0.50); p.rotate(-28)
        hl = QLinearGradient(0, -r * 0.1, 0, r * 0.1)
        hl.setColorAt(0, QColor(255, 255, 255, 190)); hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(hl)); p.drawEllipse(QPointF(0, 0), r * 0.26, r * 0.12)
        p.restore()

        self._draw_face(p, c, r)
        if deform:
            p.restore()
        self._draw_prop(p, c, r)                         # el objeto que «sostiene» (pluma, lupa, engranaje, ?...)

        # --- pensando: puntitos orbitando
        if self.state == "thinking":
            for i in range(3):
                a = self.t * 3.2 + i * 2.094
                pos = QPointF(c.x() + math.cos(a) * r * 1.4, c.y() + math.sin(a) * r * 1.4 * 0.45 - r * 0.9)
                p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 220))
                p.drawEllipse(pos, 3.6, 3.6)

        # --- corazones de la caricia
        self.hearts = [h for h in self.hearts if self.t - h[0] < 1.6]
        if self.hearts:
            p.setFont(QFont("Segoe UI", max(9, round(14 * SCALE / 0.72)), QFont.Bold))
            for born, dx in self.hearts:
                age = (self.t - born) / 1.6
                p.setPen(QColor(255, 105, 150, int(230 * (1 - age))))
                p.drawText(QPointF(c.x() + dx * r, c.y() - r * (0.9 + age * 1.0)), "♥")

        # --- durmiendo: zzz
        if sleeping:
            f = QFont("Segoe UI", 14, QFont.Bold); p.setFont(f)
            for i in range(3):
                ph = (self.t * 0.5 + i / 3) % 1.0
                p.setPen(QColor(220, 235, 255, int(200 * (1 - ph))))
                p.drawText(QPointF(c.x() + r * (0.7 + ph * 0.4), c.y() - r * (0.5 + ph * 0.9)), "z")

    def _draw_face(self, p, c, r):
        p.save()
        rot = self._rot + self._g["grot"]
        if abs(rot) > 0.05:                                      # cabeza inclinada: gira la carita alrededor del centro del cuerpo
            p.translate(c); p.rotate(rot); p.translate(-c)
        c = QPointF(c.x() + self._hx + self._g["ghx"], c.y() + self._hy + self._g["ghy"])          # y se corre / cabecea respecto al cuerpo
        f = self.p
        ink = QColor(14, 28, 70)
        gg = self._g
        wm = 0.0 if self.ia_control else 1.0                      # con el cuerpo en manos de la IA los ojos no divagan solos
        lx = (f["lx"] + gg["glx"] + self._eye_wander[0] * wm * (1 if self.state in ("idle", "listening") else 0.2)) * r * 0.10
        ly = (f["ly"] + gg["gly"] + self._eye_wander[1] * wm * (1 if self.state in ("idle", "listening") else 0.2)) * r * 0.08
        if self.edge and not self.revealed:                      # asomada: mira hacia la pantalla
            lx += (-1 if self.edge == "right" else 1) * r * 0.12
        ey = c.y() - r * 0.08 + ly

        # mejillas
        bl_ = f["blush"] + gg["grub"]
        if bl_ > 0.03:
            bc = QColor(255, 120, 150, int(120 * min(1, bl_)))
            p.setPen(Qt.NoPen); p.setBrush(bc)
            for dx in (-0.55, 0.55):
                p.drawEllipse(QPointF(c.x() + r * dx + lx * 0.5, c.y() + r * 0.22), r * 0.13, r * 0.075)

        eh = f["eye_h"] * max(0.15, 1 + gg["geh"])                   # alto de ojos: los gestos los abren o entrecierran
        pup = max(0.5, 1 + 0.3 * gg["gpup"])                          # pupila (rig): ojos más chicos o más grandes
        for idx, dx in enumerate((-0.33, 0.33)):
            ex = c.x() + r * dx + lx
            oj = gg["gel"] if idx == 0 else gg["ger"]                 # ojo por separado (rig): cerrado (-1) … muy abierto (1)
            cierre = max(self.blink, gg["gwl"] if idx == 0 else gg["gwr"], max(0.0, -oj))      # parpadeo (los dos), guiño o pose (uno)
            eh_i = eh * (1 + 0.5 * max(0.0, oj))
            # ojos redondos (se desvanecen cuando arc -> 1)
            arc = f["arc"] + gg["garc"]                               # ojos de feliz (arquitos): de la emoción o de la perilla ojos_arco
            a_round = 1 - max(0.0, min(1.0, arc))
            if a_round > 0.02:
                rx = r * 0.10 * f["eye_w"] * pup
                ry = max(1.6, r * 0.20 * eh_i * pup * (1 - min(1.0, cierre) * 0.92))
                col = QColor(ink); col.setAlpha(int(255 * a_round))
                p.setPen(Qt.NoPen); p.setBrush(col); p.drawEllipse(QPointF(ex, ey), rx, ry)
                if ry > 5:                                    # brillito en el ojo
                    wc = QColor(255, 255, 255, int(230 * a_round))
                    p.setBrush(wc); p.drawEllipse(QPointF(ex - rx * 0.3, ey - ry * 0.35), rx * 0.32, rx * 0.32)
            # ojos felices ^ ^
            if arc > 0.02:
                ac = QColor(ink); ac.setAlpha(int(255 * min(1, arc)))
                p.setBrush(Qt.NoBrush); p.setPen(QPen(ac, 3.8, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(QRectF(ex - r * 0.14, ey - r * 0.08, r * 0.28, r * 0.22), 25 * 16, 130 * 16)

        # cejas
        for sign in (-1, 1):                                          # cada ceja por su lado (la pose libre mueve la izquierda y la derecha por separado)
            extra = gg["gbl"] if sign == -1 else gg["gbr"]
            brow = f["brow"] + gg["gbrow"] + extra
            if abs(brow) <= 0.05:
                continue
            bc = QColor(ink); bc.setAlpha(int(200 * min(1, abs(brow))))
            p.setPen(QPen(bc, 3, Qt.SolidLine, Qt.RoundCap))
            by = ey - r * 0.28 - max(0.0, gg["gbrow"] + extra) * r * 0.05      # (la ceja que sube se despega un poco del ojo)
            tilt = brow * r * 0.09
            x0 = c.x() + sign * r * 0.33 + lx
            inner = x0 - sign * r * 0.10; outer = x0 + sign * r * 0.10
            p.drawLine(QPointF(inner, by - tilt), QPointF(outer, by + tilt))

        # boca
        my = c.y() + r * 0.36 + ly * 0.5
        mx = c.x() + lx * 0.6
        hablando = self.state == "speaking"
        talk = max(self._lip[0], self.level * 1.25) if hablando else 0.0
        forma = self._lip[1] if hablando else 0.0                     # «o/u» redonda (-1) … «e/i» ancha (1), sale del audio
        opened = max(f["open"] + gg["gmo"], min(1.0, talk))
        mw = max(0.4, 1 + 0.5 * gg["gmw"]) * (1 + 0.45 * forma)       # ancho de la boca (rig + forma al hablar)
        if opened > 0.06:
            p.setPen(Qt.NoPen); p.setBrush(ink)
            p.drawEllipse(QPointF(mx, my), r * (0.12 + 0.05 * opened) * mw, 2.5 + opened * r * 0.30 * (1 - 0.25 * forma))
        else:
            path = QPainterPath()
            w = r * 0.36 * mw
            path.moveTo(mx - w / 2, my)
            path.quadTo(mx, my + (f["curve"] + 0.6 * gg["gsm"]) * r * 0.42, mx + w / 2, my)
            p.setBrush(Qt.NoBrush); p.setPen(QPen(ink, 3.2, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
        p.restore()

    # ------------------------------------------------------------ objetos (los sostiene una mano invisible: Orbi no tiene manos)
    def _prop_update(self, dt):
        want = self._prop_force or PROP_FOR.get(self.emotion)
        if want is None and self.state == "thinking" and self.emotion == "neutral":
            want = "nube"                                           # esperando su respuesta: «...» sobre la cabeza
        if self.state == "sleeping" or (self.edge and not self.revealed):
            want = None
        if want != self._prop_name:                                 # primero se guarda el anterior (se encoge) y luego sale el nuevo
            self._prop_k = max(0.0, self._prop_k - dt * 7.0)
            if self._prop_k <= 0.0:
                self._prop_name = want; self._prop_t0 = self.t
        elif self._prop_name:
            self._prop_k = min(1.0, self._prop_k + dt * 4.0)         # aparece con un «pop» que se pasa tantito y regresa (easeOutBack)

    def _draw_prop(self, p, c, r):
        if not self._prop_name or self._prop_k <= 0.01:
            return
        k = self._prop_k
        s = 1 + 2.70158 * (k - 1) ** 3 + 1.70158 * (k - 1) ** 2
        tt = self.t - self._prop_t0
        name = self._prop_name
        u = r * 0.52
        ink = QColor(14, 28, 70, 225)
        pen = QPen(ink, max(1.4, r * 0.05), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        if name == "question":                                      # «?» sobre la cabeza, a la derecha; sigue a la cabeza y brinca
            ax = c.x() + r * 0.98 + self._hx + self._g["ghx"]
            ay = c.y() - r * 1.30 - abs(math.sin(tt * 3.2)) * r * 0.08 + self._hy + self._g["ghy"]
            tilt = math.sin(tt * 2.1) * 7
        elif name == "nube":                                        # nube de pensamiento sobre la cabeza, a la izquierda
            ax = c.x() - r * 1.02 + self._hx + self._g["ghx"]
            ay = c.y() - r * 1.50 + math.sin(tt * 2.0) * r * 0.05 + self._hy + self._g["ghy"]
            tilt = math.sin(tt * 1.4) * 3
        else:                                                       # el resto flota a la derecha, un poco abajo, con vaivén (como sostenido)
            ax = c.x() + r * 1.34 + math.sin(tt * 1.7) * r * 0.04
            ay = c.y() + r * 0.30 + math.sin(tt * 2.3) * r * 0.06
            tilt = math.sin(tt * 1.3) * 5
        p.save()
        p.translate(ax, ay); p.rotate(tilt); p.scale(s, s)
        p.setPen(pen)
        if name == "question":
            # chapita de cristal del color de Orbi (una mini bolita con su brillo) con un «?» trazado a mano y el puntito que brinca solo
            b = u * 1.08
            col = self._color()
            gr = QRadialGradient(QPointF(-b * 0.30, -b * 0.35), b * 1.5)
            gr.setColorAt(0.0, col.lighter(185)); gr.setColorAt(0.55, col); gr.setColorAt(1.0, col.darker(150))
            p.setPen(QPen(QColor(255, 255, 255, 200), max(1.2, r * 0.035))); p.setBrush(QBrush(gr))
            p.drawEllipse(QPointF(0, 0), b, b)
            q = QPainterPath(); q.moveTo(-0.30 * b, -0.18 * b)
            q.cubicTo(-0.30 * b, -0.74 * b, 0.36 * b, -0.74 * b, 0.36 * b, -0.22 * b)
            q.cubicTo(0.36 * b, 0.06 * b, 0.03 * b, 0.08 * b, 0.03 * b, 0.34 * b)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 250), max(2.0, b * 0.22), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(q)
            hop = max(0.0, math.sin(tt * 4.5)) ** 3                 # el punto de abajo da un saltito de vez en cuando
            p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 250))
            p.drawEllipse(QPointF(0.03 * b, 0.68 * b - hop * 0.22 * b), b * 0.12, b * 0.12)
            for j, (sx, sy) in enumerate(((1.22, -0.78), (-1.18, -0.55))):      # chispitas que titilan
                a = 0.5 + 0.5 * math.sin(tt * 3.0 + j * 2.1)
                sr = b * 0.10 * (0.5 + a)
                p.setBrush(QColor(255, 255, 255, int(110 + 120 * a)))
                p.drawEllipse(QPointF(sx * b, sy * b), sr, sr)
        elif name == "nube":
            # nube de pensamiento: «...» donde los puntos laten uno tras otro, y dos burbujitas que bajan hacia la cabeza
            cloud = QPainterPath(); cloud.setFillRule(Qt.WindingFill)        # unión sólida (con el relleno par-impar quedaban huecos)
            for (cx_, cy_, rr) in ((-0.95, 0.05, 0.62), (-0.35, -0.38, 0.78), (0.42, -0.30, 0.74), (0.98, 0.10, 0.60), (0.05, 0.28, 0.74)):
                cloud.addEllipse(QPointF(cx_ * u, cy_ * u), rr * u, rr * u)
            p.setPen(QPen(QColor(150, 160, 205, 160), max(1.0, r * 0.03))); p.setBrush(QColor(255, 255, 255, 245))
            p.drawPath(cloud.simplified())
            p.setPen(Qt.NoPen)
            for i in range(3):
                k2 = 0.62 + 0.38 * max(0.0, math.sin(tt * 4.2 - i * 0.95))
                rad = u * 0.19 * k2
                p.setBrush(QColor(60, 70, 140, 235)); p.drawEllipse(QPointF((-0.55 + 0.55 * i) * u, 0.0), rad, rad)
            p.setPen(QPen(QColor(150, 160, 205, 160), max(1.0, r * 0.03))); p.setBrush(QColor(255, 255, 255, 240))
            p.drawEllipse(QPointF(0.95 * u, 1.05 * u), 0.24 * u, 0.24 * u)
            p.drawEllipse(QPointF(1.38 * u, 1.58 * u), 0.14 * u, 0.14 * u)
        elif name == "pen":                                         # pluma que escribe un renglón (mismo ritmo que los ojos)
            prog = (tt * 1.5) % 1.0
            p.setPen(QPen(QColor(60, 80, 200, 200), max(1.4, r * 0.045), Qt.SolidLine, Qt.RoundCap))
            wave = QPainterPath(); wave.moveTo(-u * 1.7, u * 1.30)
            for i in range(1, 13):
                x = -u * 1.7 + (u * 1.5 * prog) * i / 12
                wave.lineTo(x, u * 1.30 + math.sin(i * 1.7) * u * 0.07)
            p.drawPath(wave)
            p.rotate(32 + math.sin(tt * 11) * 2.5)
            p.setPen(pen)
            body = QPainterPath(); body.addRoundedRect(QRectF(-u * 0.24, -u * 1.45, u * 0.48, u * 1.95), u * 0.16, u * 0.16)
            p.setBrush(QColor(255, 214, 102)); p.drawPath(body)
            p.setBrush(QColor(255, 140, 170)); p.drawRoundedRect(QRectF(-u * 0.24, -u * 1.45, u * 0.48, u * 0.32), u * 0.12, u * 0.12)
            nib = QPainterPath(); nib.moveTo(-u * 0.24, u * 0.5); nib.lineTo(u * 0.24, u * 0.5); nib.lineTo(0, u * 1.05); nib.closeSubpath()
            p.setBrush(QColor(236, 236, 246)); p.drawPath(nib)
            p.setBrush(ink); p.drawEllipse(QPointF(0, u * 1.0), u * 0.07, u * 0.07)
        elif name == "lupa":                                        # lupa que da vueltas, igual que los ojos al buscar
            ox, oy = math.cos(tt * 2.3) * u * 0.20, math.sin(tt * 2.3) * u * 0.16
            p.translate(ox, oy)
            p.setPen(QPen(QColor(140, 95, 55), max(2.0, r * 0.11), Qt.SolidLine, Qt.RoundCap)); p.drawLine(QPointF(u * 0.55, u * 0.55), QPointF(u * 1.45, u * 1.45))
            p.setPen(pen); p.setBrush(QColor(205, 238, 255, 120)); p.drawEllipse(QPointF(0, 0), u * 0.88, u * 0.88)
            p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(255, 190, 60), max(2.2, r * 0.09))); p.drawEllipse(QPointF(0, 0), u * 0.88, u * 0.88)
            p.setPen(QPen(QColor(255, 255, 255, 210), max(1.6, r * 0.05), Qt.SolidLine, Qt.RoundCap)); p.drawArc(QRectF(-u * 0.55, -u * 0.55, u * 1.1, u * 1.1), 110 * 16, 60 * 16)
        elif name == "gear":                                        # engranaje girando
            path = QPainterPath(); n = 8
            for i in range(n * 4):
                a = (i / (n * 4)) * 6.2832 + tt * 1.2
                rad = u * (1.0 if (i % 4) in (0, 1) else 0.74)
                (path.moveTo if i == 0 else path.lineTo)(QPointF(math.cos(a) * rad, math.sin(a) * rad))
            path.closeSubpath()
            hole = QPainterPath(); hole.addEllipse(QPointF(0, 0), u * 0.32, u * 0.32)
            p.setBrush(QColor(176, 188, 210)); p.drawPath(path.subtracted(hole)); p.setBrush(Qt.NoBrush); p.drawPath(hole)
        elif name == "folder":                                      # carpeta con una hoja que sube y baja
            p.setBrush(QColor(255, 196, 90)); p.drawRoundedRect(QRectF(-u * 1.1, -u * 0.55, u * 2.2, u * 1.3), u * 0.15, u * 0.15)
            p.drawRoundedRect(QRectF(-u * 1.1, -u * 0.82, u * 0.95, u * 0.34), u * 0.12, u * 0.12)
            p.setBrush(QColor(255, 255, 255)); p.drawRoundedRect(QRectF(-u * 0.8, -u * 0.8 + math.sin(tt * 4.5) * u * 0.14, u * 1.6, u * 1.0), u * 0.08, u * 0.08)
            p.setBrush(QColor(255, 214, 120)); p.drawRoundedRect(QRectF(-u * 1.1, -u * 0.18, u * 2.2, u * 0.93), u * 0.15, u * 0.15)
        elif name == "hourglass":                                   # reloj de arena: se vacía, se voltea y vuelve a empezar
            cyc = tt % 4.4
            ph = min(1.0, cyc / 4.0)
            if cyc > 4.0:
                x = (cyc - 4.0) / 0.4
                p.rotate(180 * (x * x * (3 - 2 * x)))
            p.setBrush(QColor(220, 240, 255, 130))
            glass = QPainterPath(); glass.moveTo(-u * 0.62, -u * 0.98); glass.lineTo(u * 0.62, -u * 0.98); glass.lineTo(u * 0.07, 0); glass.lineTo(u * 0.62, u * 0.98)
            glass.lineTo(-u * 0.62, u * 0.98); glass.lineTo(-u * 0.07, 0); glass.closeSubpath()
            p.drawPath(glass)
            p.setPen(Qt.NoPen); p.setBrush(QColor(255, 214, 102))
            top = (1 - ph) * 0.9; bot = ph * 0.9
            if top > 0.02:
                p.drawPolygon([QPointF(-u * 0.55 * top, -u * 0.05 - u * 0.85 * top), QPointF(u * 0.55 * top, -u * 0.05 - u * 0.85 * top), QPointF(0, -u * 0.05)])
            if bot > 0.02:
                p.drawPolygon([QPointF(-u * 0.55 * bot, u * 0.93), QPointF(u * 0.55 * bot, u * 0.93), QPointF(0, u * 0.93 - u * 0.85 * bot)])
            if ph < 1.0:
                p.setPen(QPen(QColor(255, 214, 102), max(1.2, r * 0.03))); p.drawLine(QPointF(0, 0), QPointF(0, u * 0.9 - u * 0.85 * bot))
            p.setPen(pen); p.setBrush(QColor(190, 130, 80))
            p.drawRoundedRect(QRectF(-u * 0.78, -u * 1.12, u * 1.56, u * 0.16), u * 0.06, u * 0.06)
            p.drawRoundedRect(QRectF(-u * 0.78, u * 0.96, u * 1.56, u * 0.16), u * 0.06, u * 0.06)
        p.restore()

    # --------------------------------------------------------------- el halo no estorba
