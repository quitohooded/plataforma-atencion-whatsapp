"""Protección CSRF con la configuración real: formularios protegidos, webhook exento (RNF03)."""

import hashlib
import hmac
import json
import re

import pytest

from app import create_app
from app.config import ConfigPruebas
from app.extensiones import db

from .conftest import crear_comercio


class ConfigConCsrf(ConfigPruebas):
    WTF_CSRF_ENABLED = True


@pytest.fixture
def app_csrf(reloj):
    aplicacion = create_app(ConfigConCsrf)
    with aplicacion.app_context():
        yield aplicacion
        db.session.remove()
        db.drop_all()


def test_formularios_sin_token_se_rechazan(app_csrf):
    crear_comercio()
    cliente = app_csrf.test_client()
    r = cliente.post("/ingresar", data={"email": "demo@casaydetalles.com.ar", "contrasena": "clave-segura-1"})
    assert r.status_code == 400


def test_formulario_con_token_funciona(app_csrf):
    crear_comercio()
    cliente = app_csrf.test_client()
    html = cliente.get("/ingresar").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    r = cliente.post("/ingresar", data={"email": "demo@casaydetalles.com.ar", "contrasena": "clave-segura-1",
                                       "csrf_token": token})
    assert r.status_code == 302


def test_webhook_exento_de_csrf_pero_firmado(app_csrf):
    comercio = crear_comercio()
    cliente = app_csrf.test_client()
    payload = {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "5493511234567", "profile": {"name": "Ana"}}],
        "messages": [{"from": "5493511234567", "id": "wamid.X", "type": "text",
                      "text": {"body": comercio.texto_primer_mensaje()}}],
    }}]}]}
    cuerpo = json.dumps(payload).encode()
    firma = "sha256=" + hmac.new(b"secreto-de-prueba", cuerpo, hashlib.sha256).hexdigest()
    r = cliente.post("/webhook/whatsapp", data=cuerpo, content_type="application/json",
                     headers={"X-Hub-Signature-256": firma})
    assert r.status_code == 200 and r.get_json()["procesados"] == 1


def test_simulador_requiere_el_token_de_la_pagina(app_csrf):
    crear_comercio()
    cliente = app_csrf.test_client()
    datos = {"telefono": "5493510000077", "texto": "hola"}
    assert cliente.post("/simulador/api/mensajes", json=datos).status_code == 400
    html = cliente.get("/simulador").get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
    r = cliente.post("/simulador/api/mensajes", json=datos, headers={"X-CSRFToken": token})
    assert r.status_code == 200
