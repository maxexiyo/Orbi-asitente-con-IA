"""Ventana de Ajustes de Orbi (distinta del asistente de configuración inicial).

Se abre desde el menú de la bolita («Ajustes…») o desde el clic derecho de la mini ventana. Guarda al pulsar «Aplicar».

  Permisos      · cosas DELICADAS (enviar, pagar, borrar…): preguntar / automático / permitir todo
                · cosas NO delicadas (clics, escribir, teclas): permitir / automático / preguntar siempre
  Mini ventana  · mostrar (siempre / solo si hay algo / oculta), tamaño, opacidad, esquina y qué secciones lleva
  Internet      · paciencia con redes lentas, navegador como último recurso
  Memoria       · resumir conversaciones para recordarlas, olvidar lo guardado
  Alarmas       · tono (con botón de prueba)
  Calendarios   · calendarios que Orbi lee (iCal) y avisos de eventos (al iniciar, 15 min antes, 1 día antes…)
  Carpetas      · otras carpetas a las que Orbi puede entrar (además de Documentos, Escritorio, Descargas…)
  Apps y límites· apps que Orbi NO debe abrir (para él no están instaladas) y cosas que no debe hacer (restricciones.py)
  Notificaciones· qué avisar, horario de silencio e historial corto (leídas / descartadas, unas horas)
  Rutinas y alarmas · ver, agregar, editar y borrar a mano rutinas/reglas, alarmas, recordatorios y timers (ajustes_pendientes.py)
  General       · lo de config.json que tiene sentido para un usuario normal (voz, tamaño de la bolita, cuándo se duerme,
                  modo compañero, notificaciones, privacidad). Se guarda en orbi_config_ventana.json y manda sobre config.json;
                  casi todo se aplica al reiniciar Orbi.
"""
from PySide6.QtCore import QObject, QTime, QTimer, Qt, Signal, Slot

import temas
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QTabWidget, QTimeEdit, QVBoxLayout, QWidget, QGridLayout, QStackedWidget, QButtonGroup)

DELICADAS = [("preguntar", "Preguntarme siempre (recomendado)"),
             ("auto", "Automático: solo pregunta lo más grave (pagos, borrar, correos, cocheras)"),
             ("permitir", "Permitir todo sin preguntar")]
NORMALES = [("permitir", "Permitir sin preguntar (normal)"),
            ("auto", "Automático: pregunta solo en terminal, registro, configuración…"),
            ("preguntar", "Preguntarme antes de cada acción")]
MINI_MODO = [("orbi", "Solo cuando Orbi decida mostrarla (recomendado)"), ("con_datos", "Solo cuando hay algo que mostrar"), ("siempre", "Siempre visible"), ("oculta", "Oculta")]
MINI_TAM = [("compacta", "Compacta"), ("media", "Media"), ("grande", "Grande (con más datos e imagen)")]
ESQUINAS = [("inferior_derecha", "Abajo a la derecha"), ("inferior_izquierda", "Abajo a la izquierda"),
            ("superior_derecha", "Arriba a la derecha"), ("superior_izquierda", "Arriba a la izquierda")]
INTERNET = [("auto", "Automático (se adapta a la velocidad)"), ("si", "Mi internet es lento: más paciencia"), ("no", "Mi internet es rápido")]
UBICACION = [("junto_a_orbi", "A un lado de Orbi (me sigue)"), ("esquina", "Fija en una esquina de la pantalla")]
PROXIMO = [15, 30, 60, 120, 240]
VOCES = ["Puck", "Charon", "Kore", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr"]
DORMIR = [(300, "5 minutos"), (600, "10 minutos"), (900, "15 minutos (normal)"), (1800, "30 minutos"), (3600, "1 hora")]
SEGUIR = [(5, "5 segundos"), (12, "12 segundos (normal)"), (20, "20 segundos"), (30, "30 segundos")]
FIN_TURNO = [("low", "Que me deje terminar de pensar lo que digo (normal)"), ("high", "Que conteste rápido, apenas me calle")]
REVISAR = [(1, "Cada segundo (gasta mucha cuota)"), (5, "Cada 5 segundos"), (10, "Cada 10 segundos"), (20, "Cada 20 segundos (normal)"), (40, "Cada 40 segundos"), (60, "Cada minuto"), (120, "Cada 2 minutos")]
TOPE = [(0, "Sin tope: Orbi decide cuándo vale la pena"), (3, "Máximo 3 por hora"), (6, "Máximo 6 por hora"), (12, "Máximo 12 por hora")]
PAUSA = [(0, "Ninguna"), (60, "1 minuto"), (120, "2 minutos"), (300, "5 minutos")]
HIST_HORAS = [(0, "No guardar historial"), (2, "2 horas"), (6, "6 horas (normal)"), (12, "12 horas")]
CATEG = [("mensajes", "Mensajes"), ("correo", "Correo"), ("calendario", "Calendario"), ("seguridad", "Seguridad")]
SECCIONES = [("calendario", "Calendario"), ("alarmas", "Alarmas"), ("recordatorios", "Recordatorios"),
             ("timers", "Timers (cuenta regresiva)"), ("busquedas", "Resúmenes de búsquedas web con imagen"),
             ("avisos", "Avisos: notificaciones, reglas, listas que pediste"), ("tarea", "Lo que Orbi hace en tu PC (paso a paso)")]


def _form(widget):
    """Formulario con la etiqueta ENCIMA del campo: con opciones largas, la columna de etiquetas se encogía a 0 de ancho."""
    f = QFormLayout(widget)
    f.setRowWrapPolicy(QFormLayout.WrapAllRows)
    f.setVerticalSpacing(8)
    return f


def _near(opts, v):
    """Valor de `opts` más cercano a `v` (para números guardados a mano en config.json que no están en la lista)."""
    try:
        return min((o[0] for o in opts), key=lambda x: abs(x - float(v)))
    except (TypeError, ValueError):
        return opts[0][0]


class _ValorPersonalizable(QWidget):
    """Lista de opciones + «Personalizado…» con un número propio (segundos, o cantidad). value() da lo elegido."""

    def __init__(self, opts, current, lo, hi, sufijo=" s", personalizado="Personalizado…"):
        super().__init__()
        self._combo = QComboBox()
        for v, txt in opts:
            self._combo.addItem(txt, v)
        self._combo.addItem(personalizado, "__custom__")
        self._spin = QSpinBox(); self._spin.setRange(lo, hi); self._spin.setSuffix(sufijo)
        try:
            cur = int(float(current))
        except (TypeError, ValueError):
            cur = opts[0][0]
        i = self._combo.findData(cur)
        if i >= 0:
            self._combo.setCurrentIndex(i)
            self._spin.setValue(max(lo, min(hi, cur)))
        else:                                              # número a mano (de config.json o de antes): queda como personalizado
            self._combo.setCurrentIndex(self._combo.count() - 1)
            self._spin.setValue(max(lo, min(hi, cur)))
        self._combo.currentIndexChanged.connect(self._sync)
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._combo, 1); lay.addWidget(self._spin)
        self._sync()

    def _sync(self):
        self._spin.setEnabled(self._combo.currentData() == "__custom__")

    def value(self) -> int:
        d = self._combo.currentData()
        return int(self._spin.value() if d == "__custom__" else d)


def _scroll(inner):
    s = QScrollArea(); s.setWidgetResizable(True); s.setFrameShape(QScrollArea.NoFrame); s.setWidget(inner)
    return s


def _combo(opts, current):
    c = QComboBox()
    c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    c.setMinimumContentsLength(28)
    for val, txt in opts:
        c.addItem(txt, val)
    i = max(0, next((k for k, (v, _t) in enumerate(opts) if v == current), 0))
    c.setCurrentIndex(i)
    return c


class _ListaBg(QObject):
    """Pide la lista de bocinas en un hilo y la entrega en el hilo de la ventana (por un slot: nunca tocar la interfaz desde el hilo)."""
    lista = Signal(list)

    def __init__(self, owner, cb):
        super().__init__(owner)
        self._cb = cb
        self.lista.connect(self._recibir)

    @Slot(list)
    def _recibir(self, nombres):
        self._cb(nombres)


class _CalendarioDialog(QDialog):
    """Agregar un calendario por su enlace iCal (.ics): sin Google Cloud ni cuenta, solo lectura."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Agregar calendario")
        self.setMinimumWidth(500)
        lay = QVBoxLayout(self)
        info = QLabel("No necesitas Google Cloud: basta el <b>enlace secreto iCal</b> de tu calendario (Orbi solo lo <b>lee</b>).<br><br>"
                      "<b>Google Calendar</b> (en la computadora): ⚙ Configuración → en la izquierda, tu calendario → "
                      "<i>Integrar el calendario</i> → copia la <b>«Dirección secreta en formato iCal»</b>.<br>"
                      "<b>Outlook / Microsoft</b>: Configuración → Calendario → Calendarios compartidos → <i>Publicar un calendario</i> → copia el enlace <b>ICS</b> "
                      "(si tu escuela no deja publicarlo, no habrá enlace).<br>"
                      "<span style='color:#c0392b'>Ese enlace es privado: quien lo tenga puede ver tu calendario. No lo compartas.</span>")
        info.setWordWrap(True); info.setTextFormat(Qt.RichText)
        lay.addWidget(info)
        bl = QHBoxLayout()
        b1 = QPushButton("Abrir configuración de Google Calendar"); b1.clicked.connect(lambda: __import__("webbrowser").open("https://calendar.google.com/calendar/u/0/r/settings"))
        bl.addWidget(b1); lay.addLayout(bl)
        f = QFormLayout()
        self.e_nombre = QLineEdit(); self.e_nombre.setPlaceholderText("Nombre corto, ej. personal o escuela")
        self.e_url = QLineEdit(); self.e_url.setPlaceholderText("https://calendar.google.com/calendar/ical/…/basic.ics")
        f.addRow("Nombre:", self.e_nombre); f.addRow("Enlace iCal:", self.e_url)
        lay.addLayout(f)
        self.estado = QLabel(""); self.estado.setWordWrap(True); lay.addWidget(self.estado)
        row = QHBoxLayout(); row.addStretch(1)
        ok = QPushButton("Probar y guardar"); ok.setDefault(True); ok.clicked.connect(self._guardar)
        no = QPushButton("Cancelar"); no.clicked.connect(self.reject)
        row.addWidget(ok); row.addWidget(no); lay.addLayout(row)

    def _guardar(self):
        nombre, url = self.e_nombre.text().strip(), self.e_url.text().strip()
        if not nombre or not url.lower().startswith(("https://", "http://", "webcal://")):
            self.estado.setText("Pon un nombre y el enlace completo (empieza con https://)."); return
        url = url.replace("webcal://", "https://", 1)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Orbi-asistente"})
            with urllib.request.urlopen(req, timeout=12) as r:
                head = r.read(4096)
            ok = b"BEGIN:VCALENDAR" in head
        except Exception as e:  # noqa: BLE001
            self.estado.setText(f"No pude abrir el enlace: {type(e).__name__}. Revisa que esté completo."); return
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            self.estado.setText("Ese enlace no parece un calendario iCal (debe terminar en .ics)."); return
        self.resultado = (nombre, url)
        self.accept()


class _TabsEnFilas(QWidget):
    """Como un QTabWidget, pero los botones de las pestañas van en VARIAS filas (sin flechitas para moverse)."""
    currentChanged = Signal(int)

    def __init__(self, columnas=4):
        super().__init__()
        self._cols = max(1, columnas)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self._grid = QGridLayout(); self._grid.setSpacing(4)
        for c in range(self._cols):
            self._grid.setColumnStretch(c, 1)
        lay.addLayout(self._grid)
        self._stack = QStackedWidget(); lay.addWidget(self._stack, 1)
        self._btns = []
        self._group = QButtonGroup(self); self._group.setExclusive(True)

    def addTab(self, w, titulo) -> int:
        i = self._stack.addWidget(w)
        b = QPushButton(titulo); b.setCheckable(True); b.setMinimumHeight(30)
        b.clicked.connect(lambda _=False, i=i: self.setCurrentIndex(i))
        self._group.addButton(b); self._btns.append(b)
        self._grid.addWidget(b, i // self._cols, i % self._cols)
        if i == 0:
            b.setChecked(True)
        return i

    def setCurrentIndex(self, i):
        if 0 <= i < len(self._btns):
            self._stack.setCurrentIndex(i); self._btns[i].setChecked(True); self.currentChanged.emit(i)

    def currentIndex(self) -> int:
        return self._stack.currentIndex()

    def currentWidget(self):
        return self._stack.currentWidget()

    def count(self) -> int:
        return self._stack.count()


class AjustesDialog(QDialog):
    def __init__(self, profile: dict, tonos: list, apply, test_tone, clear_memory, mini_defaults: dict, cfg: dict | None = None,
                 open_memory=None, skills_mod=None, on_skills_changed=None, extras=None, hub=None, alarms=None, reglas=None,
                 on_pendientes_change=None, parent=None):
        """apply({"permisos": {...}, "ajustes": {...}}) guarda y aplica · test_tone(nombre) · clear_memory() -> None."""
        super().__init__(parent)
        self.setWindowTitle("Ajustes de Orbi")
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)      # se puede minimizar; ya NO se queda encima de todo
        self.setMinimumWidth(560)
        self.resize(640, 560)
        self._apply, self._test, self._clear = apply, test_tone, clear_memory
        perm = profile.get("permisos") or {}
        aj = profile.get("ajustes") or {}
        mini = {**mini_defaults, **(aj.get("mini") or {})}
        mini["secciones"] = {**mini_defaults.get("secciones", {}), **((aj.get("mini") or {}).get("secciones") or {})}
        self._mini_pos = mini.get("pos")

        tabs = _TabsEnFilas(4)          # las pestañas van en varias filas (4 por fila)
        # ---------------- Permisos
        w = QWidget(); f = _form(w)
        modo_d = perm.get("modo_delicadas") or ("preguntar" if perm.get("confirmar_acciones", True) else "permitir")
        self.c_del = _combo(DELICADAS, modo_d)
        self.c_nor = _combo(NORMALES, perm.get("modo_normales", "permitir"))
        f.addRow("Cosas delicadas (enviar mensajes, pagar, borrar):", self.c_del)
        self.aviso = QLabel(); self.aviso.setWordWrap(True); self.aviso.setObjectName("aviso")
        f.addRow("", self.aviso)
        f.addRow("Cosas no delicadas (clics, escribir, teclas):", self.c_nor)
        nota = QLabel("Enviar un correo desde tu Gmail siempre pide tu OK, sin importar el modo (un correo podría intentar engañar a la IA).")
        nota.setWordWrap(True); nota.setObjectName("nota")
        f.addRow("", nota)
        self.c_del.currentIndexChanged.connect(self._warn); self._warn()
        tabs.addTab(w, "Permisos")

        # ---------------- Mini ventana
        w = QWidget(); f = _form(w)
        self.m_modo = _combo(MINI_MODO, mini["modo"])
        self.m_tam = _combo(MINI_TAM, mini["tam"])
        self.m_esq = _combo(ESQUINAS, mini["esquina"])
        self.m_ubi = _combo(UBICACION, mini.get("ubicacion", "junto_a_orbi"))
        _p = min(PROXIMO, key=lambda v: abs(v - int(mini.get("proximo_min", 60) or 60)))
        self.m_prox = _combo([(v, f"{v} min" if v < 60 else f"{v // 60} h") for v in PROXIMO], _p)
        nota_m = QLabel("En el modo «Solo cuando Orbi decida» la ventana no se abre sola: las secciones de abajo aplican a los otros modos.")
        nota_m.setWordWrap(True); nota_m.setObjectName("nota")
        self.m_op = QSlider(Qt.Horizontal); self.m_op.setRange(30, 100); self.m_op.setValue(int(mini["opacidad"]))
        f.addRow("Mostrar:", self.m_modo); f.addRow("", nota_m); f.addRow("Dónde aparece:", self.m_ubi); f.addRow("Tamaño:", self.m_tam)
        f.addRow("Esquina (si va fija):", self.m_esq); f.addRow("Cuenta como «próximo» lo que ocurra en:", self.m_prox)
        f.addRow("Opacidad:", self.m_op)
        self.m_sec = {}
        for k, txt in SECCIONES:
            cb = QCheckBox(txt); cb.setChecked(bool(mini["secciones"].get(k, True))); self.m_sec[k] = cb
            f.addRow("" if k != SECCIONES[0][0] else "Qué mostrar:", cb)
        b = QPushButton("Pegarla otra vez a Orbi (olvidar dónde la arrastré)"); b.clicked.connect(lambda: setattr(self, "_mini_pos", None))
        f.addRow("", b)
        tabs.addTab(w, "Mini ventana")

        # ---------------- Apariencia (el mismo tema para dashboard, mini ventana, Ajustes y menús)
        w = QWidget(); f = _form(w)
        self._tema_aplicado = aj.get("tema") if aj.get("tema") in temas.TEMAS else temas.DEFAULT
        self.t_tema = _combo([(i, n) for i, n, _d in temas.lista()], self._tema_aplicado)
        self.t_desc = QLabel(); self.t_desc.setWordWrap(True); self.t_desc.setObjectName("nota")
        f.addRow("Tema:", self.t_tema)
        f.addRow("", self.t_desc)
        nota_t = QLabel("El tema cambia cómo se ven el dashboard (los paneles que Orbi suelta de golpe), la mini ventana, esta ventana de Ajustes y los menús. "
                        "Lo ves aquí mismo al elegirlo; si cierras sin pulsar «Aplicar» se queda el que tenías. «Órbita» deja a la bolita al centro con los paneles "
                        "alrededor; los demás la mandan a la esquina mientras el dashboard está abierto.")
        nota_t.setWordWrap(True); nota_t.setObjectName("nota")
        f.addRow("", nota_t)
        self.t_tema.currentIndexChanged.connect(self._tema_vista_previa); self._tema_desc()
        tabs.addTab(w, "Apariencia")

        # ---------------- Internet y memoria
        w = QWidget(); f = _form(w)
        self.i_lento = _combo(INTERNET, {True: "si", False: "no"}.get(aj.get("internet_lento"), aj.get("internet_lento") or "auto"))
        self.i_nav = QCheckBox("Si falla todo, abrir el navegador de la PC y leer los resultados"); self.i_nav.setChecked(aj.get("busqueda_navegador", True))
        f.addRow("Velocidad de internet:", self.i_lento); f.addRow("", self.i_nav)
        self.mem = QCheckBox("Resumir mis conversaciones para recordarlas con el tiempo"); self.mem.setChecked(aj.get("memoria_larga", True))
        f.addRow("Memoria:", self.mem)
        bm = QPushButton("Olvidar lo que Orbi resumió de mis conversaciones…"); bm.clicked.connect(self._olvidar)
        f.addRow("", bm)
        if open_memory:
            bo = QPushButton("Abrir mi memoria (archivos .md que Orbi va escribiendo sobre mí)"); bo.clicked.connect(open_memory)
            f.addRow("", bo)
        tabs.addTab(w, "Internet y memoria")

        # ---------------- General (lo configurable de config.json)
        cfg = cfg or {}
        comp = cfg.get("companero") if isinstance(cfg.get("companero"), dict) else {}
        nt = cfg.get("notificaciones") if isinstance(cfg.get("notificaciones"), dict) else {}
        w = QWidget(); f = _form(w)
        voces = list(VOCES)
        if cfg.get("live_voice") and cfg["live_voice"] not in voces:
            voces.insert(0, cfg["live_voice"])
        self.g_voz = _combo([(v, v) for v in voces], cfg.get("live_voice", "Puck"))
        self.g_aud = QCheckBox("Uso audífonos (evita que Orbi se escuche a sí misma)"); self.g_aud.setChecked(bool(cfg.get("headphones", False)))
        self.g_esc = QSlider(Qt.Horizontal); self.g_esc.setRange(40, 120); self.g_esc.setValue(int(round(float(cfg.get("orb_scale", 0.65)) * 100)))
        self.g_dorm = _combo(DORMIR, _near(DORMIR, cfg.get("sleep_after_s", 900)))
        self.g_seg = _combo(SEGUIR, _near(SEGUIR, cfg.get("seguimiento_s", 12)))
        self.g_fin = _combo(FIN_TURNO, cfg.get("fin_sensibilidad", "low"))
        f.addRow("Voz de Orbi:", self.g_voz); f.addRow("", self.g_aud)
        f.addRow("Tamaño de la bolita:", self.g_esc)
        f.addRow("Se duerme si no le hablas en:", self.g_dorm)
        f.addRow("Puedes seguir hablando sin decir «Orbi» durante:", self.g_seg)
        f.addRow("Cuando termino de hablar:", self.g_fin)
        self.g_comp = QCheckBox("Modo compañero: Orbi mira mi pantalla y me avisa solo si ve algo útil (al iniciar)")
        self.g_comp.setChecked(bool(cfg.get("observer_autostart", True)))
        self.g_rev = _ValorPersonalizable(REVISAR, comp.get("revisar_cada_s", 20), 1, 3600)
        self.g_tope = _ValorPersonalizable(TOPE, comp.get("max_por_hora", 0), 0, 120, " por hora")
        self.g_pausa = _ValorPersonalizable(PAUSA, comp.get("pausa_tras_comentario_s", 0), 0, 3600)
        f.addRow("", self.g_comp); f.addRow("El compañero mira mi pantalla:", self.g_rev)
        f.addRow("Cuántos avisos como máximo:", self.g_tope); f.addRow("Pausa tras un aviso:", self.g_pausa)
        self.g_esq = QCheckBox("Orbi se aparta cuando trabaja en mi PC"); self.g_esq.setChecked(bool(cfg.get("esquivar_al_trabajar", True)))
        self.g_mouse = QCheckBox("Prefiero que use el mouse en lugar de atajos de teclado"); self.g_mouse.setChecked(bool(cfg.get("preferir_mouse", False)))
        self.g_ocul = QCheckBox("Ocultar a Orbi en las capturas que ve la IA"); self.g_ocul.setChecked(bool(cfg.get("ocultar_orbi_en_capturas", False)))
        self.g_web = QCheckBox("Permitir que Orbi busque en internet"); self.g_web.setChecked(bool(cfg.get("busqueda_web", True)))
        self.g_ext = QCheckBox("Que Orbi pueda ver mis memorias USB y discos externos (leer, buscar y mover archivos)")
        self.g_ext.setChecked(bool(cfg.get("unidades_externas", True)))
        for cb in (self.g_esq, self.g_mouse, self.g_ocul, self.g_web, self.g_ext):
            f.addRow("", cb)
        reinicio = QLabel("Voz, tamaño, compañero y privacidad se aplican al reiniciar Orbi.")
        reinicio.setWordWrap(True); reinicio.setObjectName("nota")
        f.addRow("", reinicio)
        tabs.addTab(_scroll(w), "General")

        # ---------------- Notificaciones
        w = QWidget(); f = _form(w)
        self.n_auto = QCheckBox("Avisarme de mis notificaciones al iniciar Orbi"); self.n_auto.setChecked(bool(nt.get("autostart", True)))
        f.addRow("", self.n_auto)
        cats = nt.get("categorias") or [k for k, _t in CATEG]
        self.n_cat = {}
        for k, txt in CATEG:
            cb = QCheckBox(txt); cb.setChecked(k in cats); self.n_cat[k] = cb
            f.addRow("" if k != CATEG[0][0] else "Qué avisar:", cb)
        self.n_vip = QLineEdit(", ".join(nt.get("vip") or [])); self.n_vip.setPlaceholderText("mamá, papá… (separados por comas)")
        f.addRow("Contactos importantes (siempre te aviso):", self.n_vip)
        hs = nt.get("horas_silencio") or []
        self.n_sil = QCheckBox("No avisarme de noche"); self.n_sil.setChecked(len(hs) == 2)
        self.n_ini, self.n_fin = QTimeEdit(), QTimeEdit()
        for te, s, d in ((self.n_ini, hs[0] if len(hs) == 2 else "23:00", "23:00"), (self.n_fin, hs[1] if len(hs) == 2 else "07:00", "07:00")):
            te.setDisplayFormat("HH:mm"); t = QTime.fromString(str(s), "HH:mm"); te.setTime(t if t.isValid() else QTime.fromString(d, "HH:mm"))
        hr = QHBoxLayout(); hr.addWidget(QLabel("de")); hr.addWidget(self.n_ini); hr.addWidget(QLabel("a")); hr.addWidget(self.n_fin); hr.addStretch(1)
        f.addRow("", self.n_sil); f.addRow("Horario de silencio:", hr)
        self.n_leer = QCheckBox("Que Orbi lea el contenido de los mensajes (si no, solo dice de quién)"); self.n_leer.setChecked(bool(nt.get("leer_contenido", False)))
        f.addRow("", self.n_leer)
        ca = (cfg or {}).get("correo_avisos") if isinstance((cfg or {}).get("correo_avisos"), dict) else {}
        self.c_aviso = QCheckBox("Avisarme cuando llegue un correo nuevo (de tus cuentas de Ajustes → Cuentas y conectores)")
        self.c_aviso.setChecked(bool(ca.get("activo", False)))
        self.c_cada = _ValorPersonalizable([(60, "Cada minuto"), (120, "Cada 2 minutos"), (300, "Cada 5 minutos"), (600, "Cada 10 minutos")],
                                           ca.get("cada_s", 120), 30, 3600)
        self.c_voz = QCheckBox("Decírmelo en voz alta (si no, solo sale en la burbuja y en la mini ventana)")
        self.c_voz.setChecked(bool(ca.get("voz", False)))
        self.c_imp = QCheckBox("Solo personas y avisos importantes (ignora promociones y cuentas automáticas)")
        self.c_imp.setChecked(bool(ca.get("solo_importantes", True)))
        f.addRow("", self.c_aviso); f.addRow("Revisar el correo:", self.c_cada); f.addRow("", self.c_voz); f.addRow("", self.c_imp)
        nn = QLabel("Las notificaciones también necesitan el permiso «notificaciones» en la configuración inicial de Orbi.")
        nn.setWordWrap(True); nn.setObjectName("nota"); f.addRow("", nn)
        # historial corto: lo que ya se leyó o se descartó (dura pocas horas y sobrevive si reinicias Orbi)
        self.n_hist_h = _combo(HIST_HORAS, _near(HIST_HORAS, nt.get("historial_horas", 6)))
        f.addRow("Guardar el historial de notificaciones leídas y descartadas:", self.n_hist_h)
        self.n_hist = QListWidget(); self.n_hist.setMinimumHeight(120); self.n_hist.setMaximumHeight(170)
        f.addRow("", self.n_hist)
        hb = QHBoxLayout()
        b = QPushButton("Actualizar"); b.clicked.connect(self._hist_refresh); hb.addWidget(b)
        b = QPushButton("Vaciar historial"); b.clicked.connect(self._hist_vaciar); hb.addWidget(b); hb.addStretch(1)
        f.addRow("", hb)
        tabs.addTab(_scroll(w), "Notificaciones")
        self._hist_refresh()

        # ---------------- Alarmas
        w = QWidget(); f = _form(w)
        self.a_tono = QComboBox()
        for n in tonos:
            self.a_tono.addItem(n, n)
        i = self.a_tono.findData(aj.get("alarma_tono"))
        self.a_tono.setCurrentIndex(max(0, i))
        bt = QPushButton("▶ Probar"); bt.clicked.connect(lambda: self._test(self.a_tono.currentData()))
        row = QHBoxLayout(); row.addWidget(self.a_tono, 1); row.addWidget(bt)
        f.addRow("Tono de alarma:", row)
        tabs.addTab(w, "Alarmas")

        # ---------------- Audio (micrófono, volumen y bocina)
        cfg = cfg or {}
        w = QWidget(); f = _form(w)
        u = float(cfg.get("mic_umbral", 0.15) or 0.15)
        self.au_mic = QSlider(Qt.Horizontal); self.au_mic.setRange(0, 100)
        self.au_mic.setValue(max(0, min(100, round((0.30 - u) / 0.0026))))
        nota_mic = QLabel("Más a la derecha = el micrófono capta voces más bajitas (pero también más ruido). Si Orbi se activa solo, bájalo; "
                          "si no te oye, súbelo. Se aplica al momento.")
        nota_mic.setWordWrap(True); nota_mic.setObjectName("nota")
        f.addRow("Sensibilidad del micrófono:", self.au_mic); f.addRow("", nota_mic)
        self.au_idioma = _combo([("es", "Español (México) — recomendado"), ("es+en", "Español e inglés"), ("auto", "Automático (cualquier idioma)")],
                                aj.get("idioma_oido", cfg.get("idioma_oido", "es")))
        nota_idioma = QLabel("En qué idioma te habla normalmente. Así Orbi no confunde tu voz con japonés, chino o inglés cuando hay ruido, música o "
                             "videos. No afecta al modo intérprete ni a los traductores. Se aplica en la siguiente conexión (o al reiniciar Orbi).")
        nota_idioma.setWordWrap(True); nota_idioma.setObjectName("nota")
        f.addRow("Idioma con el que te oye:", self.au_idioma); f.addRow("", nota_idioma)
        self.au_vol = QSlider(Qt.Horizontal); self.au_vol.setRange(10, 150)
        self.au_vol.setValue(max(10, min(150, round(float(cfg.get("volumen_voz", 1.0) or 1.0) * 100))))
        self.au_vol_txt = QLabel(f"{self.au_vol.value()}%")
        self.au_vol.valueChanged.connect(lambda v: self.au_vol_txt.setText(f"{v}%"))
        vr = QHBoxLayout(); vr.addWidget(self.au_vol, 1); vr.addWidget(self.au_vol_txt)
        f.addRow("Volumen de la voz de Orbi:", vr)
        self._au_actual = str(cfg.get("salida_audio") or "")
        self.au_dev = QComboBox(); self.au_dev.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.au_dev.setMinimumContentsLength(28)
        self._au_llenar([])
        bd = QPushButton("Actualizar lista"); bd.clicked.connect(self._au_refrescar)
        dr = QHBoxLayout(); dr.addWidget(self.au_dev, 1); dr.addWidget(bd)
        f.addRow("Dónde suena Orbi:", dr)
        self.au_nota = QLabel("La lista se actualiza sola cada pocos segundos mientras esta pestaña está abierta. Un dispositivo conectado "
                              "DESPUÉS de abrir Orbi se usa al reiniciarlo; «Predeterminado» siempre sigue lo que elija Windows.")
        self.au_nota.setWordWrap(True); self.au_nota.setObjectName("nota")
        f.addRow("", self.au_nota)
        self.au_alm = QSlider(Qt.Horizontal); self.au_alm.setRange(10, 150)
        self.au_alm.setValue(max(10, min(150, round(float(cfg.get("volumen_alarmas", 1.0) or 1.0) * 100))))
        self.au_alm_txt = QLabel(f"{self.au_alm.value()}%")
        self.au_alm.valueChanged.connect(lambda v: self.au_alm_txt.setText(f"{v}%"))
        ar = QHBoxLayout(); ar.addWidget(self.au_alm, 1); ar.addWidget(self.au_alm_txt)
        f.addRow("Volumen de las alarmas:", ar)
        pend = QLabel("Las alarmas suenan por la bocina predeterminada de Windows, y el tono «Clásico (pitidos)» no cambia de volumen. "
                      "Pulsa «Aplicar» y usa «▶ Probar» en la pestaña Alarmas para oírlo.")
        pend.setWordWrap(True); pend.setObjectName("nota")
        f.addRow("", pend)
        self._au_bg = _ListaBg(self, self._au_llenar)
        self._au_tab = tabs.addTab(w, "Audio")
        self._au_timer = QTimer(self); self._au_timer.timeout.connect(self._au_tick); self._au_timer.start(6000)
        self._tabs = tabs
        QTimer.singleShot(300, self._au_refrescar)

        # ---------------- Calendarios (enlaces iCal)
        cal = (cfg or {}).get("calendarios") if isinstance((cfg or {}).get("calendarios"), dict) else {}
        self._cal = dict(cal)
        w = QWidget(); lay = QVBoxLayout(w)
        info = QLabel("Calendarios que Orbi puede <b>leer</b> (para decirte tu agenda). Se agregan con su enlace iCal: sin Google Cloud ni iniciar sesión. "
                      "Los cambios se aplican al reiniciar Orbi.")
        info.setWordWrap(True); info.setTextFormat(Qt.RichText)
        self.cal_list = QListWidget()
        lay.addWidget(info); lay.addWidget(self.cal_list, 1)
        rb = QHBoxLayout()
        b = QPushButton("➕ Agregar calendario…"); b.clicked.connect(self._cal_add); rb.addWidget(b)
        b = QPushButton("Quitar el seleccionado"); b.clicked.connect(self._cal_del); rb.addWidget(b)
        lay.addLayout(rb)
        # avisos de eventos (#46): cuándo te avisa Orbi antes de cada evento
        import avisos_cal as _ac
        _av = (cfg or {}).get("avisos_calendario") if isinstance((cfg or {}).get("avisos_calendario"), dict) else {}
        _antes = _ac.parse_lista(_av.get("antes_min", _ac.DEFAULTS["antes_min"]))
        self.av_activo = QCheckBox("Avisarme de mis eventos del calendario"); self.av_activo.setChecked(bool(_av.get("activo", True)))
        lay.addWidget(self.av_activo)
        lay.addWidget(QLabel("Avisarme (puedes marcar varios):"))
        self.av_chk, g = {}, QGridLayout()
        for k, (m, txt) in enumerate(_ac.PRESETS):
            cb = QCheckBox(txt); cb.setChecked(m in _antes); self.av_chk[m] = cb
            g.addWidget(cb, k // 2, k % 2)
        lay.addLayout(g)
        otros = [m for m in _antes if m not in self.av_chk]
        self.av_otros = QLineEdit(", ".join(f"{m} min" for m in otros))
        self.av_otros.setPlaceholderText("Otros, por ejemplo: 45 minutos, 3 horas, 2 días")
        lay.addWidget(self.av_otros)
        self.av_voz = QCheckBox("Decírmelo en voz alta (si no, solo sale en la burbuja y en la mini ventana)")
        self.av_voz.setChecked(bool(_av.get("voz", True)))
        lay.addWidget(self.av_voz)
        nota_av = QLabel("Cada aviso se dice una sola vez por evento. En tu horario de silencio solo sale en pantalla. "
                         "También puedes decirle a Orbi: «avísame de mis eventos 15 minutos antes y 1 día antes». "
                         "Necesita el permiso «agenda».")
        nota_av.setWordWrap(True); nota_av.setObjectName("nota"); lay.addWidget(nota_av)
        tabs.addTab(w, "Calendarios")
        self._cal_refresh()

        # ---------------- Carpetas (a cuáles puede entrar Orbi además de las de siempre)
        import docs_reader as _dr
        self._dr = _dr
        _ce = (cfg or {}).get("carpetas_extra")
        self._carp = [str(x) for x in _ce] if isinstance(_ce, list) else []
        w = QWidget(); lay = QVBoxLayout(w)
        info = QLabel("Orbi busca, lee, abre y organiza archivos <b>solo</b> dentro de las carpetas que puede ver: siempre Documentos, Escritorio, "
                      "Descargas, Imágenes, Videos y Música (y tus memorias USB o discos externos si lo dejas activado en General). "
                      "Aquí agregas otras, por ejemplo la carpeta de tus proyectos. Para pedírselas por voz dile su nombre, "
                      "como «abre la carpeta Proyectos».<br>Solo se agregan desde esta ventana: Orbi no puede darse acceso por su cuenta. "
                      "El cambio se aplica al pulsar «Aplicar».")
        info.setWordWrap(True); info.setTextFormat(Qt.RichText)
        self.carp_list = QListWidget()
        lay.addWidget(info); lay.addWidget(self.carp_list, 1)
        rb = QHBoxLayout()
        b = QPushButton("➕ Agregar carpeta…"); b.clicked.connect(self._carp_add); rb.addWidget(b)
        b = QPushButton("Quitar la seleccionada"); b.clicked.connect(self._carp_del); rb.addWidget(b)
        lay.addLayout(rb)
        tabs.addTab(w, "Carpetas")
        self._carp_refresh()

        # ---------------- Apps y límites (apps que Orbi no abre + cosas que no debe hacer)
        import restricciones as _rs
        self._rs = _rs
        self._apps_bl = _rs.limpiar_apps((cfg or {}).get("apps_bloqueadas"))
        self._no_hacer = _rs.limpiar_reglas((cfg or {}).get("no_hacer"))
        w = QWidget(); lay = QVBoxLayout(w)
        info = QLabel("<b>Apps que Orbi no debe abrir.</b> Para él es como si no estuvieran instaladas: no salen en su lista de apps, "
                      "«abrir» le contesta que no la encontró y tiene prohibido usarlas por otro camino (menú Inicio, barra de tareas…). "
                      "El bloqueo de «abrir app» es firme; el resto depende de que la IA obedezca.")
        info.setWordWrap(True); info.setTextFormat(Qt.RichText)
        self.apps_list = QListWidget()
        self.apps_list.setMaximumHeight(130)
        lay.addWidget(info); lay.addWidget(self.apps_list)
        rb = QHBoxLayout()
        b = QPushButton("➕ Agregar app…"); b.clicked.connect(self._apps_add); rb.addWidget(b)
        b = QPushButton("Quitar la seleccionada"); b.clicked.connect(self._apps_del); rb.addWidget(b)
        lay.addLayout(rb)
        info2 = QLabel("<b>Cosas que Orbi no debe hacer.</b> Frases con tus propias palabras, por ejemplo: «no mandes mensajes a mi mamá», "
                       "«no cambies el volumen de noche», «no cierres ventanas sin avisarme». Orbi las toma como límites que mandan sobre "
                       "cualquier otra instrucción, pero son indicaciones para la IA, no un candado: para lo grave (pagos, borrar, enviar) "
                       "usa también la pestaña Permisos.")
        info2.setWordWrap(True); info2.setTextFormat(Qt.RichText)
        self.nh_list = QListWidget()
        lay.addWidget(info2); lay.addWidget(self.nh_list, 1)
        rb = QHBoxLayout()
        b = QPushButton("➕ Agregar…"); b.clicked.connect(self._nh_add); rb.addWidget(b)
        b = QPushButton("Editar"); b.clicked.connect(self._nh_edit); rb.addWidget(b)
        b = QPushButton("Quitar la seleccionada"); b.clicked.connect(self._nh_del); rb.addWidget(b)
        lay.addLayout(rb)
        nota = QLabel("Los cambios se aplican al pulsar «Aplicar». Solo se editan desde esta ventana: Orbi no puede quitarse un límite por su cuenta.")
        nota.setWordWrap(True); nota.setObjectName("nota")
        lay.addWidget(nota)
        tabs.addTab(w, "Apps y límites")
        self._apps_refresh(); self._nh_refresh()

        # ---------------- Funciones (lo que antes estaba en el clic derecho de Orbi)
        items = (extras or {}).get("items") or []
        ocultar = ("Ajustes", "Cuenta de Google", "Mini ventana:", "Abrir mi memoria")        # ya tienen su propia pestaña
        self._fn_checks = []
        fns = [it for it in items if not str(it.get("text", "")).startswith(ocultar)]
        if fns:
            w = QWidget(); lay = QVBoxLayout(w)
            info = QLabel("Todo lo que Orbi sabe hacer y se puede prender o apagar. Las casillas aplican al momento.")
            info.setWordWrap(True); info.setObjectName("nota")
            lay.addWidget(info)
            for it in fns:
                if it.get("checkable"):
                    cb = QCheckBox(it["text"])
                    try:
                        cb.setChecked(bool(it["checked"]()) if it.get("checked") else False)
                    except Exception:  # noqa: BLE001
                        pass
                    cb.clicked.connect(lambda _=False, it=it: self._fn_run(it))
                    lay.addWidget(cb); self._fn_checks.append((cb, it))
                else:
                    b = QPushButton(it["text"]); b.clicked.connect(lambda _=False, it=it: self._fn_run(it)); lay.addWidget(b)
            lay.addStretch(1)
            tabs.addTab(_scroll(w), "Funciones")

        # ---------------- Cuentas y conectores (correo de varias cuentas + Google)
        if hub is not None:
            try:
                from ajustes_cuentas import CuentasTab
                tabs.addTab(CuentasTab(hub, extras), "Cuentas y conectores")
            except Exception as e:  # noqa: BLE001
                print(f"[ajustes] no pude cargar «Cuentas y conectores»: {type(e).__name__}: {e}")

        # ---------------- Conexiones (puente MCP: Canva, Lucidchart, Figma)
        try:
            from ajustes_mcp import ConexionesTab
            tabs.addTab(ConexionesTab(on_skills_changed), "Conexiones")
        except Exception as e:  # noqa: BLE001
            print(f"[ajustes] no pude cargar «Conexiones»: {type(e).__name__}: {e}")

        # ---------------- Rutinas y alarmas (ver / agregar / editar / borrar a mano: rutinas, alarmas, recordatorios, timers)
        if alarms is not None or reglas is not None:
            try:
                from ajustes_pendientes import PendientesTab
                tabs.addTab(PendientesTab(alarms, reglas, on_change=on_pendientes_change), "Rutinas y alarmas")
            except Exception as e:  # noqa: BLE001
                print(f"[ajustes] no pude cargar «Rutinas y alarmas»: {type(e).__name__}: {e}")

        # ---------------- Skills y plugins
        self._sk, self._sk_changed = skills_mod, on_skills_changed or (lambda: None)
        if self._sk is not None:
            try:
                from ajustes_skills import SkillsTab
                tabs.addTab(SkillsTab(self._sk, self._sk_changed), "Skills y plugins")
            except Exception as e:  # noqa: BLE001
                print(f"[ajustes] no pude cargar «Skills y plugins»: {type(e).__name__}: {e}")

        bb = QHBoxLayout(); bb.addStretch(1)
        ap = QPushButton("Aplicar"); ap.setDefault(True); ap.clicked.connect(self._aplicar)
        ce = QPushButton("Cerrar"); ce.clicked.connect(self.close)
        bb.addWidget(ap); bb.addWidget(ce)
        lay = QVBoxLayout(self); lay.addWidget(tabs); lay.addLayout(bb)

    # ---- audio
    def _au_llenar(self, nombres):
        sel = self.au_dev.currentData() if self.au_dev.count() else self._au_actual
        self.au_dev.blockSignals(True)
        self.au_dev.clear()
        self.au_dev.addItem("Predeterminado de Windows (recomendado)", "")
        for n in nombres:
            self.au_dev.addItem(n, n)
        if sel and self.au_dev.findData(sel) < 0:
            self.au_dev.addItem(f"{sel} (no conectado)", sel)
        self.au_dev.setCurrentIndex(max(0, self.au_dev.findData(sel or "")))
        self.au_dev.blockSignals(False)

    def _au_refrescar(self):
        import threading
        import audio_devs
        bg = self._au_bg
        threading.Thread(target=lambda: bg.lista.emit(audio_devs.list_outputs(fresh=True)), daemon=True).start()

    def _au_tick(self):
        if self.isVisible() and getattr(self, "_tabs", None) is not None and self._tabs.currentIndex() == self._au_tab:
            self._au_refrescar()

    # ---- calendarios
    def _cal_refresh(self):
        self.cal_list.clear()
        for n, u in self._cal.items():
            it = QListWidgetItem(f"📅 {n} — {str(u)[:38]}…")
            it.setData(Qt.UserRole, n)
            self.cal_list.addItem(it)
        if not self._cal:
            self.cal_list.addItem("(no hay calendarios: usa «Agregar calendario…»)")

    def _cal_add(self):
        d = _CalendarioDialog(self)
        if d.exec():
            n, u = d.resultado
            self._cal[n] = u
            self._cal_refresh()
            QMessageBox.information(self, "Calendarios", "Listo. Pulsa «Aplicar» para guardarlo y reinicia Orbi para que lo use.")

    def _cal_del(self):
        it = self.cal_list.currentItem()
        n = it.data(Qt.UserRole) if it else None
        if n and QMessageBox.question(self, "Quitar", f"¿Quitar el calendario «{n}»?") == QMessageBox.Yes:
            self._cal.pop(n, None)
            self._cal_refresh()

    # ---- funciones (antes en el clic derecho)
    def _fn_run(self, it):
        try:
            it["cb"]()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Ajustes", f"{type(e).__name__}: {str(e)[:200]}")
        QTimer.singleShot(400, self._fn_refrescar)

    def _fn_refrescar(self):
        for cb, it in self._fn_checks:
            try:
                if it.get("checked"):
                    cb.setChecked(bool(it["checked"]()))
            except Exception:  # noqa: BLE001
                pass

    def _warn(self):
        self.aviso.setText("⚠ Orbi podrá enviar, pagar o borrar sin avisarte. Úsalo solo si confías en lo que le pides."
                           if self.c_del.currentData() == "permitir" else "")

    def _olvidar(self):
        if QMessageBox.question(self, "Olvidar memoria", "¿Borrar los resúmenes de conversaciones que Orbi guardó?\n"
                                "(Las notas que te pidió recordar no se tocan.)") == QMessageBox.Yes:
            self._clear()

    # ---- historial de notificaciones
    def _hist_refresh(self):
        self.n_hist.clear()
        try:
            import notifications as _nt
            items = _nt.HISTORIAL.ver("", 30)
        except Exception:                                    # noqa: BLE001
            items = []
        for i in items:
            self.n_hist.addItem(_nt.Historial.linea(i)[:140])
        if not items:
            self.n_hist.addItem("(vacío: aquí aparecen las notificaciones que Orbi ya te dijo o descartó)")

    def _hist_vaciar(self):
        if QMessageBox.question(self, "Historial", "¿Borrar el historial de notificaciones leídas y descartadas?") == QMessageBox.Yes:
            try:
                import notifications as _nt
                _nt.HISTORIAL.vaciar()
            except Exception:                                # noqa: BLE001
                pass
            self._hist_refresh()

    # ---- avisos de eventos
    def _av_antes(self) -> list:
        import avisos_cal as _ac
        marcados = [m for m, cb in self.av_chk.items() if cb.isChecked()]
        return sorted(set(marcados) | set(_ac.parse_lista(self.av_otros.text())), reverse=True)[:_ac.MAX_AVISOS]

    # ---- carpetas extra
    def _carp_refresh(self):
        self.carp_list.clear()
        for r in self._carp:
            p, motivo = self._dr.validar_dir(r)
            it = QListWidgetItem(f"📁 {p}" if p else f"⚠ {r} — {motivo}")
            it.setData(Qt.UserRole, r)
            self.carp_list.addItem(it)
        if not self._carp:
            self.carp_list.addItem("(todavía no agregaste ninguna)")

    def _carp_add(self):
        d = QFileDialog.getExistingDirectory(self, "Elegir una carpeta a la que Orbi pueda entrar")
        if not d:
            return
        p, motivo = self._dr.validar_dir(d)
        if p is None:
            QMessageBox.warning(self, "Carpetas", motivo)
            return
        if str(p) in [str(self._dr.validar_dir(r)[0]) for r in self._carp]:
            QMessageBox.information(self, "Carpetas", "Esa carpeta ya está en la lista.")
            return
        if self._dr.inside_roots(p):
            QMessageBox.information(self, "Carpetas", "Esa carpeta ya está dentro de una que Orbi puede ver; no hace falta agregarla.")
            return
        self._carp.append(str(p))
        self._carp_refresh()

    def _carp_del(self):
        it = self.carp_list.currentItem()
        r = it.data(Qt.UserRole) if it else None
        if r in self._carp:
            self._carp.remove(r)
            self._carp_refresh()

    # ---- apps bloqueadas y cosas que no hacer
    def _apps_refresh(self):
        self.apps_list.clear()
        for a in self._apps_bl:
            it = QListWidgetItem(f"🚫 {a}")
            it.setData(Qt.UserRole, a)
            self.apps_list.addItem(it)
        if not self._apps_bl:
            self.apps_list.addItem("(ninguna: Orbi puede abrir cualquier app instalada)")

    def _apps_add(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            opciones = self._rs.apps_instaladas()
        finally:
            QApplication.restoreOverrideCursor()
        nombre, ok = QInputDialog.getItem(self, "Apps y límites", "Elige una app de la lista o escribe su nombre (ej. discord, spotify, chrome):",
                                          opciones, 0, True)
        nombre = (nombre or "").strip()
        if not ok or not nombre:
            return
        if self._rs.norm(nombre) in [self._rs.norm(x) for x in self._apps_bl]:
            QMessageBox.information(self, "Apps y límites", "Esa app ya está en la lista.")
            return
        if len(self._apps_bl) >= self._rs.MAX_APPS:
            QMessageBox.warning(self, "Apps y límites", f"Máximo {self._rs.MAX_APPS} apps.")
            return
        self._apps_bl = self._rs.limpiar_apps(self._apps_bl + [nombre])
        self._apps_refresh()

    def _apps_del(self):
        it = self.apps_list.currentItem()
        a = it.data(Qt.UserRole) if it else None
        if a in self._apps_bl:
            self._apps_bl.remove(a)
            self._apps_refresh()

    def _nh_refresh(self):
        self.nh_list.clear()
        for r in self._no_hacer:
            it = QListWidgetItem(f"⛔ {r}")
            it.setData(Qt.UserRole, r)
            it.setToolTip(r)
            self.nh_list.addItem(it)
        if not self._no_hacer:
            self.nh_list.addItem("(todavía no agregaste ninguna)")

    def _nh_pedir(self, actual: str = ""):
        txt, ok = QInputDialog.getText(self, "Apps y límites", "Orbi NO debe… (una frase, con tus palabras):", QLineEdit.Normal, actual)
        txt = " ".join((txt or "").split())
        if not ok or not txt:
            return None
        if len(txt) > self._rs.MAX_LARGO_REGLA:
            QMessageBox.warning(self, "Apps y límites", f"Máximo {self._rs.MAX_LARGO_REGLA} caracteres: sepárala en dos frases.")
            return None
        return txt

    def _nh_add(self):
        if len(self._no_hacer) >= self._rs.MAX_REGLAS:
            QMessageBox.warning(self, "Apps y límites", f"Máximo {self._rs.MAX_REGLAS} límites.")
            return
        txt = self._nh_pedir()
        if txt:
            self._no_hacer = self._rs.limpiar_reglas(self._no_hacer + [txt])
            self._nh_refresh()

    def _nh_edit(self):
        it = self.nh_list.currentItem()
        r = it.data(Qt.UserRole) if it else None
        if r not in self._no_hacer:
            return
        txt = self._nh_pedir(r)
        if txt:
            self._no_hacer[self._no_hacer.index(r)] = txt
            self._no_hacer = self._rs.limpiar_reglas(self._no_hacer)
            self._nh_refresh()

    def _nh_del(self):
        it = self.nh_list.currentItem()
        r = it.data(Qt.UserRole) if it else None
        if r in self._no_hacer:
            self._no_hacer.remove(r)
            self._nh_refresh()

    def collect(self) -> dict:
        mini = {"modo": self.m_modo.currentData(), "tam": self.m_tam.currentData(), "esquina": self.m_esq.currentData(),
                "ubicacion": self.m_ubi.currentData(), "proximo_min": self.m_prox.currentData(),
                "opacidad": self.m_op.value(), "secciones": {k: cb.isChecked() for k, cb in self.m_sec.items()}, "pos": self._mini_pos}
        modo_d = self.c_del.currentData()
        config = {"live_voice": self.g_voz.currentData(), "headphones": self.g_aud.isChecked(),
                  "orb_scale": round(self.g_esc.value() / 100.0, 2), "sleep_after_s": self.g_dorm.currentData(),
                  "seguimiento_s": self.g_seg.currentData(), "fin_sensibilidad": self.g_fin.currentData(),
                  "observer_autostart": self.g_comp.isChecked(),
                  "companero": {"revisar_cada_s": self.g_rev.value(), "max_por_hora": self.g_tope.value(),
                                "pausa_tras_comentario_s": self.g_pausa.value()},
                  "esquivar_al_trabajar": self.g_esq.isChecked(), "preferir_mouse": self.g_mouse.isChecked(),
                  "ocultar_orbi_en_capturas": self.g_ocul.isChecked(), "busqueda_web": self.g_web.isChecked(),
                  "unidades_externas": self.g_ext.isChecked(), "calendarios": dict(self._cal), "carpetas_extra": list(self._carp),
                  "apps_bloqueadas": list(self._apps_bl), "no_hacer": list(self._no_hacer),
                  "avisos_calendario": {"activo": self.av_activo.isChecked(), "voz": self.av_voz.isChecked(),
                                        "antes_min": self._av_antes()},
                  "correo_avisos": {"activo": self.c_aviso.isChecked(), "cada_s": self.c_cada.value(), "voz": self.c_voz.isChecked(),
                                    "solo_importantes": self.c_imp.isChecked()},
                  "mic_umbral": round(0.30 - 0.0026 * self.au_mic.value(), 3), "volumen_voz": round(self.au_vol.value() / 100.0, 2),
                  "salida_audio": self.au_dev.currentData() or "", "volumen_alarmas": round(self.au_alm.value() / 100.0, 2),
                  "notificaciones": {"autostart": self.n_auto.isChecked(),
                                     "categorias": [k for k, cb in self.n_cat.items() if cb.isChecked()],
                                     "vip": [x.strip() for x in self.n_vip.text().split(",") if x.strip()],
                                     "horas_silencio": [self.n_ini.time().toString("HH:mm"), self.n_fin.time().toString("HH:mm")]
                                     if self.n_sil.isChecked() else [],
                                     "leer_contenido": self.n_leer.isChecked(),
                                     "historial_horas": self.n_hist_h.currentData()}}
        return {"config": config, "permisos": {"modo_delicadas": modo_d, "modo_normales": self.c_nor.currentData(),
                             "confirmar_acciones": modo_d != "permitir"},       # compatibilidad con el asistente de configuración
                "ajustes": {"mini": mini, "internet_lento": self.i_lento.currentData(), "busqueda_navegador": self.i_nav.isChecked(),
                            "memoria_larga": self.mem.isChecked(), "alarma_tono": self.a_tono.currentData(),
                            "tema": self.t_tema.currentData(), "idioma_oido": self.au_idioma.currentData()}}

    def _tema_desc(self) -> None:
        self.t_desc.setText(temas.get(self.t_tema.currentData()).desc)

    def _tema_vista_previa(self) -> None:
        temas.cambiar(self.t_tema.currentData())          # se ve ya mismo en toda la app (si no aplicas, se revierte al cerrar)
        self._tema_desc()

    def done(self, r):
        if self.t_tema.currentData() != self._tema_aplicado:
            temas.cambiar(self._tema_aplicado)            # cerraste sin «Aplicar»: vuelve el tema de antes
        super().done(r)

    def _aplicar(self):
        self._tema_aplicado = self.t_tema.currentData()
        try:                                                  # el historial de notificaciones cambia al momento, sin reiniciar
            import notifications as _nt
            _nt.configurar_historial({"historial_horas": self.n_hist_h.currentData(), "historial_max": _nt.HISTORIAL.max})
        except Exception:                                     # noqa: BLE001
            pass
        self._apply(self.collect())
