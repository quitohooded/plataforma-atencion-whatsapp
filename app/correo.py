"""Envío de correos: avisos de consultas pendientes (#8) y recuperación de contraseña (#9).

Sin costo por defecto. Modos (``MAIL_MODO``):

- ``archivo``: cada correo se guarda como ``.eml`` en ``instance/correos``. Sirve en
  desarrollo y en la demostración, y se abre con cualquier programa de correo.
- ``smtp``: se envía con un servidor SMTP (por ejemplo, Gmail con una contraseña de
  aplicación). El envío corre en segundo plano para no demorar la respuesta del bot.
- ``memoria``: queda en ``app.extensions["correos"]`` (lo usan las pruebas).
- ``desactivado``: no se envía nada.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from flask import Flask, current_app, has_request_context, url_for

from .utilidades import tiempo

log = logging.getLogger(__name__)


def enlace_externo(endpoint: str, **valores) -> str | None:
    """Dirección completa para un correo: con ``URL_PUBLICA`` si está configurada o, si no, la
    del pedido en curso. Fuera de un pedido y sin ``URL_PUBLICA`` no hay cómo armarla."""
    app = current_app
    base = app.config.get("URL_PUBLICA")
    if base:
        with app.test_request_context(base_url=base):
            return url_for(endpoint, _external=True, **valores)
    if has_request_context():
        return url_for(endpoint, _external=True, **valores)
    return None


def disponible(app: Flask | None = None) -> bool:
    app = app or current_app
    modo = app.config.get("MAIL_MODO", "archivo")
    if modo == "smtp":
        return bool(app.config.get("MAIL_SERVIDOR"))
    return modo in {"archivo", "memoria"}


def _mensaje(app: Flask, destinatario: str, asunto: str, texto: str) -> EmailMessage:
    remitente = app.config.get("MAIL_REMITENTE") or app.config.get("MAIL_USUARIO") or "avisos@localhost"
    mensaje = EmailMessage()
    mensaje["From"] = remitente
    mensaje["To"] = destinatario
    mensaje["Subject"] = asunto
    mensaje["Date"] = formatdate(localtime=True)
    mensaje["Message-ID"] = make_msgid(domain="localhost")
    mensaje.set_content(texto)
    return mensaje


def _enviar_smtp(config: dict, mensaje: EmailMessage) -> None:
    try:
        with smtplib.SMTP(config["MAIL_SERVIDOR"], config["MAIL_PUERTO"], timeout=15) as servidor:
            if config.get("MAIL_TLS", True):
                servidor.starttls(context=ssl.create_default_context())
            if config.get("MAIL_USUARIO"):
                servidor.login(config["MAIL_USUARIO"], config.get("MAIL_CONTRASENA", ""))
            servidor.send_message(mensaje)
        log.info("Correo enviado a %s: %s", mensaje["To"], mensaje["Subject"])
    except (OSError, smtplib.SMTPException):
        log.exception("No fue posible enviar el correo a %s", mensaje["To"])


def enviar(destinatario: str, asunto: str, texto: str) -> bool:
    """Envía un correo de texto. Devuelve si quedó enviado o guardado (no si llegó)."""
    app = current_app._get_current_object()
    if not destinatario or not disponible(app):
        return False
    mensaje = _mensaje(app, destinatario, asunto, texto)
    modo = app.config.get("MAIL_MODO")
    if modo == "memoria":
        app.extensions.setdefault("correos", []).append(mensaje)
    elif modo == "archivo":
        carpeta = Path(app.instance_path) / "correos"
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre = tiempo.ahora().strftime("%Y%m%d-%H%M%S-%f") + ".eml"
        (carpeta / nombre).write_bytes(mensaje.as_bytes())
        log.info("Correo guardado en %s (MAIL_MODO=archivo)", carpeta / nombre)
    else:
        config = {k: app.config.get(k) for k in ("MAIL_SERVIDOR", "MAIL_PUERTO", "MAIL_USUARIO", "MAIL_CONTRASENA")}
        config["MAIL_TLS"] = app.config.get("MAIL_TLS", True)
        threading.Thread(target=_enviar_smtp, args=(config, mensaje), daemon=True).start()
    return True
