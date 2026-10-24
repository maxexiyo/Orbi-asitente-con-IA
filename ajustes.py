"""Ventana de Ajustes de Orbi (distinta del asistente de configuración inicial).

Se abre desde el menú de la bolita («Ajustes…») o desde el clic derecho de la mini ventana. Guarda al pulsar «Aplicar».

  Permisos      · cosas DELICADAS (enviar, pagar, borrar…): preguntar / automático / permitir todo
                · cosas NO delicadas (clics, escribir, teclas): permitir / automático / preguntar siempre
  Mini ventana  · mostrar (siempre / solo si hay algo / oculta), tamaño, opacidad, esquina y qué secciones lleva
  Internet      · paciencia con redes lentas, navegador como último recurso
  Memoria       · resumir conversaciones para recordarlas, olvidar lo guardado
  Alarmas       · tono (con botón de prueba)
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QSlider, QTabWidget, QVBoxLayout, QWidget)

DELICADAS = [("preguntar", "Preguntarme siempre (recomendado)"),
             ("auto", "Automático: solo pregunta lo más grave (pagos, borrar, correos, cocheras)"),
             ("permitir", "Permitir todo sin preguntar")]
NORMALES = [("permitir", "Permitir sin preguntar (normal)"),
            ("auto", "Automático: pregunta solo en terminal, registro, configuración…"),
            ("preguntar", "Preguntarme antes de cada acción")]
MINI_MODO = [("con_datos", "Solo cuando hay algo que mostrar"), ("siempre", "Siempre visible"), ("oculta", "Oculta")]
MINI_TAM = [("compacta", "Compacta"), ("media", "Media"), ("grande", "Grande (con más datos e imagen)")]
ESQUINAS = [("inferior_derecha", "Abajo a la derecha"), ("inferior_izquierda", "Abajo a la izquierda"),
            ("superior_derecha", "Arriba a la derecha"), ("superior_izquierda", "Arriba a la izquierda")]
INTERNET = [("auto", "Automático (se adapta a la velocidad)"), ("si", "Mi internet es lento: más paciencia"), ("no", "Mi internet es rápido")]
UBICACION = [("junto_a_orbi", "A un lado de Orbi (me sigue)"), ("esquina", "Fija en una esquina de la pantalla")]
PROXIMO = [15, 30, 60, 120, 240]
SECCIONES = [("calendario", "Calendario"), ("alarmas", "Alarmas"), ("recordatorios", "Recordatorios"),
             ("timers", "Timers (cuenta regresiva)"), ("busquedas", "Resúmenes de búsquedas web con imagen"),
             ("avisos", "Avisos: notificaciones, reglas, listas que pediste"), ("tarea", "Lo que Orbi hace en tu PC (paso a paso)")]


def _form(widget):
    """Formulario con la etiqueta ENCIMA del campo: con opciones largas, la columna de etiquetas se encogía a 0 de ancho."""
    f = QFormLayout(widget)
    f.setRowWrapPolicy(QFormLayout.WrapAllRows)
    f.setVerticalSpacing(8)
    return f


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
    def __init__(self, profile: dict, tonos: list, apply, test_tone, clear_memory, mini_defaults: dict, parent=None):
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
        self.m_op = QSlider(Qt.Horizontal); self.m_op.setRange(30, 100); self.m_op.setValue(int(mini["opacidad"]))
        f.addRow("Mostrar:", self.m_modo); f.addRow("Dónde aparece:", self.m_ubi); f.addRow("Tamaño:", self.m_tam)
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
        tabs.addTab(w, "Internet y memoria")

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

        bb = QHBoxLayout(); bb.addStretch(1)
        ap = QPushButton("Aplicar"); ap.setDefault(True); ap.clicked.connect(self._aplicar)
        ce = QPushButton("Cerrar"); ce.clicked.connect(self.close)
        bb.addWidget(ap); bb.addWidget(ce)
        lay = QVBoxLayout(self); lay.addWidget(tabs); lay.addLayout(bb)

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
        return {"permisos": {"modo_delicadas": modo_d, "modo_normales": self.c_nor.currentData(),
                             "confirmar_acciones": modo_d != "permitir"},       # compatibilidad con el asistente de configuración
                "ajustes": {"mini": mini, "internet_lento": self.i_lento.currentData(), "busqueda_navegador": self.i_nav.isChecked(),
                            "memoria_larga": self.mem.isChecked(), "alarma_tono": self.a_tono.currentData()}}

    def _aplicar(self):
        self._apply(self.collect())
