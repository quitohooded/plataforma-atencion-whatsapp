"""Aviso por correo de consultas pendientes (#8).

Opcional, lo activa cada comercio en su cuenta. Para no saturar, se manda como máximo un
correo cada ``AVISOS_CORREO_MINUTOS``: el correo dice cuántas consultas esperan y muestra la
más reciente. Si el correo no está configurado, no se manda nada y el bot sigue igual.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import select

from .. import correo
from ..extensiones import db
from ..modelos import Comercio, Consulta, DireccionMensaje, Mensaje
from .metricas import contar_pendientes

log = logging.getLogger(__name__)


def _texto_del_mensaje(consulta: Consulta) -> str:
    texto = db.session.scalar(
        select(Mensaje.texto)
        .where(
            Mensaje.id_conversacion == consulta.id_conversacion,
            Mensaje.direccion == DireccionMensaje.ENTRANTE,
            Mensaje.fecha_hora <= consulta.fecha_hora,
        )
        .order_by(Mensaje.fecha_hora.desc(), Mensaje.id_mensaje.desc())
    )
    texto = (texto or "").replace("\n", " ")
    return texto if len(texto) <= 160 else texto[:157].rstrip() + "…"


def notificar_pendiente(comercio: Comercio, consulta: Consulta, ahora: datetime) -> bool:
    """Manda el aviso si el comercio lo activó y no recibió otro hace poco."""
    if not comercio.avisos_correo or not comercio.usuario or not correo.disponible():
        return False
    intervalo = timedelta(minutes=current_app.config.get("AVISOS_CORREO_MINUTOS", 30))
    if comercio.ultimo_aviso_correo and ahora - comercio.ultimo_aviso_correo < intervalo:
        return False
    plataforma = current_app.config["PLATAFORMA_NOMBRE"]
    pendientes = contar_pendientes(comercio)
    comprador = consulta.conversacion.comprador
    quien = comprador.nombre or comprador.telefono_legible
    if consulta.alerta:
        asunto = f"{plataforma}: alerta de seguridad en {comercio.nombre}"
    else:
        cantidad = "1 consulta pendiente" if pendientes == 1 else f"{pendientes} consultas pendientes"
        asunto = f"{plataforma}: {cantidad} en {comercio.nombre}"
    enlace = correo.enlace_externo("resumen.inicio")
    minutos = int(intervalo.total_seconds() // 60)
    lineas = [
        "Hola,",
        "",
        f"{'Hay 1 consulta pendiente' if pendientes == 1 else f'Hay {pendientes} consultas pendientes'} en "
        f"{comercio.nombre}. La más reciente:",
        "",
        f"{consulta.etiqueta_tema}: {quien} ({comprador.telefono_legible})",
        f"«{_texto_del_mensaje(consulta)}»",
        "",
    ]
    if enlace:
        lineas += [f"Para verlas y responder: {enlace}", ""]
    lineas += [
        f"El bot ya le avisó al comprador que le van a escribir desde {comercio.telefono_contacto}.",
        f"Este aviso llega como máximo una vez cada {minutos} minutos. Puede desactivarlo en la sección Cuenta del "
        "panel.",
        "",
        plataforma,
    ]
    enviado = correo.enviar(comercio.usuario.email, asunto, "\n".join(lineas))
    if enviado:
        comercio.ultimo_aviso_correo = ahora
        db.session.commit()
    return enviado
