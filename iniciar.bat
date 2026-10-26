@echo off
cd /d "%~dp0"
echo Instalando dependencias...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Nao encontrei o Python. Instale em https://www.python.org/downloads/ marcando "Add Python to PATH".
  pause
  exit /b
)
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5000"
python app.py
pause
