"""Punto de entrada WSGI (gunicorn, waitress u otro servidor)."""

from app import create_app

app = create_app()
