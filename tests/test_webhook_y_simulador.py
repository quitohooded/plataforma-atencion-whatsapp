"""Integración con WhatsApp Business Platform (webhook y envío) y simulador (RNF01, CU12 excepción)."""

import hashlib
import hmac
import json

from sqlalchemy import select

from app.extensiones import db
from app.mensajeria import cloud_api
from app.mensajeria.cloud_api import ClienteWhatsApp, ErrorEnvio, extraer_mensajes
from app.modelos import Consulta, Mensaje


def evento(texto, telefono="5493511234567", id_mensaje="wamid.A1", nombre="Lucía", tipo="text"):
    mensaje = {"from": telefono, "id": id_mensaje, "timestamp": "1793151000", "type": tipo}
    if tipo == "text":
        mensaje["text"] = {"body": texto}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "15550000000", "phone_number_id": "123"},
                            "contacts": [{"profile": {"name": nombre}, "wa_id": telefono}],
                            "messages": [mensaje],
                        },
                    }
                ],
            }
        ],
    }


def firmar(cuerpo: bytes, secreto="secreto-de-prueba"):
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def publicar(cliente, payload, firma=None):
    cuerpo = json.dumps(payload).encode()
    return cliente.post(
        "/webhook/whatsapp",
        data=cuerpo,
        content_type="application/json",
        headers={"X-Hub-Signature-256": firma or firmar(cuerpo)},
    )


def test_verificacion_del_webhook(cliente):
    ok = cliente.get("/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=token-de-prueba&hub.challenge=42")
    assert ok.status_code == 200 and ok.get_data(as_text=True) == "42"
    assert cliente.get("/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=otro&hub.challenge=42").status_code == 403


def test_firma_invalida_se_rechaza(cliente, comercio):
    assert publicar(cliente, evento("hola"), firma="sha256=falsa").status_code == 401


def test_mensaje_entrante_se_atiende_y_se_responde_por_la_api(cliente, comercio, monkeypatch):
    enviados = []
    monkeypatch.setattr(ClienteWhatsApp, "enviar", lambda self, tel, respuesta: enviados.append((tel, respuesta)))
    publicar(cliente, evento(comercio.texto_primer_mensaje(), id_mensaje="wamid.1"))
    r = publicar(cliente, evento("¿Aceptan Mercado Pago?", id_mensaje="wamid.2"))
    assert r.status_code == 200
    assert len(enviados) == 2
    assert enviados[0][1].botones  # la bienvenida lleva botones
    assert enviados[1][0] == "5493511234567" and "Mercado Pago" in enviados[1][1].texto
    assert db.session.scalar(select(Consulta)).tema.value == "MEDIOS_PAGO"
    # Reenvío del mismo evento: no se procesa dos veces.
    publicar(cliente, evento("¿Aceptan Mercado Pago?", id_mensaje="wamid.2"))
    assert len(enviados) == 2


def test_falla_de_envio_conserva_la_consulta_pendiente(cliente, comercio, monkeypatch):
    def falla(self, tel, respuesta):
        raise ErrorEnvio("WhatsApp rechazó el envío", 131030)

    monkeypatch.setattr(ClienteWhatsApp, "enviar", falla)
    publicar(cliente, evento(comercio.texto_primer_mensaje(), id_mensaje="wamid.1"))
    assert publicar(cliente, evento("tienen almohadones?", id_mensaje="wamid.2")).status_code == 200
    assert db.session.scalar(select(Consulta)).pendiente


def test_mensajes_que_no_son_texto_y_estados(comercio):
    audio = extraer_mensajes(evento(None, tipo="audio"))
    assert (audio[0].tipo, audio[0].texto, audio[0].nombre) == ("audio", "", "Lucía")
    estados = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "read"}]}}]}]}
    assert extraer_mensajes(estados) == []


def _con_mensaje(datos: dict):
    payload = evento("x")
    payload["entry"][0]["changes"][0]["value"]["messages"] = [{"from": "5493511234567", "id": "wamid.Z", **datos}]
    return extraer_mensajes(payload)[0]


def test_extrae_botones_e_imagenes_con_texto():
    boton = _con_mensaje(
        {
            "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": "op_pago", "title": "Medios de pago"}},
        }
    )
    assert (boton.tipo, boton.texto, boton.boton) == ("interactive", "Medios de pago", "op_pago")
    imagen = _con_mensaje({"type": "image", "image": {"id": "1", "caption": "el comprobante"}})
    assert (imagen.tipo, imagen.texto) == ("image", "el comprobante")
    reaccion = _con_mensaje({"type": "reaction", "reaction": {"emoji": "👍", "message_id": "wamid.Y"}})
    assert (reaccion.tipo, reaccion.texto) == ("reaction", "👍")


def test_boton_tocado_en_whatsapp_llega_al_bot(cliente, comercio, monkeypatch):
    enviados = []
    monkeypatch.setattr(ClienteWhatsApp, "enviar", lambda self, tel, respuesta: enviados.append(respuesta))
    publicar(cliente, evento(comercio.texto_primer_mensaje(), id_mensaje="wamid.1"))
    payload = evento("", id_mensaje="wamid.2")
    payload["entry"][0]["changes"][0]["value"]["messages"][0] = {
        "from": "5493511234567",
        "id": "wamid.2",
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": "op_horario", "title": "Horarios"}},
    }
    publicar(cliente, payload)
    assert "Nuestro horario de atención" in enviados[-1].texto


def test_numero_argentino_sin_el_9_para_enviar():
    cliente = ClienteWhatsApp(token="t", phone_number_id="123")
    assert cliente.destino("5493511234567") == "543511234567"
    assert cliente.destino("15551234567") == "15551234567"
    assert (
        ClienteWhatsApp(token="t", phone_number_id="123", quitar_9_argentina=False).destino("5493511234567")
        == "5493511234567"
    )


class RespuestaFalsa:
    def __init__(self, estado, cuerpo):
        self.status_code, self._cuerpo, self.text = estado, cuerpo, json.dumps(cuerpo)

    def json(self):
        return self._cuerpo


def test_envio_con_botones_por_graph_api(monkeypatch):
    from app.bot.respuestas import Boton, Respuesta

    llamadas = []

    def post(url, json=None, timeout=None, headers=None):
        llamadas.append(json)
        return RespuestaFalsa(200, {"messages": [{"id": "wamid.OK"}]})

    monkeypatch.setattr(cloud_api.requests, "post", post)
    cliente = ClienteWhatsApp(token="TOKEN", phone_number_id="123")
    respuesta = Respuesta(
        "¿Qué necesitás?", (Boton("op_envio", "Envíos"), Boton("op_pago", "Medios de pago")), "Escribí 1 o 2."
    )
    assert cliente.enviar("5493511234567", respuesta) == "wamid.OK"
    cuerpo = llamadas[0]
    assert cuerpo["type"] == "interactive" and cuerpo["interactive"]["type"] == "button"
    assert cuerpo["interactive"]["body"]["text"] == "¿Qué necesitás?"
    assert cuerpo["interactive"]["action"]["buttons"][1] == {
        "type": "reply",
        "reply": {"id": "op_pago", "title": "Medios de pago"},
    }


def test_si_whatsapp_rechaza_los_botones_se_envia_texto(monkeypatch):
    from app.bot.respuestas import Boton, Respuesta

    llamadas = []

    def post(url, json=None, timeout=None, headers=None):
        llamadas.append(json)
        if json["type"] == "interactive":
            return RespuestaFalsa(400, {"error": {"code": 131009, "message": "Parameter value is not valid"}})
        return RespuestaFalsa(200, {"messages": [{"id": "wamid.TXT"}]})

    monkeypatch.setattr(cloud_api.requests, "post", post)
    respuesta = Respuesta("Elegí una opción.", (Boton("op_envio", "Envíos"),), "Escribí *1* para envíos.")
    assert ClienteWhatsApp(token="T", phone_number_id="1").enviar("5493511234567", respuesta) == "wamid.TXT"
    assert llamadas[1]["text"]["body"] == "Elegí una opción.\n\nEscribí *1* para envíos."


def test_envio_por_graph_api(monkeypatch):
    llamadas = []

    def post(url, json=None, timeout=None, headers=None):
        llamadas.append((url, json, headers))
        return RespuestaFalsa(200, {"messages": [{"id": "wamid.OK"}]})

    monkeypatch.setattr(cloud_api.requests, "post", post)
    cliente = ClienteWhatsApp(token="TOKEN", phone_number_id="123", version="v23.0")
    assert cliente.enviar_texto("5493511234567", "hola") == "wamid.OK"
    url, cuerpo, encabezados = llamadas[0]
    assert url == "https://graph.facebook.com/v23.0/123/messages"
    assert cuerpo["to"] == "543511234567" and cuerpo["text"]["body"] == "hola"
    assert encabezados["Authorization"] == "Bearer TOKEN"


def test_error_de_la_api_explica_la_lista_de_destinatarios(monkeypatch):
    monkeypatch.setattr(
        cloud_api.requests,
        "post",
        lambda *a, **k: RespuestaFalsa(
            400, {"error": {"code": 131030, "message": "Recipient phone number not in allowed list"}}
        ),
    )
    try:
        ClienteWhatsApp(token="T", phone_number_id="1").enviar_texto("5493511234567", "hola")
    except ErrorEnvio as error:
        assert error.codigo == 131030 and "lista de destinatarios" in str(error)
    else:
        raise AssertionError("se esperaba ErrorEnvio")


def test_sin_credenciales_no_envia(app):
    assert ClienteWhatsApp(token="", phone_number_id="").enviar_texto("549351", "hola") is None


def test_simulador_usa_el_mismo_servicio(cliente, comercio):
    r = cliente.post(
        "/simulador/api/mensajes", json={"telefono": "5493510000077", "texto": comercio.texto_primer_mensaje()}
    )
    bienvenida = r.get_json()["respuestas"][0]
    assert r.status_code == 200 and "Casa & Detalles" in bienvenida["texto"]
    assert [b["id"] for b in bienvenida["botones"]] == ["op_envio", "op_pago", "op_horario"]
    cliente.post(
        "/simulador/api/mensajes", json={"telefono": "5493510000077", "texto": "Horarios", "boton": "op_horario"}
    )
    historial = cliente.get("/simulador/api/mensajes?telefono=5493510000077").get_json()["mensajes"]
    assert len(historial) == 4 and historial[-1]["saliente"]
    assert historial[1]["botones"][0]["titulo"] == "Envíos"
    assert db.session.scalar(select(Consulta)).tema.value == "HORARIOS"


def test_simulador_solo_admite_numeros_de_prueba(cliente, comercio):
    r = cliente.post("/simulador/api/mensajes", json={"telefono": "5493511234567", "texto": "hola"})
    assert r.status_code == 400
    assert db.session.scalar(select(Mensaje)) is None


def test_simulador_deshabilitado(app, cliente):
    app.config["SIMULADOR_HABILITADO"] = False
    assert cliente.get("/simulador").status_code == 404
