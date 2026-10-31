"""Pestaña «Conexiones» de la ventana de Ajustes: conectar Orbi con Canva, Lucidchart y Figma (puente MCP, ver mcp_puente.py).

El login de Canva y Lucid abre tu navegador (hasta 3 min); corre en un hilo para que la ventana no se congele.
"""
import webbrowser

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

import mcp_puente as MP
from ajustes_cuentas import run_bg

_ESTADOS = {"listo": ("✅ Conectado", "#27ae60"), "conectando": ("⏳ Conectando…", "#e67e22"), "login": ("Sin conectar", "#7f8c8d"),
            "apagado": ("Sin conectar", "#7f8c8d"), "error": ("❌ Error", "#c0392b")}


class ConexionesTab(QWidget):
    def __init__(self, on_change=None, parent=None):
        super().__init__(parent)
        self._on_change = on_change or (lambda: None)
        self._filas: dict = {}
        self._ocupado: set = set()
        self._msg: dict = {}
        outer = QVBoxLayout(self)
        info = QLabel("Conecta Orbi con otros servicios para que los use por ti («hazme un diseño en Canva», «arma un diagrama de flujo en "
                      "Lucidchart», «mira mi archivo de Figma»). El login se hace en <b>tu navegador</b>: Orbi nunca ve tu contraseña, y la "
                      "llave de acceso se guarda <b>cifrada en esta PC</b>. Lo que pueda cambiar, compartir o publicar algo te pide OK antes.")
        info.setWordWrap(True); info.setTextFormat(Qt.RichText)
        outer.addWidget(info)
        cont = QWidget(); lay = QVBoxLayout(cont)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.NoFrame); sc.setWidget(cont)
        outer.addWidget(sc, 1)
        for sid, s in MP.servidores().items():
            lay.addWidget(self._fila(sid, s))
        lay.addStretch(1)
        self._nota = QLabel("")
        self._nota.setWordWrap(True); self._nota.setStyleSheet("color:#7f8c8d;")
        outer.addWidget(self._nota)
        self._t = QTimer(self); self._t.timeout.connect(self._refrescar); self._t.start(1500)
        self._refrescar()

    # ------------------------------------------------------------------ una fila por servicio
    def _fila(self, sid: str, s: dict) -> QWidget:
        w = QFrame(); w.setFrameShape(QFrame.StyledPanel)
        v = QVBoxLayout(w)
        top = QHBoxLayout()
        nom = QLabel(f"<b>{s.get('nombre', sid)}</b>"); nom.setTextFormat(Qt.RichText)
        est = QLabel(""); est.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(nom); top.addStretch(1); top.addWidget(est)
        v.addLayout(top)
        ay = QLabel(s.get("ayuda", "")); ay.setWordWrap(True); ay.setStyleSheet("color:#7f8c8d;")
        v.addWidget(ay)
        f = {"estado": est}
        if s.get("tipo") == "figma":
            tok = QLineEdit(); tok.setEchoMode(QLineEdit.Password); tok.setPlaceholderText("Pega aquí tu token personal de Figma (figd_…)")
            r = QHBoxLayout(); r.addWidget(tok, 1)
            b = QPushButton("Guardar token"); b.clicked.connect(lambda: self._guardar_figma(tok)); r.addWidget(b)
            q = QPushButton("Quitar"); q.clicked.connect(lambda: self._quitar_figma(tok)); r.addWidget(q)
            v.addLayout(r)
            nota = QLabel("Cómo conseguirlo: entra a Figma, en la lista de archivos haz clic en el <b>menú de tu cuenta</b> (arriba a la "
                          "izquierda) → <b>Settings</b> → pestaña <b>Security</b> → <b>Personal access tokens</b> → <b>Generate new token</b>. "
                          "Ponle una fecha de vencimiento y activa los permisos <code>file_content:read</code>, <code>file_comments:read</code> "
                          "y, si quieres que Orbi comente, <code>file_comments:write</code>. Figma muestra el token <b>una sola vez</b>: "
                          "cópialo y pégalo aquí."
                          "<br><i>Figma no deja que apps propias entren a su conexión MCP remota (solo a clientes de su catálogo), por eso Orbi "
                          "usa su API normal con tu token.</i>")
            nota.setWordWrap(True); nota.setTextFormat(Qt.RichText); nota.setStyleSheet("color:#7f8c8d;")
            v.addWidget(nota)
            bw = QPushButton("Abrir Figma"); bw.clicked.connect(lambda: webbrowser.open("https://www.figma.com/files"))
            v.addWidget(bw, 0, Qt.AlignLeft)
            f["tok"] = tok
        else:
            r = QHBoxLayout()
            bc = QPushButton("Conectar…"); bc.clicked.connect(lambda _=False, i=sid: self._conectar(i)); r.addWidget(bc)
            bd = QPushButton("Desconectar"); bd.clicked.connect(lambda _=False, i=sid: self._desconectar(i)); r.addWidget(bd)
            r.addStretch(1); v.addLayout(r)
            f["bc"], f["bd"] = bc, bd
        err = QLabel(""); err.setWordWrap(True); err.setStyleSheet("color:#c0392b;"); err.hide()
        v.addWidget(err); f["err"] = err
        self._filas[sid] = f
        return w

    # ------------------------------------------------------------------ acciones
    def _conectar(self, sid: str) -> None:
        if sid in self._ocupado:
            return
        self._ocupado.add(sid)
        self._msg[sid] = ("Conectando con la app de tu PC…" if MP.servidores().get(sid, {}).get("auth") == "ninguna"
                          else "Se abrió tu navegador: inicia sesión y acepta. Tienes 3 minutos.")
        self._refrescar()

        def hecho(r):
            self._ocupado.discard(sid)
            self._msg.pop(sid, None)
            if isinstance(r, tuple):                     # run_bg entrega (False, texto) si el hilo falló
                r = {"ok": False, "error": str(r[1])}
            if r.get("ok"):
                self._nota.setText("✅ Conectado. Para que Orbi use sus herramientas desde ya, reinicia Orbi (si no, se activan solas en su "
                                   "próxima reconexión).")
                try:
                    self._on_change()
                except Exception:                        # noqa: BLE001
                    pass
            else:
                self._msg[sid] = ""
                self._filas[sid]["err"].setText(str(r.get("error", "No se pudo conectar.")))
            self._refrescar()
        run_bg(self, lambda: MP.conectar_interactivo(sid), hecho)

    def _desconectar(self, sid: str) -> None:
        nombre = MP.servidores().get(sid, {}).get("nombre", sid)
        if QMessageBox.question(self, "Desconectar", f"¿Desconectar {nombre}? Orbi dejará de usarlo y se borra el acceso guardado en esta PC.") \
                != QMessageBox.Yes:
            return
        self._filas[sid]["err"].hide()
        run_bg(self, lambda: MP.desconectar(sid, olvidar=True), lambda _r: (self._on_change(), self._refrescar()))

    def _guardar_figma(self, tok: QLineEdit) -> None:
        t = tok.text().strip()
        if not t:
            return
        MP.guardar_token_figma(t)
        tok.clear()
        self._nota.setText("✅ Token de Figma guardado (cifrado). Reinicia Orbi para que pueda usarlo ya.")
        try:
            self._on_change()
        except Exception:                                # noqa: BLE001
            pass
        self._refrescar()

    def _quitar_figma(self, tok: QLineEdit) -> None:
        MP.guardar_token_figma("")
        tok.clear()
        try:
            self._on_change()
        except Exception:                                # noqa: BLE001
            pass
        self._refrescar()

    # ------------------------------------------------------------------ estado en pantalla
    def _refrescar(self) -> None:
        for sid, f in self._filas.items():
            e = MP.estado(sid)
            est = "conectando" if sid in self._ocupado else e["estado"]
            txt, col = _ESTADOS.get(est, _ESTADOS["apagado"])
            if est == "listo" and e.get("tools"):
                txt += f" · {e['tools']} herramientas"
            f["estado"].setText(f"<span style='color:{col}'>{txt}</span>"); f["estado"].setTextFormat(Qt.RichText)
            if "bc" in f:
                f["bc"].setEnabled(sid not in self._ocupado)
                f["bc"].setText("Reconectar…" if est == "listo" else "Conectar…")
                f["bd"].setEnabled(sid not in self._ocupado and (est == "listo" or sid in MP.activos()))
            err = f["err"]
            extra = self._msg.get(sid) or (e["error"] if est == "error" else "")
            if sid in self._ocupado and e.get("etapa"):             # en qué paso va ahora mismo
                et = e["etapa"]
                extra = f"{et}…" + (" (tienes 3 minutos)" if et.startswith("Esperando") else "")
            if extra:
                err.setStyleSheet("color:#c0392b;" if est == "error" else "color:#7f8c8d;")
                err.setText(extra); err.show()
            elif not err.text() or est == "listo":
                err.hide(); err.setText("")
