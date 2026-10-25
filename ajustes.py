"""Ventana de Ajustes de Orbi (distinta del asistente de configuración inicial).

Se abre desde el menú de la bolita («Ajustes…») o desde el clic derecho de la mini ventana. Guarda al pulsar «Aplicar».

  Permisos      · cosas DELICADAS (enviar, pagar, borrar…): preguntar / automático / permitir todo
                · cosas NO delicadas (clics, escribir, teclas): permitir / automático / preguntar siempre
  Mini ventana  · mostrar (siempre / solo si hay algo / oculta), tamaño, opacidad, esquina y qué secciones lleva
  Internet      · paciencia con redes lentas, navegador como último recurso
  Memoria       · resumir conversaciones para recordarlas, olvidar lo guardado
  Alarmas       · tono (con botón de prueba)
  General       · lo de config.json que tiene sentido para un usuario normal (voz, tamaño de la bolita, cuándo se duerme,
                  modo compañero, notificaciones, privacidad). Se guarda en orbi_config_ventana.json y manda sobre config.json;
                  casi todo se aplica al reiniciar Orbi.
"""
from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

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


class AjustesDialog(QDialog):
    def __init__(self, profile: dict, tonos: list, apply, test_tone, clear_memory, mini_defaults: dict, cfg: dict | None = None,
                 open_memory=None, skills_mod=None, on_skills_changed=None, parent=None):
        """apply({"permisos": {...}, "ajustes": {...}}) guarda y aplica · test_tone(nombre) · clear_memory() -> None."""
        super().__init__(parent)
        self.setWindowTitle("Ajustes de Orbi")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setMinimumWidth(560)
        self._apply, self._test, self._clear = apply, test_tone, clear_memory
        perm = profile.get("permisos") or {}
        aj = profile.get("ajustes") or {}
        mini = {**mini_defaults, **(aj.get("mini") or {})}
        mini["secciones"] = {**mini_defaults.get("secciones", {}), **((aj.get("mini") or {}).get("secciones") or {})}
        self._mini_pos = mini.get("pos")

        tabs = QTabWidget()
        # ---------------- Permisos
        w = QWidget(); f = _form(w)
        modo_d = perm.get("modo_delicadas") or ("preguntar" if perm.get("confirmar_acciones", True) else "permitir")
        self.c_del = _combo(DELICADAS, modo_d)
        self.c_nor = _combo(NORMALES, perm.get("modo_normales", "permitir"))
        f.addRow("Cosas delicadas (enviar mensajes, pagar, borrar):", self.c_del)
        self.aviso = QLabel(); self.aviso.setWordWrap(True); self.aviso.setStyleSheet("color:#c0392b;")
        f.addRow("", self.aviso)
        f.addRow("Cosas no delicadas (clics, escribir, teclas):", self.c_nor)
        nota = QLabel("Enviar un correo desde tu Gmail siempre pide tu OK, sin importar el modo (un correo podría intentar engañar a la IA).")
        nota.setWordWrap(True); nota.setStyleSheet("color:#7f8c8d;")
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
        nota_m.setWordWrap(True); nota_m.setStyleSheet("color:#7f8c8d;")
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
        reinicio.setWordWrap(True); reinicio.setStyleSheet("color:#7f8c8d;")
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
        nn = QLabel("Las notificaciones también necesitan el permiso «notificaciones» en la configuración inicial de Orbi.")
        nn.setWordWrap(True); nn.setStyleSheet("color:#7f8c8d;"); f.addRow("", nn)
        tabs.addTab(_scroll(w), "Notificaciones")

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

        # ---------------- Skills y plugins
        self._sk, self._sk_changed = skills_mod, on_skills_changed or (lambda: None)
        if self._sk is not None:
            w = QWidget(); lay = QVBoxLayout(w)
            info = QLabel("<b>Skills</b>: instrucciones que Orbi carga cuando encajan con lo que pides (no ejecutan código).<br>"
                          "<b>Plugins</b>: herramientas nuevas hechas con código de Python. Solo instala los de gente de confianza: "
                          "nacen desactivados y cada uso te pide permiso.<br>Orbi también puede buscar skills por ti en GitHub "
                          "(dile «busca una skill para…»); siempre te pide tu OK antes de instalar.")
            info.setWordWrap(True); info.setTextFormat(Qt.RichText)
            self.sk_list = QListWidget()
            self.sk_list.itemChanged.connect(self._sk_toggle)
            lay.addWidget(info); lay.addWidget(self.sk_list, 1)
            for txt, fn in (("Instalar desde GitHub o enlace…", self._sk_install_url), ("Instalar desde un .zip…", self._sk_install_zip),
                            ("Instalar desde una carpeta…", self._sk_install_dir), ("Quitar la seleccionada", self._sk_remove),
                            ("Abrir la carpeta de skills", self._sk.open_folder)):
                b = QPushButton(txt); b.clicked.connect(fn); lay.addWidget(b)
            tabs.addTab(w, "Skills y plugins")
            self._sk_refresh()

        bb = QHBoxLayout(); bb.addStretch(1)
        ap = QPushButton("Aplicar"); ap.setDefault(True); ap.clicked.connect(self._aplicar)
        ce = QPushButton("Cerrar"); ce.clicked.connect(self.close)
        bb.addWidget(ap); bb.addWidget(ce)
        lay = QVBoxLayout(self); lay.addWidget(tabs); lay.addLayout(bb)

    # ---- skills y plugins
    def _sk_refresh(self):
        self.sk_list.blockSignals(True)
        self.sk_list.clear()
        for s in self._sk.scan():
            it = QListWidgetItem(f"{'🧩 Plugin' if s['kind'] == 'plugin' else '📘 Skill'} · {s['name']} — {s['desc'][:80]}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if s["enabled"] else Qt.Unchecked)
            it.setData(Qt.UserRole, (s["name"], s["kind"]))
            self.sk_list.addItem(it)
        if self.sk_list.count() == 0:
            self.sk_list.addItem("(todavía no hay nada instalado)")
        self.sk_list.blockSignals(False)

    def _sk_toggle(self, item):
        d = item.data(Qt.UserRole)
        if not d:
            return
        name, kind = d
        on = item.checkState() == Qt.Checked
        if on and kind == "plugin" and QMessageBox.warning(
                self, "Activar plugin", f"«{name}» es código de Python que se ejecuta en tu PC con tus permisos.\n"
                "Actívalo solo si confías en quien lo hizo y revisaste su plugin.py.\n\nCada vez que se use, Orbi te pedirá permiso.\n\n¿Activarlo?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            self.sk_list.blockSignals(True); item.setCheckState(Qt.Unchecked); self.sk_list.blockSignals(False)
            return
        self._sk.set_enabled(name, on)
        self._sk_changed()

    def _sk_instalar(self, fn):
        """fn(allow_code) -> resultado. Primero sin código; si trae plugins, avisa y pregunta."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = fn(False)
        finally:
            QApplication.restoreOverrideCursor()
        if res.get("plugins_no_instalados") and QMessageBox.warning(
                self, "Plugin con código",
                "Este paquete trae plugin(s): " + ", ".join(res["plugins_no_instalados"]) + ".\n\nUn plugin ejecuta código de Python en tu PC. "
                "Instálalo solo si confías en la fuente. Se instalará DESACTIVADO.\n\n¿Instalarlo de todos modos?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                res = fn(True)
            finally:
                QApplication.restoreOverrideCursor()
        if res.get("error"):
            QMessageBox.warning(self, "Skills y plugins", res["error"])
        else:
            QMessageBox.information(self, "Skills y plugins", "Instalado: " + (", ".join(res.get("instaladas", [])) or "nada nuevo"))
            self._sk_changed()
        self._sk_refresh()

    def _sk_install_url(self):
        url, ok = QInputDialog.getText(self, "Instalar desde internet", "Enlace de GitHub, .zip o SKILL.md (https):")
        if ok and url.strip():
            self._sk_instalar(lambda code: self._sk.install_url(url.strip(), allow_code=code))

    def _sk_install_zip(self):
        p, _f = QFileDialog.getOpenFileName(self, "Elegir paquete", "", "Paquetes (*.zip)")
        if p:
            self._sk_instalar(lambda code: self._sk.install_zip(p, f"zip local: {p}", allow_code=code))

    def _sk_install_dir(self):
        p = QFileDialog.getExistingDirectory(self, "Elegir carpeta con skills o plugins")
        if p:
            self._sk_instalar(lambda code: self._sk.install_folder(p, allow_code=code))

    def _sk_remove(self):
        it = self.sk_list.currentItem()
        d = it.data(Qt.UserRole) if it else None
        if d and QMessageBox.question(self, "Quitar", f"¿Quitar «{d[0]}» de Orbi?") == QMessageBox.Yes:
            self._sk.remove(d[0]); self._sk_changed(); self._sk_refresh()

    def _warn(self):
        self.aviso.setText("⚠ Orbi podrá enviar, pagar o borrar sin avisarte. Úsalo solo si confías en lo que le pides."
                           if self.c_del.currentData() == "permitir" else "")

    def _olvidar(self):
        if QMessageBox.question(self, "Olvidar memoria", "¿Borrar los resúmenes de conversaciones que Orbi guardó?\n"
                                "(Las notas que te pidió recordar no se tocan.)") == QMessageBox.Yes:
            self._clear()

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
                  "unidades_externas": self.g_ext.isChecked(),
                  "notificaciones": {"autostart": self.n_auto.isChecked(),
                                     "categorias": [k for k, cb in self.n_cat.items() if cb.isChecked()],
                                     "vip": [x.strip() for x in self.n_vip.text().split(",") if x.strip()],
                                     "horas_silencio": [self.n_ini.time().toString("HH:mm"), self.n_fin.time().toString("HH:mm")]
                                     if self.n_sil.isChecked() else [],
                                     "leer_contenido": self.n_leer.isChecked()}}
        return {"config": config, "permisos": {"modo_delicadas": modo_d, "modo_normales": self.c_nor.currentData(),
                             "confirmar_acciones": modo_d != "permitir"},       # compatibilidad con el asistente de configuración
                "ajustes": {"mini": mini, "internet_lento": self.i_lento.currentData(), "busqueda_navegador": self.i_nav.isChecked(),
                            "memoria_larga": self.mem.isChecked(), "alarma_tono": self.a_tono.currentData()}}

    def _aplicar(self):
        self._apply(self.collect())
