"""CU Live Inbox & Atención Humana en Vivo (Panel Multi-Agente - Pilar 3).

Permite al comerciante y sus operadores ver conversaciones en vivo de WhatsApp
y Canal Web, pausar al bot, responder en tiempo real y cerrar chats.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import or_, select

from ..extensiones import db
from ..mensajeria.cloud_api import ClienteWhatsApp
from ..modelos import Comprador, Conversacion, DireccionMensaje, EstadoConversacion, Mensaje
from ..utilidades import tiempo
from . import del_comercio, requiere_onboarding

log = logging.getLogger(__name__)

bp = Blueprint("inbox", __name__, url_prefix="/inbox")


@bp.get("")
@bp.get("/")
@requiere_onboarding
def inicio():
    ahora = tiempo.ahora()
    filtro = request.args.get("filtro", "todas").strip().lower()
    q = request.args.get("q", "").strip()
    id_sel = request.args.get("conversacion", type=int)

    consulta = (
        select(Conversacion)
        .join(Comprador)
        .where(Conversacion.id_comercio == g.comercio.id_comercio)
    )

    if filtro == "humanas":
        consulta = consulta.where(
            or_(
                Conversacion.pausa_humana_hasta > ahora,
                Conversacion.estado == EstadoConversacion.DERIVADA,
            )
        )
    elif filtro == "bot":
        consulta = consulta.where(
            Conversacion.estado == EstadoConversacion.ACTIVA,
            or_(
                Conversacion.pausa_humana_hasta.is_(None),
                Conversacion.pausa_humana_hasta <= ahora,
            ),
        )
    elif filtro == "cerradas":
        consulta = consulta.where(Conversacion.estado == EstadoConversacion.CERRADA)

    if q:
        patron = f"%{q}%"
        consulta = consulta.where(
            or_(
                Comprador.nombre.ilike(patron),
                Comprador.telefono.contains(q),
            )
        )

    consulta = consulta.order_by(Conversacion.ultima_actividad.desc(), Conversacion.id_conversacion.desc())
    conversaciones = db.session.scalars(consulta).all()

    conversacion_seleccionada = None
    if id_sel:
        conversacion_seleccionada = db.session.scalar(
            select(Conversacion).where(
                Conversacion.id_conversacion == id_sel,
                Conversacion.id_comercio == g.comercio.id_comercio,
            )
        )
    if conversacion_seleccionada is None and conversaciones:
        conversacion_seleccionada = conversaciones[0]

    return render_template(
        "panel/inbox.html",
        seccion="inbox",
        conversaciones=conversaciones,
        conversacion_seleccionada=conversacion_seleccionada,
        filtro=filtro,
        q=q,
        ahora=ahora,
        respuestas_rapidas=g.comercio.respuestas_activas,
    )


@bp.get("/<int:id_conversacion>/mensajes")
@requiere_onboarding
def mensajes(id_conversacion: int):
    conversacion = del_comercio(Conversacion, id_conversacion)
    ahora = tiempo.ahora()
    items = []
    for m in conversacion.mensajes:
        items.append(
            {
                "id_mensaje": m.id_mensaje,
                "texto": m.texto,
                "hora": m.fecha_hora.strftime("%H:%M"),
                "fecha": m.fecha_hora.strftime("%d/%m/%Y"),
                "direccion": m.direccion.value if hasattr(m.direccion, "value") else str(m.direccion),
                "emisor_tipo": m.emisor_tipo,
                "nombre_emisor": m.nombre_emisor,
                "estado_envio": m.estado_envio,
            }
        )
    return jsonify(
        ok=True,
        pausa_humana=conversacion.en_pausa_humana(ahora),
        estado=conversacion.estado.value if hasattr(conversacion.estado, "value") else str(conversacion.estado),
        mensajes=items,
    )


@bp.post("/<int:id_conversacion>/responder")
@requiere_onboarding
def responder(id_conversacion: int):
    conversacion = del_comercio(Conversacion, id_conversacion)
    if request.is_json:
        texto = (request.json.get("texto") or "").strip()
    else:
        texto = (request.form.get("texto") or "").strip()

    es_ajax = (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )

    if not texto:
        if es_ajax:
            return jsonify(ok=False, error="El texto no puede estar vacío"), 400
        flash("El mensaje no puede estar vacío.", "error")
        return redirect(url_for("inbox.inicio", conversacion=id_conversacion))

    ahora = tiempo.ahora()
    nombre_operador = getattr(g.usuario, "nombre", None) or (g.comercio.nombre if g.comercio else "Operador")

    mensaje = Mensaje(
        conversacion=conversacion,
        texto=texto,
        direccion=DireccionMensaje.SALIENTE,
        fecha_hora=ahora,
        emisor_tipo="OPERADOR",
        nombre_emisor=nombre_operador,
    )
    db.session.add(mensaje)

    # Si es WhatsApp (no es teléfono virtual web 5493518...)
    if not conversacion.comprador.telefono.startswith("5493518"):
        cliente = ClienteWhatsApp.para_comercio(g.comercio)
        try:
            id_ext = cliente.enviar_texto(conversacion.comprador.telefono, texto)
            if id_ext and isinstance(id_ext, str):
                mensaje.id_externo = id_ext
            mensaje.estado_envio = "enviado"
        except Exception as e:
            log.warning("No se pudo enviar mensaje WhatsApp: %s", e)
            mensaje.estado_envio = "fallido"

    # Pausa humana por 2 horas y marcar atendida
    conversacion.pausa_humana_hasta = ahora + timedelta(hours=2)
    conversacion.atendida_por_humano = True
    if g.get("operador"):
        conversacion.id_operador_asignado = g.operador.id_operador
        conversacion.nombre_operador = g.operador.nombre
    else:
        conversacion.nombre_operador = nombre_operador
    conversacion.ultima_actividad = ahora

    for c in conversacion.consultas_pendientes:
        c.marcar_atendida(ahora)

    db.session.commit()

    if es_ajax:
        return jsonify(ok=True)
    return redirect(url_for("inbox.inicio", conversacion=id_conversacion))


@bp.post("/<int:id_conversacion>/pausar-bot")
@requiere_onboarding
def pausar_bot(id_conversacion: int):
    conversacion = del_comercio(Conversacion, id_conversacion)
    ahora = tiempo.ahora()
    conversacion.pausa_humana_hasta = ahora + timedelta(hours=2)
    db.session.commit()

    es_ajax = (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )
    if es_ajax:
        return jsonify(ok=True, pausa_humana=True)
    flash("Bot pausado por 2 horas en esta conversación.", "info")
    return redirect(url_for("inbox.inicio", conversacion=id_conversacion))


@bp.post("/<int:id_conversacion>/reactivar-bot")
@requiere_onboarding
def reactivar_bot(id_conversacion: int):
    conversacion = del_comercio(Conversacion, id_conversacion)
    conversacion.pausa_humana_hasta = None
    db.session.commit()

    es_ajax = (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )
    if es_ajax:
        return jsonify(ok=True, pausa_humana=False)
    flash("Bot reactivado en esta conversación.", "exito")
    return redirect(url_for("inbox.inicio", conversacion=id_conversacion))


@bp.post("/<int:id_conversacion>/cerrar")
@requiere_onboarding
def cerrar(id_conversacion: int):
    conversacion = del_comercio(Conversacion, id_conversacion)
    conversacion.cambiar_estado(EstadoConversacion.CERRADA)
    conversacion.pausa_humana_hasta = None
    db.session.commit()

    es_ajax = (
        request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )
    if es_ajax:
        return jsonify(ok=True, estado="CERRADA")
    flash("Conversación cerrada.", "info")
    return redirect(url_for("inbox.inicio", conversacion=id_conversacion))
