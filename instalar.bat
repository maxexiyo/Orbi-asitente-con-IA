@echo off
python -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
echo.
echo Listo. Pon tu .env (con tus keys) en esta carpeta y corre demo.bat o live_orb.bat
pause
