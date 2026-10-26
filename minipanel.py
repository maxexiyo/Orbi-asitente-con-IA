"""Mini ventana de Orbi: se despliega JUNTO a la bolita y solo aparece cuando hay algo que mostrar (modo «con_datos»).
Muestra: tarea en curso, avisos/resultados que Orbi empuja con push(), timers (cuenta regresiva), alarmas, recordatorios,
calendario y resúmenes de búsquedas web con imagen.

Ajustes (profile["ajustes"]["mini"]): modo "orbi"|"siempre"|"con_datos"|"oculta" («orbi» = por defecto: solo sale cuando ORBI decide
mostrar algo con la herramienta mini_ventana, o suena una alarma; calendario, timers y avisos automáticos no la abren), tam, opacidad, esquina (solo si no hay bolita
a la que seguir), secciones {calendario, alarmas, recordatorios, timers, busquedas}, pos (arrastre manual, solo sin bolita).

API que usa live_orb.py:
  push(icono, titulo, lineas, segundos, clave, url=None) -> muestra un aviso temporal (misma clave = reemplaza)
      · cada línea puede ser un str (si trae http(s)://... o una ruta de archivo se vuelve clicable sola)
        o un dict {"texto": "...", "url": "https://..."}  ó  {"texto": "...", "accion": "correo", "datos": {...}}
      · url (opcional) hace clicable el título del aviso
  set_tarea(texto, paso) / set_tarea(None) -> tarea en curso (.tarea es dict o None)
  hide_now() -> quita avisos y tarea
  add_web_card(card) · refresh()      (card puede traer "url"; si "fuentes" son URLs también se pueden abrir)
  get_anchor() -> (QPoint centro_bolita, radio, escondida_en_borde)
  get_events() puede devolver str o dict {"texto": "...", "url": "..."} por evento
  on_action(accion, datos) -> callback (opcional) que live_orb pasa al crear el panel; se llama al hacer clic en
      una línea con "accion" (ej. "correo", "notificacion", "evento")
"""
import html as _html
import os
import re
import time
from datetime import date, datetime, timedelta
from PySide6.QtCore import Qt, QTimer, QPoint, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPixmap, QPen, QBrush
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget
from PySide6.QtGui import QGuiApplication

DEFAULT = {"modo": "orbi", "tam": "media", "opacidad": 92, "esquina": "inferior_derecha",
           "secciones": {"calendario": True, "alarmas": True, "recordatorios": True, "timers": True, "busquedas": True}, "pos": None}
TAM = {"compacta": dict(w=250, fs=11, items=2, img=0), "media": dict(w=310, fs=12, items=4, img=84),
       "grande": dict(w=400, fs=13, items=6, img=116)}
CARD_TTL_S = 45 * 60
TIMER_MAX_S = 3 * 3600
MAX_PUSH = 4
_URL = re.compile(r"(https?://[^\s<>\"']+)")
_RUTA = re.compile(r"([A-Za-z]:\\[^\s<>\"|?*]+)")
LINK_STYLE = "color:#9cc2ff;text-decoration:none"


def merged(cfg: dict | None) -> dict:
    out = {**DEFAULT, **(cfg or {})}
    out["secciones"] = {**DEFAULT["secciones"], **((cfg or {}).get("secciones") or {})}
    if out["modo"] not in ("orbi", "siempre", "con_datos", "oculta"):
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


class _Clickable(QLabel):
    """QLabel que avisa con clicked al hacer clic izquierdo (para las imágenes); el clic derecho sigue al menú del panel."""
    clicked = Signal()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        else:
            e.ignore()


class MiniPanel(QWidget):
    def __init__(self, get_cfg, save_cfg, get_alarms, get_events, open_settings=None, get_anchor=None, on_action=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.get_cfg, self.save_cfg, self.get_alarms, self.get_events = get_cfg, save_cfg, get_alarms, get_events
        self.open_settings, self.get_anchor, self.on_action = open_settings, get_anchor, on_action
        self.cards: list = []
        self.pushes: dict = {}   # clave -> {icono, titulo, lineas, hasta, url}
        self.tarea = None        # {"texto", "paso", "t"}
        self.acts: list = []     # actividad de herramientas: dict(key, label, t0, t1, ok, bg)
        self.pend: list = []     # lo que sigue (etiquetas) cuando el modelo pide varias herramientas juntas
        self._drag = None
        self._cache = None
        self._dismissed = None   # firma de los datos fijos (alarmas, calendario...) que el usuario ya cerró
        self._tlinks: dict = {}  # destinos de los enlaces del texto principal (se regeneran en cada _html)
        self._clinks: dict = {}  # destinos de los enlaces de las tarjetas de búsqueda
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(12, 10, 12, 10)
        self._lay.setSpacing(6)
        self._text = QLabel(); self._text.setTextFormat(Qt.RichText); self._text.setWordWrap(True)
        # clicable: solo los enlaces reciben el clic; lo demás (arrastrar, clic derecho) sigue pasando al panel
        self._text.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self._text.setOpenExternalLinks(False)
        self._text.linkActivated.connect(lambda h: self._on_link(h, self._tlinks))
        self._lay.addWidget(self._text)
        self._card_boxes: list = []
        self._close = QPushButton("✕", self)  # botón de cerrar (antes solo había menú con clic derecho)
        self._close.setFixedSize(20, 20)
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.setFocusPolicy(Qt.NoFocus)
        self._close.setStyleSheet("QPushButton{color:#cfd6e6;background:rgba(255,255,255,25);border:none;border-radius:10px;"
                                  "font-size:11px;}QPushButton:hover{background:rgba(255,80,80,170);color:white;}")
        self._close.clicked.connect(self.hide_now)
        self._close.raise_()
        self._timer = QTimer(self); self._timer.timeout.connect(self._tick); self._timer.start(1000)
        self._n = 0
        self.refresh()

    # ------------------------------------------------------------------ enlaces clicables
    @staticmethod
    def _a(store: dict, inner_html: str, target) -> str:
        """Envuelve inner_html en un enlace; el destino real (url, ruta, dict de acción o función) se guarda en store."""
        k = str(len(store))
        store[k] = target
        return f"<a href='orbi://{k}' style='{LINK_STYLE}'>{inner_html}</a>"

    def _rich(self, store: dict, txt: str, target=None) -> str:
        """Texto -> html. Con target, toda la línea es un enlace; sin target, se enlazan solas las URLs y rutas de archivo."""
        s = _esc(txt)
        if target:
            return self._a(store, s, target)

        def url(m):
            u = _html.unescape(m.group(1)).rstrip(".,;:)!?")
            cola = _html.unescape(m.group(1))[len(u):]
            vis = u if len(u) <= 42 else u[:39] + "…"
            return self._a(store, _esc(vis), u) + _esc(cola)

        s = _URL.sub(url, s)
        if "orbi://" not in s:  # rutas tipo C:\Users\...\archivo.docx (solo si no había URL, para no mezclar)
            s = _RUTA.sub(lambda m: self._a(store, m.group(1), _html.unescape(m.group(1))), s)
        return s

    def _on_link(self, href: str, store: dict) -> None:
        self._abrir(store.get(str(href).replace("orbi://", "")))

    def _abrir(self, target) -> None:
        try:
            if target is None:
                return
            if callable(target):
                target(); return
            if isinstance(target, dict):
                if target.get("url"):
                    self._abrir(target["url"])
                elif self.on_action and target.get("accion"):
                    self.on_action(target["accion"], target.get("datos") or {})
                return
            t = str(target)
            if re.match(r"(https?://|mailto:)", t):
                QDesktopServices.openUrl(QUrl(t))
            elif os.path.exists(t):  # archivo o carpeta
                QDesktopServices.openUrl(QUrl.fromLocalFile(t))
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _norm_line(x) -> dict:
        if isinstance(x, dict):
            tgt = x.get("url") or ({"accion": x["accion"], "datos": x.get("datos") or {}} if x.get("accion") else None)
            return {"texto": str(x.get("texto") or x.get("text") or "")[:90], "target": tgt}
        s = str(x)
        return {"texto": s[:220 if ("http" in s or ":\\" in s) else 90], "target": None}

    @staticmethod
    def _ev_url(line: str) -> str:
        """Si el evento no trae enlace propio, abre Google Calendar en el día del evento («hoy», «mañana» o d/m)."""
        now = datetime.now()
        d = now.date()
        m = re.match(r"\s*(hoy|mañana|(\d{1,2})/(\d{1,2}))", line)
        if m:
            if m.group(1) == "mañana":
                d = d + timedelta(days=1)
            elif m.group(2):
                try:
                    d = date(now.year, int(m.group(3)), int(m.group(2)))
                    if d < now.date() - timedelta(days=60):
                        d = date(now.year + 1, d.month, d.day)
                except ValueError:
                    pass
        return f"https://calendar.google.com/calendar/u/0/r/day/{d.year}/{d.month}/{d.day}"

    # ------------------------------------------------------------------ datos
    def _solo_orbi(self) -> bool:
        try:
            return merged(self.get_cfg())["modo"] == "orbi"
        except Exception:  # noqa: BLE001
            return False

    def push(self, icono, titulo, lineas, segundos=40, clave=None, url=None) -> None:
        k = str(clave or "")
        importante = k.startswith("res:") and k[4:] not in ("listar_ventanas", "casa_estado", "wiz_listar", "escuchar_audio_pc")
        if self._solo_orbi() and not (k == "orbi" or k.startswith("alarm:") or importante):
            return  # modo «orbi»: avisos automáticos no abren la ventana; solo lo que Orbi decide
        if isinstance(lineas, str):
            lineas = [x.strip() for x in lineas.splitlines() if x.strip()]
        lineas = [self._norm_line(x) for x in (lineas or [])][:6]
        try:
            seg = max(5.0, min(300.0, float(segundos or 40)))
        except (TypeError, ValueError):
            seg = 40.0
        key = clave or f"p{time.time()}"
        self.pushes.pop(key, None)
        self.pushes[key] = dict(icono=str(icono or "📌")[:4], titulo=str(titulo or "Orbi")[:40], lineas=lineas,
                                hasta=time.time() + seg, url=url)
        while len(self.pushes) > MAX_PUSH:
            self.pushes.pop(next(iter(self.pushes)))
        self.refresh()

    def set_tarea(self, texto, paso="") -> None:
        if texto and self._solo_orbi():
            return
        self.tarea = {"texto": str(texto)[:80], "paso": str(paso)[:60], "t": time.time()} if texto else None
        self.refresh()

    @staticmethod
    def _firma(d: dict) -> tuple:
        """Qué datos «fijos» hay ahora (sin contar la cuenta regresiva): si cambian, la ventana puede volver a salir."""
        return (tuple(str(i.get("id") or i.get("texto")) + str(w) for w, i in d["alarmas"]),
                tuple(str(i.get("id") or i.get("texto")) + str(w) for w, i in d["recs"]),
                tuple(str(i.get("id") or i.get("texto")) + str(w) for w, i in d["timers"]),
                tuple(str(x) for x in d["evs"]))

    # ---- actividad: qué va a hacer, qué ya hizo y qué está haciendo (compacta; sale sola aunque la ventana esté en modo «Orbi decide»)
    def act_plan(self, labels) -> None:
        self.pend = [str(x)[:34] for x in (labels or [])][:4]
        self.refresh()

    def act_start(self, key, label) -> None:
        label = str(label)[:44]
        if label in self.pend:
            self.pend.remove(label)
        self.acts.append(dict(key=key, label=label, t0=time.time(), t1=None, ok=True, bg=False))
        del self.acts[:-6]
        self.refresh()

    def act_bg(self, key) -> None:
        for a in reversed(self.acts):
            if a["key"] == key and a["t1"] is None:
                a["bg"] = True
                break
        self.refresh()

    def act_end(self, key, ok=True) -> None:
        for a in reversed(self.acts):
            if a["key"] == key and a["t1"] is None:
                a["t1"], a["ok"] = time.time(), bool(ok)
                break
        self.refresh()

    def act_running(self) -> bool:
        return any(a["t1"] is None for a in self.acts)

    def hide_now(self) -> None:
        """Cierra la ventana YA. Antes solo borraba avisos y tarea, y con alarmas, calendario o búsquedas seguía abierta
        (por eso el botón «no hacía nada»). Ahora además recuerda los datos fijos actuales y no reabre hasta que lleguen otros."""
        self.pushes.clear(); self.tarea = None; self.cards = []; self.acts = []; self.pend = []
        try:
            self._dismissed = self._firma(self._collect(merged(self.get_cfg())))
        except Exception:  # noqa: BLE001
            self._dismissed = None
        self.hide()
        self.refresh()

    def add_web_card(self, card: dict) -> None:
        if self._solo_orbi():
            return
        pix = None
        if card.get("imagen"):
            p = QPixmap()
            if p.loadFromData(card["imagen"]):
                pix = p
        fuentes = card.get("fuentes", [])
        url = card.get("url") or next((str(f) for f in fuentes if str(f).startswith("http")), None)
        self.cards.insert(0, {"consulta": card.get("consulta", ""), "resumen": card.get("resumen", ""), "fuentes": fuentes,
                              "titulo": card.get("titulo", ""), "pix": pix, "t": card.get("t", time.time()), "url": url})
        del self.cards[6:]
        self.refresh()

    def _collect(self, c: dict) -> dict:
        sec = c["secciones"] if c["modo"] != "orbi" else {k: False for k in c["secciones"]}
        now = datetime.now()
        alarmas, recs, timers = [], [], []
        try:
            items = self.get_alarms() or []
        except Exception:  # noqa: BLE001
            items = []
        for it in items:
            try:
                w = datetime.fromisoformat(it["when"])
            except Exception:  # noqa: BLE001
                continue
            left = (w - now).total_seconds()
            if it.get("kind") == "alarma":
                alarmas.append((w, it))
            elif 0 <= left <= TIMER_MAX_S and it.get("repetir", "no") == "no":
                timers.append((w, it))
            elif left <= 6 * 3600:  # recordatorios lejanos no abren la ventana solos
                recs.append((w, it))
        try:
            evs = list(self.get_events() or [])
        except Exception:  # noqa: BLE001
            evs = []
        t = time.time()
        self.cards = [k for k in self.cards if t - k["t"] < CARD_TTL_S]
        self.pushes = {k: v for k, v in self.pushes.items() if v["hasta"] > t}
        if self.tarea and t - self.tarea["t"] > 600:  # tarea olvidada: se limpia sola
            self.tarea = None
        self.acts = [a for a in self.acts if a["t1"] is None or t - a["t1"] < 7]  # lo terminado se queda 7 s
        running = [a for a in self.acts if a["t1"] is None]
        if not running and not self.acts:
            self.pend = []
        # no parpadear con herramientas rápidas: sale si algo lleva >1.5 s, hay algo en segundo plano o ya van 2 o más pasos
        mostrar_acts = bool(self.acts) and (any(t - a["t0"] > 1.5 for a in running) or any(a["bg"] for a in running)
                                            or len(self.acts) >= 3)
        # alarmas/timers/recordatorios cercanos y calendario abren la ventana en modo «con_datos» solo si son relevantes pronto
        alarmas = [(w, i) for w, i in alarmas if (w - now).total_seconds() <= 3 * 3600]
        return dict(alarmas=alarmas if sec["alarmas"] else [], recs=recs if sec["recordatorios"] else [],
                    timers=timers if sec["timers"] else [], evs=evs if sec["calendario"] else [],
                    cards=self.cards if sec["busquedas"] else [], pushes=list(self.pushes.values()), tarea=self.tarea,
                    acts=list(self.acts) if mostrar_acts else [], pend=list(self.pend) if mostrar_acts else [])

    # ------------------------------------------------------------------ dibujo
    def refresh(self) -> None:
        c = merged(self.get_cfg())
        d = self._collect(c)
        self._cache = (c, d)
        t = TAM[c["tam"]]
        n, fs = t["items"], t["fs"]
        self.setFixedWidth(t["w"])
        self.setWindowOpacity(max(0.3, min(1.0, c["opacidad"] / 100.0)))
        hay = bool(d["tarea"]) or any(d[k] for k in ("alarmas", "recs", "timers", "evs", "cards", "pushes", "acts"))
        if self._dismissed is not None:  # cerrada a mano: solo vuelve con algo NUEVO
            if d["tarea"] or d["cards"] or d["pushes"] or d["acts"] or self._firma(d) != self._dismissed:
                self._dismissed = None
            else:
                self.hide()
                return
        if c["modo"] == "oculta" or (c["modo"] in ("con_datos", "orbi") and not hay):
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
        self._tlinks.clear()  # los destinos se regeneran junto con el html (cada refresco/tick)
        st = self._tlinks

        def h(txt):
            return f"<div style='color:#8fb4ff;font-weight:bold;margin-top:4px'>{txt}</div>"
        out = []
        if d["tarea"]:
            tk = d["tarea"]
            out.append(h("🖱️ Trabajando en tu PC"))
            out.append(f"<div>{_esc(tk['texto'])}</div>")
            if tk["paso"]:
                out.append(f"<div style='color:#9aa4b8'>{_esc(tk['paso'])}…</div>")
        if d["acts"]:
            now = time.time()
            out.append(h("⚙️ Orbi está trabajando" if any(a["t1"] is None for a in d["acts"]) else "⚙️ Listo"))
            hechos = [a for a in d["acts"] if a["t1"] is not None][-2:]
            for a in hechos:
                out.append(f"<div style='color:#7f8c8d'>{'✓' if a['ok'] else '✗'} {_esc(a['label'])}</div>")
            for a in [a for a in d["acts"] if a["t1"] is None][-2:]:
                seg = int(now - a["t0"])
                tiempo = f"{seg // 60}:{seg % 60:02d}" if seg >= 60 else f"{seg} s"
                out.append(f"<div><b>▶ {_esc(a['label'])}</b>{' · en segundo plano' if a['bg'] else ''} <span style='color:#9aa4b8'>{tiempo}</span></div>")
            if d["pend"]:
                out.append(f"<div style='color:#9aa4b8'>⏭ sigue: {_esc(', '.join(d['pend'][:3]))}</div>")
        for p in d["pushes"]:
            ttl = f"{_esc(p['icono'])} {_esc(p['titulo'])}"
            if p.get("url"):
                ttl = self._a(st, ttl, p["url"])
            out.append(h(ttl))
            for ln in p["lineas"]:
                out.append(f"<div>{self._rich(st, ln['texto'], ln['target'])}</div>")
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
            for ev in d["evs"][:n]:
                txt, url = (str(ev.get("texto", "")), ev.get("url")) if isinstance(ev, dict) else (str(ev), None)
                url = url or self._ev_url(txt)
                shown = _esc(re.sub(r"\s*\(id:[^)]*\)", "", txt)[:48])  # el id interno no le sirve al usuario
                out.append(f"<div>{self._a(st, shown, url)}</div>")
        return "".join(out) or "<div style='color:#9aa4b8'>Nada pendiente por ahora ✨</div>"

    def _rebuild_cards(self, cards: list, c: dict, t: dict, fs: int) -> None:
        for w in self._card_boxes:
            self._lay.removeWidget(w); w.deleteLater()
        self._card_boxes = []
        self._clinks.clear()
        if not cards:
            return
        head = QLabel("🔎 Búsquedas recientes"); head.setStyleSheet(f"color:#8fb4ff;font-weight:bold;font-size:{fs}px;")
        self._lay.addWidget(head); self._card_boxes.append(head)
        for k in cards[: 2 if c["tam"] == "grande" else 1]:
            row = QWidget(); hl = QHBoxLayout(row); hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(8)
            if k["pix"] is not None and t["img"]:
                im = _Clickable(); im.setFixedSize(t["img"], t["img"])
                im.setPixmap(k["pix"].scaled(t["img"], t["img"], Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
                im.setScaledContents(False)
                if k.get("url"):
                    im.setCursor(Qt.PointingHandCursor)
                    im.clicked.connect(lambda u=k["url"]: self._abrir(u))
                hl.addWidget(im, 0, Qt.AlignTop)
            tx = QLabel(); tx.setWordWrap(True); tx.setTextFormat(Qt.RichText)
            tx.setTextInteractionFlags(Qt.LinksAccessibleByMouse); tx.setOpenExternalLinks(False)
            tx.linkActivated.connect(lambda h_: self._on_link(h_, self._clinks))
            lim = 110 if c["tam"] == "compacta" else 170 if c["tam"] == "media" else 240
            partes = []
            for f in (k["fuentes"] or [])[:2]:
                f = str(f)
                if f.startswith("http"):
                    host = re.sub(r"^https?://(www\.)?", "", f).split("/")[0]
                    partes.append(self._a(self._clinks, _esc(host[:30]), f))
                else:
                    partes.append(_esc(f[:30]))
            fu = " · ".join(partes)
            ttl = _esc((k["titulo"] or k["consulta"])[:40])
            if k.get("url"):
                ttl = self._a(self._clinks, ttl, k["url"])
            tx.setText(f"<b>{ttl}</b><br><span style='color:#cfd6e6'>{_esc(k['resumen'][:lim])}…</span>"
                       + (f"<br><span style='color:#7f8aa3;font-size:{max(9, fs - 3)}px'>{fu}</span>" if fu else ""))
            tx.setStyleSheet(f"color:#e8ecf5;font-size:{fs - 1}px;")
            hl.addWidget(tx, 1)
            self._lay.addWidget(row); self._card_boxes.append(row)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._close.move(self.width() - self._close.width() - 8, 8)
        self._close.raise_()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor(20, 25, 40, 235))); p.setPen(QPen(QColor(120, 160, 255, 90), 1))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 14, 14)

    def _tick(self) -> None:
        self._n += 1
        if self.acts:  # hay actividad: se actualiza cada segundo (cronómetro, y aparece a los 1.5 s)
            self.refresh()
            return
        if self._n % 15 == 0 or (not self.isVisible() and self._n % 3 == 0):
            self.refresh()
            return
        if not self.isVisible() or not self._cache:
            return
        c, d = self._cache
        now = time.time()
        if any(v["hasta"] <= now for v in self.pushes.values()):
            self.refresh(); return
        if d["timers"] or d["tarea"] or d["acts"]:
            self._text.setText(self._html(d, TAM[c["tam"]]["items"], TAM[c["tam"]]["fs"]))
        if self.get_anchor:  # sigue a la bolita si se mueve
            self._place(c)

    # ------------------------------------------------------------------ posición: junto a la bolita
    def _place(self, c: dict) -> None:
        anchor = None
        if self.get_anchor:
            try:
                anchor = self.get_anchor()
            except Exception:  # noqa: BLE001
                anchor = None
        if anchor:
            ctr, r, escondida = anchor
            scr = QGuiApplication.screenAt(ctr) or QGuiApplication.primaryScreen()
            g = scr.availableGeometry()
            gap = int(r * 1.5) + 8
            if escondida:  # bolita asomada en el borde: la ventana va hacia el lado de la pantalla
                x = ctr.x() - gap - self.width() if ctr.x() > g.center().x() else ctr.x() + gap
            else:
                x = ctr.x() + gap
                if x + self.width() > g.right() - 8:  # no cabe a la derecha: va a la izquierda
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
            m.addAction("Solo cuando Orbi decida", lambda: self._set_modo("orbi"))
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
