# Orbi — asistente de escritorio con bolita azul (Windows)

Bolita con estados, emociones y burbuja de texto; conversa por voz en tiempo real con **Gemini Live**, ve tu pantalla,
hace tareas en tu PC con un **agente**, lee tus archivos, controla tus luces y te avisa de tus notificaciones.

## 1. Instalar (Windows, Python 3.10+)

Doble clic a `instalar.bat` (vuelve a correrlo al actualizar: hay librerías nuevas) o a mano:

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt

**Keys:** usa tu `.env` de siempre (en esta carpeta o en la de arriba): `GEMINI_API_KEY`, `GEMINI_API_KEY_1`, `GEMINI_API_KEYS=k1,k2`,
`GROQ_API_KEY...`, `OPENROUTER_API_KEY...`. También sirve todo en una variable: `GEMINI_API_KEYS=["AIza...","AIza..."]`.
Si tu variable tiene otro nombre: `ORBI_GEMINI_VAR=NOMBRE`. Los ajustes finos van en `config.json` (ver `config.example.json`).

> **Ojo con las cuotas:** los límites de Gemini son **por proyecto de Google Cloud**, no por key, y **por modelo**.
> Dos keys del mismo proyecto comparten cuota. En tu tabla de límites los modelos Live muestran peticiones "Ilimitado" pero
> **tokens por minuto limitados (65K en Gemini 3.x Live)**: por eso lo pesado (documentos largos, capturas de tareas) se
> hace con otro modelo, no por la voz.

> **Modelo Live:** el predeterminado ahora es `gemini-3.8-live`, con `gemini-3.1-flash-live-preview` de respaldo.
> Si en tu `.env` tenías `LIVE_MODEL=gemini-3.1-flash-live-preview`, bórralo o cámbialo.

## 2. Qué correr

| Comando | Para qué |
|---|---|
| `Orbi.vbs` (doble clic) | **Abre la bolita sin consola.** Errores y registro de cada acción en `orbi.log` |
| `python live_orb.py` | Lo mismo, con consola |
| `python live_orb.py --setup` | Vuelve a abrir el asistente de configuración |
| `python live_orb.py --no-tools` | Solo platicar |
| `python live_test.py --models` | Lista los modelos Live de tu cuenta |
| `python wake_test.py` | Prueba la palabra «Orbi» con tu micro (ver qué entiende) |
| `python demo.py` | Solo la bolita (sin internet) |

**Con audífonos** (`--headphones` o `"headphones": true`) puedes interrumpirla mientras habla; sin ellos el micro se calla mientras habla.

## 3. Controles

- **Arrastrar** la bolita; cerca del borde se esconde. **Clic** o **Ctrl+Espacio**: caja para escribirle.
- **Ctrl+Alt+Espacio**: «hablar ahora» (abre la ventana de conversación sin decir «Orbi»).
- **Ctrl+Alt+O** o el **icono junto al reloj** (bandeja): trae a Orbi si se perdió detrás de otra ventana.
- **Clic derecho**: menú (micro, modo de escucha, pantalla continua, compañero, notificaciones, control, detener tarea, configurar…).
- **Tamaño** `orb_scale` (0.72 por defecto; 1.0 = el original) y **sueño** `sleep_after_s` (900 s; 0 = nunca) en `config.json`.
  Nunca se duerme mientras hay una tarea, el modo compañero o las notificaciones activas.

## 4. Primera vez: te conoce

Un asistente pregunta nombre/apodo, tono, a qué te dedicas, intereses, **cómo quieres que te escuche** y **qué permisos le das**.
Se guarda en `orbi_profile.json` (solo en tu PC). Cámbialo con clic derecho → **Configurar a Orbi…**. Orbi también anota cosas
tuyas con la tool `recordar`.

## 5. ¿Cuándo me hablan a mí? (escucha)

Tres modos (menú → Escucha):
- **Solo si digo «Orbi»** (recomendado): en espera, tu voz **no sale de la PC** (la palabra clave se detecta local con Vosk).
  Al oírla abre una **ventana de conversación** de ~25 s que se renueva mientras platican; si te despides («gracias, es todo»)
  o hay silencio, vuelve a la espera. Lo que dijiste justo antes («Orbi, ¿qué hora es?») no se pierde (pre-roll de 1.6 s).
  La primera vez descarga un modelo de voz pequeño (~40 MB). Si falla, Orbi avisa y cae a «atajo» sin romperse.
  Prueba y ajusta con `python wake_test.py`; alias y sensibilidad en `config.json` (`wake_aliases`, `wake_threshold`).
- **Solo con atajo**: Ctrl+Alt+Espacio abre la ventana.
- **Siempre**: como antes. Con `gemini-3.8-live` el modelo ya filtra mejor lo que no es para él, y el prompt le prohíbe
  responder a plática ajena o inventar familiares/hechos de tu vida.

## 6. Agente: tareas de varios pasos (y en segundo plano)

La voz solo conversa. Para cualquier cosa de varios pasos llama a **`tarea_pc`**: un **agente** (modelo normal de Gemini con visión y
function calling, `agent_model`) trabaja por su cuenta hasta terminar — con captura de cómo quedó cada paso — y la voz te cuenta
el resultado. Mientras trabaja puedes seguir platicando; **menú → Detener tarea** la cancela (tope: 30 pasos / 4 min).
Prefiere herramientas **sin ver ni enfocar nada**: `cerrar_ventana` / `minimizar_ventana` (por programa o título, p. ej. todas las del
Explorador de una vez), `listar_ventanas`, archivos, casa. Mouse y teclado solo si no hay otra forma.
Escribir texto usa **SendInput Unicode** (no el portapapeles), mucho más confiable en Discord/Electron.

**Permisos:** lo normal (clic, escribir, cambiar de ventana, cerrar, volumen, abrir apps/páginas) no pide OK. Lo **delicado** (enviar
mensajes/correos, publicar, pagar, borrar, abrir cocheras) sí, con diálogo Sí/No. Lo decide la IA (`delicada=true`) **más un respaldo
propio** que mira la ventana activa (WhatsApp, Gmail, Discord, banco, checkout…). Interruptor general: menú → *Control de la PC activo*;
mouse a la esquina superior izquierda corta pyautogui; máx. 60 acciones/min; Alt+F4, Win+R, Ctrl+Alt+Supr… bloqueadas.

## 7. Documentos y archivos (sin abrirlos)

Permiso «archivos» (solo Documentos, Escritorio y Descargas, incluido OneDrive):
`buscar_archivos` (nombre), `buscar_en_archivos` (contenido de texto/código/Word/PowerPoint), `leer_archivo` (por partes),
`abrir_archivo` (por ruta o solo nombre) y **`analizar_documento`**: revisa un documento **completo**, por largo que sea, con un modelo
de contexto largo (`analysis_model`) y le devuelve a la voz un resumen corto citando párrafo/línea/página.
`fuente="abierto"` = el documento de la ventana activa (Word, PDF, VS Code…): se ubica por el título. Si es una página web o un
documento sin guardar, el agente lo copia con `copiar_texto_de_ventana` (Ctrl+A/C, restaura tu portapapeles).
Lee `.docx .pptx .xlsx .pdf` y texto/código; los PDF escaneados (imagen) no se pueden sin OCR. Nunca abre `.exe/.bat/.py/...`.

## 8. Casa inteligente

Alexa **no** tiene una API para que una app de PC prenda tus focos, así que Orbi usa **Home Assistant** (gratis; Raspberry Pi, PC vieja o
Docker), que integra Tuya/Smart Life, Hue, TP-Link Kasa, WiZ, Shelly, Xiaomi… (y puede exponerlos a Alexa si quieres).
En tu `.env`: `HA_URL=http://homeassistant.local:8123` y `HA_TOKEN=...` (Perfil de usuario de HA → Seguridad → Token de larga duración).
Activa «casa» en el asistente. Orbi controla luces, enchufes, ventiladores, persianas, escenas y clima («enciende la luz del cuarto», «brillo
al 40», «ponla azul»). **No** expone cerraduras ni alarmas; cocheras/portones piden tu OK.

## 9. Notificaciones

Permiso «notificaciones». Orbi lee la base de datos de notificaciones de Windows (`wpndatabase.db`) cada pocos segundos. Las **clasifica**
(mensajes, correo, calendario, seguridad, descargas, otras), **solo avisa** de las categorías que dejaste activas, **no molesta** en
pantalla completa ni en tus horas de silencio, **agrupa** («3 mensajes de Mamá en WhatsApp»), por **privacidad** dice quién escribió pero no
lee el contenido (a menos que preguntes «¿qué decía?» → `leer_notificaciones`), deja pasar a tus **VIP** siempre y tiene tope de avisos
por minuto. Todo se ajusta en `config.json` → `"notificaciones"` (ver ejemplo). Menú → *Probar notificaciones* escribe un diagnóstico en `orbi.log`.
Límites: depende de que tu Windows siga usando ese archivo y de que la app muestre la notificación; el texto lo pone la app.

## 10. Modo compañero (observador)

Menú → *Modo compañero*. Cada ~25 s mira la pantalla **solo si cambió** y un modelo ligero (`observer_model`) decide si hay algo que valga la
pena decir (error visible, typo, mejor forma de hacerlo). Espera 4 min tras cada comentario, máx. 6/hora, no habla en pantalla completa ni
mientras platicas o corre una tarea, y **ni captura** ventanas de banco/contraseñas/incógnito. Las capturas se mandan a Gemini mientras esté activo.

## 11. Si algo falla

- **Siempre mira `orbi.log`**: cada tool queda como `[tool] nombre {args} -> ok/ERROR … (segundos)`, y ahí salen errores de keys/cuota.
- **Errores de keys**: ya no se rinde para siempre; reintenta con espera creciente, enfría cada key según el error (cuota por modelo, key
  inválida, red) y cambia al modelo de respaldo. El mensaje dice el motivo real (sin cuota / key inválida / red).
- **La bolita desapareció**: Ctrl+Alt+O, o clic en el icono de la bandeja (junto al reloj). Además re-afirma «siempre encima» cada 1.5 s.
- **No me oye con «Orbi»**: `python wake_test.py`; agrega alias en `wake_aliases` o cambia a modo «atajo».

## 12. Archivos

    orb.py            la bolita (estados, emociones, burbuja, tamaño, siempre-encima)
    live_client.py    Gemini Live: keys con enfriamiento, modelos de respaldo, reconexión sin rendirse, compuerta de micro
    live_orb.py       une todo: bolita, voz, agente, escucha, casa, notificaciones, bandeja, atajos
    agent.py          agente de varios pasos (function calling + capturas)
    attention.py      ventana de conversación + palabra clave local «Orbi» (Vosk)
    llm.py            pool de keys y generate_content con fallback de modelos
    pc_tools.py       todas las tools (voz vs agente), permisos y confirmaciones delicadas
    docs_reader.py    leer/buscar docx, pptx, xlsx, pdf, texto sin abrirlos
    smart_home.py     Home Assistant      ·  notifications.py  notificaciones de Windows
    windows.py        ventanas (listar, cerrar, minimizar en segundo plano, topmost)  ·  winput.py  escribir con SendInput
    screen.py         capturas       ·  observer.py  modo compañero
    perfil.py / onboarding.py   perfil del dueño, prompt y asistente
    ai/router.py      respaldo de texto (Groq → Gemini → OpenRouter) con errores clasificados

## 13. Seguridad

Lo que aparece en pantalla (páginas, chats, documentos) puede traer texto que intente darle órdenes a la IA (*prompt injection*): los prompts
lo prohíben, las acciones delicadas piden tu OK con un respaldo que no depende de la IA, y las tools usan listas blancas (apps, carpetas,
extensiones). No hay shell y **nunca se borra ni se sobrescribe** un archivo (mover/organizar/escribir solo dentro de Documentos, Escritorio y
Descargas, con registro para deshacer). Aun así, cuida el control activo con sitios desconocidos abiertos.

## Expresividad, intérprete y audio de la PC

- **Colores y caras**: `set_emotion` (happy, love, sad, surprised, thinking, angry, excited…); el color de la bolita cambia con la emoción.
- **Moverse y señalar**: «ven para acá / ponte en la esquina» (`mover_bolita`) y «¿dónde está el botón X?» (`senalar`: ver_pantalla +
  anillo pulsante junto al elemento).
- **Acariciarla**: pasa el mouse de un lado a otro sobre la bolita (sin clic) varias veces y se pone feliz con corazones.
- **Compañero libre**: sin temporizador de silencio ni tope por hora; la IA decide si habla. Para volver a poner límites:
  `config.json` → `"companero": {"revisar_cada_s": 20, "pausa_tras_comentario_s": 240, "max_por_hora": 6}`.
- **Intérprete** («Orbi, sé mi intérprete de español a inglés»): traduce en voz alta todo lo que oiga, sin conversar, y el micro queda
  siempre abierto hasta «termina el modo intérprete». Funciona mejor con audífonos (sin ellos no te oye mientras habla).
- **Audio de la PC** (permiso «audio_pc», apagado por defecto): «escucha lo que suena y tradúcelo» graba 3 a 30 s del audio de tus
  bocinas (WASAPI loopback, librería `soundcard`, solo Windows), se lo manda a Gemini y no guarda nada.

## Calendario y correo (solo lectura)

Permiso «agenda» (Configurar a Orbi…). Sin OAuth ni apps registradas:
- **Calendario**: pega la dirección ICS secreta de cada calendario en `config.json` → `"calendarios"` (Google: Configuración del
  calendario > Integrar calendario > Dirección secreta en formato iCal). Outlook/@ceti.live.mx: «Publicar un calendario» (si tu escuela
  lo bloquea, no hay forma sin registrar una app en Azure). Voz: «¿qué tengo mañana?».
- **Correo (Gmail)**: activa la verificación en 2 pasos, crea una «contraseña de aplicación», ponla en el `.env` como
  `ORBI_MAIL_PASS_PERSONAL=...` y el usuario en `config.json` → `"correo"`. Solo lee y ni siquiera marca como leído.
  El correo de Microsoft no se puede por IMAP con contraseña.
Pide `pip install -r requirements.txt` (icalendar, recurring-ical-events). Orbi no puede enviar ni borrar correos.

## Alarmas, recordatorios y luces WiZ
- **Alarmas / recordatorios:** «ponme una alarma a las 7:30 am», «recuérdame a las 10:20 pm lo de los tokens». Se guardan en
  `orbi_alarmas.json` (sobreviven reinicios). La alarma suena hasta que digas «ya», hagas clic en Orbi o la pospongas.
- **Luces WiZ:** sin Home Assistant. En la app WiZ activa «control local»; PC y focos en la misma red WiFi. Orbi las descubre sola;
  ponles nombre con «al foco 1 llámalo cuarto». Si el descubrimiento falla, en `config.json`: `"wiz": {"cuarto": "192.168.1.50"}`.
  Requiere el permiso «casa inteligente» en «Configurar a Orbi…».


## Rapidez (ajustes)

- **Espera adaptativa**: tras una acción, el agente ya no duerme un tiempo fijo; espera a que la pantalla deje de cambiar
  (`screen.wait_settled`). Los topes viejos (`SETTLE` en `agent.py`) siguen como máximo, y `SETTLE_FLOOR` es lo mínimo si no cambia nada.
- **Estado sin captura**: las tools devuelven `ventana_activa` (y el agente añade `cambio_de_ventana`). `cerrar/minimizar_ventana` y el
  dictado (`escribir_texto` con `ventana`) ya no piden captura.
- **config.json**: `screen_interval_s` (pantalla continua; mínimo 1.0, es el máximo de Live), `agent_shot_side` y `agent_shot_quality`
  (capturas de verificación del agente; la inicial sigue a 1280 px). Si el agente falla leyendo letra chica, sube `agent_shot_side` a 1280.
- **`INPUT_PAUSE`** en `pc_tools.py` (0.04): pausa de pyautogui tras cada pulsación. Si una app se traba con atajos, súbela a 0.08.
- **`agent_thinking`** (config.json, `"low"` por defecto): cuánto piensa el modelo del agente en cada paso. Es lo que más pesa en la
  velocidad. En Gemini 3.8 Flash `"minimal"` da error (según la doc); `"default"` deja el del modelo. Con `gemini-3.8-live` no hay ajuste.
- **Diagnóstico en `orbi.log`**: el agente escribe `[agente] paso N: modelo X s · herramientas Y s · espera Z s` y el modo "Live hace
  todo" escribe `[live] el modelo tardó X s en pedir el siguiente paso`. Con eso se ve dónde se va el tiempo.
- **Planes (`ejecutar_plan`)**: el agente (y la voz en modo "Live hace todo") puede mandar TODA una secuencia de pasos en una sola
  llamada: se ejecutan uno tras otro sin volver al modelo (cada consulta al modelo cuesta segundos; cada herramienta, décimas).
  Entre pasos espera a que la pantalla se asiente, y con `esperar_ventana` espera a que abra/cargue algo (se comprueba por el título o
  programa de la ventana activa, sin ver la pantalla). Se detiene en el primer error o aviso y devuelve lo hecho + una captura. Pasos
  permitidos: abrir_app, abrir_url, buscar_en_web, enfocar/cerrar/minimizar_ventana, escribir_texto, presionar_teclas, hacer_clic,
  scroll, esperar, volumen, multimedia (máx. 15 pasos / 90 s). Las acciones delicadas siguen pidiendo tu OK paso por paso.
- **Diagnóstico**: `[agente] paso N` ahora incluye los tokens (prompt / pensó / salida) y `[llm]` avisa si el ajuste de thinking se aplicó o
  fue rechazado.
- **Arreglo**: `orb.wander()` fallaba con `'list' object is not callable` (un atributo del mismo nombre tapaba el método).

## Huella de voz y fin de turno (rápido, parte 2)
- **Aprender mi voz**: clic derecho en Orbi > «Aprender mi voz (20 s)…», habla normal con pausas. La huella queda en `orbi_voz.json` (solo en tu PC, no se sube). Con «Solo hacerle caso a mi voz» activo, si otra persona habla (o dice «Orbi») se cancela la respuesta de ese turno, incluidas las herramientas.
- **Afinar**: pon `"voz_debug": true` en `config.json` para ver en la burbuja la distancia de cada frase (tú ≈ bajo, otra persona ≈ alto) y ajusta `"voz_umbral"` (por defecto se calibra solo, entre 0.45 y 0.65). Las frases de menos de ~1 s no se juzgan.
- **Fin de turno**: `"fin_turno_ms"` (silencio que espera Live antes de darte por terminado, 1100 por defecto) y `"fin_sensibilidad"` (`low`/`high`). Si aún te corta, súbelo a 1500-2000; si tarda mucho en contestar, bájalo a 800.

## Iniciar sesión con Google (rápido, parte 3): leer y administrar calendario y Gmail
Con la sesión de Google Orbi puede, por voz: ver tu agenda (de TODOS tus calendarios, con id), **crear / editar / borrar eventos**, y en Gmail **leer, buscar, marcar leído, archivar y mandar a la papelera**. Borrar, papelera y enviar piden tu OK en pantalla. Sin sesión de Google todo sigue funcionando como antes (ICS + IMAP).

**Preparación (una sola vez, ~10 min; los nombres de los menús de Google pueden variar un poco):**
1. Entra a <https://console.cloud.google.com> con TU cuenta de Google y crea un proyecto nuevo (ej. «Orbi»).
2. «APIs y servicios» > «Biblioteca»: activa **Gmail API** y **Google Calendar API**.
3. «Pantalla de consentimiento de OAuth» (o «Google Auth Platform»): tipo de usuario **Externo**, nombre «Orbi», tu correo como contacto. En **Usuarios de prueba** agrega tu propio correo.
4. «Credenciales» > «Crear credenciales» > «ID de cliente de OAuth» > tipo **Aplicación de escritorio**. Descarga el JSON y guárdalo en la carpeta de Orbi como `google_client_secret.json`.
5. `pip install -r requirements.txt` (agrega google-api-python-client y google-auth-oauthlib).
6. Clic derecho en Orbi > **Cuenta de Google (calendario y correo)**: se abre el navegador, elige tu cuenta y acepta. Si sale «Google no verificó esta app»: *Avanzado > Continuar* (es tu propia app).

**Cosas a saber**
- Mientras la app esté en modo «Prueba», Google caduca la sesión a los **7 días** (Orbi te avisa y vuelves a iniciar sesión). Para evitarlo: en la pantalla de consentimiento pulsa «Publicar aplicación» (para uso personal no necesita verificación).
- **Cuentas de escuela o empresa (Google Workspace, ej. @ceti.mx):** el administrador puede bloquear apps externas («Acceso bloqueado»). Si pasa, usa una cuenta personal de Gmail o sigue con ICS/IMAP. Las cuentas de Microsoft (@ceti.live.mx) no son de Google: ahí sigue el calendario por enlace ICS.
- **Enviar correos** viene apagado. Para activarlo: `"google": {"enviar_correo": true}` en `config.json`, cierra la sesión de Google en el menú y vuelve a iniciarla (pide un permiso más). Cada envío siempre pide tu OK, aunque desactives «confirmar acciones».
- `token_google.json` y `google_client_secret.json` son secretos: están en `.gitignore`, no los compartas.
- Lo que digan correos y eventos es dato, no instrucciones: Orbi no obedece lo que lean ahí.

## Modo todo con visión (parte 4)
Con `live_todo.bat` (o `"live_hace_todo": true`), Live ahora **ve lo que hace**: la pantalla continua se enciende sola (hasta 1 imagen/s, solo si algo cambia) y, además, tras cada acción de mouse, teclado o ventanas recibe una **captura nueva** para comprobar qué pasó antes del siguiente paso. Si escribe exactamente el mismo texto dos veces seguidas, se frena. Para quitar la captura extra: `"todo_captura_tras_accion": false`. Cuesta más tokens y añade ~1 s por acción.

## Búsqueda en internet (parte 5)
Orbi tiene la herramienta `investigar_web`: busca con Gemini + Google Search y **lee** la respuesta (antes solo podía abrirte Google en el navegador con `buscar_en_web`, sin ver los resultados). La usa cuando le preguntas algo reciente o que no sabe, y cuando duda de cómo hacer algo en una app o en Windows. La consulta sale a Google, así que el prompt le pide no meter datos privados. Se apaga con `"busqueda_web": false`. Usa la misma cuota que tus análisis (`analysis_models`).

## Mouse y capturas (parte 6)
- **Orbi ya no se ve a sí mismo**: su bolita, burbuja y chat se excluyen de las capturas (si estaban encima de lo que escribías, tapaban ese texto y la IA no lo veía). Requiere Windows 10 versión 2004 o más nueva. Efecto secundario: tampoco sale en tus capturas ni al compartir pantalla; se apaga en el menú de la bolita («Ocultar a Orbi en capturas…») o con `"ocultar_orbi_en_capturas": false`.
- **Mouse**: por diseño Orbi prefiere herramientas sin mouse (abrir_app, escribir_texto con `ventana`, cerrar_ventana...), porque son más rápidas y fiables. Con `"preferir_mouse": true` maneja las apps con mouse y teclado como una persona. Si le pides expresamente «usa el mouse», lo hace. Cuando hace clic, el cursor ahora se desliza (`"mouse_suave_s": 0.3`) en vez de saltar, para que se note.

## Micro menos sensible, emote de trabajo y esquivar (parte 7)
- **Micro**: antes cualquier ruido por encima de un nivel fijo hacía «brincar» a Orbi (y lo ponía a pensar hasta 8 s). Ahora el umbral se adapta al ruido de fondo (se sube solo si hay ventilador o tele) y el sonido debe durar al menos `mic_min_ms` (250 ms): los clics y golpecitos ya no cuentan, y la bolita solo se mueve con voz real. Si aún brinca, sube `mic_umbral` (0.20, 0.25) o `mic_min_ms` (350). Si no te oye bien, bájalos.
- **Emote «trabajando»**: mientras usa herramientas o el agente trabaja, pone cara concentrada (ojos entrecerrados, cejas serias, mirada de lado a lado como leyendo). Se quita al empezar a hablar o al terminar.
- **Esquivar**: mientras trabaja, si la bolita (o su burbuja) queda sobre el cursor de texto o el mouse, se pasa a una esquina o borde libre. Se apaga con `"esquivar_al_trabajar": false`. Ya NO se oculta de las capturas por defecto (`"ocultar_orbi_en_capturas": false`; sigue disponible en el menú).

## Si Orbi se queda sordo o mudo (parte 8)
Cuando Windows cambia o reinicia un dispositivo de audio (audífonos Bluetooth, driver, otra app que lo toma), PortAudio no se recupera solo: el micrófono quedaba «vivo» pero mudo y la bocina colgada, y Orbi se quedaba sordo sin avisar (y el anti-eco se quedaba pegado en «hablando»). Ahora:
- si el micrófono no entrega audio por ~4 s, se reabre solo (`[audio] El micrófono dejó de enviar audio; lo reabro…`);
- si la bocina se traba más de ~3 s, se reabre y se suelta el estado «hablando»; si la reproducción no avanza 8 s, también se reinicia;
- el modo baile deja de reintentar el loopback tras 3 fallos (puede estorbar al micrófono): se reactiva desde el menú;
- `cerrar_ventana` ya no cierra la consola donde corre Orbi ni las ventanas de Orbi.
Si vuelve a pasar, busca líneas `[audio]` en el log y mándamelas.

## Organizar y escribir archivos, Word y mini ventana (parte 9)
**Archivos sin pantalla** (permiso «archivos»; ahora su casilla dice «Buscar, leer, organizar y escribir…»): `crear_carpeta`, `mover_archivo`,
`copiar_archivo`, `renombrar_archivo`, `organizar_carpeta` (por `tipo`, `fecha` o `inicial`; `vista_previa` solo cuenta qué haría),
`deshacer_organizacion` y `escribir_archivo` (txt/md/csv). Solo dentro de Documentos, Escritorio y Descargas; **nunca borra ni sobrescribe**
(si el nombre ya existe pone « (2)»), no toca subcarpetas, salta archivos abiertos o recién modificados y deja el registro en
`organizacion_log.json` para «deshaz eso». Si son más de 25 archivos pide tu OK (según tu modo de acciones delicadas). Los prompts ahora le
prohíben decir «no puedo» a ciegas: si falta el permiso dice cuál activar, y si algo falla dice el motivo real.

**Word:** `redactar_documento` crea un `.docx` completo (títulos, viñetas, negritas) sin abrir Word ni teclear; lo redacta un modelo de texto
(`analysis_model`) y la voz solo recibe «listo, quedó en…». Para escribir en un Word que YA está abierto: `escribir_texto` con `redactar`
(se redacta aparte y se teclea en texto plano). Antes `escribir_texto` recortaba en silencio a 2000 caracteres y la voz armaba el texto
largo ella misma (se cortaba o se le colaba lo que pensaba); ahora el tope es 20 000 y avisa si recortó. Si el Word está abierto, no se
puede modificar por detrás (Windows lo bloquea): lo dice y se escribe en la ventana.

**Mini ventana:** ya no se abre por lo que el modo compañero nota (ortografía, detalles de la pantalla): eso sale por la burbuja y la voz.
La tool `mini_ventana` también tiene prohibido usarse para eso.
