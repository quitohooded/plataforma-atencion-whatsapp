"""Atención de los mensajes entrantes con persistencia (CU08 a CU12).

Este servicio es el punto de entrada común para el webhook de WhatsApp y para
el simulador. Identifica el comercio (por el código de acceso o por la
conversación vigente), registra al comprador, sostiene la conversación,
guarda los mensajes y registra las consultas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import select

from ..extensiones import db
from ..modelos import (
    Comercio,
    Comprador,
    Consulta,
    Conversacion,
    DireccionMensaje,
    EstadoComercio,
    EstadoConversacion,
    Mensaje,
    PalabraClave,
)
from ..utilidades import tiempo
from . import respuestas
from .normalizacion import candidatos_codigo, quitar_texto

log = logging.getLogger(__name__)


@dataclass
class MensajeEntrante:
    telefono: str
    texto: str
    nombre: str | None = None
    id_externo: str | None = None
    fecha_hora: datetime | None = None


@dataclass
class ResultadoAtencion:
    respuestas: list[str] = field(default_factory=list)
    conversacion: Conversacion | None = None
    consulta: Consulta | None = None
    duplicado: bool = False


def procesar_mensaje_entrante(entrante: MensajeEntrante) -> ResultadoAtencion:
    ahora = entrante.fecha_hora or tiempo.ahora()
    telefono = normalizar_telefono(entrante.telefono)
    texto = (entrante.texto or "").strip()

    # WhatsApp puede reenviar el mismo evento: se descarta si ya fue procesado.
    if entrante.id_externo and db.session.scalar(
        select(Mensaje.id_mensaje).where(Mensaje.id_externo == entrante.id_externo)
    ):
        return ResultadoAtencion(duplicado=True)

    comprador = db.session.scalar(select(Comprador).where(Comprador.telefono == telefono))
    conversacion = conversacion_vigente(comprador, ahora) if comprador else None

    comercio, codigo = buscar_comercio_por_codigo(texto)
    texto_util = texto
    primer_contacto = False

    if comercio:
        # El mensaje trae un código de acceso: primer contacto o cambio de comercio.
        texto_util = quitar_texto(quitar_texto(texto, f"#{codigo}"), codigo)
        texto_util = quitar_texto(texto_util, comercio.nombre)
        primer_contacto = True
        if conversacion and conversacion.id_comercio != comercio.id_comercio:
            conversacion.cambiar_estado(EstadoConversacion.CERRADA)
            conversacion = None
    elif conversacion:
        comercio = conversacion.comercio
    else:
        # Comprador que vuelve sin el enlace: se retoma con el último comercio con el que habló.
        anterior = ultima_conversacion(comprador) if comprador else None
        if anterior is None:
            db.session.commit()
            return ResultadoAtencion([respuestas.comercio_no_identificado()])
        comercio = anterior.comercio

    # Durante la derivación no se responde, aunque el bot esté pausado (CU12).
    derivada = conversacion is not None and conversacion.estado == EstadoConversacion.DERIVADA

    if comercio.estado != EstadoComercio.ACTIVO and not derivada:
        aviso = respuestas.bot_pausado(comercio.nombre, comercio.telefono_contacto)
        if conversacion:
            _guardar_mensaje(conversacion, texto, DireccionMensaje.ENTRANTE, ahora, entrante.id_externo)
            _guardar_mensaje(conversacion, aviso, DireccionMensaje.SALIENTE, ahora)
            conversacion.ultima_actividad = ahora
        db.session.commit()
        return ResultadoAtencion([aviso], conversacion)

    if comprador is None:
        comprador = Comprador(telefono=telefono, nombre=entrante.nombre or None, fecha_primer_contacto=ahora)
        db.session.add(comprador)
    elif entrante.nombre and not comprador.nombre:
        comprador.nombre = entrante.nombre

    if conversacion is None:
        conversacion = Conversacion(
            comercio=comercio,
            comprador=comprador,
            estado=EstadoConversacion.ACTIVA,
            fecha_inicio=ahora,
            ultima_actividad=ahora,
            intentos_cp=0,
        )
        db.session.add(conversacion)

    _guardar_mensaje(conversacion, texto, DireccionMensaje.ENTRANTE, ahora, entrante.id_externo)

    palabras = db.session.scalars(select(PalabraClave)).all()
    resultado = conversacion.procesar_mensaje(
        texto_util,
        palabras,
        ahora,
        max_intentos_cp=current_app.config.get("BOT_MAX_INTENTOS_CP", 2),
        primer_contacto=primer_contacto,
    )

    for texto_respuesta in resultado.respuestas:
        _guardar_mensaje(conversacion, texto_respuesta, DireccionMensaje.SALIENTE, ahora)

    consulta = None
    if resultado.consulta:
        consulta = Consulta(
            conversacion=conversacion,
            tema=resultado.consulta.tema,
            resultado=resultado.consulta.resultado,
            codigo_postal=resultado.consulta.codigo_postal,
            fecha_hora=ahora,
            atendida=False,
        )
        db.session.add(consulta)

    conversacion.ultima_actividad = ahora
    db.session.commit()
    log.info(
        "Mensaje de %s para %s: estado=%s tema=%s",
        telefono,
        comercio.nombre,
        conversacion.estado.value,
        resultado.tema_detectado.value if resultado.tema_detectado else "-",
    )
    return ResultadoAtencion(resultado.respuestas, conversacion, consulta)


def _guardar_mensaje(
    conversacion: Conversacion,
    texto: str,
    direccion: DireccionMensaje,
    fecha_hora: datetime,
    id_externo: str | None = None,
) -> Mensaje:
    mensaje = Mensaje(
        conversacion=conversacion,
        texto=texto or "",
        direccion=direccion,
        fecha_hora=fecha_hora,
        id_externo=id_externo,
    )
    db.session.add(mensaje)
    return mensaje


def normalizar_telefono(telefono: str) -> str:
    return "".join(ch for ch in (telefono or "") if ch.isdigit())


def buscar_comercio_por_codigo(texto: str) -> tuple[Comercio | None, str | None]:
    candidatos = candidatos_codigo(texto)
    if not candidatos:
        return None, None
    comercio = db.session.scalar(select(Comercio).where(Comercio.codigo_acceso.in_(candidatos)))
    if comercio is None:
        return None, None
    return comercio, comercio.codigo_acceso


def conversacion_vigente(comprador: Comprador, ahora: datetime) -> Conversacion | None:
    """Conversación no cerrada más reciente. Si superó el tiempo de inactividad, se cierra."""
    conversacion = db.session.scalar(
        select(Conversacion)
        .where(Conversacion.id_comprador == comprador.id_comprador, Conversacion.estado != EstadoConversacion.CERRADA)
        .order_by(Conversacion.ultima_actividad.desc(), Conversacion.id_conversacion.desc())
    )
    if conversacion is None:
        return None
    horas = current_app.config.get("CONVERSACION_HORAS_INACTIVIDAD", 24)
    if ahora - conversacion.ultima_actividad > timedelta(hours=horas):
        conversacion.cambiar_estado(EstadoConversacion.CERRADA)
        return None
    return conversacion


def ultima_conversacion(comprador: Comprador) -> Conversacion | None:
    return db.session.scalar(
        select(Conversacion)
        .where(Conversacion.id_comprador == comprador.id_comprador)
        .order_by(Conversacion.ultima_actividad.desc(), Conversacion.id_conversacion.desc())
    )


def historial_comprador(telefono: str, limite: int = 200) -> list[Mensaje]:
    """Mensajes de todas las conversaciones de un comprador (lo usa el simulador)."""
    telefono = normalizar_telefono(telefono)
    comprador = db.session.scalar(select(Comprador).where(Comprador.telefono == telefono))
    if comprador is None:
        return []
    mensajes = db.session.scalars(
        select(Mensaje)
        .join(Conversacion)
        .where(Conversacion.id_comprador == comprador.id_comprador)
        .order_by(Mensaje.fecha_hora, Mensaje.id_mensaje)
    ).all()
    return list(mensajes)[-limite:]
