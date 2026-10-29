"""Envío de correos sin costo: modo archivo, SMTP y enlaces externos."""

from __future__ import annotations

import time
from pathlib import Path

from app import correo


def test_modo_archivo_guarda_un_eml(app, tmp_path):
    app.config["MAIL_MODO"] = "archivo"
    app.instance_path = str(tmp_path)
    assert correo.enviar("demo@casaydetalles.com.ar", "Asunto de prueba", "Hola") is True
    archivos = list(Path(tmp_path, "correos").glob("*.eml"))
    assert len(archivos) == 1
    contenido = archivos[0].read_text(encoding="utf-8")
    assert "Subject: Asunto de prueba" in contenido and "To: demo@casaydetalles.com.ar" in contenido


def test_modo_smtp_envia_en_segundo_plano(app, monkeypatch):
    enviados = []

    class ServidorFalso:
        def __init__(self, servidor, puerto, timeout):
            enviados.append(("conexion", servidor, puerto))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context):
            enviados.append(("tls",))

        def login(self, usuario, contrasena):
            enviados.append(("login", usuario))

        def send_message(self, mensaje):
            enviados.append(("mensaje", mensaje["Subject"]))

    monkeypatch.setattr(correo.smtplib, "SMTP", ServidorFalso)
    app.config.update(
        MAIL_MODO="smtp", MAIL_SERVIDOR="smtp.ejemplo.com", MAIL_PUERTO=587, MAIL_USUARIO="avisos@ejemplo.com"
    )
    assert correo.enviar("demo@casaydetalles.com.ar", "Pendientes", "Hola") is True
    for _ in range(50):
        if any(e[0] == "mensaje" for e in enviados):
            break
        time.sleep(0.02)
    assert ("conexion", "smtp.ejemplo.com", 587) in enviados and ("login", "avisos@ejemplo.com") in enviados
    assert ("mensaje", "Pendientes") in enviados


def test_smtp_sin_servidor_no_esta_disponible(app):
    app.config.update(MAIL_MODO="smtp", MAIL_SERVIDOR="")
    assert correo.disponible() is False
    assert correo.enviar("demo@casaydetalles.com.ar", "Asunto", "Hola") is False


def test_una_falla_de_smtp_queda_registrada(app, monkeypatch, caplog):
    def falla(*_args, **_kwargs):
        raise OSError("sin conexión")

    monkeypatch.setattr(correo.smtplib, "SMTP", falla)
    mensaje = correo._mensaje(app, "demo@casaydetalles.com.ar", "Asunto", "Hola")
    correo._enviar_smtp({"MAIL_SERVIDOR": "x", "MAIL_PUERTO": 587}, mensaje)
    assert "No fue posible enviar el correo" in caplog.text


def test_enlace_externo(app):
    assert correo.enlace_externo("resumen.inicio") == "http://localhost/panel"
    app.config["URL_PUBLICA"] = ""
    assert correo.enlace_externo("resumen.inicio") is None
    with app.test_request_context(base_url="https://panel.ejemplo.com"):
        assert correo.enlace_externo("resumen.inicio") == "https://panel.ejemplo.com/panel"
