"""Asistente de primera vez de Orbi: te conoce y configura qué puede hacer.

run_onboarding(existing=None) -> perfil (dict) o None si lo cancelas.
Se abre solo la primera vez (cuando no existe orbi_profile.json) y desde el menú: "Configurar a Orbi…".
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWizard, QWizardPage, QVBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QRadioButton, QButtonGroup, QCheckBox)

from perfil import DEFAULT_PROFILE, PERMISOS_DEFAULT, TONOS, save_profile

STYLE = """
QWizard, QWizardPage { background: #101a36; color: #eaf2ff; font: 14px 'Segoe UI'; }
QLabel { color: #eaf2ff; }
QLabel#hint { color: #9db4e6; font-size: 12px; }
QLabel#title { font-size: 20px; font-weight: 600; }
QLineEdit, QPlainTextEdit { background: #18264d; color: #eaf2ff; border: 1px solid #3d5ba8;
                            border-radius: 10px; padding: 8px 10px; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #8cc8ff; }
QRadioButton, QCheckBox { color: #eaf2ff; padding: 4px 0; }
QPushButton { background: #2c4a9a; color: white; border: none; border-radius: 10px; padding: 8px 18px; }
QPushButton:hover { background: #3a5cb8; }
QPushButton:disabled { background: #22305c; color: #7384ad; }
"""

TONO_TEXTOS = {
    "casual": "Casual — como un cuate",
    "bromista": "Bromista — con humor",
    "formal": "Formal — educado y serio",
    "directo": "Directo — breve y sin rodeos",
}


def _title(text):
    l = QLabel(text); l.setObjectName("title"); l.setWordWrap(True); return l


def _hint(text):
    l = QLabel(text); l.setObjectName("hint"); l.setWordWrap(True); return l


class PageNombre(QWizardPage):
    def __init__(self, prof):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(_title("¡Hola! Soy Orbi 👋"))
        lay.addWidget(_hint("Antes de empezar quiero conocerte un poquito para saber cómo hablarte. "
                            "Todo se guarda solo en tu PC (orbi_profile.json) y lo puedes cambiar cuando quieras."))
        lay.addSpacing(8)
        lay.addWidget(QLabel("¿Cómo te llamas?"))
        self.nombre = QLineEdit(prof.get("nombre", "")); lay.addWidget(self.nombre)
        lay.addWidget(QLabel("¿Cómo prefieres que te diga? (apodo, opcional)"))
        self.apodo = QLineEdit(prof.get("apodo", "")); lay.addWidget(self.apodo)
        lay.addStretch()
        self.nombre.textChanged.connect(self.completeChanged)

    def isComplete(self):
        return bool(self.nombre.text().strip())


class PageTono(QWizardPage):
    def __init__(self, prof):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(_title("¿Cómo quieres que te hable?"))
        self.group, self.radios = QButtonGroup(self), {}
        actual = prof.get("tono", "casual")
        for key in TONOS:
            r = QRadioButton(TONO_TEXTOS.get(key, key))
            r.setChecked(key == actual)
            self.group.addButton(r); self.radios[key] = r; lay.addWidget(r)
        lay.addStretch()

    def tono(self):
        return next((k for k, r in self.radios.items() if r.isChecked()), "casual")


class PageSobreTi(QWizardPage):
    def __init__(self, prof):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(_title("Cuéntame de ti"))
        lay.addWidget(_hint("Todo es opcional; entre más sepa, mejor te ayudo. Evita poner contraseñas o datos sensibles."))
        lay.addWidget(QLabel("¿A qué te dedicas / qué estudias?"))
        self.ocupacion = QLineEdit(prof.get("ocupacion", "")); lay.addWidget(self.ocupacion)
        lay.addWidget(QLabel("¿Qué cosas te gustan o te interesan?"))
        self.intereses = QLineEdit(prof.get("intereses", "")); lay.addWidget(self.intereses)
        lay.addWidget(QLabel("¿Algo más que quieras que sepa de ti?"))
        self.sobre_mi = QPlainTextEdit(prof.get("sobre_mi", "")); self.sobre_mi.setFixedHeight(70)
        lay.addWidget(self.sobre_mi)
        lay.addWidget(QLabel("¿Para qué quieres que te ayude principalmente?"))
        self.quiere = QPlainTextEdit(prof.get("quiere_que_haga", "")); self.quiere.setFixedHeight(70)
        lay.addWidget(self.quiere)


ESCUCHA_TEXTOS = {
    "palabra": "Solo cuando diga «Orbi» (recomendado): no contesta si hablo solo o con otras personas",
    "atajo": "Solo cuando use el atajo Ctrl+Alt+Espacio",
    "siempre": "Siempre escuchando (contesta a todo lo que oiga)",
}


class PageEscucha(QWizardPage):
    def __init__(self, prof):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addWidget(_title("¿Cuándo quieres que te escuche?"))
        lay.addWidget(_hint("Así no me contesto cuando hablas solo, con tu familia o con la tele. En los dos primeros modos "
                            "tu voz NO sale de la PC hasta que me llamas."))
        self.group, self.radios = QButtonGroup(self), {}
        actual = prof.get("escucha_modo", "palabra")
        for key, text in ESCUCHA_TEXTOS.items():
            r = QRadioButton(text); r.setChecked(key == actual)
            self.group.addButton(r); self.radios[key] = r; lay.addWidget(r)
        lay.addSpacing(8)
        lay.addWidget(QLabel("Mi palabra de llamada:"))
        self.palabra = QLineEdit(prof.get("palabra_clave", "orbi")); lay.addWidget(self.palabra)
        lay.addWidget(_hint("La primera vez que uses la palabra clave se descarga un modelo de voz pequeño (~40 MB). "
                            "Una vez abierta la conversación, sigo escuchando unos 25 s sin que tengas que repetir mi nombre."))
        lay.addStretch()

    def modo(self):
        return next((k for k, r in self.radios.items() if r.isChecked()), "palabra")


class PagePermisos(QWizardPage):
    def __init__(self, prof):
        super().__init__()
        perm = {**PERMISOS_DEFAULT, **prof.get("permisos", {})}
        lay = QVBoxLayout(self)
        lay.addWidget(_title("¿Qué puedo hacer en tu PC?"))
        lay.addWidget(_hint("Tú decides. Puedes cambiar esto después desde «Configurar a Orbi…» en el menú."))
        self.ver = QCheckBox("Ver mi pantalla (cuando me lo pidas, o en modo continuo)")
        self.ver.setChecked(perm["ver_pantalla"])
        self.obs = QCheckBox("Modo compañero: mirar mi pantalla de vez en cuando y avisarme si noto algo útil")
        self.obs.setChecked(perm["observar"])
        self.ctrl = QCheckBox("Controlar la PC: mouse, teclado, escribir texto, volumen y música")
        self.ctrl.setChecked(perm["controlar_pc"])
        self.arch = QCheckBox("Buscar, leer, organizar y escribir archivos (y Word) en Documentos, Escritorio y Descargas")
        self.arch.setChecked(perm["archivos"])
        self.casa = QCheckBox("Controlar mi casa inteligente (luces, enchufes) vía Home Assistant")
        self.casa.setChecked(perm["casa"])
        self.notif = QCheckBox("Ver mis notificaciones de Windows y avisarme de las importantes")
        self.notif.setChecked(perm["notificaciones"])
        self.agenda = QCheckBox("Leer mi calendario y mi correo (solo lectura; configurado en config.json y .env)")
        self.agenda.setChecked(perm["agenda"])
        self.audio = QCheckBox("Escuchar el audio que suena en mi PC (videos, llamadas) cuando te lo pida")
        self.audio.setChecked(perm["audio_pc"])
        self.conf = QCheckBox("Preguntarme antes de acciones delicadas: enviar mensajes, pagar, borrar (recomendado)")
        self.conf.setChecked(perm["confirmar_acciones"])
        for w in (self.ver, self.obs, self.ctrl, self.arch, self.casa, self.notif, self.agenda, self.audio, self.conf):
            lay.addWidget(w)
        lay.addSpacing(6)
        lay.addWidget(_hint(
            "El modo compañero manda capturas a Gemini (no mira ventanas de bancos/contraseñas). "
            "Siempre puedo: decirte la hora, abrir apps de una lista segura, buscar en Google y anotar cosas tuyas. "
            "Nunca ejecuto comandos arbitrarios, ni borro archivos, ni abro programas ejecutables. "
            "Las acciones normales las hago sin molestarte; solo pregunto en las delicadas. "
            "Para parar el control en cualquier momento: menú de la bolita, o mueve el mouse a la esquina superior izquierda."))
        lay.addStretch()

    def permisos(self):
        return dict(ver_pantalla=self.ver.isChecked(), observar=self.obs.isChecked(), controlar_pc=self.ctrl.isChecked(),
                    archivos=self.arch.isChecked(), casa=self.casa.isChecked(),
                    notificaciones=self.notif.isChecked(), agenda=self.agenda.isChecked(), audio_pc=self.audio.isChecked(), confirmar_acciones=self.conf.isChecked())


class Wizard(QWizard):
    def __init__(self, existing=None):
        super().__init__()
        self.base = {**DEFAULT_PROFILE, **(existing or {})}
        self.setWindowTitle("Orbi — configuración")
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setStyleSheet(STYLE)
        self.setMinimumSize(640, 560)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setButtonText(QWizard.NextButton, "Siguiente")
        self.setButtonText(QWizard.BackButton, "Atrás")
        self.setButtonText(QWizard.CancelButton, "Cancelar")
        self.setButtonText(QWizard.FinishButton, "¡Listo!")
        self.p_nombre, self.p_tono = PageNombre(self.base), PageTono(self.base)
        self.p_sobre, self.p_perm = PageSobreTi(self.base), PagePermisos(self.base)
        self.p_escucha = PageEscucha(self.base)
        for p in (self.p_nombre, self.p_tono, self.p_sobre, self.p_escucha, self.p_perm):
            self.addPage(p)

    def result_profile(self) -> dict:
        prof = dict(self.base)
        prof.update(
            nombre=self.p_nombre.nombre.text().strip(),
            apodo=self.p_nombre.apodo.text().strip(),
            tono=self.p_tono.tono(),
            ocupacion=self.p_sobre.ocupacion.text().strip(),
            intereses=self.p_sobre.intereses.text().strip(),
            sobre_mi=self.p_sobre.sobre_mi.toPlainText().strip(),
            quiere_que_haga=self.p_sobre.quiere.toPlainText().strip(),
            permisos=self.p_perm.permisos(),
            escucha_modo=self.p_escucha.modo(),
            palabra_clave=(self.p_escucha.palabra.text().strip().lower() or "orbi"),
        )
        return prof


def run_onboarding(existing=None):
    """Muestra el asistente (bloquea hasta cerrarlo). Devuelve el perfil guardado o None si cancelaron."""
    w = Wizard(existing)
    if w.exec() != QWizard.Accepted:
        return None
    prof = w.result_profile()
    save_profile(prof)
    return prof
