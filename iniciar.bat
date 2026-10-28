@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"
title Plataforma de atención automatizada

echo.
echo  Plataforma de atención automatizada de consultas por WhatsApp
echo  -------------------------------------------------------------
echo.

set "PY=python"
where py > nul 2> nul && set "PY=py -3"

%PY% --version > nul 2> nul
if errorlevel 1 goto sin_python

if not exist ".venv\Scripts\python.exe" (
  echo  Creando el entorno virtual de Python...
  %PY% -m venv .venv
  if errorlevel 1 goto error
)

echo  Instalando o actualizando dependencias...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto error

if not exist ".env" copy ".env.example" ".env" > nul

echo  Preparando la base de datos de demostración...
".venv\Scripts\python.exe" -m flask --app app demo --solo-si-vacia
if errorlevel 1 goto error

echo.
echo  Panel:      http://localhost:5000
echo  Simulador:  http://localhost:5000/simulador
echo  Usuario de prueba: demo@casaydetalles.com.ar  /  demo1234
echo.
echo  Para detener el servidor, cierre esta ventana o presione Ctrl+C.
echo.
start "" cmd /c "timeout /t 3 > nul & start http://localhost:5000"
".venv\Scripts\python.exe" serve.py
goto fin

:sin_python
echo  No se encontró Python. Instale Python 3.10 o superior desde https://www.python.org/downloads/
echo  y marque la opción "Add python.exe to PATH" durante la instalación.
pause
goto fin

:error
echo.
echo  Ocurrió un error. Revise el mensaje de arriba.
pause

:fin
endlocal
