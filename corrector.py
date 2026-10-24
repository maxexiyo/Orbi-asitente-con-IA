"""Corrector de ortografía que NO estorba: espera a que termines de escribir, revisa lo que quedó en el campo donde estabas y te AVISA
en la burbuja de Orbi. Nunca mueve el mouse, no pulsa teclas, no roba el foco y no escribe en tu documento.

  · «Termines de escribir» = pasaron `espera_s` segundos sin tocar teclado ni mouse DESPUÉS de haber escrito. Una sola revisión por pausa.
  · Lee el campo con UI Automation (pip install uiautomation), solo en ese momento, y NUNCA campos de contraseña ni apps excluidas.
  · Revisa con el diccionario de LibreOffice en español de México (carpeta diccionario_es, motor `pip install spylls`): todo corre
    en tu PC, nada se manda a internet.
  · Para aplicar las correcciones, Ctrl+Alt+K deja el texto corregido en el portapapeles (tú lo pegas con Ctrl+V). Con
    "corrector_aplicar": "campo" en config.json intenta escribirlo directo en campos de texto simples.
  · Tus palabras propias van en orbi_diccionario.txt (una por línea) y no se vuelven a marcar.

Limitación honesta: UI Automation no deja leer el texto de todas las apps (Word y los navegadores a veces sí, a veces no). Donde no se
puede leer, simplemente no avisa. Un corrector ortográfico no detecta errores de contexto (hay/ahí/ay, a ver/haber).
"""
import re, threading, time
from pathlib import Path

WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")
SKIP_TOKEN = re.compile(r"\S*(?:://|www\.|@|\\|/)\S*")          # enlaces, correos y rutas no se revisan
PROPIAS_DEFAULT = ("orbi", "bolita", "bolitas", "wey", "weyes", "güey", "bro", "ceti", "jira", "sprint", "sprints", "gemini", "whatsapp",
                  "youtube", "spotify", "chrome", "excel", "powerpoint", "outlook", "gmail", "classroom", "zoom", "meet", "teams", "github")
EXCLUIR_EXE = {"keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "lastpass.exe", "dashlane.exe"}


def _dic_path() -> Path:
    return Path(__file__).parent / "orbi_diccionario.txt"


def palabras_propias(extra=()) -> set:
    out = {str(w).strip().lower() for w in extra if str(w).strip()}
    try:
        out |= {l.strip().lower() for l in _dic_path().read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
    except OSError:
        pass
    return out


def _mantener_mayusculas(orig: str, nueva: str) -> str:
    if orig.isupper() and len(orig) > 1:
        return nueva.upper()
    if orig[:1].isupper():
        return nueva[:1].upper() + nueva[1:]
    return nueva


class Corrector:
    def __init__(self, on_text, set_clipboard=None, espera_s=2.5, min_len=4, extra_words=(), debug=False, leer=None, spell=None, idle=None):
        """on_text(msg): aviso para la burbuja · set_clipboard(txt): pone texto en el portapapeles (hilo principal) ·
        leer/spell/idle: solo para pruebas (si no, usan UI Automation, pyspellchecker y GetLastInputInfo)."""
        self.on_text, self.set_clipboard = on_text, set_clipboard
        self.espera_s, self.min_len, self.debug = max(1.0, float(espera_s)), max(3, int(min_len)), debug
        self.enabled = False
        self.aplicar_en = "portapapeles"                      # o "campo"
        self._leer, self._spell, self._idle = leer, spell, idle
        self._extra = set(extra_words)
        self._activo = False                                  # ¿hubo actividad de teclado/mouse desde la última revisión?
        self._busy = False
        self._visto = set()                                   # palabras ya avisadas (no se repite el aviso)
        self.last = None                                      # {"text","fixes","can_set"} de la última revisión con errores
        self._falla = False

    # ------------------------------------------------------------------ cuándo revisar
    def tick(self):
        """Llamar cada ~0.5 s desde el hilo principal. Revisa UNA vez cuando terminas de escribir."""
        if not self.enabled or self._busy:
            return
        idle = self._idle() if self._idle else _idle_seconds()
        if idle < self.espera_s:
            self._activo = True                               # sigues escribiendo (o moviendo el mouse): espera
            return
        if self._activo and idle < self.espera_s + 2.0:       # justo hiciste una pausa: ahora sí
            self._activo = False
            self._busy = True
            threading.Thread(target=self._revisar_en_hilo, daemon=True).start()

    def _revisar_en_hilo(self):
        try:
            leido = self._leer() if self._leer else _leer_campo()
            if not leido or not leido.get("text"):
                return
            if leido.get("password") or (leido.get("exe") or "").lower() in EXCLUIR_EXE:
                return
            fixes = self.revisar(leido["text"])
            if self.debug:
                print(f"[corrector] {len(leido['text'])} caracteres en {leido.get('exe') or '?'}: {len(fixes)} posibles errores {fixes[:4]}")
            if not fixes:
                self.last = None
                return
            self.last = {"text": leido["text"], "fixes": fixes, "can_set": bool(leido.get("can_set"))}
            muestra = " · ".join(f"{a} → {b}" for a, b in fixes[:3]) + (f" (+{len(fixes) - 3} más)" if len(fixes) > 3 else "")
            self.on_text(f"✏️ {muestra}\nCtrl+Alt+K = copiar el texto corregido")
        except Exception as e:                                # noqa: BLE001
            if self.debug or not self._falla:
                print(f"[corrector] {type(e).__name__}: {str(e)[:120]}")
            self._falla = True
        finally:
            self._busy = False

    # ------------------------------------------------------------------ revisión
    def _sp(self):
        if self._spell is None:
            from spylls.hunspell import Dictionary
            self._spell = Dictionary.from_files(str(Path(__file__).parent / "diccionario_es" / "index"))
        return self._spell

    @staticmethod
    def _fon(w: str) -> str:
        """Forma «fonética» para comparar (sin acentos; k=c, v=b, z=s, h muda, ll=y): komo ≈ como, prueva ≈ prueba."""
        w = w.lower().translate(str.maketrans("áéíóúü", "aeiouu"))
        for a_, b_ in (("qu", "k"), ("c", "k"), ("v", "b"), ("z", "s"), ("ll", "y"), ("h", ""), ("w", "g")):
            w = w.replace(a_, b_)
        return w

    @staticmethod
    def _dist(a: str, b: str) -> int:
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]

    def _mejor(self, sp, w: str):
        """La mejor sugerencia para una palabra mal escrita (o None): primero ponerle el acento que le falta (ortografia → ortografía),
        si no, la sugerencia de Hunspell más cercana por sonido."""
        low = w.lower()
        acentos = []
        for i, ch in enumerate(low):
            for rep in {"a": "á", "e": "é", "i": "í", "o": "ó", "u": "ú"}.get(ch, ""):
                cand = low[:i] + rep + low[i + 1:]
                if sp.lookup(cand):
                    acentos.append(cand)
        if len(acentos) == 1:
            return acentos[0]
        sug = [s for s in list(sp.suggest(low))[:10] if s and s != low and " " not in s]
        if not sug:
            return acentos[0] if acentos else None
        f = self._fon(low)
        ranked = sorted(enumerate(sug), key=lambda p: (self._dist(f, self._fon(p[1])), p[0]))
        mejor = ranked[0][1]
        return mejor if self._dist(f, self._fon(mejor)) <= max(1, len(low) // 3) else None

    def revisar(self, texto: str) -> list:
        """[(mal escrita, sugerida)] sin repetir; ignora nombres propios, siglas, enlaces, palabras cortas y tu diccionario."""
        sp = self._sp()
        propias = palabras_propias(set(PROPIAS_DEFAULT) | self._extra)
        limpio = SKIP_TOKEN.sub(" ", texto[-6000:])
        fixes, vistas = [], set()
        for m in WORD.finditer(limpio):
            w = m.group(0)
            low = w.lower()
            inicio = m.start() == 0 or re.search(r"[.!?¡¿\n]\s*$", limpio[max(0, m.start() - 4):m.start()]) is not None
            if len(w) < self.min_len or w.isupper() or low in propias or low in self._visto or low in vistas:
                continue
            if w[0].isupper() and not inicio:                  # nombre propio a mitad de frase: no se revisa
                continue
            vistas.add(low)
            if sp.lookup(w) or sp.lookup(low):
                continue
            best = self._mejor(sp, w)
            if best and best != low:
                fixes.append((w, _mantener_mayusculas(w, best)))
                self._visto.add(low)
                if len(fixes) >= 8:                           # tope por pausa: no te llena de avisos ni gasta CPU
                    break
        return fixes

    @staticmethod
    def corregir_texto(texto: str, fixes: list) -> str:
        out = texto
        for mal, bien in fixes:
            out = re.sub(r"(?<![A-Za-zÁÉÍÓÚÜÑáéíóúüñ])" + re.escape(mal) + r"(?![A-Za-zÁÉÍÓÚÜÑáéíóúüñ])", bien, out)
        return out

    # ------------------------------------------------------------------ aplicar (atajo Ctrl+Alt+K, hilo principal)
    def aplicar(self) -> str:
        """Devuelve el mensaje para la burbuja. Por defecto solo deja el texto corregido en el portapapeles."""
        if not self.last:
            return "✏️ No tengo nada que corregir ahora."
        corregido = self.corregir_texto(self.last["text"], self.last["fixes"])
        if self.aplicar_en == "campo" and self.last.get("can_set"):
            try:
                if _escribir_campo(corregido):
                    self.last = None
                    return "✏️ Corregido en el campo."
            except Exception as e:                            # noqa: BLE001
                print(f"[corrector] no pude escribir en el campo: {type(e).__name__}: {str(e)[:100]}")
        if self.set_clipboard:
            self.set_clipboard(corregido)
            self.last = None
            return "✏️ Texto corregido copiado: pégalo con Ctrl+V"
        return "✏️ No pude copiar el texto."

    def agregar_palabra(self, palabra: str):
        """Añade una palabra a tu diccionario propio (orbi_diccionario.txt)."""
        w = palabra.strip().lower()
        if w:
            with open(_dic_path(), "a", encoding="utf-8") as fh:
                fh.write(w + "\n")


# ---------------------------------------------------------------------- Windows (UI Automation); no se usa en las pruebas
def _idle_seconds() -> float:
    try:
        from windows import idle_seconds
        return idle_seconds()
    except Exception:                                          # noqa: BLE001
        return 0.0


def _leer_campo():
    """Texto del campo con foco: {"text","password","exe","can_set"} o None si no se puede leer en esta app."""
    import uiautomation as auto
    with auto.UIAutomationInitializerInThread():
        c = auto.GetFocusedControl()
        if c is None:
            return None
        pw = False
        try:
            pw = bool(c.IsPassword)
        except Exception:                                      # noqa: BLE001
            pass
        exe = ""
        try:
            import windows
            exe = windows._pid_exe(c.ProcessId) or ""
            exe = exe.rsplit("\\", 1)[-1]
        except Exception:                                      # noqa: BLE001
            pass
        if pw:
            return {"text": "", "password": True, "exe": exe}
        text, can_set = "", False
        try:
            tp = c.GetTextPattern()
            if tp is not None:
                text = tp.DocumentRange.GetText(6000) or ""
        except Exception:                                      # noqa: BLE001
            pass
        try:
            vp = c.GetValuePattern()
            if vp is not None:
                if not text:
                    text = vp.Value or ""
                can_set = not vp.IsReadOnly
        except Exception:                                      # noqa: BLE001
            pass
        return {"text": text, "password": False, "exe": exe, "can_set": can_set}


def _escribir_campo(texto: str) -> bool:
    import uiautomation as auto
    with auto.UIAutomationInitializerInThread():
        c = auto.GetFocusedControl()
        vp = c.GetValuePattern() if c is not None else None
        if vp is None or vp.IsReadOnly:
            return False
        vp.SetValue(texto)
        return True
