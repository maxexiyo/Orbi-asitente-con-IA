"""Pestaña «Rutinas y alarmas» de Ajustes: ver, agregar, editar y borrar A MANO

  Rutinas       · las reglas/rutinas de reglas.py (orbi_reglas.json): activarlas/pausarlas, crearlas, editarlas, borrarlas
  Alarmas       · alarmas de alarmas.py (orbi_alarmas.json), con hora, fecha y repetición
  Recordatorios · recordatorios de alarmas.py (los que Orbi avisa sin sonar)
  Timers        · cuenta regresiva (en Orbi un timer es un recordatorio «dentro de X minutos», hasta 3 h)

Trabaja directo sobre los MISMOS objetos `Alarmas` y `Reglas` que usa Orbi (con sus candados), así que lo que cambias aquí
lo ve Orbi al instante y lo que Orbi cambia por voz se ve aquí (la lista se actualiza sola).
"""
import json
from datetime import datetime, timedelta

from PySide6.QtCore import QDateTime, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

from reglas import CUANDO, SEGURAS

TIMER_MAX_MIN = 180            # igual que minipanel.TIMER_MAX_S (3 h): más allá ya no se ve como timer
_DIAS3 = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
REPETIR = [("no", "No se repite"), ("diaria", "Todos los días"), ("laborales", "Lunes a viernes")]
_REP_TXT = {"no": "", "diaria": " · todos los días", "laborales": " · lunes a viernes"}

CUANDO_TXT = [("hora", "A una hora (y ciertos días)"), ("intervalo", "Cada cierto tiempo"), ("inactividad", "Llevo X min sin tocar la PC"),
              ("bateria", "Batería / cargador"), ("app_abre", "Se abre un programa"), ("app_cierra", "Se cierra un programa"),
              ("notificacion", "Llega una notificación"), ("internet", "Internet: se cae o regresa"), ("frase", "Digo una frase"),
              ("ausente", "Me ausento"), ("regreso", "Regreso"),
              ("correo", "Llega un correo"), ("recordatorio", "Hay un recordatorio (avisar antes)"),
              ("sesion_activa", "Vuelvo a usar la PC"), ("ventana", "Aparece una ventana")]
# qué campos usa cada disparador (nombre y «una sola vez» siempre están)
CAMPOS = {"hora": {"hora", "dias", "acciones"}, "intervalo": {"cada_min", "acciones"}, "inactividad": {"cada_min", "acciones"},
          "bateria": {"estado", "umbral", "acciones"}, "app_abre": {"filtro", "acciones"}, "app_cierra": {"filtro", "acciones"},
          "notificacion": {"filtro", "acciones"}, "frase": {"filtro", "acciones"}, "internet": {"estado", "acciones"},
          "ausente": {"filtro_aus", "acciones"}, "regreso": {"filtro_aus", "cada_min", "acciones"},
          "correo": {"filtro", "antes_h", "texto"}, "recordatorio": {"filtro", "antes_h"},
          "sesion_activa": {"texto"}, "ventana": {"filtro", "texto"}}
FILTRO_TXT = {"app_abre": "Programa (nombre, exe o título):", "app_cierra": "Programa (nombre, exe o título):",
              "notificacion": "App, título o palabras de la notificación:", "frase": "Frases que la activan (separadas por coma):",
              "correo": "Remitente o asunto (palabras separadas por coma):", "recordatorio": "Recordatorios cuyo texto contenga:",
              "ventana": "Ventana o programa (ej. Meet, Zoom, Teams):"}
CADA_TXT = {"intervalo": "Cada cuántos minutos (mínimo 5):", "inactividad": "Minutos sin tocar la PC:",
            "regreso": "Mínimo de minutos fuera (0 = cualquiera):"}
ESTADOS = {"bateria": [("baja", "La batería está baja"), ("llena", "La batería está llena"), ("conectado", "Conecto el cargador"),
                       ("desconectado", "Desconecto el cargador")],
           "internet": [("caida", "Se cae el internet"), ("regreso", "Regresa el internet")]}


# ------------------------------------------------------------------ utilidades (sin interfaz)
def acciones_a_texto(acciones) -> str:
    """Lista de acciones de una rutina -> texto editable, una por línea."""
    out = []
    for a in acciones or []:
        if a.get("tipo") == "herramienta":
            args = a.get("argumentos") or {}
            out.append(f"herramienta: {a.get('herramienta', '')}" + (f" {json.dumps(args, ensure_ascii=False)}" if args else ""))
        else:
            out.append(f"{a.get('tipo', 'decir')}: {a.get('texto', '')}")
    return "\n".join(out)


def texto_a_acciones(txt: str) -> list:
    """Texto (una acción por línea) -> lista de acciones. «decir: …» · «orbi: …» · «herramienta: nombre {json}». Sin prefijo = decir."""
    out = []
    for n, linea in enumerate(str(txt or "").splitlines(), 1):
        linea = linea.strip()
        if not linea:
            continue
        tipo, sep, resto = linea.partition(":")
        t = tipo.strip().lower()
        if not sep or t not in ("decir", "orbi", "herramienta"):
            out.append(dict(tipo="decir", texto=linea))
            continue
        resto = resto.strip()
        if t != "herramienta":
            out.append(dict(tipo=t, texto=resto))
            continue
        nombre, _s, args = resto.partition(" ")
        args = args.strip()
        try:
            datos = json.loads(args) if args else {}
        except ValueError:
            raise ValueError(f"Línea {n}: los argumentos de la herramienta deben ser JSON, ej. herramienta: abrir_app {{\"nombre\": \"spotify\"}}")
        if not isinstance(datos, dict):
            raise ValueError(f"Línea {n}: los argumentos deben ser un objeto JSON {{…}}.")
        out.append(dict(tipo="herramienta", herramienta=nombre.strip(), argumentos=datos))
    return out


def cuando_txt(iso: str) -> str:
    try:
        w = datetime.fromisoformat(iso)
    except Exception:                                           # noqa: BLE001
        return str(iso)
    hoy = datetime.now().date()
    if w.date() == hoy:
        dia = "hoy"
    elif w.date() == hoy + timedelta(days=1):
        dia = "mañana"
    else:
        dia = f"{_DIAS3[w.weekday()]} {w.day}/{w.month}"
    return f"{dia} {w:%H:%M}"


def restante_txt(iso: str) -> str:
    try:
        s = int((datetime.fromisoformat(iso) - datetime.now()).total_seconds())
    except Exception:                                           # noqa: BLE001
        return "?"
    s = max(0, s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def _a_actualizar(alarms, id_: str, **campos) -> bool:
    with alarms._lock:
        for it in alarms.items:
            if it.get("id") == id_:
                it.update(campos)
                alarms._save()
                return True
    return False


def _a_borrar(alarms, id_: str) -> bool:
    with alarms._lock:
        n = len(alarms.items)
        alarms.items = [i for i in alarms.items if i.get("id") != id_]
        alarms._save()
        return len(alarms.items) < n


def _r_borrar(reglas, id_: str) -> bool:
    with reglas._lock:
        n = len(reglas.data["reglas"])
        reglas.data["reglas"] = [r for r in reglas.data["reglas"] if r.get("id") != id_]
        reglas._save()
        return len(reglas.data["reglas"]) < n


def _r_activar(reglas, id_: str):
    """Pausa o reactiva una regla. -> nuevo estado (True = activa) o None si ya no existe."""
    with reglas._lock:
        for r in reglas.data["reglas"]:
            if r.get("id") == id_:
                r["activa"] = not r.get("activa", True)
                reglas._save()
                return r["activa"]
    return None


def _dt_de(q: QDateTime) -> datetime:
    d, t = q.date(), q.time()
    return datetime(d.year(), d.month(), d.day(), t.hour(), t.minute())


# ------------------------------------------------------------------ diálogos
class ReglaDialog(QDialog):
    """Crear o editar una rutina/regla. Al crear usa reglas.add / add_rutina (validan igual que cuando se lo pides a Orbi)."""

    def __init__(self, reglas, regla=None, parent=None):
        super().__init__(parent)
        self.reglas, self.regla = reglas, regla
        self.setWindowTitle("Editar rutina" if regla else "Nueva rutina o regla")
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)
        f = QFormLayout(); f.setRowWrapPolicy(QFormLayout.WrapAllRows); lay.addLayout(f)
        self._rows = {}

        def fila(key, etiqueta, w):
            lab = QLabel(etiqueta)
            f.addRow(lab, w)
            self._rows[key] = (lab, w)
            return w

        self.c_cuando = fila("cuando", "Cuándo pasa:", QComboBox())
        for k, t in CUANDO_TXT:
            if k in CUANDO:
                self.c_cuando.addItem(t, k)
        self.e_nombre = fila("nombre", "Nombre (opcional):", QLineEdit()); self.e_nombre.setPlaceholderText("ej. modo estudio")
        self.e_filtro = fila("filtro", "Filtro:", QLineEdit())
        self.t_hora = fila("hora", "A qué hora:", QTimeEdit()); self.t_hora.setDisplayFormat("HH:mm")
        self.e_dias = fila("dias", "Qué días:", QLineEdit()); self.e_dias.setText("todos los días")
        self.e_dias.setPlaceholderText("todos los días · lunes a viernes · fines de semana · lunes y jueves")
        self.s_cada = fila("cada_min", "Minutos:", QDoubleSpinBox()); self.s_cada.setRange(0, 100000); self.s_cada.setDecimals(1)
        self.c_estado = fila("estado", "Qué pasa:", QComboBox())
        self.s_umbral = fila("umbral", "Batería baja = a partir de (%):", QSpinBox()); self.s_umbral.setRange(1, 100); self.s_umbral.setValue(20)
        self.c_faus = fila("filtro_aus", "Cuándo cuenta:", QComboBox())
        for v, t in (("", "Cualquiera de las dos"), ("aviso", "Cuando yo aviso que me voy"), ("inactivo", "Cuando dejo la PC sin tocar")):
            self.c_faus.addItem(t, v)
        self.s_antes = fila("antes_h", "Horas antes (0 = solo avisar que llegó):", QDoubleSpinBox())
        self.s_antes.setRange(0, 720); self.s_antes.setDecimals(1); self.s_antes.setSuffix(" h")
        self.e_texto = fila("texto", "Qué te digo:", QLineEdit())
        self.e_acc = fila("acciones", "Qué hace (una acción por línea):", QPlainTextEdit()); self.e_acc.setFixedHeight(110)
        self.e_acc.setPlaceholderText("decir: ¡Buenos días!\norbi: ponme música tranquila\nherramienta: abrir_app {\"nombre\": \"spotify\"}")
        self.k_una = QCheckBox("Hacerla solo una vez (se borra después de disparar)"); f.addRow("", self.k_una)
        ayuda = QLabel("Acciones: «decir: texto» (Orbi lo dice) · «orbi: algo» (se lo pides a Orbi en libre) · «herramienta: nombre {json}» "
                       "(solo seguras: " + ", ".join(sorted(SEGURAS)) + "). Sin prefijo = decir. "
                       "En los textos puedes usar {app} {titulo} {texto} {hora} {bateria}.")
        ayuda.setWordWrap(True); ayuda.setStyleSheet("color:#7f8c8d;")
        self._ayuda = ayuda
        lay.addWidget(ayuda)
        self.err = QLabel(""); self.err.setWordWrap(True); self.err.setStyleSheet("color:#c0392b;"); lay.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Guardar"); bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._guardar); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        if regla:
            self.c_cuando.setCurrentIndex(max(0, self.c_cuando.findData(regla.get("cuando"))))
            self.c_cuando.setEnabled(False)                      # cambiar el disparador = crear otra rutina
        self.c_cuando.currentIndexChanged.connect(self._ajustar)
        self._ajustar()
        if regla:
            self._cargar(regla)

    # ---- mostrar solo los campos del disparador elegido
    def _ajustar(self):
        c = self.c_cuando.currentData()
        usa = CAMPOS.get(c, set())
        for k, (lab, w) in self._rows.items():
            if k in ("cuando", "nombre"):
                continue
            lab.setVisible(k in usa); w.setVisible(k in usa)
        self._rows["filtro"][0].setText(FILTRO_TXT.get(c, "Filtro:"))
        self._rows["cada_min"][0].setText(CADA_TXT.get(c, "Minutos:"))
        self._ayuda.setVisible("acciones" in usa)
        self.c_estado.blockSignals(True)
        self.c_estado.clear()
        for v, t in ESTADOS.get(c, []):
            self.c_estado.addItem(t, v)
        self.c_estado.blockSignals(False)
        self.adjustSize()

    def _cargar(self, r):
        self.e_nombre.setText(r.get("nombre", ""))
        c = r.get("cuando")
        if c in ("ausente", "regreso"):
            self.c_faus.setCurrentIndex(max(0, self.c_faus.findData(r.get("filtro", ""))))
        else:
            self.e_filtro.setText(r.get("filtro", ""))
        if r.get("hora"):
            from PySide6.QtCore import QTime
            t = QTime.fromString(str(r["hora"]), "HH:mm")
            if t.isValid():
                self.t_hora.setTime(t)
        if r.get("dias") is not None:
            self.e_dias.setText(self.reglas._dias_txt(r.get("dias")))
        self.s_cada.setValue(float(r.get("cada_min") or 0))
        self.c_estado.setCurrentIndex(max(0, self.c_estado.findData(r.get("estado"))))
        self.s_umbral.setValue(int(float(r.get("umbral") or 20)))
        self.s_antes.setValue(float(r.get("antes_h") or 0))
        self.e_texto.setText(r.get("texto", ""))
        self.e_acc.setPlainText(acciones_a_texto(self.reglas._acciones_de(r)))
        self.k_una.setChecked(bool(r.get("una_vez")))

    def _valores(self) -> dict:
        c = self.c_cuando.currentData()
        usa = CAMPOS.get(c, set())
        v = dict(cuando=c, nombre=self.e_nombre.text().strip(), una_vez=self.k_una.isChecked(), filtro="", hora="", dias="",
                 cada_min=0.0, estado="", umbral=0, antes_h=0.0, texto="", acciones=None)
        if "filtro" in usa:
            v["filtro"] = self.e_filtro.text().strip()
        if "filtro_aus" in usa:
            v["filtro"] = self.c_faus.currentData() or ""
        if "hora" in usa:
            v["hora"] = self.t_hora.time().toString("HH:mm")
        if "dias" in usa:
            v["dias"] = self.e_dias.text().strip()
        if "cada_min" in usa:
            v["cada_min"] = self.s_cada.value()
        if "estado" in usa:
            v["estado"] = self.c_estado.currentData() or ""
        if "umbral" in usa:
            v["umbral"] = self.s_umbral.value()
        if "antes_h" in usa:
            v["antes_h"] = self.s_antes.value()
        if "texto" in usa:
            v["texto"] = self.e_texto.text().strip()
        if "acciones" in usa:
            v["acciones"] = texto_a_acciones(self.e_acc.toPlainText())
        return v

    # ---- guardar
    def _guardar(self):
        try:
            v = self._valores()
        except ValueError as e:
            self.err.setText(str(e)); return
        try:
            r, err = self._editar(v) if self.regla else self._crear(v)
        except Exception as e:                                   # noqa: BLE001
            r, err = None, f"{type(e).__name__}: {str(e)[:160]}"
        if not r:
            self.err.setText(err or "No se pudo guardar."); return
        self.accept()

    def _crear(self, v):
        rg = self.reglas
        if v["cuando"] in CUANDO[4:]:
            return rg.add_rutina(v["cuando"], v["nombre"], v["filtro"], v["hora"], v["dias"], v["cada_min"], v["umbral"], v["estado"],
                                 v["acciones"], "", v["una_vez"])
        return rg.add(v["cuando"], v["filtro"], v["antes_h"], v["texto"], v["una_vez"], v["nombre"])

    def _editar(self, v):
        rg, old = self.reglas, self.regla
        if v["cuando"] in CUANDO[4:]:
            nuevo, err = rg.add_rutina(v["cuando"], v["nombre"], v["filtro"], v["hora"], v["dias"], v["cada_min"], v["umbral"],
                                       v["estado"], v["acciones"], "", v["una_vez"])       # valida igual que al crearla
            if not nuevo:
                return None, err
            with rg._lock:                                        # la nueva se anexó al final: ocupa el lugar y el id de la vieja
                lst = rg.data["reglas"]
                lst[:] = [x for x in lst if x is not nuevo]
                idx = next((i for i, x in enumerate(lst) if x.get("id") == old["id"]), None)
                orig = lst[idx] if idx is not None else old
                nuevo.update(id=old["id"], creada=orig.get("creada", nuevo["creada"]), activa=orig.get("activa", True),
                             ultima=orig.get("ultima", 0))
                if idx is None:
                    lst.append(nuevo)
                else:
                    lst[idx] = nuevo
                rg._save()
            return nuevo, ""
        c = v["cuando"]                                           # correo / recordatorio / sesion_activa / ventana: sin efectos secundarios
        if c in ("sesion_activa", "ventana") and not v["texto"]:
            return None, "Dime qué debo decirte cuando pase."
        if c == "ventana" and not v["filtro"]:
            return None, "Dime qué ventana o programa (ej. Meet, Zoom, Teams)."
        if c == "recordatorio" and v["antes_h"] <= 0:
            return None, "Dime con cuánta anticipación avisar (mayor que 0)."
        with rg._lock:
            for x in rg.data["reglas"]:
                if x.get("id") == old["id"]:
                    x.update(nombre=v["nombre"][:60], filtro=v["filtro"][:120], antes_h=float(v["antes_h"]), texto=v["texto"][:200],
                             una_vez=bool(v["una_vez"]))
                    rg._save()
                    return x, ""
        return None, "Esa regla ya no existe (¿la borraste?)."


class ItemDialog(QDialog):
    """Alarma o recordatorio: texto, fecha y hora, repetición."""

    def __init__(self, kind: str, item=None, parent=None):
        super().__init__(parent)
        self.kind = kind
        nombre = "alarma" if kind == "alarma" else "recordatorio"
        self.setWindowTitle(("Editar " if item else "Nueva ") + nombre)
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        f = QFormLayout(); f.setRowWrapPolicy(QFormLayout.WrapAllRows); lay.addLayout(f)
        self.e_texto = QLineEdit(); self.e_texto.setMaxLength(160)
        self.e_texto.setPlaceholderText("ej. Despertar" if kind == "alarma" else "ej. Tomar agua")
        self.dt = QDateTimeEdit(); self.dt.setCalendarPopup(True); self.dt.setDisplayFormat("dd/MM/yyyy  HH:mm")
        self.c_rep = QComboBox()
        for v, t in REPETIR:
            self.c_rep.addItem(t, v)
        f.addRow("Texto:", self.e_texto); f.addRow("Fecha y hora:", self.dt); f.addRow("Repetir:", self.c_rep)
        base = datetime.now().replace(second=0, microsecond=0) + timedelta(hours=1 if kind == "alarma" else 0, minutes=0 if kind == "alarma" else 30)
        if item:
            self.e_texto.setText(item.get("texto", ""))
            try:
                base = datetime.fromisoformat(item["when"])
            except Exception:                                   # noqa: BLE001
                pass
            self.c_rep.setCurrentIndex(max(0, self.c_rep.findData(item.get("repetir", "no"))))
        self.dt.setDateTime(QDateTime(base.year, base.month, base.day, base.hour, base.minute))
        self.err = QLabel(""); self.err.setStyleSheet("color:#c0392b;"); self.err.setWordWrap(True); lay.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Guardar"); bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        when = _dt_de(self.dt.dateTime())
        if when <= datetime.now():
            self.err.setText("Esa fecha y hora ya pasó."); return
        self.resultado = (when, self.e_texto.text().strip(), self.c_rep.currentData())
        self.accept()


class TimerDialog(QDialog):
    """Timer: en cuántos minutos avisar y de qué."""

    def __init__(self, item=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar timer" if item else "Nuevo timer")
        lay = QVBoxLayout(self)
        f = QFormLayout(); f.setRowWrapPolicy(QFormLayout.WrapAllRows); lay.addLayout(f)
        self.s_min = QSpinBox(); self.s_min.setRange(1, TIMER_MAX_MIN); self.s_min.setSuffix(" min"); self.s_min.setValue(10)
        self.e_texto = QLineEdit(); self.e_texto.setMaxLength(160); self.e_texto.setPlaceholderText("ej. Sacar la pizza")
        f.addRow("Avisarme dentro de:", self.s_min); f.addRow("Texto:", self.e_texto)
        if item:
            self.e_texto.setText(item.get("texto", ""))
            try:
                left = (datetime.fromisoformat(item["when"]) - datetime.now()).total_seconds() / 60
                self.s_min.setValue(max(1, min(TIMER_MAX_MIN, round(left))))
            except Exception:                                   # noqa: BLE001
                pass
            f.addRow("", QLabel("Al guardar, la cuenta regresiva vuelve a empezar con estos minutos."))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Guardar"); bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)


# ------------------------------------------------------------------ la pestaña
def _llenar(lw: QListWidget, filas: list, vacio: str):
    """Rellena la lista solo si cambió (sin parpadeo), conservando la selección y el scroll."""
    firma = tuple(filas)
    if getattr(lw, "_firma", None) == firma:
        return
    lw._firma = firma
    sel = lw.currentItem().data(Qt.UserRole) if lw.currentItem() else None
    pos = lw.verticalScrollBar().value()
    lw.blockSignals(True)
    lw.clear()
    for id_, txt in filas:
        it = QListWidgetItem(txt); it.setData(Qt.UserRole, id_); lw.addItem(it)
        if id_ == sel:
            lw.setCurrentItem(it)
    if not filas:
        it = QListWidgetItem(vacio); it.setFlags(Qt.NoItemFlags); lw.addItem(it)
    lw.blockSignals(False)
    lw.verticalScrollBar().setValue(pos)


def _sel(lw: QListWidget):
    it = lw.currentItem()
    return it.data(Qt.UserRole) if it else None


class PendientesTab(QWidget):
    def __init__(self, alarms, reglas, on_change=None, parent=None):
        super().__init__(parent)
        self.alarms, self.reglas = alarms, reglas
        self._on_change = on_change or (lambda: None)
        lay = QVBoxLayout(self)
        info = QLabel("Lo que Orbi tiene programado. Todo lo que cambies aquí vale al instante (no hace falta «Aplicar»); "
                      "lo que Orbi cree por voz aparece solo.")
        info.setWordWrap(True); info.setStyleSheet("color:#7f8c8d;")
        lay.addWidget(info)
        self.sub = QTabWidget(); lay.addWidget(self.sub, 1)
        self.l_reg = self._pagina("Rutinas", self.reglas is not None,
                                  [("➕ Agregar…", self._reg_add), ("✏ Editar…", self._reg_edit), ("⏯ Activar / pausar", self._reg_toggle),
                                   ("🗑 Borrar", self._reg_del)], self._reg_edit)
        self.l_alm = self._pagina("Alarmas", self.alarms is not None,
                                  [("➕ Agregar…", lambda: self._it_add("alarma")), ("✏ Editar…", lambda: self._it_edit("alarma")),
                                   ("🗑 Borrar", lambda: self._it_del("alarma"))], lambda: self._it_edit("alarma"))
        self.l_rec = self._pagina("Recordatorios", self.alarms is not None,
                                  [("➕ Agregar…", lambda: self._it_add("recordatorio")), ("✏ Editar…", lambda: self._it_edit("recordatorio")),
                                   ("🗑 Borrar", lambda: self._it_del("recordatorio"))], lambda: self._it_edit("recordatorio"))
        self.l_tim = self._pagina("Timers", self.alarms is not None,
                                  [("➕ Nuevo timer…", self._tim_add), ("✏ Editar…", self._tim_edit), ("🗑 Cancelar", self._tim_del)], self._tim_edit)
        self.refrescar()
        self._t5 = QTimer(self); self._t5.timeout.connect(self._tick5); self._t5.start(5000)
        self._t1 = QTimer(self); self._t1.timeout.connect(self._tick1); self._t1.start(1000)

    def _pagina(self, titulo, activo, botones, doble_clic):
        w = QWidget(); lay = QVBoxLayout(w)
        lw = QListWidget(); lay.addWidget(lw, 1)
        if not activo:
            lw.addItem(QListWidgetItem("(no disponible en esta versión de Orbi)")); lw.setEnabled(False)
        else:
            lw.itemDoubleClicked.connect(lambda _i: doble_clic())
            row = QHBoxLayout()
            for txt, fn in botones:
                b = QPushButton(txt); b.clicked.connect(lambda _=False, fn=fn: fn()); row.addWidget(b)
            row.addStretch(1); lay.addLayout(row)
        self.sub.addTab(w, titulo)
        return lw

    # ---- datos en pantalla
    def _tick5(self):
        if self.isVisible():
            self.refrescar()

    def _tick1(self):
        if self.isVisible() and self.alarms is not None and self.sub.currentWidget() is self.l_tim.parentWidget():
            self._llenar_timers()

    def refrescar(self):
        if self.reglas is not None:
            filas = [(r["id"], ("" if r.get("activa", True) else "⏸ (pausada) ") + self.reglas.describe(r)) for r in self.reglas.listing()]
            _llenar(self.l_reg, filas, "(no hay rutinas ni reglas: usa «Agregar…»)")
        if self.alarms is not None:
            items = self.alarms.listing()
            _llenar(self.l_alm, [(i["id"], f"⏰ {cuando_txt(i['when'])} · {i['texto']}{_REP_TXT.get(i.get('repetir', 'no'), '')}")
                                 for i in items if i.get("kind") == "alarma"], "(no hay alarmas)")
            _llenar(self.l_rec, [(i["id"], f"🔔 {cuando_txt(i['when'])} · {i['texto']}{_REP_TXT.get(i.get('repetir', 'no'), '')}")
                                 for i in items if i.get("kind") == "recordatorio"], "(no hay recordatorios)")
            self._llenar_timers(items)

    def _timers(self, items=None):
        now = datetime.now()
        out = []
        for i in (items if items is not None else self.alarms.listing()):
            try:
                left = (datetime.fromisoformat(i["when"]) - now).total_seconds()
            except Exception:                                   # noqa: BLE001
                continue
            if i.get("kind") == "recordatorio" and i.get("repetir", "no") == "no" and 0 <= left <= TIMER_MAX_MIN * 60:
                out.append(i)
        return out

    def _llenar_timers(self, items=None):
        _llenar(self.l_tim, [(i["id"], f"⏱ {restante_txt(i['when'])} · {i['texto']}") for i in self._timers(items)],
                "(no hay timers corriendo; un timer es un recordatorio de menos de 3 h)")

    def _cambio(self):
        self.refrescar()
        try:
            self._on_change()                                   # la mini ventana se pone al día
        except Exception:                                       # noqa: BLE001
            pass

    def _aviso(self, txt):
        QMessageBox.information(self, "Rutinas y alarmas", txt)

    def _confirmar(self, txt) -> bool:
        return QMessageBox.question(self, "Confirmar", txt) == QMessageBox.Yes

    # ---- rutinas
    def _reg_actual(self):
        id_ = _sel(self.l_reg)
        return next((r for r in self.reglas.listing() if r["id"] == id_), None) if id_ else None

    def _reg_add(self):
        if ReglaDialog(self.reglas, None, self).exec():
            self._cambio()

    def _reg_edit(self):
        r = self._reg_actual()
        if not r:
            self._aviso("Elige primero una rutina de la lista."); return
        if ReglaDialog(self.reglas, r, self).exec():
            self._cambio()

    def _reg_toggle(self):
        r = self._reg_actual()
        if not r:
            self._aviso("Elige primero una rutina de la lista."); return
        _r_activar(self.reglas, r["id"])
        self._cambio()

    def _reg_del(self):
        r = self._reg_actual()
        if not r:
            self._aviso("Elige primero una rutina de la lista."); return
        if self._confirmar(f"¿Borrar esta rutina?\n\n{self.reglas.describe(r)[:200]}"):
            _r_borrar(self.reglas, r["id"])
            self._cambio()

    # ---- alarmas y recordatorios
    def _it_actual(self, kind):
        lw = self.l_alm if kind == "alarma" else self.l_rec
        id_ = _sel(lw)
        return next((i for i in self.alarms.listing() if i["id"] == id_), None) if id_ else None

    def _it_add(self, kind):
        d = ItemDialog(kind, None, self)
        if d.exec():
            when, texto, rep = d.resultado
            self.alarms.add(kind, when, texto, rep)
            self._cambio()

    def _it_edit(self, kind):
        it = self._it_actual(kind)
        if not it:
            self._aviso("Elige primero uno de la lista."); return
        d = ItemDialog(kind, it, self)
        if d.exec():
            when, texto, rep = d.resultado
            _a_actualizar(self.alarms, it["id"], when=when.isoformat(timespec="seconds"),
                          texto=texto or ("Alarma" if kind == "alarma" else "Recordatorio"), repetir=rep)
            self._cambio()

    def _it_del(self, kind):
        it = self._it_actual(kind)
        if not it:
            self._aviso("Elige primero uno de la lista."); return
        if self._confirmar(f"¿Borrar «{it['texto']}» ({cuando_txt(it['when'])})?"):
            _a_borrar(self.alarms, it["id"])
            self._cambio()

    # ---- timers
    def _tim_actual(self):
        id_ = _sel(self.l_tim)
        return next((i for i in self._timers() if i["id"] == id_), None) if id_ else None

    def _tim_add(self):
        d = TimerDialog(None, self)
        if d.exec():
            it, err = self.alarms.set_by_time("recordatorio", minutos=d.s_min.value(), texto=d.e_texto.text().strip() or "Timer")
            if not it:
                self._aviso(err or "No pude crear el timer."); return
            self._cambio()

    def _tim_edit(self):
        it = self._tim_actual()
        if not it:
            self._aviso("Elige primero un timer de la lista."); return
        d = TimerDialog(it, self)
        if d.exec():
            cuando = datetime.now() + timedelta(minutes=d.s_min.value())
            _a_actualizar(self.alarms, it["id"], when=cuando.isoformat(timespec="seconds"), texto=d.e_texto.text().strip() or "Timer")
            self._cambio()

    def _tim_del(self):
        it = self._tim_actual()
        if not it:
            self._aviso("Elige primero un timer de la lista."); return
        if self._confirmar(f"¿Cancelar el timer «{it['texto']}»?"):
            _a_borrar(self.alarms, it["id"])
            self._cambio()
