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
from PySide6.QtCore import QObject, QTime, QTimer, Qt, Signal, Slot
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


class AjustesDialog(QDialog):
    def __init__(self, profile: dict, tonos: list, apply, test_tone, clear_memory, mini_defaults: dict, cfg: dict | None = None,
                 open_memory=None, skills_mod=None, on_skills_changed=None, extras=None, hub=None, parent=None):
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

        # ---------------- Audio (micrófono, volumen y bocina)
        cfg = cfg or {}
        w = QWidget(); f = _form(w)
        u = float(cfg.get("mic_umbral", 0.15) or 0.15)
        self.au_mic = QSlider(Qt.Horizontal); self.au_mic.setRange(0, 100)
        self.au_mic.setValue(max(0, min(100, round((0.30 - u) / 0.0026))))
        nota_mic = QLabel("Más a la derecha = el micrófono capta voces más bajitas (pero también más ruido). Si Orbi se activa solo, bájalo; "
                          "si no te oye, súbelo. Se aplica al momento.")
        nota_mic.setWordWrap(True); nota_mic.setStyleSheet("color:#7f8c8d;")
        f.addRow("Sensibilidad del micrófono:", self.au_mic); f.addRow("", nota_mic)
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
        self.au_nota.setWordWrap(True); self.au_nota.setStyleSheet("color:#7f8c8d;")
        f.addRow("", self.au_nota)
        self.au_alm = QSlider(Qt.Horizontal); self.au_alm.setRange(10, 150)
        self.au_alm.setValue(max(10, min(150, round(float(cfg.get("volumen_alarmas", 1.0) or 1.0) * 100))))
        self.au_alm_txt = QLabel(f"{self.au_alm.value()}%")
        self.au_alm.valueChanged.connect(lambda v: self.au_alm_txt.setText(f"{v}%"))
        ar = QHBoxLayout(); ar.addWidget(self.au_alm, 1); ar.addWidget(self.au_alm_txt)
        f.addRow("Volumen de las alarmas:", ar)
        pend = QLabel("Las alarmas suenan por la bocina predeterminada de Windows, y el tono «Clásico (pitidos)» no cambia de volumen. "
                      "Pulsa «Aplicar» y usa «▶ Probar» en la pestaña Alarmas para oírlo.")
        pend.setWordWrap(True); pend.setStyleSheet("color:#7f8c8d;")
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
        tabs.addTab(w, "Calendarios")
        self._cal_refresh()

        # ---------------- Funciones (lo que antes estaba en el clic derecho de Orbi)
        items = (extras or {}).get("items") or []
        ocultar = ("Ajustes", "Cuenta de Google", "Mini ventana:", "Abrir mi memoria")        # ya tienen su propia pestaña
        self._fn_checks = []
        fns = [it for it in items if not str(it.get("text", "")).startswith(ocultar)]
        if fns:
            w = QWidget(); lay = QVBoxLayout(w)
            info = QLabel("Todo lo que Orbi sabe hacer y se puede prender o apagar. Las casillas aplican al momento.")
            info.setWordWrap(True); info.setStyleSheet("color:#7f8c8d;")
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
                  "unidades_externas": self.g_ext.isChecked(), "calendarios": dict(self._cal),
                  "mic_umbral": round(0.30 - 0.0026 * self.au_mic.value(), 3), "volumen_voz": round(self.au_vol.value() / 100.0, 2),
                  "salida_audio": self.au_dev.currentData() or "", "volumen_alarmas": round(self.au_alm.value() / 100.0, 2),
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
