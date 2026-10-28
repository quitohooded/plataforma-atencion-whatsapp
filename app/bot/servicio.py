"""Atención de los mensajes entrantes con persistencia (CU08 a CU12).

Este servicio es el punto de entrada común para el webhook de WhatsApp y para el
simulador. Identifica el comercio (por el código de acceso o por la conversación
vigente), registra al comprador, sostiene la conversación, guarda los mensajes y
registra las consultas.
"""

from __future__ import annotations

import json
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
from .motor import BOTONES
from .normalizacion import candidatos_codigo, limpiar_texto_enlace
from .respuestas import Respuesta

log = logging.getLogger(__name__)

# Texto con el que se guarda un mensaje que no es de texto (lo ve el comercio en el historial).
DESCRIPCION_TIPO = {
    "image": "📷 Imagen",
    "audio": "🎤 Audio",
    "video": "🎬 Video",
    "document": "📄 Documento",
    "sticker": "Sticker",
    "location": "📍 Ubicación",
    "contacts": "👤 Contacto",
    "reaction": "Reacción",
}


@dataclass
class MensajeEntrante:
    telefono: str
    texto: str
    nombre: str | None = None
    id_externo: str | None = None
    fecha_hora: datetime | None = None
    # Tipo de mensaje de WhatsApp: text, image, audio, location, interactive...
    tipo: str = "text"
    # Identificador del botón tocado (mensajes interactivos); el texto es su título.
    boton: str | None = None


@dataclass
class ResultadoAtencion:
    respuestas: list[Respuesta] = field(default_factory=list)
    conversacion: Conversacion | None = None
    consultas: list[Consulta] = field(default_factory=list)
    duplicado: bool = False
    acciones: list[str] = field(default_factory=list)

    @property
    def consulta(self) -> Consulta | None:
        return self.consultas[0] if self.consultas else None

    @property
    def textos(self) -> list[str]:
        return [r.texto for r in self.respuestas]


def procesar_mensaje_entrante(entrante: MensajeEntrante) -> ResultadoAtencion:
    ahora = entrante.fecha_hora or tiempo.ahora()
    telefono = normalizar_telefono(entrante.telefono)
    texto = (entrante.texto or "").strip()
    tipo = entrante.tipo or "text"
    texto_guardado = texto if tipo in {"text", "interactive", "button"} else _descripcion(tipo, texto)

    # WhatsApp puede reenviar el mismo evento: se descarta si ya fue procesado.
    if entrante.id_externo and db.session.scalar(
        select(Mensaje.id_mensaje).where(Mensaje.id_externo == entrante.id_externo)
    ):
        return ResultadoAtencion(duplicado=True)

    comprador = db.session.scalar(select(Comprador).where(Comprador.telefono == telefono))
    conversacion = conversacion_vigente(comprador, ahora) if comprador else None

    comercio, codigo = buscar_comercio_por_codigo(texto)
    # Un botón del bot llega con su identificador; otro botón (por ejemplo, de una plantilla) se
    # entiende por su texto.
    texto_util = entrante.boton if entrante.boton in BOTONES else texto
    primer_contacto = False

    if comercio:
        # El mensaje trae un código de acceso: primer contacto o cambio de comercio.
        texto_util = limpiar_texto_enlace(texto, codigo, comercio.nombre)
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
            return ResultadoAtencion([respuestas.comercio_no_identificado()], acciones=["SIN_COMERCIO"])
        comercio = anterior.comercio

    # Con la consulta derivada se registra el mensaje aunque el bot esté pausado (CU12).
    derivada = conversacion is not None and conversacion.estado == EstadoConversacion.DERIVADA

    if comercio.estado != EstadoComercio.ACTIVO and not derivada:
        aviso = respuestas.bot_pausado(comercio.nombre, comercio.telefono_contacto)
        if conversacion:
            _guardar_mensaje(conversacion, texto_guardado, DireccionMensaje.ENTRANTE, ahora, entrante.id_externo)
            _guardar_mensaje(conversacion, aviso, DireccionMensaje.SALIENTE, ahora)
            conversacion.ultima_actividad = ahora
        db.session.commit()
        return ResultadoAtencion([aviso], conversacion, acciones=["BOT_PAUSADO"])

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
            intentos_sin_entender=0,
        )
        db.session.add(conversacion)

    _guardar_mensaje(conversacion, texto_guardado, DireccionMensaje.ENTRANTE, ahora, entrante.id_externo)

    palabras = db.session.scalars(select(PalabraClave)).all()
    resultado = conversacion.procesar_mensaje(
        texto_util,
        palabras,
        ahora,
        max_intentos_cp=current_app.config.get("BOT_MAX_INTENTOS_CP", 2),
        primer_contacto=primer_contacto,
        tipo="text" if tipo in {"interactive", "button"} else tipo,
    )

    for respuesta in resultado.respuestas:
        _guardar_mensaje(conversacion, respuesta, DireccionMensaje.SALIENTE, ahora)

    consultas = []
    for registro in resultado.consultas:
        consulta = Consulta(
            conversacion=conversacion,
            tema=registro.tema,
            resultado=registro.resultado,
            codigo_postal=registro.codigo_postal,
            fecha_hora=ahora,
            atendida=False,
            id_respuesta=registro.id_respuesta,
        )
        db.session.add(consulta)
        consultas.append(consulta)

    conversacion.ultima_actividad = ahora
    db.session.commit()
    log.info(
        "Mensaje para %s: estado=%s acciones=%s",
        comercio.nombre,
        conversacion.estado.value,
        ",".join(resultado.acciones) or "-",
    )
    return ResultadoAtencion(resultado.respuestas, conversacion, consultas, acciones=resultado.acciones)


def _descripcion(tipo: str, texto: str) -> str:
    descripcion = DESCRIPCION_TIPO.get(tipo, f"Mensaje de tipo {tipo}")
    return f"{descripcion}: {texto}" if texto else descripcion


def _guardar_mensaje(
    conversacion: Conversacion,
    contenido: str | Respuesta,
    direccion: DireccionMensaje,
    fecha_hora: datetime,
    id_externo: str | None = None,
) -> Mensaje:
    botones = None
    if isinstance(contenido, Respuesta):
        if contenido.botones:
            botones = json.dumps([{"id": b.id, "titulo": b.titulo} for b in contenido.botones], ensure_ascii=False)
        texto = contenido.texto
    else:
        texto = contenido
    mensaje = Mensaje(
        conversacion=conversacion,
        texto=texto or "",
        direccion=direccion,
        fecha_hora=fecha_hora,
        id_externo=id_externo,
        botones=botones,
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
