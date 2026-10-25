"""Pestaña «Skills y plugins» de la ventana de Ajustes (versión mejorada).

  · lista con buscador y filtro (todo / skills / plugins), casilla para activar y detalle de lo seleccionado
  · plugins: se ve qué hace su código (internet, programas, archivos…) ANTES de activarlos, se puede leer el código, y si el código
    cambia después de activarlo se desactiva solo (⚠)
  · skills: crear las tuyas, editarlas, actualizarlas desde donde se instalaron
  · instalar desde GitHub/enlace, buscar en GitHub, .zip o carpeta
"""
import html
import threading

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTextBrowser,
                               QVBoxLayout, QWidget)


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


def _bg(owner, fn, cb):
    b = _Bg(owner, cb)

    def work():
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            r = {"error": f"{type(e).__name__}: {str(e)[:150]}"}
        b.listo.emit(r)
    threading.Thread(target=work, daemon=True).start()


class _Editor(QDialog):
    """Ver o editar un archivo de texto (SKILL.md editable; plugin.py solo lectura)."""

    def __init__(self, titulo, texto, editable, parent=None, aviso=""):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        if aviso:
            a = QLabel(aviso); a.setWordWrap(True); a.setTextFormat(Qt.RichText)
            lay.addWidget(a)
        self.ed = QPlainTextEdit(texto); self.ed.setReadOnly(not editable)
        self.ed.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        lay.addWidget(self.ed, 1)
        row = QHBoxLayout(); row.addStretch(1)
        if editable:
            b = QPushButton("Guardar"); b.setDefault(True); b.clicked.connect(self.accept); row.addWidget(b)
        c = QPushButton("Cerrar" if not editable else "Cancelar"); c.clicked.connect(self.reject); row.addWidget(c)
        lay.addLayout(row)

    def texto(self):
        return self.ed.toPlainText()


class _NuevaSkill(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nueva skill")
        self.resize(600, 480)
        lay = QVBoxLayout(self)
        i = QLabel("Una skill son <b>instrucciones</b> que Orbi carga cuando el tema encaja (no ejecuta código). "
                   "La descripción es lo que Orbi lee para decidir cuándo usarla: di <i>qué hace y cuándo</i>.")
        i.setWordWrap(True); i.setTextFormat(Qt.RichText)
        lay.addWidget(i)
        f = QFormLayout()
        self.n = QLineEdit(); self.n.setPlaceholderText("ej. resumen-escolar")
        self.d = QLineEdit(); self.d.setPlaceholderText("ej. Resume apuntes de clase en bullets cuando el usuario lo pida")
        f.addRow("Nombre:", self.n); f.addRow("Descripción:", self.d)
        lay.addLayout(f)
        lay.addWidget(QLabel("Instrucciones (markdown):"))
        self.t = QPlainTextEdit(); lay.addWidget(self.t, 1)
        row = QHBoxLayout(); row.addStretch(1)
        b = QPushButton("Crear"); b.setDefault(True); b.clicked.connect(self.accept)
        c = QPushButton("Cancelar"); c.clicked.connect(self.reject)
        row.addWidget(b); row.addWidget(c); lay.addLayout(row)


class SkillsTab(QWidget):
    def __init__(self, sk, on_changed=None, parent=None):
        super().__init__(parent)
        self._sk, self._changed = sk, on_changed or (lambda: None)
        lay = QVBoxLayout(self)
        info = QLabel("<b>Skills</b>: instrucciones que Orbi carga cuando encajan con lo que pides (no ejecutan código).<br>"
                      "<b>Plugins</b>: herramientas nuevas hechas con código de Python: nacen desactivados, cada uso te pide permiso y "
                      "si su código cambia se desactivan solos. Instala solo los de gente de confianza.")
        info.setWordWrap(True); info.setTextFormat(Qt.RichText)
        lay.addWidget(info)
        top = QHBoxLayout()
        self.q = QLineEdit(); self.q.setPlaceholderText("Buscar entre lo instalado…"); self.q.textChanged.connect(self._refresh)
        self.f = QComboBox(); self.f.addItems(["Todo", "Solo skills", "Solo plugins"]); self.f.currentIndexChanged.connect(self._refresh)
        top.addWidget(self.q, 1); top.addWidget(self.f)
        lay.addLayout(top)
        sp = QSplitter(Qt.Horizontal)
        self.lista = QListWidget(); self.lista.itemChanged.connect(self._toggle); self.lista.currentItemChanged.connect(self._detalle)
        self.det = QTextBrowser(); self.det.setOpenExternalLinks(True)
        sp.addWidget(self.lista); sp.addWidget(self.det); sp.setStretchFactor(0, 2); sp.setStretchFactor(1, 3)
        lay.addWidget(sp, 1)
        self.msg = QLabel(""); self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        for fila in ((("Instalar desde enlace…", self._url), ("Buscar en GitHub…", self._buscar), ("Desde .zip…", self._zip), ("Desde carpeta…", self._dir)),
                     (("Nueva skill…", self._nueva), ("Ver / editar", self._ver), ("Actualizar", self._actualizar),
                      ("Quitar", self._quitar), ("Abrir carpeta", self._sk.open_folder))):
            row = QHBoxLayout()
            for txt, fn in fila:
                b = QPushButton(txt); b.clicked.connect(lambda _=False, fn=fn: fn()); row.addWidget(b)
            lay.addLayout(row)
        self._refresh()

    # ---- lista y detalle
    def _sel(self):
        it = self.lista.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _refresh(self, *_):
        sel = self._sel()
        q, filtro = self.q.text().strip().lower(), self.f.currentIndex()
        self.lista.blockSignals(True)
        self.lista.clear()
        for s in self._sk.scan():
            if filtro == 1 and s["kind"] != "skill" or filtro == 2 and s["kind"] != "plugin":
                continue
            if q and q not in s["name"].lower() and q not in s["desc"].lower():
                continue
            it = QListWidgetItem(f"{'🧩' if s['kind'] == 'plugin' else '📘'} {s['name']}" + ("   ⚠ código cambiado" if s.get("changed") else ""))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if s["enabled"] else Qt.Unchecked)
            it.setData(Qt.UserRole, (s["name"], s["kind"]))
            it.setToolTip(s["desc"])
            self.lista.addItem(it)
        if self.lista.count() == 0:
            self.lista.addItem("(nada por aquí todavía)")
        else:
            fila = next((i for i in range(self.lista.count()) if self.lista.item(i).data(Qt.UserRole) and self.lista.item(i).data(Qt.UserRole)[0] == (sel[0] if sel else None)), 0)
            self.lista.setCurrentRow(fila)
        self.lista.blockSignals(False)
        self._detalle()

    def _detalle(self, *_):
        d = self._sel()
        if not d:
            self.det.setHtml("<i>Elige algo de la lista para ver los detalles.</i>")
            return
        x = self._sk.details(d[0])
        if x.get("error"):
            self.det.setHtml(html.escape(x["error"]))
            return
        e = html.escape
        h = [f"<h3>{'🧩 Plugin' if x['kind'] == 'plugin' else '📘 Skill'} · {e(x['name'])}</h3>", f"<p>{e(x['desc'])}</p>"]
        o = x.get("origen") or {}
        if o:
            h.append(f"<p><b>Origen:</b> {e(str(o.get('fuente', '?')))} <span style='color:gray'>({e(str(o.get('fecha', '')))})</span></p>")
        if x["kind"] == "plugin":
            if x.get("changed"):
                h.append("<p style='color:#c0392b'><b>⚠ Su código cambió desde que lo activaste, así que se desactivó solo.</b> "
                         "Revísalo con «Ver / editar» y vuelve a activarlo si te parece bien.</p>")
            r = x.get("riesgos") or []
            h.append("<p><b>Lo que parece hacer su código:</b> " + (e(", ".join(r)) if r else "nada especial a simple vista") +
                     "<br><span style='color:gray'>(análisis automático: ayuda, pero no es una garantía)</span></p>")
            if x.get("herramientas"):
                h.append("<p><b>Herramientas que le da a Orbi:</b></p><ul>" + "".join(f"<li><b>{e(n)}</b>: {e(t)}</li>" for n, t in x["herramientas"]) + "</ul>")
        else:
            h.append(f"<p><b>Instrucciones:</b></p><pre style='white-space:pre-wrap'>{e(x.get('vista', ''))}</pre>")
        if x.get("archivos"):
            h.append("<p><b>Archivos:</b> " + e(", ".join(x["archivos"][:20])) + "</p>")
        self.det.setHtml("".join(h))

    def _toggle(self, item):
        d = item.data(Qt.UserRole)
        if not d:
            return
        name, kind = d
        on = item.checkState() == Qt.Checked
        if on and kind == "plugin":
            x = self._sk.details(name)
            riesgos = x.get("riesgos") or []
            txt = (f"«{name}» es código de Python que se ejecuta en tu PC con tus permisos.\n\n"
                   + ("Parece que su código: " + ", ".join(riesgos) + ".\n\n" if riesgos else "")
                   + "Antes de activarlo conviene leer su código («Ver / editar»). Cada vez que se use, Orbi te pedirá permiso, y si el código "
                     "cambia después se desactivará solo.\n\n¿Activarlo?")
            if QMessageBox.warning(self, "Activar plugin", txt, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                self.lista.blockSignals(True); item.setCheckState(Qt.Unchecked); self.lista.blockSignals(False)
                return
        self._sk.set_enabled(name, on)
        self._changed()
        self._refresh()

    # ---- instalar
    def _instalar(self, fn):
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
            self.msg.setText("Instalado: " + (", ".join(res.get("instaladas", [])) or "nada nuevo"))
        self._changed()
        self._refresh()

    def _url(self):
        url, ok = QInputDialog.getText(self, "Instalar desde internet", "Enlace de GitHub, .zip o SKILL.md (https):")
        if ok and url.strip():
            self._instalar(lambda code: self._sk.install_url(url.strip(), allow_code=code))

    def _zip(self):
        p, _f = QFileDialog.getOpenFileName(self, "Elegir paquete", "", "Paquetes (*.zip)")
        if p:
            self._instalar(lambda code: self._sk.install_zip(p, f"zip local: {p}", allow_code=code))

    def _dir(self):
        p = QFileDialog.getExistingDirectory(self, "Elegir carpeta con skills o plugins")
        if p:
            self._instalar(lambda code: self._sk.install_folder(p, allow_code=code))

    def _buscar(self):
        q, ok = QInputDialog.getText(self, "Buscar skills en GitHub", "¿Qué necesitas que Orbi sepa hacer? (en inglés suele haber más):")
        if not (ok and q.strip()):
            return
        self.msg.setText("Buscando en GitHub…")
        _bg(self, lambda: self._sk.search_github(q.strip()), self._resultados_busqueda)

    def _resultados_busqueda(self, r):
        self.msg.setText("")
        if r.get("error"):
            QMessageBox.warning(self, "GitHub", r["error"])
            return
        res = r.get("resultado")
        if not isinstance(res, list) or not res:
            QMessageBox.information(self, "GitHub", str(res or "No encontré nada."))
            return
        d = QDialog(self); d.setWindowTitle("Resultados en GitHub"); d.resize(640, 380)
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel("Una skill es contenido de terceros: instala solo si confías en el autor (mira el repositorio antes)."))
        lst = QListWidget()
        for x in res:
            it = QListWidgetItem(f"{x['nombre']}  ★{x['estrellas']}\n    {x['descripcion']}")
            it.setData(Qt.UserRole, x["url"]); lst.addItem(it)
        lst.setCurrentRow(0); lay.addWidget(lst, 1)
        row = QHBoxLayout(); row.addStretch(1)
        bi = QPushButton("Instalar la seleccionada"); bi.setDefault(True); bi.clicked.connect(d.accept)
        bc = QPushButton("Cerrar"); bc.clicked.connect(d.reject)
        row.addWidget(bi); row.addWidget(bc); lay.addLayout(row)
        if d.exec() and lst.currentItem():
            url = lst.currentItem().data(Qt.UserRole)
            self._instalar(lambda code: self._sk.install_url(url, allow_code=code))

    # ---- crear / ver / editar / actualizar / quitar
    def _nueva(self):
        d = _NuevaSkill(self)
        while d.exec():
            r = self._sk.create_skill(d.n.text(), d.d.text(), d.t.toPlainText())
            if r.get("error"):
                QMessageBox.warning(self, "Nueva skill", r["error"])
                continue
            self.msg.setText(f"Creaste la skill «{r['creada']}» ✅")
            self._changed(); self._refresh()
            return

    def _ver(self):
        d = self._sel()
        if not d:
            return
        name, kind = d
        r = self._sk.source_text(name)
        if r.get("error"):
            QMessageBox.warning(self, "Ver", r["error"])
            return
        if kind == "plugin":
            x = self._sk.details(name)
            riesgos = x.get("riesgos") or []
            aviso = ("<b>Lee el código antes de activarlo.</b> Parece que: " + html.escape(", ".join(riesgos) if riesgos else "no hace nada especial a simple vista")
                     + ". <span style='color:gray'>Solo lectura: si lo editas con otro programa, se desactiva solo.</span>")
            _Editor(f"plugin.py · {name}", r["resultado"], False, self, aviso).exec()
            return
        ed = _Editor(f"SKILL.md · {name}", r["resultado"], True, self)
        while ed.exec():
            g = self._sk.save_skill_text(name, ed.texto())
            if g.get("error"):
                QMessageBox.warning(self, "Guardar", g["error"])
                continue
            self.msg.setText("Guardada ✅"); self._changed(); self._refresh()
            return

    def _actualizar(self):
        d = self._sel()
        if not d:
            return
        self.msg.setText("Actualizando…")
        _bg(self, lambda: self._sk.update(d[0]), self._fin_actualizar)

    def _fin_actualizar(self, r):
        if r.get("error"):
            self.msg.setText("")
            QMessageBox.information(self, "Actualizar", r["error"])
            return
        self.msg.setText("Actualizado: " + ", ".join(r.get("instaladas", [])) + "  (los plugins quedan desactivados hasta que los revises)")
        self._changed(); self._refresh()

    def _quitar(self):
        d = self._sel()
        if d and QMessageBox.question(self, "Quitar", f"¿Quitar «{d[0]}» de Orbi?") == QMessageBox.Yes:
            self._sk.remove(d[0]); self._changed(); self._refresh()
