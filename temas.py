"""Temas visuales de Orbi: UN solo lugar que define cómo se ve todo (dashboard, mini ventana, ventana de Ajustes, menús y diálogos).

Se elige en Ajustes → Apariencia (se guarda en profile["ajustes"]["tema"]). Por defecto: «orbita».

  orbita         paneles flotando alrededor de la bolita, que se queda al centro (el predeterminado)
  vidrio         vidrio azul translúcido
  juego          estilo juego acogedor (crema, bordes gruesos, colores pastel)
  editorial      claro, como revista
  terminal       consola verde sobre negro
  neobrutalista  amarillo, bordes negros y sombras duras
  cinta          barra compacta arriba, casi no tapa nada
  reloj          anillo de 24 horas con tu día en el centro
  hud            el HUD original (cian con esquinitas)

Para agregar uno: copia uno de TEMAS, cámbiale colores y `layout` (grid | orbita | cinta | reloj) y ya sale en Ajustes.
Las fuentes son listas de preferencia: se usa la primera que tengas instalada (si no, la del sistema).
"""
from dataclasses import dataclass, replace

DEFAULT = "orbita"


@dataclass(frozen=True)
class Tema:
    id: str
    nombre: str
    desc: str
    layout: str                      # grid | orbita | cinta | reloj
    oscuro: bool
    bg: tuple                        # relleno de los paneles (r, g, b, a)
    borde: tuple                     # color del borde (r, g, b, a)
    texto: str
    tenue: str
    acento: str
    enlace: str
    ventana: str                     # fondo de Ajustes y diálogos
    campo: str                       # fondo de casillas y listas dentro de Ajustes
    radio: int = 16
    borde_px: int = 1
    sombra: tuple | None = None      # sombra dura (dx, dy, (r, g, b, a))
    brillo: bool = False             # resplandor del color del borde
    paleta: tuple = ()
    paleta_modo: str = ""            # borde | relleno | banda
    fuente: tuple = ("Segoe UI",)
    fuente_titulo: tuple = ()
    mayus: bool = False              # títulos en MAYÚSCULAS
    etiqueta: str = "normal"         # normal | punto | llaves | ninguna
    scan: bool = False
    esquinas: bool = False
    barras: str = "redonda"          # linea | redonda | segmentos | bloques | gruesa


def _h(hexs: str, a: int = 255) -> tuple:
    hexs = hexs.lstrip("#")
    return int(hexs[0:2], 16), int(hexs[2:4], 16), int(hexs[4:6], 16), a


TEMAS = {t.id: t for t in (
    Tema("orbita", "Órbita", "Paneles flotando alrededor de la bolita, que se queda al centro", "orbita", True,
         _h("#120e3a", 205), _h("#aab3e6", 90), "#ffffff", "#aab3e6", "#8ea2ff", "#b7c4ff", "#0f0c33", "#1b1752",
         24, 1, None, True, ("#ffd479", "#ff9bd2", "#7fe7c4", "#8ea2ff"), "borde", ("Space Grotesk", "Segoe UI"), (), False, "normal", False, False, "redonda"),
    Tema("vidrio", "Vidrio azul", "Vidrio azul translúcido", "grid", True,
         _h("#162242", 205), _h("#aac4ff", 60), "#eaf0ff", "#a7b8d6", "#5b9dff", "#9fdcff", "#0e1730", "#17254a",
         22, 1, None, False, (), "", ("Manrope", "Segoe UI"), (), False, "normal", False, False, "redonda"),
    Tema("juego", "Estilo juego", "Crema, bordes gruesos y colores pastel", "grid", False,
         _h("#fff8e8"), _h("#3d2f2a"), "#3d2f2a", "#6d5a52", "#4aa57a", "#2f7d5c", "#fff3da", "#ffffff",
         26, 3, (0, 7, (0, 0, 0, 70)), False, ("#ffd2a8", "#bfe8cf", "#bcdcf5", "#ffeba0", "#d9cdf5"), "banda",
         ("Nunito", "Segoe UI"), ("Fredoka", "Segoe UI Semibold"), False, "ninguna", False, False, "segmentos"),
    Tema("editorial", "Editorial claro", "Claro, limpio, como revista", "grid", False,
         _h("#ffffff"), _h("#e4ddcf"), "#1f2430", "#5b6270", "#d9623b", "#b84a28", "#f4f1ea", "#ffffff",
         16, 1, None, False, (), "", ("DM Sans", "Segoe UI"), ("Fraunces", "Georgia"), False, "ninguna", False, False, "linea"),
    Tema("terminal", "Terminal", "Consola verde sobre negro", "grid", True,
         _h("#07120c", 240), _h("#5dffa0", 115), "#b6f5c5", "#6fa27d", "#5dffa0", "#8dffc0", "#070b09", "#0d1a12",
         0, 1, None, False, (), "", ("Cascadia Mono", "Consolas", "IBM Plex Mono"), (), False, "llaves", True, False, "bloques"),
    Tema("neobrutalista", "Neobrutalista", "Amarillo, bordes negros y sombras duras", "grid", False,
         _h("#ffffff"), _h("#111111"), "#111111", "#333333", "#ff6fb1", "#c2185b", "#ffe94a", "#ffffff",
         0, 4, (8, 8, (17, 17, 17, 255)), False, ("#ffffff", "#7ee8fa", "#b6f23a", "#ffb347", "#ff6fb1"), "relleno",
         ("Archivo", "Segoe UI"), ("Archivo Black", "Arial Black"), True, "ninguna", False, False, "gruesa"),
    Tema("cinta", "Cinta compacta", "Barra delgada arriba: casi no tapa nada", "cinta", True,
         _h("#0a0e1e", 228), _h("#a0b4ff", 56), "#eef2ff", "#a9b4d6", "#7f9bff", "#b9c8ff", "#0b1020", "#151c36",
         18, 1, None, False, (), "", ("Manrope", "Segoe UI"), (), False, "normal", False, False, "redonda"),
    Tema("reloj", "Reloj del día", "Anillo de 24 horas con tu día en el centro", "reloj", True,
         _h("#1e140e", 228), _h("#fbeee0", 40), "#fbeee0", "#cdb7a3", "#ff7a59", "#ffb08f", "#17120f", "#261b14",
         22, 1, None, False, (), "", ("Outfit", "Segoe UI"), (), False, "normal", False, False, "redonda"),
    Tema("hud", "HUD clásico", "El HUD original: cian con esquinitas", "grid", True,
         _h("#060c16", 232), _h("#5ac8ff", 110), "#dcebf7", "#7f9bb3", "#5ac8ff", "#9fdcff", "#0e1626", "#152238",
         6, 1, None, False, (), "", ("Segoe UI",), (), False, "punto", True, True, "linea"),
)}

_estado = {"id": DEFAULT, "oyentes": []}


def lista() -> list:
    """[(id, nombre, descripción)] en el orden que sale en Ajustes (el predeterminado primero)."""
    orden = [DEFAULT] + [k for k in TEMAS if k != DEFAULT]
    return [(k, TEMAS[k].nombre, TEMAS[k].desc) for k in orden]


def get(id_: str | None = None) -> Tema:
    return TEMAS.get(id_ or _estado["id"]) or TEMAS[DEFAULT]


def actual() -> Tema:
    return get(_estado["id"])


def alpha(c: tuple, a: float) -> str:
    return f"rgba({c[0]},{c[1]},{c[2]},{int(max(0, min(1, a)) * 255)})"


def rgba(c: tuple) -> str:
    return f"rgba({c[0]},{c[1]},{c[2]},{c[3]})"


def familias(t: Tema, titulo: bool = False) -> str:
    fam = (t.fuente_titulo if titulo and t.fuente_titulo else t.fuente)
    return ", ".join(f'"{f}"' for f in fam)


def qfont(t: Tema, px: int, bold: bool = False, titulo: bool = False):
    from PySide6.QtGui import QFont
    f = QFont()
    f.setFamilies(list((t.fuente_titulo if titulo and t.fuente_titulo else t.fuente)))
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def qss(t: Tema | None = None) -> str:
    """Hoja de estilo de TODA la aplicación (Ajustes, diálogos, menús). La mini ventana y el dashboard se pintan con los mismos colores."""
    t = t or actual()
    ac = t.acento
    suave = f"rgba({int(ac[1:3], 16)},{int(ac[3:5], 16)},{int(ac[5:7], 16)},0.22)"
    brd = rgba(t.borde) if t.borde[3] > 120 else alpha(t.borde, 0.5)
    bpx = max(1, min(t.borde_px, 2))
    rad = min(t.radio, 14)
    txt_sobre_ac = "#111111" if t.oscuro else "#ffffff"
    return f"""
QDialog, QMessageBox, QInputDialog, QFileDialog {{ background:{t.ventana}; color:{t.texto}; font-family:{familias(t)}; }}
QDialog QWidget {{ font-family:{familias(t)}; }}
QDialog QLabel, QDialog QCheckBox, QDialog QRadioButton, QMessageBox QLabel {{ color:{t.texto}; background:transparent; }}
QLabel#nota, QLabel#tenue {{ color:{t.tenue}; }}
QLabel#aviso {{ color:#e5484d; }}
QDialog QPushButton {{ background:{t.campo}; color:{t.texto}; border:{bpx}px solid {brd}; border-radius:{rad}px; padding:6px 14px; }}
QDialog QPushButton:hover {{ border-color:{ac}; }}
QDialog QPushButton:checked {{ background:{suave}; border:2px solid {ac}; font-weight:600; }}
QDialog QPushButton:default {{ background:{ac}; color:{txt_sobre_ac}; border-color:{ac}; }}
QDialog QComboBox, QDialog QLineEdit, QDialog QSpinBox, QDialog QTimeEdit, QDialog QListWidget, QDialog QPlainTextEdit, QDialog QTextEdit
  {{ background:{t.campo}; color:{t.texto}; border:{bpx}px solid {brd}; border-radius:{rad}px; padding:4px 8px; selection-background-color:{ac}; selection-color:{txt_sobre_ac}; }}
QDialog QComboBox QAbstractItemView {{ background:{t.ventana}; color:{t.texto}; border:1px solid {brd}; selection-background-color:{ac}; selection-color:{txt_sobre_ac}; }}
QDialog QComboBox::drop-down {{ border:none; width:22px; }}
QDialog QCheckBox::indicator, QDialog QRadioButton::indicator {{ width:16px; height:16px; border:{bpx}px solid {brd}; background:{t.campo}; border-radius:{min(rad, 5)}px; }}
QDialog QRadioButton::indicator {{ border-radius:8px; }}
QDialog QCheckBox::indicator:checked, QDialog QRadioButton::indicator:checked {{ background:{ac}; border-color:{ac}; }}
QDialog QSlider::groove:horizontal {{ height:6px; background:{alpha(t.borde, 0.35)}; border-radius:3px; }}
QDialog QSlider::sub-page:horizontal {{ background:{ac}; border-radius:3px; }}
QDialog QSlider::handle:horizontal {{ background:{ac}; width:16px; height:16px; margin:-6px 0; border-radius:8px; border:{bpx}px solid {brd}; }}
QDialog QScrollArea, QDialog QScrollArea > QWidget > QWidget {{ background:transparent; border:none; }}
QDialog QScrollBar:vertical {{ background:transparent; width:10px; margin:0; }}
QDialog QScrollBar::handle:vertical {{ background:{alpha(t.borde, 0.6)}; border-radius:5px; min-height:30px; }}
QDialog QScrollBar::add-line, QDialog QScrollBar::sub-line {{ height:0; width:0; }}
QDialog QListWidget::item:selected {{ background:{suave}; color:{t.texto}; }}
QDialog QGroupBox {{ border:{bpx}px solid {brd}; border-radius:{rad}px; margin-top:10px; padding-top:8px; }}
QMenu {{ background:{t.ventana}; color:{t.texto}; border:{bpx}px solid {brd}; border-radius:{min(rad, 10)}px; padding:4px; font-family:{familias(t)}; }}
QMenu::item {{ padding:6px 22px 6px 14px; border-radius:6px; }}
QMenu::item:selected {{ background:{suave}; color:{t.texto}; }}
QMenu::separator {{ height:1px; background:{alpha(t.borde, 0.4)}; margin:4px 8px; }}
QToolTip {{ background:{t.ventana}; color:{t.texto}; border:1px solid {brd}; padding:4px 8px; }}
"""


def cambiar(id_: str | None) -> Tema:
    """Pone el tema (None = el predeterminado), reaplica la hoja de estilo a toda la app y avisa a quien lo necesite (dashboard, mini ventana)."""
    _estado["id"] = id_ if id_ in TEMAS else DEFAULT
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss())
    except Exception:                                    # noqa: BLE001
        pass
    for fn in list(_estado["oyentes"]):
        try:
            fn(actual())
        except Exception:                                # noqa: BLE001
            pass
    return actual()


def al_cambiar(fn) -> None:
    """Registra fn(tema) para que se llame cada vez que se cambie de tema."""
    _estado["oyentes"].append(fn)
