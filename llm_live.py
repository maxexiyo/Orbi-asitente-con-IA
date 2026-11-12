"""Modo «solo Live» (config.json "solo_live": true): TODO lo que antes iba a modelos de texto (ubicar para señalar, OCR, redactar, investigar_web,
traducir chats, género de canciones, análisis de documentos...) pasa por Gemini Live. Un solo punto de entrada: reemplaza llm.generate.

Cada petición abre una sesión Live corta (texto/imagen -> texto), espera el turno completo y devuelve un objeto con `.text`.
Intenta modalidad TEXT; si el modelo solo da audio, usa AUDIO y lee la transcripción de su salida (se recuerda cuál sirvió).
Límites: no hay function calling aquí (el agente de texto no existe en este modo: Live ya hace las tareas), el audio de entrada
(escuchar_audio_pc) no va por esta vía y el JSON no se puede forzar (se pide en el prompt)."""
from __future__ import annotations

import asyncio
import concurrent.futures as cf
import types as _t

_MODO: dict = {}          # modelo -> "TEXT" | "AUDIO"
_POOL = cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="orbi-sololive")


def _partes(contents, types):
    items = contents if isinstance(contents, (list, tuple)) else [contents]
    out = []
    for it in items:
        if isinstance(it, str):
            out.append(types.Part(text=it))
        elif hasattr(it, "inline_data") or hasattr(it, "text"):
            mime = getattr(getattr(it, "inline_data", None), "mime_type", "") or ""
            if mime.startswith("audio/"):
                raise RuntimeError("el audio de la PC no se puede analizar en modo solo_live")
            out.append(it)
        else:
            out.append(types.Part(text=str(it)))
    return out


async def _una(client, model, modo, partes, sysi, tools, types, timeout):
    kw = dict(response_modalities=[modo])
    if sysi:
        kw["system_instruction"] = sysi
    if tools:
        kw["tools"] = tools
    if modo == "AUDIO":
        kw["output_audio_transcription"] = types.AudioTranscriptionConfig()
    texto = []
    async with client.aio.live.connect(model=model, config=types.LiveConnectConfig(**kw)) as s:
        await s.send_client_content(turns=types.Content(role="user", parts=partes), turn_complete=True)

        async def leer():
            async for m in s.receive():
                sc = getattr(m, "server_content", None)
                if not sc:
                    continue
                if modo == "TEXT" and getattr(sc, "model_turn", None):
                    for p in sc.model_turn.parts or []:
                        if getattr(p, "text", None):
                            texto.append(p.text)
                ot = getattr(sc, "output_transcription", None)
                if modo == "AUDIO" and ot and getattr(ot, "text", None):
                    texto.append(ot.text)
                if getattr(sc, "turn_complete", False):
                    return
        await asyncio.wait_for(leer(), timeout)
    return "".join(texto).strip()


def instalar(llm, cfg: dict, live_models: list, say=print) -> None:
    from google.genai import types
    modelos = [m for m in live_models if "extended" not in m] or list(live_models)
    timeout = float(cfg.get("solo_live_timeout_s", 40))

    def generate(pool, models, contents, config=None, retries_per_model=None, thinking=None):
        tools = None
        sysi = getattr(config, "system_instruction", None) if config is not None else None
        pedir_json = config is not None and getattr(config, "response_mime_type", "") == "application/json"
        if config is not None and getattr(config, "tools", None):
            tl = []
            for t in config.tools:
                if getattr(t, "function_declarations", None):
                    raise llm.AllBusy("solo_live: no hay agente de texto (Live ya hace las tareas)")
                tl.append(t)
            tools = tl or None
        partes = _partes(contents, types)
        if pedir_json:
            partes.append(types.Part(text="Responde SOLO con el JSON pedido, sin texto extra ni markdown."))
        ultimo = None
        for model in modelos:
            for modo in ([_MODO[model]] if model in _MODO else ["TEXT", "AUDIO"]):
                key = pool.pick(model)
                if key is None:
                    break
                try:
                    client = llm.client_for(key)
                    fut = _POOL.submit(lambda: asyncio.run(_una(client, model, modo, partes, sysi, tools, types, timeout)))
                    txt = fut.result(timeout + 10)
                    if not txt:
                        raise RuntimeError("Live no devolvió texto")
                    _MODO[model] = modo
                    return _t.SimpleNamespace(text=txt, candidates=[]), model
                except Exception as e:                       # noqa: BLE001
                    ultimo = f"{model} ({modo}): {type(e).__name__}: {str(e)[:140]}"
                    kind, wait = llm.classify(e)
                    if kind == llm.QUOTA:
                        pool.penalize(key, wait, kind, e, scope=model)
                        break
                    if kind in (llm.AUTH, llm.TRANSIENT):
                        pool.penalize(key, wait, kind, e)
                        break
        raise llm.AllBusy(ultimo or "solo_live: sin respuesta de Live")

    llm.generate = generate
    say(f"[solo_live] ACTIVO: todo pasa por Gemini Live ({', '.join(modelos)}); sin modelos de texto")
