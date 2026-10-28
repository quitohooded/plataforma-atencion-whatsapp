"""Chat de prueba del panel (CU07, pasos 2 y 3).

Responde con la información que el comercio tiene cargada usando el mismo
motor que la línea real, pero sin guardar mensajes ni consultas. El estado de la
conversación de prueba se conserva en la sesión del navegador.
"""

from __future__ import annotations

from datetime import datetime

from flask import current_app
from sqlalchemy import select

from ..extensiones import db
from ..modelos import Comercio, EstadoConversacion, PalabraClave
from .contexto import DatosComercio
from .motor import MotorConversacional

CLAVE_SESION = "chat_prueba"


def estado_inicial() -> dict:
    return {"estado": EstadoConversacion.ACTIVA.value, "intentos_cp": 0, "iniciada": False}


def responder(comercio: Comercio, estado_sesion: dict | None, texto: str, ahora: datetime) -> tuple[dict, dict]:
    estado_sesion = dict(estado_sesion or estado_inicial())
    motor = MotorConversacional(max_intentos_cp=current_app.config.get("BOT_MAX_INTENTOS_CP", 2))
    palabras = [(p.termino, p.tema) for p in db.session.scalars(select(PalabraClave)).all()]

    resultado = motor.procesar(
        datos=DatosComercio.desde_comercio(comercio),
        estado=EstadoConversacion(estado_sesion["estado"]),
        intentos_cp=estado_sesion.get("intentos_cp", 0),
        texto=texto,
        palabras=palabras,
        ahora=ahora,
        primer_contacto=not estado_sesion.get("iniciada", False),
    )

    nota = None
    if resultado.consulta and resultado.consulta.resultado.value == "DERIVADA":
        nota = (
            "En la línea real, esta consulta quedaría pendiente en el resumen del panel y el bot "
            "dejaría de responder a este comprador hasta que la marque como atendida."
        )
        nuevo_estado = EstadoConversacion.ACTIVA
    else:
        nuevo_estado = resultado.estado

    estado_sesion.update(
        estado=nuevo_estado.value,
        intentos_cp=resultado.intentos_cp if nuevo_estado == EstadoConversacion.ESPERANDO_CP else 0,
        iniciada=True,
    )
    detalle = {
        "respuestas": resultado.respuestas,
        "nota": nota,
        "tema": resultado.tema_detectado.etiqueta if resultado.tema_detectado else None,
        "estado": EstadoConversacion(estado_sesion["estado"]).etiqueta,
    }
    return estado_sesion, detalle
