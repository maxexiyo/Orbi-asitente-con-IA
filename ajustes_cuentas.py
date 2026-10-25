"""Pestaña «Cuentas y conectores» de la ventana de Ajustes: varias cuentas de correo (Gmail y Microsoft) y la cuenta de Google (calendario).

Las operaciones lentas (probar una cuenta, hablar con Microsoft) corren en un hilo para que la ventana no se congele.
"""
import threading
import webbrowser

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QMessageBox, QPushButton, QVBoxLayout, QWidget)

import correo_cuentas as cc

PROV = {"gmail": "Gmail", "microsoft": "Microsoft"}


class _Bg(QObject):
    """Corre una función en un hilo y entrega el resultado EN EL HILO DE LA VENTANA.
    (Antes el resultado se entregaba con un lambda: Qt lo ejecutaba en el hilo de fondo, tocaba la interfaz desde ahí y Orbi se
    congelaba o se cerraba sin dejar nada en el log. Un slot de un QObject creado en el hilo de la ventana va por cola, que es lo correcto.)"""
    listo = Signal(object)

    def __init__(self, owner, cb):
        super().__init__(owner)
        self._cb = cb
        self.listo.connect(self._recibir)

    @Slot(object)
    def _recibir(self, r):
        try:
            self._cb(r)
        finally:
            self.deleteLater()


def run_bg(owner: QWidget, fn, cb) -> None:
    bg = _Bg(owner, cb)

    def work():
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            r = (False, cc.CorreoHub.err(e))
        bg.listo.emit(r)
    threading.Thread(target=work, daemon=True).start()


# ====================================================================== Gmail
class GmailDialog(QDialog):
    def __init__(self, hub: "cc.CorreoHub", parent=None):
        super().__init__(parent)
        self.hub = hub
        self.setWindowTitle("Agregar cuenta de Gmail")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        info = QLabel("Gmail se conecta con una <b>contraseña de aplicación</b> (no es tu contraseña normal; sin Google Cloud):<br>"
                      "<b>1)</b> Activa la <b>verificación en dos pasos</b> (botón 1).<br>"
                      "<b>2)</b> En «Contraseñas de aplicaciones» escribe de nombre <i>Orbi</i> y pulsa <b>Crear</b> (botón 2). "
                      "Google te muestra un código de 16 letras: <b>cópialo</b>, solo se ve una vez.<br>"
                      "<b>3)</b> Pega aquí tu correo completo y ese código. Se guarda cifrado en esta PC.<br>"
                      "<span style='color:#7f8c8d'>Con este método Orbi puede ver todo el correo de esa cuenta. "
                      "Si es una cuenta de escuela o trabajo de Google, el administrador puede tener bloqueadas las contraseñas de aplicación.</span>")
        info.setWordWrap(True); info.setTextFormat(Qt.RichText); info.setOpenExternalLinks(True)
        lay.addWidget(info)
        bl = QHBoxLayout()
        b1 = QPushButton("1 · Activar verificación en dos pasos"); b1.clicked.connect(lambda: webbrowser.open("https://myaccount.google.com/signinoptions/two-step-verification"))
        b2 = QPushButton("2 · Crear contraseña de aplicación"); b2.clicked.connect(lambda: webbrowser.open("https://myaccount.google.com/apppasswords"))
        bl.addWidget(b1); bl.addWidget(b2)
        lay.addLayout(bl)
        f = QFormLayout()
        self.e_mail = QLineEdit(); self.e_mail.setPlaceholderText("tucorreo@gmail.com")
        self.e_pass = QLineEdit(); self.e_pass.setEchoMode(QLineEdit.Password); self.e_pass.setPlaceholderText("xxxx xxxx xxxx xxxx")
        self.e_alias = QLineEdit(); self.e_alias.setPlaceholderText("Nombre corto, ej. personal (opcional)")
        f.addRow("Correo:", self.e_mail); f.addRow("Contraseña de aplicación:", self.e_pass); f.addRow("Nombre:", self.e_alias)
        lay.addLayout(f)
        self.estado = QLabel(""); self.estado.setWordWrap(True)
        lay.addWidget(self.estado)
        row = QHBoxLayout(); row.addStretch(1)
        self.b_ok = QPushButton("Probar y guardar"); self.b_ok.setDefault(True); self.b_ok.clicked.connect(self._guardar)
        b_no = QPushButton("Cancelar"); b_no.clicked.connect(self.reject)
        row.addWidget(self.b_ok); row.addWidget(b_no)
        lay.addLayout(row)

    def _guardar(self):
        self.b_ok.setEnabled(False); self.estado.setText("Probando la conexión…")
        mail, pwd, alias = self.e_mail.text(), self.e_pass.text(), self.e_alias.text()
        run_bg(self, lambda: self.hub.add_gmail(alias, mail, pwd), self._fin)

    def _fin(self, r):
        ok, msg = r
        self.b_ok.setEnabled(True)
        self.estado.setText(msg)
        if ok:
            self.accept()


# ====================================================================== Microsoft
PASOS_MS = ("Microsoft ya <b>no acepta contraseñas</b> (ni contraseñas de aplicación) para correo, ni en cuentas personales ni de escuela: "
            "solo OAuth. Por eso hay que registrar <b>una app tuya, gratis</b>, una sola vez:<br>"
            "1) Entra a <a href='https://entra.microsoft.com'>entra.microsoft.com</a> → Identidad → Aplicaciones → Registros de aplicaciones → "
            "<b>Nuevo registro</b>.<br>"
            "2) Nombre: <i>Orbi</i>. Tipos de cuenta: <b>«Cuentas en cualquier directorio organizativo y cuentas Microsoft personales»</b>. Registrar.<br>"
            "3) <b>Autenticación</b> → Configuración avanzada → «Permitir flujos de cliente público» = <b>Sí</b> → Guardar.<br>"
            "4) <b>Permisos de API</b> → Agregar → Microsoft Graph → Permisos delegados → <b>Mail.ReadWrite</b> y <b>Mail.Send</b> (User.Read ya viene).<br>"
            "5) Copia el <b>«Id. de aplicación (cliente)»</b> de la página principal de la app y pégalo aquí abajo.<br>"
            "<span style='color:#7f8c8d'>Registrar apps no cuesta; si el portal te ofrece una suscripción de Azure, no la necesitas. "
            "Sirve para tu cuenta personal y para la de tu escuela (@live.ceti.mx): al iniciar sesión con la de la escuela, Microsoft te "
            "pedirá aceptar los permisos; si tu escuela exige aprobación de un administrador, el mensaje te lo dirá.</span>")


class MicrosoftDialog(QDialog):
    def __init__(self, hub: "cc.CorreoHub", parent=None):
        super().__init__(parent)
        self.hub = hub
        self._cancel = False
        self._flow = None
        self.setWindowTitle("Agregar cuenta de Microsoft")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        info = QLabel(PASOS_MS); info.setWordWrap(True); info.setTextFormat(Qt.RichText); info.setOpenExternalLinks(True)
        lay.addWidget(info)
        f = QFormLayout()
        self.e_id = QLineEdit(hub.ms_client_id()); self.e_id.setPlaceholderText("12345678-abcd-1234-abcd-1234567890ab")
        self.c_ten = QComboBox()
        for v, t in cc.TENANTS:
            self.c_ten.addItem(t, v)
        self.e_alias = QLineEdit(); self.e_alias.setPlaceholderText("Nombre corto, ej. escuela (opcional)")
        f.addRow("Id. de aplicación (cliente):", self.e_id); f.addRow("Tipo de cuenta:", self.c_ten); f.addRow("Nombre:", self.e_alias)
        lay.addLayout(f)
        self.codigo = QLabel(""); self.codigo.setAlignment(Qt.AlignCenter); self.codigo.setTextFormat(Qt.RichText)
        self.codigo.setOpenExternalLinks(True); self.codigo.setWordWrap(True)
        lay.addWidget(self.codigo)
        self.estado = QLabel(""); self.estado.setWordWrap(True)
        lay.addWidget(self.estado)
        row = QHBoxLayout(); row.addStretch(1)
        self.b_rev = QPushButton("Revisar app"); self.b_rev.clicked.connect(self._revisar)
        self.b_go = QPushButton("Iniciar sesión"); self.b_go.setDefault(True); self.b_go.clicked.connect(self._iniciar)
        b_no = QPushButton("Cancelar"); b_no.clicked.connect(self.reject)
        row.addWidget(self.b_rev); row.addWidget(self.b_go); row.addWidget(b_no)
        lay.addLayout(row)

    def _datos(self):
        return self.e_id.text().strip(), self.c_ten.currentData()

    def _revisar(self):
        cid, ten = self._datos()
        self.estado.setText("Revisando la app en Microsoft…"); self.b_rev.setEnabled(False)
        run_bg(self, lambda: self.hub.ms_preflight(cid, ten), lambda r: (self.estado.setText(r[1]), self.b_rev.setEnabled(True)))

    def _iniciar(self):
        cid, ten = self._datos()
        self.estado.setText("Pidiendo el código a Microsoft…"); self.b_go.setEnabled(False); self.b_rev.setEnabled(False)

        def begin():
            return True, self.hub.ms_begin(cid, ten)
        run_bg(self, begin, self._mostrar_codigo)

    def _mostrar_codigo(self, r):
        ok, flow = r
        if not ok:
            self.estado.setText(str(flow)); self.b_go.setEnabled(True); self.b_rev.setEnabled(True)
            return
        self._flow = flow
        QApplication.clipboard().setText(flow["user_code"])
        self.codigo.setText(f"<div style='font-size:26px;font-weight:700;letter-spacing:3px'>{flow['user_code']}</div>"
                            f"<div>Ya lo copié. Se abrió <a href='{flow['url']}'>{flow['url']}</a>: pega el código e inicia sesión con tu cuenta.</div>")
        self.estado.setText("Esperando a que inicies sesión en el navegador…")
        try:
            webbrowser.open(flow["url"])
        except Exception:  # noqa: BLE001
            pass
        alias = self.e_alias.text()
        run_bg(self, lambda: self.hub.ms_wait(flow, alias, cancelar=lambda: self._cancel), self._fin)

    def _fin(self, r):
        ok, msg = r
        self.estado.setText(msg)
        if ok:
            self.accept()
        else:
            self.codigo.setText(""); self.b_go.setEnabled(True); self.b_rev.setEnabled(True)

    def done(self, code):
        self._cancel = True
        super().done(code)


# ====================================================================== la pestaña
class CuentasTab(QWidget):
    """hub: correo_cuentas.CorreoHub · extras: lo que registró Orbi (para mostrar la cuenta de Google del calendario)."""

    def __init__(self, hub: "cc.CorreoHub", extras: dict | None = None, parent=None):
        super().__init__(parent)
        self.hub = hub
        self._estado: dict = {}                 # n -> último resultado de «revisar conexión»
        lay = QVBoxLayout(self)
        info = QLabel("<b>Correo</b>: puedes conectar varias cuentas (Gmail y Microsoft, personales o de escuela). "
                      "Orbi lee todas juntas, o la que le pidas por nombre. Enviar siempre te pide tu OK.")
        info.setWordWrap(True); info.setTextFormat(Qt.RichText)
        lay.addWidget(info)
        self.lista = QListWidget()
        lay.addWidget(self.lista, 1)
        self.msg = QLabel(""); self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        r1 = QHBoxLayout()
        for txt, fn in (("➕ Gmail…", self._add_gmail), ("➕ Microsoft…", self._add_ms)):
            b = QPushButton(txt); b.clicked.connect(fn); r1.addWidget(b)
        lay.addLayout(r1)
        r2 = QHBoxLayout()
        for txt, fn in (("Revisar conexión", self._revisar), ("Revisar todas", self._revisar_todas), ("Predeterminada", self._pred),
                        ("Renombrar…", self._renombrar), ("Quitar", self._quitar)):
            b = QPushButton(txt); b.clicked.connect(fn); r2.addWidget(b)
        lay.addLayout(r2)
        self.c_env = QCheckBox("Permitir que Orbi envíe correos (siempre te muestra el correo y te pide OK antes)")
        self.c_env.setChecked(hub.enviar)
        self.c_env.clicked.connect(lambda v=False: hub.set_enviar(self.c_env.isChecked()))
        lay.addWidget(self.c_env)

        # ---- otros conectores: cuenta de Google (calendario), usando lo que Orbi ya registró
        self._g = next((i for i in (extras or {}).get("items", []) if str(i.get("text", "")).startswith("Cuenta de Google")), None)
        if self._g:
            sep = QLabel("<b>Calendario de Google</b>"); sep.setTextFormat(Qt.RichText)
            lay.addWidget(sep)
            row = QHBoxLayout()
            self.g_estado = QLabel("")
            self.g_btn = QPushButton(""); self.g_btn.clicked.connect(self._google)
            row.addWidget(self.g_estado, 1); row.addWidget(self.g_btn)
            lay.addLayout(row)
            self._google_refrescar()
        self._llenar()

    # ---- lista
    def _llenar(self, sel_n=None):
        self.lista.clear()
        for c in self.hub.cuentas():
            est = self._estado.get(c["n"], "")
            self.lista.addItem(f"{'⭐ ' if c['predeterminada'] else ''}{c['alias']} — {c['email']}  ({PROV.get(c['proveedor'], c['proveedor'])})"
                                    + (f"   ·   {est}" if est else ""))
            self.lista.item(self.lista.count() - 1).setData(Qt.UserRole, c["n"])
        if self.lista.count() == 0:
            self.lista.addItem("(todavía no hay cuentas: usa «Gmail…» o «Microsoft…»)")
        else:
            fila = next((i for i in range(self.lista.count()) if self.lista.item(i).data(Qt.UserRole) == sel_n), 0)
            self.lista.setCurrentRow(fila)
        self.c_env.setChecked(self.hub.enviar)

    def _sel(self):
        it = self.lista.currentItem()
        n = it.data(Qt.UserRole) if it else None
        return n

    def _add_gmail(self):
        if GmailDialog(self.hub, self).exec():
            self._llenar()

    def _add_ms(self):
        if MicrosoftDialog(self.hub, self).exec():
            self._llenar()

    def _revisar(self):
        n = self._sel()
        if n is None:
            return
        self.msg.setText("Revisando la conexión…")
        run_bg(self, lambda: self.hub.check(n), lambda r: self._resultado(n, r))

    def _resultado(self, n, r):
        ok, msg = r
        self._estado[n] = ("✅ " if ok else "⚠ ") + msg.replace("Conectado ✅ · ", "")
        self.msg.setText(msg)
        self._llenar(n)

    def _revisar_todas(self):
        self.msg.setText("Revisando todas las cuentas…")

        def todas():
            return [(c["n"], *self.hub.check(c["n"])) for c in self.hub.cuentas()]
        run_bg(self, todas, self._resultado_todas)

    def _resultado_todas(self, r):
        for n, ok, msg in r:
            self._estado[n] = ("✅ " if ok else "⚠ ") + msg.replace("Conectado ✅ · ", "")
        self.msg.setText("Listo: " + (", ".join(f"{'✅' if ok else '⚠'}" for _n, ok, _m in r) or "no hay cuentas"))
        self._llenar(self._sel())

    def _pred(self):
        n = self._sel()
        if n is not None:
            self.hub.set_default(n); self._llenar(n)

    def _renombrar(self):
        n = self._sel()
        if n is None:
            return
        nuevo, ok = QInputDialog.getText(self, "Renombrar cuenta", "Nombre corto (así se lo puedes decir a Orbi):")
        if ok and nuevo.strip():
            self.hub.rename(n, nuevo); self._llenar(n)

    def _quitar(self):
        n = self._sel()
        if n is None:
            return
        if QMessageBox.question(self, "Quitar cuenta", "¿Quitar esta cuenta de Orbi? (Tu correo no se toca; solo se borra la sesión guardada.)") == QMessageBox.Yes:
            self.hub.remove(n); self._estado.pop(n, None); self._llenar()

    # ---- Google (calendario)
    def _google_refrescar(self):
        try:
            ck = self._g.get("checked")
            on = bool(ck() if callable(ck) else ck)
        except Exception:  # noqa: BLE001
            on = False
        self.g_estado.setText("Conectada ✅ (calendario de Google)" if on else "Sin conectar")
        self.g_btn.setText("Desconectar" if on else "Conectar…")

    def _google(self):
        try:
            self._g["cb"]()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Google", f"{type(e).__name__}: {str(e)[:200]}")
        QTimer.singleShot(1500, self._google_refrescar)
        QTimer.singleShot(8000, self._google_refrescar)
