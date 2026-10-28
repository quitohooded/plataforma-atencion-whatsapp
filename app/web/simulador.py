"""Simulador de la línea de WhatsApp para demos y pruebas sin Meta.

Reproduce lo que vive un comprador: escribe a la línea compartida de la
plataforma y recibe las respuestas del bot. Usa exactamente el mismo servicio
que el webhook, por lo que las conversaciones y consultas quedan registradas en
el panel del comercio. Se desactiva con SIMULADOR_HABILITADO=false.
"""

import secrets

from flask import Blueprint, abort, current_app, jsonify, render_template, request
from sqlalchemy import select

from ..bot.servicio import MensajeEntrante, historial_comprador, normalizar_telefono, procesar_mensaje_entrante
from ..extensiones import db
from ..modelos import Comercio, DireccionMensaje, EstadoComercio

bp = Blueprint("simulador", __name__, url_prefix="/simulador")

# 549 351 0XXXXXX: un número local que empieza con 0 no es asignable en Argentina,
# así que los compradores simulados nunca coinciden con una persona real.
PREFIJO_PRUEBA = "5493510"


@bp.before_request
def habilitado():
    if not current_app.config.get("SIMULADOR_HABILITADO"):
        abort(404)


def numero_de_prueba() -> str:
    return PREFIJO_PRUEBA + "".join(secrets.choice("0123456789") for _ in range(6))


@bp.get("")
def inicio():
    comercios = db.session.scalars(
        select(Comercio).where(Comercio.codigo_acceso.is_not(None)).order_by(Comercio.nombre)
    ).all()
    return render_template(
        "simulador/simulador.html",
        comercios=comercios,
        texto_inicial=request.args.get("text", ""),
        numero_sugerido=numero_de_prueba(),
        EstadoComercio=EstadoComercio,
    )


def _serializar(mensaje) -> dict:
    return {
        "texto": mensaje.texto,
        "saliente": mensaje.direccion == DireccionMensaje.SALIENTE,
        "hora": mensaje.fecha_hora.strftime("%H:%M"),
        "fecha": mensaje.fecha_hora.strftime("%d/%m/%Y"),
        "comercio": mensaje.conversacion.comercio.nombre,
    }


@bp.get("/api/mensajes")
def mensajes():
    telefono = normalizar_telefono(request.args.get("telefono", ""))
    if not telefono:
        return jsonify(mensajes=[])
    return jsonify(mensajes=[_serializar(m) for m in historial_comprador(telefono)])


@bp.post("/api/mensajes")
def enviar():
    datos = request.get_json(silent=True) or {}
    telefono = normalizar_telefono(str(datos.get("telefono", "")))
    texto = str(datos.get("texto", "")).strip()[:1000]
    nombre = str(datos.get("nombre", "")).strip()[:60] or None
    if not telefono.startswith(PREFIJO_PRUEBA) or len(telefono) != 13:
        return jsonify(error="El simulador solo admite números de prueba (549 351 0XXXXXX)."), 400
    if not texto:
        return jsonify(error="Escriba un mensaje."), 400
    resultado = procesar_mensaje_entrante(MensajeEntrante(telefono=telefono, texto=texto, nombre=nombre))
    conversacion = resultado.conversacion
    return jsonify(
        respuestas=resultado.respuestas,
        comercio=conversacion.comercio.nombre if conversacion else None,
        estado=conversacion.estado.etiqueta if conversacion else None,
    )
