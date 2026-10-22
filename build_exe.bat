@echo off
setlocal
cd /d "%~dp0"
REM ---------------------------------------------------------------
REM  Convierte Orbi en Orbi.exe (carpeta dist\Orbi)
REM    build_exe.bat          -> sin consola (uso normal)
REM    build_exe.bat debug    -> con consola, para ver errores si algo falla
REM ---------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo No encuentro .venv. Corre instalar.bat primero.
  pause & exit /b 1
)
set PY=.venv\Scripts\python.exe
%PY% -m pip install -U pyinstaller || (pause & exit /b 1)
%PY% -m pip install -r requirements.txt || (pause & exit /b 1)

set MODE=--windowed
if /i "%~1"=="debug" set MODE=--console

taskkill /f /im Orbi.exe >nul 2>&1
timeout /t 2 /nobreak >nul
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

%PY% -m PyInstaller --noconfirm --clean %MODE% --name Orbi --icon orbi.ico ^
  --collect-all vosk ^
  --collect-all soundcard ^
  --collect-all sounddevice ^
  --collect-all _sounddevice_data ^
  --collect-all googleapiclient ^
  --collect-all icalendar ^
  --collect-all recurring_ical_events ^
  --hidden-import google.genai ^
  --hidden-import google_auth_oauthlib ^
  live_orb.py
if errorlevel 1 (
  echo.
  echo Fallo el build. Prueba: build_exe.bat debug
  pause & exit /b 1
)

REM --- Archivos de usuario junto al .exe (solo si existen) ---
copy /y .env.example dist\Orbi\ >nul 2>&1
copy /y config.example.json dist\Orbi\ >nul 2>&1
for %%F in (.env config.json orbi_profile.json orbi_keys.json orbi_voz.json orbi_sesion.json orbi_alarmas.json apps.json wiz_nombres.json token_google.json google_client_secret.json) do (
  if exist "%%F" copy /y "%%F" "dist\Orbi\" >nul
)
if exist models xcopy /e /i /y models dist\Orbi\models >nul

echo.
echo ===============================================================
echo  Listo: dist\Orbi\Orbi.exe
echo  OJO: dist\Orbi\ ahora incluye tu .env con tus keys.
echo  No compartas ni subas esa carpeta tal cual.
echo ===============================================================
pause
