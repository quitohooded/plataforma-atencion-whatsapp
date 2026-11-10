"""Pruebas del Sprint 4: Onboarding de WhatsApp Oficial (Meta Embedded Signup - Pilar 2)."""

from unittest.mock import MagicMock

import pytest

from app.extensiones import db
from app.modelos import PlanComercio
from app.servicios.meta_signup import (
    desconectar_whatsapp_comercio,
    intercambiar_codigo_embedded,
)


def test_endpoint_meta_config(sesion, app):
    """El endpoint /plan/whatsapp/meta-config devuelve las credenciales públicas o modo simulado."""
    # 1. Modo simulado por defecto (sin META_APP_ID)
    r = sesion.get("/plan/whatsapp/meta-config")
    assert r.status_code == 200
    datos = r.get_json()
    assert datos["simulado"] is True
    assert datos["app_id"] == ""
    assert datos["config_id"] == ""

    # 2. Con credenciales configuradas
    app.config["META_APP_ID"] = "meta_app_999"
    app.config["META_CONFIG_ID"] = "meta_cfg_888"

    r2 = sesion.get("/plan/whatsapp/meta-config")
    assert r2.status_code == 200
    datos2 = r2.get_json()
    assert datos2["simulado"] is False
    assert datos2["app_id"] == "meta_app_999"
    assert datos2["config_id"] == "meta_cfg_888"


def test_intercambio_simulado_servicio_y_endpoint(sesion, comercio):
    """En entornos sin credenciales, el canje de código activa una línea simulada."""
    comercio.plan = PlanComercio.PRO
    db.session.commit()

    r = sesion.post(
        "/plan/whatsapp/embedded-callback",
        json={"code": "demo_code_123"},
    )
    assert r.status_code == 200
    datos = r.get_json()
    assert datos["ok"] is True
    assert datos["numero"] == "5493512345678"

    db.session.refresh(comercio)
    assert comercio.whatsapp_phone_number_id == "10987654321"
    assert comercio.whatsapp_waba_id == "waba_demo_123"
    assert comercio.whatsapp_token == "token_meta_simulado"
    assert comercio.whatsapp_numero_publico == "5493512345678"
    assert comercio.tiene_whatsapp_propio is True

    # Aprovisionamiento simulado respetando IDs provistos por el frontend
    r2 = sesion.post(
        "/plan/whatsapp/embedded-callback",
        json={"code": "demo_custom", "waba_id": "mi_waba_custom", "phone_number_id": "99887766"},
    )
    assert r2.status_code == 200
    db.session.refresh(comercio)
    assert comercio.whatsapp_waba_id == "mi_waba_custom"
    assert comercio.whatsapp_phone_number_id == "99887766"


def test_intercambio_real_con_mock_graph_api(sesion, comercio, app, monkeypatch):
    """Flujo real: canje de access_token, inspección debug_token, listado de teléfonos y suscripción webhook."""
    comercio.plan = PlanComercio.PRO
    db.session.commit()

    app.config["META_APP_ID"] = "app_real_123"
    app.config["WHATSAPP_APP_SECRET"] = "secret_real_456"
    app.config["META_SYSTEM_USER_TOKEN"] = "system_user_token_789"
    app.config["WHATSAPP_API_VERSION"] = "v23.0"

    llamadas_get = []
    llamadas_post = []

    def mock_get(url, params=None, timeout=10):
        llamadas_get.append((url, params))
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        if "/oauth/access_token" in url:
            mock_resp.json.return_value = {
                "access_token": "EAAG_real_token_comercio",
                "token_type": "bearer",
            }
        elif "/debug_token" in url:
            mock_resp.json.return_value = {
                "data": {
                    "granular_scopes": [
                        {
                            "scope": "whatsapp_business_management",
                            "target_ids": ["waba_oficial_1001"],
                        }
                    ]
                }
            }
        elif "/waba_oficial_1001/phone_numbers" in url:
            mock_resp.json.return_value = {
                "data": [
                    {
                        "id": "phone_id_2002",
                        "display_phone_number": "+54 9 351 444-5555",
                        "verified_name": "Casa & Detalles Oficial",
                    }
                ]
            }
        else:
            mock_resp.json.return_value = {}

        return mock_resp

    def mock_post(url, params=None, timeout=10):
        llamadas_post.append((url, params))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True}
        return mock_resp

    import requests

    monkeypatch.setattr(requests, "get", mock_get)
    monkeypatch.setattr(requests, "post", mock_post)

    r = sesion.post(
        "/plan/whatsapp/embedded-callback",
        json={"code": "meta_auth_code_xyz"},
    )
    assert r.status_code == 200
    datos = r.get_json()
    assert datos["ok"] is True
    assert datos["numero"] == "+54 9 351 444-5555"

    # Verificar que se guardó en la base de datos
    db.session.refresh(comercio)
    assert comercio.whatsapp_phone_number_id == "phone_id_2002"
    assert comercio.whatsapp_waba_id == "waba_oficial_1001"
    assert comercio.whatsapp_token == "EAAG_real_token_comercio"
    assert comercio.whatsapp_numero_publico == "+54 9 351 444-5555"
    assert comercio.tiene_whatsapp_propio is True

    # Verificar que se suscribió el webhook al WABA
    assert any("/waba_oficial_1001/subscribed_apps" in llamada[0] for llamada in llamadas_post)


def test_intercambio_real_con_ids_en_payload(sesion, comercio, app, monkeypatch):
    """Si el frontend ya envía waba_id y phone_number_id, no necesita consultar debug_token."""
    comercio.plan = PlanComercio.PRO
    db.session.commit()

    app.config["META_APP_ID"] = "app_real_123"
    app.config["WHATSAPP_APP_SECRET"] = "secret_real_456"

    llamadas_get = []
    llamadas_post = []

    def mock_get(url, params=None, timeout=10):
        llamadas_get.append((url, params))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        if "/oauth/access_token" in url:
            mock_resp.json.return_value = {"access_token": "token_directo_abc"}
        elif "/phone_directo_3003" in url:
            mock_resp.json.return_value = {"display_phone_number": "+54 9 351 777-8888"}
        return mock_resp

    def mock_post(url, params=None, timeout=10):
        llamadas_post.append((url, params))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True}
        return mock_resp

    import requests

    monkeypatch.setattr(requests, "get", mock_get)
    monkeypatch.setattr(requests, "post", mock_post)

    r = sesion.post(
        "/plan/whatsapp/embedded-callback",
        json={
            "code": "auth_directo",
            "waba_id": "waba_directo_3003",
            "phone_number_id": "phone_directo_3003",
        },
    )
    assert r.status_code == 200

    db.session.refresh(comercio)
    assert comercio.whatsapp_waba_id == "waba_directo_3003"
    assert comercio.whatsapp_phone_number_id == "phone_directo_3003"
    assert comercio.whatsapp_token == "token_directo_abc"
    assert comercio.whatsapp_numero_publico == "+54 9 351 777-8888"


def test_desconexion_whatsapp_comercio(sesion, comercio, app, monkeypatch):
    """Desconectar la línea limpia los campos y desuscribe la app en Meta si hay credenciales."""
    comercio.plan = PlanComercio.PRO
    comercio.whatsapp_phone_number_id = "10987654321"
    comercio.whatsapp_waba_id = "waba_activo_123"
    comercio.whatsapp_token = "token_activo"
    comercio.whatsapp_numero_publico = "5493512345678"
    db.session.commit()

    app.config["META_APP_ID"] = "app_123"
    app.config["WHATSAPP_APP_SECRET"] = "secret_123"

    llamadas_delete = []

    def mock_delete(url, params=None, timeout=10):
        llamadas_delete.append((url, params))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        return mock_resp

    import requests

    monkeypatch.setattr(requests, "delete", mock_delete)

    # 1. Probar desconexión vía endpoint web
    r = sesion.post("/plan/whatsapp", data={"accion": "desconectar"}, follow_redirects=True)
    assert r.status_code == 200
    assert "Línea de WhatsApp desconectada" in r.get_data(as_text=True)

    db.session.refresh(comercio)
    assert comercio.whatsapp_phone_number_id is None
    assert comercio.whatsapp_waba_id is None
    assert comercio.whatsapp_token is None
    assert comercio.whatsapp_numero_publico is None
    assert comercio.tiene_whatsapp_propio is False

    assert len(llamadas_delete) == 1
    assert "/waba_activo_123/subscribed_apps" in llamadas_delete[0][0]


def test_errores_codigos_invalidos_meta(sesion, comercio, app, monkeypatch):
    """Manejo de errores ante códigos vacíos o rechazados por Meta."""
    # 1. Código vacío
    r = sesion.post("/plan/whatsapp/embedded-callback", json={})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False

    # 2. Código inválido en modo simulado
    r_sim = sesion.post("/plan/whatsapp/embedded-callback", json={"code": "invalido"})
    assert r_sim.status_code == 400
    assert "inválido" in r_sim.get_json()["error"].lower()

    # 3. Código rechazado por Meta en modo real
    app.config["META_APP_ID"] = "app_123"
    app.config["WHATSAPP_APP_SECRET"] = "secret_123"

    def mock_get_error(url, params=None, timeout=10):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": {
                "message": "Invalid verification code or code expired",
                "type": "OAuthException",
                "code": 100,
            }
        }
        return mock_resp

    import requests

    monkeypatch.setattr(requests, "get", mock_get_error)

    r_err = sesion.post("/plan/whatsapp/embedded-callback", json={"code": "expired_code"})
    assert r_err.status_code == 400
    datos_err = r_err.get_json()
    assert datos_err["ok"] is False
    assert "Invalid verification code" in datos_err["error"]


def test_render_plan_html_boton_y_modal(sesion, comercio):
    """La vista /plan incluye el botón data-meta-embedded-signup y el modal con los 3 pasos."""
    comercio.plan = PlanComercio.PRO
    db.session.commit()

    r = sesion.get("/plan")
    assert r.status_code == 200
    html = r.get_data(as_text=True)

    assert "data-meta-embedded-signup" in html
    assert "modal-meta-signup" in html
    assert "1. Iniciar sesión en Facebook" in html
    assert "2. Seleccionar o registrar el número de su comercio" in html
    assert "3. Autorizar conexión" in html
    assert "Modo asistido / prueba disponible con un clic" in html
