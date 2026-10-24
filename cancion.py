"""¿Qué canción suena? Lee el TÍTULO de la ventana de Spotify o la pestaña de YouTube (no escucha ni sube nada) y adivina el género
con un diccionario local de palabras y artistas. Orbi lo usa para elegir cómo baila (salsa, cumbia, reggaetón, rock...).
Si la canción no está en el diccionario, baila según el tempo y los graves que detecta audio_react.py.

Para añadir artistas o palabras: edita GENEROS (todo en minúsculas y sin acentos).
"""
import json, re, unicodedata
from pathlib import Path

GENEROS = {
    "salsa": ("salsa", "tumbao", "celia cruz", "marc anthony", "hector lavoe", "willie colon", "gran combo", "ruben blades", "oscar d leon",
              "tito puente", "joe arroyo", "grupo niche", "fania", "la india", "gilberto santa rosa", "victor manuelle", "eddie palmieri",
              "ismael rivera", "tito nieves", "buena vista", "sonora ponceña", "son cubano", "guaguanco", "mambo"),
    "cumbia": ("cumbia", "angeles azules", "celso pina", "sonora dinamita", "sonora santanera", "los palmeras", "kumbia kings", "selena",
               "grupo cañaveral", "grupo canaveral", "la sonora", "cumbion", "sonidero", "rebelde", "raymix", "electrocumbia", "ke personajes",
               "los askis", "cumbia pop"),
    "bachata": ("bachata", "romeo santos", "aventura", "prince royce", "merengue", "juan luis guerra", "elvis crespo"),
    "reggaeton": ("reggaeton", "reguetón", "perreo", "dembow", "bad bunny", "daddy yankee", "don omar", "wisin", "yandel", "j balvin", "karol g",
                  "ozuna", "anuel", "feid", "rauw alejandro", "myke towers", "natti natasha", "maluma", "nicky jam", "farruko", "sech", "bzrp"),
    "hiphop": ("hip hop", "hiphop", "rap", "trap", "kendrick", "drake", "eminem", "travis scott", "21 savage", "2pac", "tupac", "notorious",
               "snoop dogg", "dr dre", "post malone", "c tangana", "lil ", "kanye", "j cole", "nicki minaj", "cardi b", "mc "),
    "metal": ("metal", "metallica", "slipknot", "iron maiden", "black sabbath", "megadeth", "sepultura", "pantera", "system of a down",
              "avenged", "rammstein", "disturbed", "korn"),
    "rock": ("rock", "punk", "grunge", "queen", "led zeppelin", "ac dc", "acdc", "nirvana", "foo fighters", "guns n roses", "red hot chili",
             "linkin park", "green day", "soda stereo", "caifanes", "enjambre", "zoe", "cafe tacvba", "molotov", "the beatles", "rolling stones",
             "arctic monkeys", "imagine dragons", "coldplay", "my chemical", "blink 182", "fall out boy", "paramore", "mana", "heroes del silencio"),
    "electronica": ("edm", "house", "techno", "trance", "dubstep", "electronica", "avicii", "calvin harris", "david guetta", "martin garrix",
                    "skrillex", "daft punk", "marshmello", "deadmau5", "tiesto", "alan walker", "zedd", "kygo", "swedish house", "bassnectar",
                    "drum and bass", "dnb", "hardstyle", "remix", "dj "),
    "regional": ("corrido", "corridos", "banda", "norteno", "regional mexicano", "tumbados", "peso pluma", "grupo frontera", "fuerza regida",
                 "junior h", "natanael cano", "eslabon armado", "gerardo ortiz", "banda ms", "el fantasma", "tigres del norte", "tucanes",
                 "intocable", "ramon ayala", "chalino", "calibre 50", "los plebes", "luis r conriquez", "xavi", "polka", "grupo firme", "los dos carnales", "carin leon",
                 "christian nodal", "grupo pesado"),
    "ranchera": ("mariachi", "ranchera", "vicente fernandez", "pedro infante", "jorge negrete", "alejandro fernandez", "jose alfredo",
                 "rocio durcal", "antonio aguilar", "javier solis", "lola beltran", "bolero ranchero"),
    "suave": ("lofi", "lo fi", "lofi hip hop", "lo fi hip hop", "chill", "relax", "ambient", "piano", "jazz", "bossa", "acoustic", "acustica", "instrumental", "study",
              "balada", "romantica", "bolero", "luis miguel", "juan gabriel", "jose jose", "camila", "reik", "sin bandera", "ricardo arjona",
              "beethoven", "mozart", "bach", "chopin", "vivaldi", "clasica", "symphony", "sinfonia", "orquesta", "adele", "sam smith", "lana del rey"),
    "disco": ("disco", "funk", "soul", "motown", "michael jackson", "earth wind", "bee gees", "abba", "donna summer", "jamiroquai", "bruno mars",
              "dua lipa", "doja cat", "lizzo"),
    "pop": ("pop", "taylor swift", "the weeknd", "ariana grande", "ed sheeran", "shakira", "justin bieber", "billie eilish", "harry styles",
            "olivia rodrigo", "kpop", "k pop", "bts", "blackpink", "twice", "stray kids", "newjeans", "katy perry", "lady gaga", "rosalia",
            "sabrina carpenter", "selena gomez", "miley cyrus", "one direction", "camilo", "sebastian yatra"),
}

# géneros → cómo baila Orbi (los nombres son los de DANCE_STYLES en orb.py)
GENERO_A_ESTILO = {"salsa": "salsa", "cumbia": "cumbia", "bachata": "bachata", "reggaeton": "reggaeton", "hiphop": "hiphop",
                   "metal": "metal", "rock": "rock", "electronica": "electronica", "regional": "regional", "ranchera": "regional",
                   "suave": "suave", "disco": "disco", "pop": "pop"}

# estilo que detecta el audio (tempo y graves) → cómo baila cuando no se conoce la canción
AUDIO_A_ESTILO = {"suave": "suave", "balanceo": "cumbia", "grave": "reggaeton", "pop": "pop", "fiesta": "electronica", "intenso": "rock"}

SPOTIFY_IDLE = {"spotify", "spotify free", "spotify premium", "spotify - web player"}
_NAV = ("chrome.exe", "msedge.exe", "brave.exe", "firefox.exe", "opera.exe", "vivaldi.exe")


def fold(t: str) -> str:
    t = unicodedata.normalize("NFD", str(t).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " " + re.sub(r"[^a-z0-9 ]+", " ", t) + " "


def _limpia(titulo: str) -> str:
    t = re.sub(r"^\(\d+\)\s*", "", titulo)                         # «(3) » = notificaciones de YouTube
    t = re.sub(r"\s+[-–—]\s+(YouTube Music|YouTube)\s*$", "", t)
    t = re.sub(r"\s*[-–—]\s*(Google Chrome|Microsoft\u200b? Edge|Brave|Mozilla Firefox).*$", "", t)
    return t.strip()


def actual(ventanas=None) -> str:
    """Texto «Artista - Canción» (o el título del video) de lo que suena ahora, o «» si no se sabe.
    `ventanas`: lista de dict(title, exe) (para pruebas); si no, usa windows.list_windows()."""
    if ventanas is None:
        try:
            import windows
            ventanas = windows.list_windows()
        except Exception:                                          # noqa: BLE001
            return ""
    yt = ""
    for w in ventanas:
        exe, title = (w.get("exe") or "").lower(), (w.get("title") or "").strip()
        if exe == "spotify.exe" and title.lower() not in SPOTIFY_IDLE and " - " in title:
            return title                                           # Spotify: «Artista - Canción» solo mientras suena
        if exe in _NAV and re.search(r"[-–—]\s*YouTube( Music)?\s*(?:[-–—].*)?$", title) and not yt:
            yt = _limpia(title)
    return yt


def genero(texto: str) -> str:
    """Género adivinado por palabras y artistas conocidos, o «» si no se reconoce. Gana el que coincida con la palabra más larga."""
    f = fold(texto)
    mejor, largo = "", 0
    for gen, claves in GENEROS.items():
        for c in claves:
            k = fold(c)
            if k in f and len(k) > largo:
                mejor, largo = gen, len(k)
    return mejor


def estilo(genero_: str, estilo_audio: str) -> str:
    """Estilo de baile final: el del género si se conoce; si no, el que sale del tempo y los graves."""
    return GENERO_A_ESTILO.get(genero_) or AUDIO_A_ESTILO.get(estilo_audio) or "pop"


# --- canciones que el diccionario no conoce: se le pregunta UNA vez a Gemini y se recuerda (orbi_generos.json) -----------------------
VALIDOS = tuple(GENERO_A_ESTILO) + ("ninguno",)
PROMPT_IA = ("Clasifica esta canción por género musical. Responde SOLO con una palabra de esta lista: salsa, cumbia, bachata, reggaeton, "
             "hiphop, metal, rock, electronica, regional, ranchera, suave, disco, pop, ninguno. Usa «cumbia» también para cumbia electrónica "
             "o sonidera, «regional» para corridos, banda y norteño, «suave» para baladas, lo-fi y música clásica, y «ninguno» si no es "
             "música o no la conoces.\nCanción: {t}")
_CACHE = {"d": None}


def _cache_path() -> Path:
    return Path(__file__).parent / "orbi_generos.json"


def _cache() -> dict:
    if _CACHE["d"] is None:
        try:
            _CACHE["d"] = json.loads(_cache_path().read_text(encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            _CACHE["d"] = {}
    return _CACHE["d"]


def cache_get(texto: str):
    """Género recordado de esa canción (puede ser «ninguno»), o None si nunca se ha preguntado."""
    return _cache().get(fold(texto).strip())


def cache_put(texto: str, gen: str):
    d = _cache()
    d[fold(texto).strip()] = gen
    if len(d) > 2000:
        for k in list(d)[:200]:
            d.pop(k, None)
    try:
        _cache_path().write_text(json.dumps(d, ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception:                                              # noqa: BLE001
        pass


def parse_ia(texto: str) -> str:
    """Saca el género de la respuesta del modelo (primera palabra válida); «ninguno» si no se entiende."""
    for w in fold(texto).split():
        if w in VALIDOS:
            return w
    return "ninguno"
