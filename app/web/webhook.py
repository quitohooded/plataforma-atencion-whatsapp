"""Webhook de WhatsApp Business Platform (Cloud API).

GET  /webhook/whatsapp  verificación de la suscripción (hub.challenge).
POST /webhook/whatsapp  recepción de mensajes y de estados de entrega. Cada mensaje se
                        marca como leído, se atiende con el servicio del bot y las
                        respuestas se envían por la Graph API; los estados de entrega se
                        guardan en el mensaje enviado (y las fallas quedan en el registro).
"""

import logging
from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, request
from sqlalchemy import select

from ..bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from ..extensiones import csrf, db
from ..mensajeria.cloud_api import ClienteWhatsApp, ErrorEnvio, extraer_estados, extraer_mensajes, firma_valida
from ..modelos import Mensaje
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
    if not firma_valida(
        cuerpo,
        request.headers.get("X-Hub-Signature-256"),
        current_app.config.get("WHATSAPP_APP_SECRET", ""),
        permitir_sin_clave=current_app.config.get("WHATSAPP_PERMITIR_SIN_FIRMA", False),
    ):
        log.warning("Webhook rechazado: firma inválida o sin WHATSAPP_APP_SECRET configurado.")
        abort(401)

    payload = request.get_json(silent=True) or {}
    cliente = ClienteWhatsApp.desde_config()
    procesados = 0
    for evento in extraer_mensajes(payload):
        fecha_hora = None
        if evento.timestamp:
            fecha_hora = datetime.fromtimestamp(evento.timestamp, tiempo.zona_horaria()).replace(tzinfo=None)
        try:
            resultado = procesar_mensaje_entrante(
                MensajeEntrante(
                    telefono=evento.telefono,
                    texto=evento.texto,
                    nombre=evento.nombre,
                    id_externo=evento.id_externo or None,
                    fecha_hora=fecha_hora,
                    tipo=evento.tipo,
                    boton=evento.boton,
                )
            )
        except Exception:
            db.session.rollback()
            log.exception("Error al procesar el mensaje %s", evento.id_externo)
            continue
        if resultado.duplicado:
            continue
        procesados += 1
        _marcar_leido(cliente, evento.id_externo)
        _enviar_respuestas(cliente, evento.telefono, resultado)

    _registrar_estados(extraer_estados(payload))
    # Meta espera un 200 rápido; si no lo recibe, reintenta el envío del evento.
    return jsonify(procesados=procesados), 200


def _marcar_leido(cliente: ClienteWhatsApp, id_externo: str) -> None:
    """El comprador ve su mensaje como leído: sabe que llegó aunque la respuesta tarde."""
    try:
        cliente.marcar_leido(id_externo)
    except ErrorEnvio as error:
        log.info("No se pudo marcar como leído el mensaje %s: %s", id_externo, error)


def _enviar_respuestas(cliente: ClienteWhatsApp, telefono: str, resultado) -> None:
    """Envía las respuestas y guarda el identificador de WhatsApp de cada una, para seguir su entrega."""
    salientes = list(resultado.salientes) + [None] * (len(resultado.respuestas) - len(resultado.salientes))
    for respuesta, mensaje in zip(resultado.respuestas, salientes[: len(resultado.respuestas)], strict=True):
        try:
            id_whatsapp = cliente.enviar(telefono, respuesta)
        except ErrorEnvio as error:
            # CU12, excepción: se registra el error; la conversación queda en el panel y el
            # detalle muestra la respuesta como no entregada.
            log.error("No se pudo enviar la respuesta a %s: %s", _ocultar(telefono), error)
            if mensaje is not None:
                mensaje.actualizar_estado_envio("fallido")
            continue
        if mensaje is not None and id_whatsapp:
            mensaje.id_externo = id_whatsapp
            mensaje.actualizar_estado_envio("enviado")
    db.session.commit()


def _registrar_estados(estados) -> None:
    """Estados de entrega (enviado, entregado, leído, fallido) de las respuestas del bot (O7)."""
    if not estados:
        return
    for estado in estados:
        if estado.estado == "fallido":
            log.warning(
                "WhatsApp no pudo entregar el mensaje %s a %s: %s",
                estado.id_externo,
                _ocultar(estado.destinatario),
                estado.error or "sin detalle",
            )
        mensaje = db.session.scalar(select(Mensaje).where(Mensaje.id_externo == estado.id_externo))
        if mensaje is not None:
            mensaje.actualizar_estado_envio(estado.estado)
    db.session.commit()


def _ocultar(telefono: str) -> str:
    """Teléfono para los registros: solo los últimos cuatro dígitos."""
    digitos = "".join(ch for ch in telefono or "" if ch.isdigit())
    return f"…{digitos[-4:]}" if digitos else "-"
