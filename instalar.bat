@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
echo Instalacao concluida. Abra iniciar.bat.
pause
exit /b 0
:error
echo Nao foi possivel instalar. Confira a mensagem acima. Requer Python 3.11 a 3.13 de 64 bits.
pause
exit /b 1
