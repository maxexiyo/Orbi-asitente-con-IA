"""Cliente de Gemini Live (voz en tiempo real) con rotación de keys, reconexión y eventos.

Eventos que emite (emit(kind, data)):
  connected(model) | state(idle|listening|thinking|speaking) | level((mic|out, 0..1))
  user_text(str) | model_text(str) | turn_complete | interrupted | tool((name,args))
  emotion(str) | info(str) | error(str) | fatal(str)

Visión: `send_image(jpeg)` manda un frame a la conversación; `screen_watch = True` manda la pantalla
sola cada ~2 s (solo si cambió). Las tools pueden devolver {"_image": jpeg} para que la IA lo vea.
"""
import asyncio, collections, copy, re, time

import numpy as np
from google import genai
from google.genai import types

import llm

IN_RATE = 16000     # el micro se manda a 16 kHz
OUT_RATE = 24000    # Gemini responde a 24 kHz
CHUNK = 1024        # frames por callback del micro (~64 ms)
VOICE_THRESHOLD = 0.12   # nivel (escalado) para considerar que estás hablando

DEFAULT_SYSTEM = (
    "Eres Orbi, un asistente virtual amigable que vive como una bolita azul en el escritorio. "
    "Hablas en español mexicano, informal y cálido. Respondes corto (1 a 3 frases) y natural, como en "
    "una plática. Si el usuario te pide hacer algo en la PC y tienes una herramienta para eso, úsala."
)


def rms(data: bytes) -> float:
    a = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    if a.size == 0:
        return 0.0
    return float(min(1.0, np.sqrt(np.mean(a * a)) / 32768.0 * 6))


# Cosas que el modelo a veces DICE/ESCRIBE cuando "decide no responder" (el silencio no debe sonar ni verse)
_NO_RESPUESTA = re.compile(
    r"^(no speech|nospeech|sin voz|silencio|silenciando|en silencio|sin respuesta|no respondo|no hay respuesta|"
    r"no responder|no respondere|no tengo respuesta|callado|me quedo callado|me quedo en silencio|"
    r"no es para mi|no me hablan a mi|ruido|ninguna respuesta|sin salida|no output|no response|silence)$")


def es_no_respuesta(texto) -> bool:
    """¿Este texto es solo una forma de 'no respondo' dicha en voz alta? (para no mostrarla ni dejarla sonar)"""
    import unicodedata
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return bool(t) and bool(_NO_RESPUESTA.match(t))


class LiveSession:
    def __init__(self, keys, model, emit, system_prompt=DEFAULT_SYSTEM, tools=None, tool_runner=None,
                 voice=None, headphones=False, input_device=None, output_device=None):
        # keys: lista o llm.KeyPool (compartido con el agente/observador) · model: un modelo o lista en orden de preferencia
        self.pool = keys if isinstance(keys, llm.KeyPool) else llm.KeyPool(keys)
        self.models = [model] if isinstance(model, str) else list(model)
        self.model = self.models[0]                  # el modelo activo (se actualiza al conectar)
        self.emit = emit
        self.gate = None                              # callable -> bool: ¿mandar el micro a Live? (None = siempre)
        self.mic_hooks = []                           # callables(bytes) que reciben cada trozo de micro (palabra clave)
        self._bad_models = {}                          # modelo -> hasta cuándo se descarta (caduca: puede ser un fallo pasajero)
        self._worked = set()                           # modelos que ya conectaron alguna vez en esta ejecución
        self._handle_model = None
        self._gate_was_open = True
        self._pre = collections.deque()               # pre-roll: último ~1.6 s de micro mientras la compuerta está cerrada
        self.system_prompt, self.tools, self.tool_runner = system_prompt, tools, tool_runner
        self.voice, self.headphones = voice, headphones
        self.input_device, self.output_device = input_device, output_device
        self.proactive = False        # True = pide «proactive audio» a Live (opcional, experimental; ver config.json)
        # fin de turno: cuánto silencio espera Live antes de darte por terminado (más = no te corta a media frase)
        self.fin_turno_ms = 1100
        self.fin_sensibilidad = "low"        # low = le cuesta más decidir que terminaste · high = responde más rápido
        self.prefijo_ms = 250
        self.use_aad = True                  # se apaga solo si el servidor rechaza la configuración
        self._suppress_until = 0.0           # mientras sea futuro: ignora todo lo que Live conteste (voz de otra persona)
        self._turn_done_t = 0.0
        self.muted = False
        self.mute_output = False      # True = no reproduce la voz (solo texto en burbuja)
        self.screen_watch = False     # True = manda la pantalla cada ~2 s si cambió (modo "ver todo")
        self.screen_interval = 2.0
        self._handle = None            # handle para reanudar la sesión al reconectar
        self._handle_key = None        # key con la que se obtuvo ese handle (un handle de otra key da "session not found")
        self._last_key = None          # última key que conectó bien: se prefiere para no perder el handle
        self._task = None
        self._speaking = False
        self._waiting = False
        self._last_voice = 0.0
        self._last_audio_out = 0.0
        self._tool_tasks = set()

    # ------------------------------------------------------------ control
    def set_muted(self, v: bool):
        self.muted = v

    def send_text(self, text: str) -> bool:
        """Manda texto escrito a la conversación en vivo. Se puede llamar desde cualquier hilo."""
        if not self._task or self._task.done():
            return False
        self._task.get_loop().call_soon_threadsafe(self._enqueue_text, text)
        return True

    def send_image(self, jpeg: bytes) -> bool:
        """Manda un frame JPEG a la conversación en vivo. Se puede llamar desde cualquier hilo."""
        if not self._task or self._task.done():
            return False
        self._task.get_loop().call_soon_threadsafe(self._img_q.put_nowait, jpeg)
        return True

    def _enqueue_text(self, text):
        self._waiting = True                 # para que la bolita se vea "pensando"
        self._last_voice = time.time()
        self._text_q.put_nowait(text)

    def stop(self):
        """Se puede llamar desde cualquier hilo."""
        if self._task and not self._task.done():
            self._task.get_loop().call_soon_threadsafe(self._task.cancel)

    def _choose(self):
        """(key, modelo) preferido con key disponible. La cuota es POR MODELO, así que si el principal se agotó se usa el siguiente."""
        now = time.time()
        for m in self.models:
            if self._bad_models.get(m, 0) > now:
                continue
            if self._last_key and self._last_key in self.pool.available(m):
                return self._last_key, m          # misma key = el handle de reanudación sigue valiendo
            k = self.pool.pick(m)
            if k:
                return k, m
        return None, None

    async def run(self):
        self._task = asyncio.current_task()
        self._out_q = asyncio.Queue()
        self._text_q = asyncio.Queue()
        self._img_q = asyncio.Queue(maxsize=4)
        ticker = asyncio.create_task(self._ticker())
        fails, last_msg, sess_fails = 0, "", 0
        try:
            while True:
                key, model = self._choose()
                if key is None:
                    now = time.time()
                    live = [m for m in self.models if self._bad_models.get(m, 0) <= now]
                    if not live:        # todos descartados: NO te rindas, espera y vuelve a probar
                        wait = max(5.0, min(self._bad_models.values()) - now)
                        msg = ("Gemini Live no está disponible ahora (" + ", ".join(self.models) + "). "
                               f"Reintento en {wait:.0f} s.")
                        if msg != last_msg:
                            self.emit("error", msg); last_msg = msg
                        await asyncio.sleep(min(wait, 60.0))
                        continue
                    wait = min(30.0, max(3.0, min(self.pool.wait_seconds(m) for m in live)))
                    msg = f"Sin cuota o keys por ahora ({self.pool.describe()}). Reintento en {wait:.0f} s."
                    if msg != last_msg:
                        self.emit("error", msg); last_msg = msg
                    await asyncio.sleep(wait)
                    continue
                try:
                    await self._session_once(key, model)
                    fails = 0; last_msg = ""; sess_fails = 0
                    await asyncio.sleep(1.0)          # si la sesión terminó sola, no reconectes en bucle apretado
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    kind, wait = llm.classify(e)
                    short = str(e)[:300]
                    if self.use_aad and re.search(r"activity|silence_duration|realtime_input|sensitivity|prefix_padding",
                                                  short, re.I):
                        self.use_aad = False       # este modelo no acepta ajustar el fin de turno: reintenta con el de fábrica
                        self.emit("info", f"El modelo no acepta ajustar el fin de turno ({short[:100]}); uso el de fábrica.")
                        continue
                    if kind == llm.SESSION:
                        # handle caducado/ajeno: se borra y se reconecta desde cero enseguida (sin castigar la key ni el modelo)
                        self._handle = self._handle_key = None
                        sess_fails += 1
                        self.emit("info", f"Sesión de Live inválida ({short[:120]}); reconecto desde cero.")
                        if sess_fails <= 3:
                            await asyncio.sleep(0.5)
                            continue
                        kind, wait = llm.TRANSIENT, 5.0       # sigue fallando aun sin handle: ya es otra cosa, espera creciente normal
                    if kind == llm.MODEL and model in self._worked:
                        kind, wait = llm.TRANSIENT, 5.0       # ya funcionó antes: fue un corte, no que el modelo no exista
                    if kind == llm.MODEL:
                        self._bad_models[model] = time.time() + 600     # lo reintenta en 10 min
                        self.emit("info", f"El modelo '{model}' no está disponible para Live: {short[:160]}; pruebo el siguiente.")
                        continue
                    self.pool.penalize(key, wait if kind != llm.TRANSIENT else 0.0, kind, e, scope=model)
                    fails += 1
                    if short != last_msg or fails % 5 == 0:
                        self.emit("error", short); last_msg = short
                    await asyncio.sleep(min(2 ** min(fails, 5), 30))      # espera creciente, pero NUNCA se rinde
        except asyncio.CancelledError:
            pass
        finally:
            ticker.cancel()

    # ------------------------------------------------------------- sesión
    def _tools_for(self, model):
        if not self.tools:
            return None
        tools = copy.deepcopy(self.tools)
        if "3.8" in model:       # gemini-3.8-live llama a las tools en modo asíncrono por defecto: aquí queremos esperar el resultado
            for t in tools:
                for d in t.get("function_declarations", []):
                    d["behavior"] = "BLOCKING"
        return tools

    async def _session_once(self, key, model):
        if self._handle_model != model:      # el handle de reanudación de otro modelo no sirve
            self._handle, self._handle_model = None, model
        self.model = model
        if self._handle_key != key:          # el handle solo sirve con la key que lo creó
            self._handle = None
        use_pa = bool(self.proactive) and hasattr(types, "ProactivityConfig")
        if self.proactive and not use_pa:
            self.emit("info", "live_proactive_audio: tu versión de google-genai no lo soporta (pip install -U google-genai)")
        client = genai.Client(api_key=key, http_options={"api_version": "v1alpha"}) if use_pa else genai.Client(api_key=key)
        cfg = dict(
            response_modalities=["AUDIO"],
            system_instruction=self.system_prompt,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # comprime el contexto para que la sesión no muera a los 15 min
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()),
            session_resumption=types.SessionResumptionConfig(handle=self._handle),
        )
        if self.use_aad and hasattr(types, "RealtimeInputConfig") and hasattr(types, "AutomaticActivityDetection"):
            end_sens = (types.EndSensitivity.END_SENSITIVITY_LOW if self.fin_sensibilidad == "low"
                        else types.EndSensitivity.END_SENSITIVITY_HIGH)
            cfg["realtime_input_config"] = types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    end_of_speech_sensitivity=end_sens,
                    silence_duration_ms=int(self.fin_turno_ms),
                    prefix_padding_ms=int(self.prefijo_ms)))
        if use_pa:
            cfg["proactivity"] = types.ProactivityConfig(proactive_audio=True)
        if self.voice:
            cfg["speech_config"] = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)))
        tools = self._tools_for(model)
        if tools:
            cfg["tools"] = tools
        config = types.LiveConnectConfig(**cfg)

        async with client.aio.live.connect(model=model, config=config) as session:
            self.emit("connected", model)
            self._last_key = key
            tasks = [asyncio.create_task(self._send_audio(session)),
                     asyncio.create_task(self._play_audio()),
                     asyncio.create_task(self._send_text_loop(session)),
                     asyncio.create_task(self._send_image_loop(session)),
                     asyncio.create_task(self._screen_loop())]
            try:
                self._worked.add(model)
                recv = asyncio.create_task(self._receive(session))
                pending = {recv, *tasks}
                while recv in pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for t in done:
                        if not t.cancelled() and t.exception():
                            raise t.exception()      # micro/bocina/red murieron: run() reintenta con espera creciente
                    # una tarea que terminó sin error (p. ej. el modo pantalla se apagó solo) no tumba la sesión
                recv.cancel()
            finally:
                for t in [*tasks, *self._tool_tasks]:
                    t.cancel()
                await asyncio.gather(*tasks, recv, *self._tool_tasks, return_exceptions=True)
                self._tool_tasks.clear()

    async def _send_text_loop(self, session):
        while True:
            text = await self._text_q.get()
            try:
                await session.send_realtime_input(text=text)
            except TypeError:        # SDK/modelo que prefiere turnos de contenido
                await session.send_client_content(
                    turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=True)

    async def _send_image_loop(self, session):
        while True:
            jpeg = await self._img_q.get()
            await session.send_realtime_input(video=types.Blob(data=jpeg, mime_type="image/jpeg"))

    async def _screen_loop(self):
        """Modo continuo: captura la pantalla y la manda solo si cambió."""
        from screen import capture, ChangeDetector
        det = ChangeDetector()
        while True:
            await asyncio.sleep(self.screen_interval)
            if not self.screen_watch:
                det.reset()
                continue
            try:
                jpeg, _ = await asyncio.to_thread(capture)
                if det.changed(jpeg) and not self._img_q.full():
                    self._img_q.put_nowait(jpeg)
            except Exception as e:
                self.screen_watch = False
                self.emit("error", f"No pude capturar la pantalla ({e}); apagué el modo continuo.")

    async def _send_audio(self, session):
        import sounddevice as sd
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=60)

        def put(data):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

        def cb(indata, frames, t, status):
            loop.call_soon_threadsafe(put, bytes(indata))

        try:
            stream = sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16", blocksize=CHUNK,
                                       callback=cb, device=self.input_device)
        except Exception as e:
            self.emit("info", f"Micrófono {self.input_device!r} no disponible ({e}); uso el predeterminado")
            stream = sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16", blocksize=CHUNK, callback=cb)
        with stream:
            while True:
                data = await q.get()
                if self.muted:
                    continue
                now = time.time()
                # sin audífonos: no mandes el micro mientras la IA habla (evita que se escuche a sí misma)
                if not self.headphones and (self._speaking or now - self._last_audio_out < 0.5):
                    continue
                for hook in self.mic_hooks:           # palabra clave: ve el micro aunque la compuerta esté cerrada
                    try:
                        hook(data)
                    except Exception:
                        pass
                if self.gate is not None and not self.gate():
                    if self._gate_was_open:           # cierra el flujo de audio limpiamente (libera lo que Live tenga en buffer)
                        self._gate_was_open = False
                        try:
                            await session.send_realtime_input(audio_stream_end=True)
                        except Exception:
                            pass
                    self._pre.append((now, data))
                    while self._pre and now - self._pre[0][0] > 1.6:
                        self._pre.popleft()
                    continue
                if not self._gate_was_open:           # se acaba de abrir: manda primero lo que dijiste justo antes (el «Orbi, ...»)
                    for _t, d in self._pre:
                        await session.send_realtime_input(audio=types.Blob(data=d, mime_type=f"audio/pcm;rate={IN_RATE}"))
                    self._pre.clear()
                self._gate_was_open = True
                lvl = rms(data)
                self.emit("level", ("mic", lvl))
                if lvl > VOICE_THRESHOLD:
                    self._last_voice = now
                    if not self._speaking:
                        self._waiting = True
                await session.send_realtime_input(
                    audio=types.Blob(data=data, mime_type=f"audio/pcm;rate={IN_RATE}"))

    def suppress_turn(self, utt_start: float) -> bool:
        """La frase que acaba de oírse NO era del dueño: cancela la respuesta de ese turno (voz, texto y herramientas).
        utt_start: cuándo empezó esa frase. Si Live ya había terminado de contestar antes, no hace nada (así no se
        come tu siguiente turno)."""
        if self._turn_done_t > utt_start:
            return False
        self._suppress_until = time.time() + 10.0
        while not self._out_q.empty():
            self._out_q.get_nowait()
        self._speaking = False
        return True

    async def _play_audio(self):
        import sounddevice as sd
        slice_bytes = int(OUT_RATE * 0.05) * 2        # 50 ms
        try:
            out_stream = sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", device=self.output_device, latency="low")
        except Exception as e:
            self.emit("info", f"Bocina {self.output_device!r} no disponible ({e}); uso la predeterminada")
            out_stream = sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", latency="low")
        with out_stream as out:
            while True:
                data = await self._out_q.get()
                for i in range(0, len(data), slice_bytes):
                    part = data[i:i + slice_bytes]
                    self.emit("level", ("out", rms(part)))
                    if self.mute_output:
                        await asyncio.sleep(len(part) / (2 * OUT_RATE))
                    else:
                        await asyncio.to_thread(out.write, part)
                    self._last_audio_out = time.time()

    async def _receive(self, session):
        empty = 0
        while True:
            got_any = False
            async for r in session.receive():
                got_any = True
                sup = time.time() < self._suppress_until
                if r.data and not sup:
                    self._speaking = True
                    self._waiting = False
                    self._last_audio_out = time.time()
                    self._out_q.put_nowait(r.data)
                sc = r.server_content
                if sc:
                    if sc.interrupted:
                        while not self._out_q.empty():
                            self._out_q.get_nowait()
                        self._speaking = False
                        self.emit("interrupted", None)
                    if sc.input_transcription and sc.input_transcription.text and not sup:
                        self.emit("user_text", sc.input_transcription.text)
                    if sc.output_transcription and sc.output_transcription.text and not sup:
                        if es_no_respuesta(sc.output_transcription.text):
                            # dijo «silencio»/«no speech»: que no se vea y corta el audio que falta por sonar
                            while not self._out_q.empty():
                                self._out_q.get_nowait()
                        else:
                            self.emit("model_text", sc.output_transcription.text)
                    if sc.turn_complete:
                        self._waiting = False
                        self._turn_done_t = time.time()
                        self._suppress_until = 0.0
                        self.emit("turn_complete", None)
                if r.tool_call:
                    t = asyncio.create_task(self._handle_tools(session, r.tool_call))
                    self._tool_tasks.add(t)
                    t.add_done_callback(self._tool_tasks.discard)
                if getattr(r, "tool_call_cancellation", None):
                    self.emit("info", f"Live canceló llamadas a tools: {r.tool_call_cancellation.ids}")
                upd = r.session_resumption_update
                if upd and upd.resumable and upd.new_handle:
                    self._handle, self._handle_key = upd.new_handle, self._last_key
                if r.go_away:
                    self.emit("info", "El servidor va a cerrar la sesión, reconecto solito...")
            if not got_any:
                empty += 1
                if empty > 40:       # ~2 s devolviendo nada: la conexión murió sin avisar -> reconecta (antes se quedaba "colgado")
                    raise ConnectionError("Live dejó de responder (conexión cerrada)")
                await asyncio.sleep(0.05)
            else:
                empty = 0

    async def _handle_tools(self, session, tool_call):
        now = time.time()
        gap = now - getattr(self, "_last_tool_resp", 0.0)
        names = ", ".join(fc.name for fc in (tool_call.function_calls or []))
        if gap < 90:                              # diagnóstico: lo que Live tardó en pedir el siguiente paso (va a orbi.log)
            print(f"[live] el modelo tardó {gap:.1f}s en pedir el siguiente paso: {names}")
        responses = []
        for fc in tool_call.function_calls or []:
            if time.time() < self._suppress_until:      # lo pidió una voz que no es la del dueño: no se ejecuta nada
                print(f"[voz] ignoré la herramienta «{fc.name}» (la frase no era del dueño)")
                responses.append(types.FunctionResponse(
                    id=fc.id, name=fc.name, response={"error": "Ignorado: esa voz no es la del dueño. No lo hagas ni lo comentes."}))
                continue
            args = dict(fc.args or {})
            self.emit("tool", (fc.name, args))
            try:
                result = await asyncio.to_thread(self.tool_runner, fc.name, args) if self.tool_runner \
                    else {"error": "sin tool_runner"}
            except Exception as e:
                result = {"error": str(e)}
            image = result.pop("_image", None) if isinstance(result, dict) else None
            if isinstance(result, dict):
                result.pop("_sin_captura", None)      # llave interna del agente: no tiene sentido para la voz
            if image:            # la tool pidió que la IA vea una imagen (ver_pantalla)
                try:
                    await session.send_realtime_input(video=types.Blob(data=image, mime_type="image/jpeg"))
                except Exception as e:
                    result = {"error": f"No pude enviar la captura: {e}"}
            responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=result))
        self._last_tool_resp = time.time()
        try:
            await session.send_tool_response(function_responses=responses)
        except Exception as e:
            self.emit("info", f"No pude devolver el resultado de la herramienta (sesión caída): {str(e)[:120]}")

    async def _ticker(self):
        last = None
        while True:
            await asyncio.sleep(0.1)
            now = time.time()
            if self._speaking and self._out_q.empty() and now - self._last_audio_out > 0.7:
                self._speaking = False
            if self._speaking:
                st = "speaking"
            elif now - self._last_voice < 0.5:
                st = "listening"
            elif self._waiting and now - self._last_voice < 8:
                st = "thinking"
            else:
                st = "idle"
                self._waiting = False
            if st != last:
                last = st
                self.emit("state", st)
