"""Atención de los mensajes entrantes con persistencia (CU08 a CU12).

Este servicio es el punto de entrada común para el webhook de WhatsApp y para el
simulador. Identifica el comercio (por el código de acceso o por la conversación
vigente), registra al comprador, sostiene la conversación, guarda los mensajes y
registra las consultas.

Además (#6, #7, #11): guarda los mensajes con los datos sensibles ocultos, no responde a
los números que el comercio bloqueó, cuenta los mensajes del último minuto para frenar
las ráfagas, no registra dos veces la misma consulta resuelta en pocos minutos y guarda
si cada consulta llegó con el comercio cerrado.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import func, select

from ..extensiones import db
from ..modelos import (
    Bloqueo,
    Comercio,
    Comprador,
    Consulta,
    Conversacion,
    DireccionMensaje,
    EstadoComercio,
    EstadoConversacion,
    Mensaje,
    PalabraClave,
    ResultadoConsulta,
)
from ..utilidades import tiempo
from . import respuestas, seguridad
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
# Más mensajes que estos en un minuto es una ráfaga: una advertencia y una pausa breve (#7).
MENSAJES_POR_MINUTO = 8
# Una consulta resuelta igual a otra de la misma conversación en este lapso no se registra (#11).
VENTANA_REPETIDAS = timedelta(minutes=30)


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
    # Mensajes guardados para cada respuesta, en el mismo orden (para registrar su entrega).
    salientes: list[Mensaje] = field(default_factory=list)

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
    # Lo que se guarda (y ve el comercio) nunca incluye datos de tarjeta, claves ni códigos.
    seguro = seguridad.ocultar(texto).texto
    texto_guardado = seguro if tipo in {"text", "interactive", "button"} else _descripcion(tipo, seguro)

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

    # Número bloqueado por el comercio: se guarda el mensaje (si hay conversación) y no se responde.
    if comprador and esta_bloqueado(comercio, comprador):
        if conversacion:
            _guardar_mensaje(conversacion, texto_guardado, DireccionMensaje.ENTRANTE, ahora, entrante.id_externo)
            conversacion.ultima_actividad = ahora
        db.session.commit()
        log.info("Mensaje de un número bloqueado por %s: sin respuesta", comercio.nombre)
        return ResultadoAtencion([], conversacion, acciones=["BLOQUEADO"])

    # Con la consulta derivada se registra el mensaje aunque el bot esté pausado (CU12).
    derivada = conversacion is not None and conversacion.estado == EstadoConversacion.DERIVADA

    if comercio.estado != EstadoComercio.ACTIVO and not derivada:
        aviso = respuestas.bot_pausado(comercio.nombre, comercio.telefono_contacto)
        salientes = []
        if conversacion:
            _guardar_mensaje(conversacion, texto_guardado, DireccionMensaje.ENTRANTE, ahora, entrante.id_externo)
            salientes.append(_guardar_mensaje(conversacion, aviso, DireccionMensaje.SALIENTE, ahora))
            conversacion.ultima_actividad = ahora
        db.session.commit()
        return ResultadoAtencion([aviso], conversacion, acciones=["BOT_PAUSADO"], salientes=salientes)

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
    rafaga = _mensajes_del_ultimo_minuto(conversacion, ahora) > MENSAJES_POR_MINUTO

    palabras = db.session.scalars(select(PalabraClave)).all()
    resultado = conversacion.procesar_mensaje(
        texto_util,
        palabras,
        ahora,
        max_intentos_cp=current_app.config.get("BOT_MAX_INTENTOS_CP", 2),
        primer_contacto=primer_contacto,
        tipo="text" if tipo in {"interactive", "button"} else tipo,
        rafaga=rafaga,
    )

    salientes = [_guardar_mensaje(conversacion, r, DireccionMensaje.SALIENTE, ahora) for r in resultado.respuestas]

    fuera_de_horario = (not comercio.esta_abierto(ahora)) if comercio.horarios else None
    consultas = []
    for registro in resultado.consultas:
        if registro.resultado == ResultadoConsulta.RESUELTA and _repetida(conversacion, registro, ahora):
            continue
        consulta = Consulta(
            conversacion=conversacion,
            tema=registro.tema,
            resultado=registro.resultado,
            codigo_postal=registro.codigo_postal,
            fecha_hora=ahora,
            atendida=False,
            id_respuesta=registro.id_respuesta,
            alerta=registro.alerta,
            fuera_de_horario=fuera_de_horario,
        )
        db.session.add(consulta)
        consultas.append(consulta)

    conversacion.ultima_actividad = ahora
    db.session.commit()
    derivadas = [c for c in consultas if c.resultado == ResultadoConsulta.DERIVADA]
    if derivadas:
        _avisar(comercio, max(derivadas, key=lambda c: c.tema.prioritario), ahora)
    log.info(
        "Mensaje para %s: estado=%s acciones=%s",
        comercio.nombre,
        conversacion.estado.value,
        ",".join(resultado.acciones) or "-",
    )
    return ResultadoAtencion(
        resultado.respuestas, conversacion, consultas, acciones=resultado.acciones, salientes=salientes
    )


def _avisar(comercio: Comercio, consulta: Consulta, ahora: datetime) -> None:
    """Aviso por correo de la consulta pendiente (#8). Una falla no afecta la atención."""
    from ..servicios.avisos import notificar_pendiente

    try:
        notificar_pendiente(comercio, consulta, ahora)
    except Exception:  # el aviso es accesorio: el bot ya respondió
        db.session.rollback()
        log.exception("No fue posible avisar por correo al comercio %s", comercio.id_comercio)


def _mensajes_del_ultimo_minuto(conversacion: Conversacion, ahora: datetime) -> int:
    db.session.flush()  # la conversación nueva necesita su identificador
    return (
        db.session.scalar(
            select(func.count(Mensaje.id_mensaje)).where(
                Mensaje.id_conversacion == conversacion.id_conversacion,
                Mensaje.direccion == DireccionMensaje.ENTRANTE,
                Mensaje.fecha_hora > ahora - timedelta(minutes=1),
                Mensaje.fecha_hora <= ahora,
            )
        )
        or 0
    )


def _repetida(conversacion: Conversacion, registro, ahora: datetime) -> bool:
    """La misma consulta resuelta en la misma conversación hace poco: preguntar dos veces lo
    mismo no son dos consultas para el resumen (#11). Las alertas se registran siempre."""
    if registro.alerta:
        return False
    return any(
        c.resultado == ResultadoConsulta.RESUELTA
        and c.tema == registro.tema
        and c.codigo_postal == registro.codigo_postal
        and c.id_respuesta == registro.id_respuesta
        and ahora - c.fecha_hora <= VENTANA_REPETIDAS
        for c in conversacion.consultas
    )


def esta_bloqueado(comercio: Comercio, comprador: Comprador) -> bool:
    return (
        db.session.scalar(
            select(Bloqueo.id_bloqueo).where(
                Bloqueo.id_comercio == comercio.id_comercio, Bloqueo.id_comprador == comprador.id_comprador
            )
        )
        is not None
    )


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
