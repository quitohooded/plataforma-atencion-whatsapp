#!/usr/bin/env bash
# Inicio rápido en macOS o Linux: crea el entorno, instala dependencias, carga la demo y levanta el servidor.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
[ -f .env ] || cp .env.example .env
.venv/bin/python -m flask --app app demo --solo-si-vacia
echo
echo "Panel:     http://localhost:5000"
echo "Simulador: http://localhost:5000/simulador"
echo "Usuario de prueba: demo@casaydetalles.com.ar / demo1234"
echo
exec .venv/bin/python serve.py "$@"
