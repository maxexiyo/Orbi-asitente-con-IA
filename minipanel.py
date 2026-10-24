"""Mini ventana de Orbi: se despliega JUNTO a la bolita y solo aparece cuando hay algo que mostrar (modo «con_datos»).

Muestra: tarea en curso, avisos/resultados que Orbi empuja con push(), timers (cuenta regresiva), alarmas, recordatorios,
calendario y resúmenes de búsquedas web con imagen.

Ajustes (profile["ajustes"]["mini"]): modo "siempre"|"con_datos"|"oculta", tam, opacidad, esquina (solo si no hay bolita
a la que seguir), secciones {calendario, alarmas, recordatorios, timers, busquedas}, pos (arrastre manual, solo sin bolita).

API que usa live_orb.py:
  push(icono, titulo, lineas, segundos, clave)  -> muestra un aviso temporal (misma clave = reemplaza)
  set_tarea(texto, paso) / set_tarea(None)      -> tarea en curso (.tarea es dict o None)
  hide_now()                                    -> quita avisos y tarea
  add_web_card(card) · refresh()
  get_anchor() -> (QPoint centro_bolita, radio, escondida_en_borde)
"""
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QColor, QPainter, QPixmap, QPen, QBrush
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget
from PySide6.QtGui import QGuiApplication

DEFAULT = {"modo": "con_datos", "tam": "media", "opacidad": 92, "esquina": "inferior_derecha",
           "secciones": {"calendario": True, "alarmas": True, "recordatorios": True, "timers": True, "busquedas": True}, "pos": None}
TAM = {"compacta": dict(w=250, fs=11, items=2, img=0), "media": dict(w=310, fs=12, items=4, img=84),
       "grande": dict(w=400, fs=13, items=6, img=116)}
CARD_TTL_S = 45 * 60
TIMER_MAX_S = 3 * 3600
MAX_PUSH = 4


def merged(cfg: dict | None) -> dict:
    out = {**DEFAULT, **(cfg or {})}
    out["secciones"] = {**DEFAULT["secciones"], **((cfg or {}).get("secciones") or {})}
    if out["modo"] not in ("siempre", "con_datos", "oculta"):
        out["modo"] = DEFAULT["modo"]
    if out["tam"] not in TAM:
        out["tam"] = DEFAULT["tam"]
    return out


def _fmt_left(sec: float) -> str:
    sec = max(0, int(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _esc(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class MiniPanel(QWidget):
    def __init__(self, get_cfg, save_cfg, get_alarms, get_events, open_settings=None, get_anchor=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.get_cfg, self.save_cfg, self.get_alarms, self.get_events = get_cfg, save_cfg, get_alarms, get_events
        self.open_settings, self.get_anchor = open_settings, get_anchor
        self.cards: list = []
        self.pushes: dict = {}           # clave -> {icono, titulo, lineas, hasta}
        self.tarea = None                # {"texto", "paso", "t"}
        self._drag = None
        self._cache = None
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(12, 10, 12, 10)
        self._lay.setSpacing(6)
        self._text = QLabel(); self._text.setTextFormat(Qt.RichText); self._text.setWordWrap(True)
        self._text.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._lay.addWidget(self._text)
        self._card_boxes: list = []
        self._timer = QTimer(self); self._timer.timeout.connect(self._tick); self._timer.start(1000)
        self._n = 0
        self.refresh()

    # ------------------------------------------------------------------ datos
    def push(self, icono, titulo, lineas, segundos=40, clave=None) -> None:
        if isinstance(lineas, str):
            lineas = [x.strip() for x in lineas.splitlines() if x.strip()]
        lineas = [str(x)[:90] for x in (lineas or [])][:6]
        try:
            seg = max(5.0, min(300.0, float(segundos or 40)))
        except (TypeError, ValueError):
            seg = 40.0
        key = clave or f"p{time.time()}"
        self.pushes.pop(key, None)
        self.pushes[key] = dict(icono=str(icono or "📌")[:4], titulo=str(titulo or "Orbi")[:40], lineas=lineas,
                                hasta=time.time() + seg)
        while len(self.pushes) > MAX_PUSH:
            self.pushes.pop(next(iter(self.pushes)))
        self.refresh()

    def set_tarea(self, texto, paso="") -> None:
        self.tarea = {"texto": str(texto)[:80], "paso": str(paso)[:60], "t": time.time()} if texto else None
        self.refresh()

    def hide_now(self) -> None:
        self.pushes.clear(); self.tarea = None
        self.refresh()

    def add_web_card(self, card: dict) -> None:
        pix = None
        if card.get("imagen"):
            p = QPixmap()
            if p.loadFromData(card["imagen"]):
                pix = p
        self.cards.insert(0, {"consulta": card.get("consulta", ""), "resumen": card.get("resumen", ""), "fuentes": card.get("fuentes", []),
                              "titulo": card.get("titulo", ""), "pix": pix, "t": card.get("t", time.time())})
        del self.cards[6:]
        self.refresh()

    def _collect(self, c: dict) -> dict:
        sec, now = c["secciones"], datetime.now()
        alarmas, recs, timers = [], [], []
        try:
            items = self.get_alarms() or []
        except Exception:                                  # noqa: BLE001
            items = []
        for it in items:
            try:
                w = datetime.fromisoformat(it["when"])
            except Exception:                              # noqa: BLE001
                continue
            left = (w - now).total_seconds()
            if it.get("kind") == "alarma":
                alarmas.append((w, it))
            elif 0 <= left <= TIMER_MAX_S and it.get("repetir", "no") == "no":
                timers.append((w, it))
            elif left <= 6 * 3600:                         # recordatorios lejanos no abren la ventana solos
                recs.append((w, it))
        try:
            evs = list(self.get_events() or [])
        except Exception:                                  # noqa: BLE001
            evs = []
        t = time.time()
        self.cards = [k for k in self.cards if t - k["t"] < CARD_TTL_S]
        self.pushes = {k: v for k, v in self.pushes.items() if v["hasta"] > t}
        if self.tarea and t - self.tarea["t"] > 600:       # tarea olvidada: se limpia sola
            self.tarea = None
        # alarmas/timers/recordatorios cercanos y calendario abren la ventana en modo «con_datos» solo si son relevantes pronto
        alarmas = [(w, i) for w, i in alarmas if (w - now).total_seconds() <= 3 * 3600]
        return dict(alarmas=alarmas if sec["alarmas"] else [], recs=recs if sec["recordatorios"] else [],
                    timers=timers if sec["timers"] else [], evs=evs if sec["calendario"] else [],
                    cards=self.cards if sec["busquedas"] else [], pushes=list(self.pushes.values()), tarea=self.tarea)

    # ------------------------------------------------------------------ dibujo
    def refresh(self) -> None:
        c = merged(self.get_cfg())
        d = self._collect(c)
        self._cache = (c, d)
        t = TAM[c["tam"]]
        n, fs = t["items"], t["fs"]
        self.setFixedWidth(t["w"])
        self.setWindowOpacity(max(0.3, min(1.0, c["opacidad"] / 100.0)))
        hay = bool(d["tarea"]) or any(d[k] for k in ("alarmas", "recs", "timers", "evs", "cards", "pushes"))
        if c["modo"] == "oculta" or (c["modo"] == "con_datos" and not hay):
            self.hide()
            return
        self._text.setStyleSheet(f"color:#e8ecf5; font-size:{fs}px;")
        self._text.setText(self._html(d, n, fs))
        self._rebuild_cards(d["cards"], c, t, fs)
        self._lay.activate()
        self.adjustSize()
        self._place(c)
        if not self.isVisible():
            self.show()

    def _html(self, d: dict, n: int, fs: int) -> str:
        def h(txt):
            return f"<div style='color:#8fb4ff;font-weight:bold;margin-top:4px'>{txt}</div>"
        out = []
        if d["tarea"]:
            tk = d["tarea"]
            out.append(h("🖱️ Trabajando en tu PC"))
            out.append(f"<div>{_esc(tk['texto'])}</div>")
            if tk["paso"]:
                out.append(f"<div style='color:#9aa4b8'>{_esc(tk['paso'])}…</div>")
        for p in d["pushes"]:
            out.append(h(f"{_esc(p['icono'])} {_esc(p['titulo'])}"))
            for ln in p["lineas"]:
                out.append(f"<div>{_esc(ln)}</div>")
        if d["timers"]:
            out.append(h("⏱ Timers"))
            for w, it in d["timers"][:n]:
                out.append(f"<div>{_esc(it.get('texto', '')[:34])} — <b>{_fmt_left((w - datetime.now()).total_seconds())}</b></div>")
        if d["alarmas"]:
            out.append(h("⏰ Alarmas"))
            for w, it in d["alarmas"][:n]:
                rep = " ↻" if it.get("repetir", "no") != "no" else ""
                out.append(f"<div>{w:%H:%M}{rep} — {_esc(it.get('texto', '')[:34])}</div>")
        if d["recs"]:
            out.append(h("🔔 Recordatorios"))
            for w, it in d["recs"][:n]:
                dia = "hoy" if w.date() == datetime.now().date() else f"{w.day}/{w.month}"
                out.append(f"<div>{dia} {w:%H:%M} — {_esc(it.get('texto', '')[:34])}</div>")
        if d["evs"]:
            out.append(h("📅 Calendario"))
            for line in d["evs"][:n]:
                out.append(f"<div>{_esc(str(line)[:48])}</div>")
        return "".join(out) or "<div style='color:#9aa4b8'>Nada pendiente por ahora ✨</div>"

    def _rebuild_cards(self, cards: list, c: dict, t: dict, fs: int) -> None:
        for w in self._card_boxes:
            self._lay.removeWidget(w); w.deleteLater()
        self._card_boxes = []
        if not cards:
            return
        head = QLabel("🔎 Búsquedas recientes"); head.setStyleSheet(f"color:#8fb4ff;font-weight:bold;font-size:{fs}px;")
        self._lay.addWidget(head); self._card_boxes.append(head)
        for k in cards[: 2 if c["tam"] == "grande" else 1]:
            row = QWidget(); hl = QHBoxLayout(row); hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(8)
            if k["pix"] is not None and t["img"]:
                im = QLabel(); im.setFixedSize(t["img"], t["img"])
                im.setPixmap(k["pix"].scaled(t["img"], t["img"], Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
                im.setScaledContents(False)
                hl.addWidget(im, 0, Qt.AlignTop)
            tx = QLabel(); tx.setWordWrap(True); tx.setTextFormat(Qt.RichText)
            lim = 110 if c["tam"] == "compacta" else 170 if c["tam"] == "media" else 240
            fu = (" · ".join(k["fuentes"][:2])) if k["fuentes"] else ""
            tx.setText(f"<b>{_esc((k['titulo'] or k['consulta'])[:40])}</b><br><span style='color:#cfd6e6'>{_esc(k['resumen'][:lim])}…</span>"
                       + (f"<br><span style='color:#7f8aa3;font-size:{max(9, fs - 3)}px'>{_esc(fu[:60])}</span>" if fu else ""))
            tx.setStyleSheet(f"color:#e8ecf5;font-size:{fs - 1}px;")
            hl.addWidget(tx, 1)
            self._lay.addWidget(row); self._card_boxes.append(row)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(20, 25, 40, 235))); p.setPen(QPen(QColor(120, 160, 255, 90), 1))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 14, 14)

    def _tick(self) -> None:
        self._n += 1
        if self._n % 15 == 0 or (not self.isVisible() and self._n % 3 == 0):
            self.refresh()
            return
        if not self.isVisible() or not self._cache:
            return
        c, d = self._cache
        now = time.time()
        if any(v["hasta"] <= now for v in self.pushes.values()):
            self.refresh(); return
        if d["timers"] or d["tarea"]:
            self._text.setText(self._html(d, TAM[c["tam"]]["items"], TAM[c["tam"]]["fs"]))
        if self.get_anchor:                                # sigue a la bolita si se mueve
            self._place(c)

    # ------------------------------------------------------------------ posición: junto a la bolita
    def _place(self, c: dict) -> None:
        anchor = None
        if self.get_anchor:
            try:
                anchor = self.get_anchor()
            except Exception:                              # noqa: BLE001
                anchor = None
        if anchor:
            ctr, r, escondida = anchor
            scr = QGuiApplication.screenAt(ctr) or QGuiApplication.primaryScreen()
            g = scr.availableGeometry()
            gap = int(r * 1.5) + 8
            if escondida:                                  # bolita asomada en el borde: la ventana va hacia el lado de la pantalla
                x = ctr.x() - gap - self.width() if ctr.x() > g.center().x() else ctr.x() + gap
            else:
                x = ctr.x() + gap
                if x + self.width() > g.right() - 8:       # no cabe a la derecha: va a la izquierda
                    x = ctr.x() - gap - self.width()
            y = ctr.y() - self.height() // 2
            x = max(g.left() + 8, min(x, g.right() - self.width() - 8))
            y = max(g.top() + 8, min(y, g.bottom() - self.height() - 8))
            self.move(int(x), int(y))
            return
        if c.get("pos"):
            self.move(QPoint(*c["pos"])); return
        scr = QApplication.primaryScreen().availableGeometry()
        m = 16
        x = scr.left() + m if "izquierda" in c["esquina"] else scr.right() - self.width() - m
        y = scr.top() + m if "superior" in c["esquina"] else scr.bottom() - self.height() - m - 70
        self.move(x, y)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.get_anchor:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif e.button() == Qt.RightButton:
            m = QMenu(self)
            m.addAction("Cerrar avisos", self.hide_now)
            m.addAction("Ocultar mini ventana", lambda: self._set_modo("oculta"))
            m.addAction("Mostrar siempre", lambda: self._set_modo("siempre"))
            m.addAction("Mostrar solo si hay algo", lambda: self._set_modo("con_datos"))
            if self.open_settings:
                m.addSeparator(); m.addAction("Ajustes…", self.open_settings)
            m.exec(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):
        if self._drag is not None:
            self._drag = None
            cfg = dict(merged(self.get_cfg())); cfg["pos"] = [self.x(), self.y()]
            self.save_cfg(cfg)

    def _set_modo(self, modo: str) -> None:
        cfg = dict(merged(self.get_cfg())); cfg["modo"] = modo
        self.save_cfg(cfg); self.refresh()
