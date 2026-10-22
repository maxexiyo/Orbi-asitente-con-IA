@echo off
rem PRUEBA: Gemini 3.8 Live hace TODO (voz con mouse, teclado y ventanas; sin agente de segundo plano)
call .venv\Scripts\activate
set LIVE_MODEL=gemini-3.8-live
python live_orb.py --live-todo
pause
