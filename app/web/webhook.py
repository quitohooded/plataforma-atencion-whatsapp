"""Webhook de WhatsApp Business Platform (Cloud API).

GET  /webhook/whatsapp  verificación de la suscripción (hub.challenge).
POST /webhook/whatsapp  recepción de mensajes; cada uno se atiende con el
                        servicio del bot y las respuestas se envían por la Graph API.
"""

import logging
from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, request

from ..bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from ..extensiones import csrf, db
from ..mensajeria.cloud_api import ClienteWhatsApp, ErrorEnvio, extraer_mensajes, firma_valida
from ..utilidades import tiempo

log = logging.getLogger(__name__)

bp = Blueprint("webhook", __name__, url_prefix="/webhook")
csrf.exempt(bp)


@bp.get("/whatsapp")
def verificar():
    modo = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    desafio = request.args.get("hub.challenge", "")
    esperado = current_app.config.get("WHATSAPP_VERIFY_TOKEN")
    if modo == "subscribe" and esperado and token == esperado:
        log.info("Webhook de WhatsApp verificado.")
        return desafio, 200, {"Content-Type": "text/plain"}
    abort(403)


@bp.post("/whatsapp")
def recibir():
    cuerpo = request.get_data()
    if not firma_valida(cuerpo, request.headers.get("X-Hub-Signature-256"),
                        current_app.config.get("WHATSAPP_APP_SECRET", "")):
        log.warning("Webhook rechazado: firma inválida.")
        abort(401)

    payload = request.get_json(silent=True) or {}
    cliente = ClienteWhatsApp.desde_config()
    procesados = 0
    for evento in extraer_mensajes(payload):
        fecha_hora = None
        if evento.timestamp:
            fecha_hora = datetime.fromtimestamp(evento.timestamp, tiempo.zona_horaria()).replace(tzinfo=None)
        try:
            resultado = procesar_mensaje_entrante(MensajeEntrante(
                telefono=evento.telefono, texto=evento.texto, nombre=evento.nombre,
                id_externo=evento.id_externo or None, fecha_hora=fecha_hora,
            ))
        except Exception:
            db.session.rollback()
            log.exception("Error al procesar el mensaje %s", evento.id_externo)
            continue
        if resultado.duplicado:
            continue
        procesados += 1
        for texto in resultado.respuestas:
            try:
                cliente.enviar_texto(evento.telefono, texto)
            except ErrorEnvio as error:
                # CU12, excepción: se registra el error y la consulta queda pendiente en el panel.
                log.error("No se pudo enviar la respuesta a %s: %s", evento.telefono, error)
    # Meta espera un 200 rápido; si no lo recibe, reintenta el envío del evento.
    return jsonify(procesados=procesados), 200
