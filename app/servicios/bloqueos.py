"""Bloqueo de números (#7): el comercio deja de recibir respuestas automáticas y consultas de
un comprador que molesta. Se puede deshacer."""

from __future__ import annotations

from sqlalchemy import select

from ..extensiones import db
from ..modelos import Bloqueo, Comercio, Comprador, Consulta
from ..utilidades import tiempo
from . import ErrorValidacion

LARGO_MOTIVO = 120


def bloqueo_de(comercio: Comercio, comprador: Comprador) -> Bloqueo | None:
    return db.session.scalar(
        select(Bloqueo).where(
            Bloqueo.id_comercio == comercio.id_comercio, Bloqueo.id_comprador == comprador.id_comprador
        )
    )


def bloquear(comercio: Comercio, consulta: Consulta, motivo: str = "") -> Bloqueo:
    """Bloquea al comprador de una consulta del comercio. Sus consultas pendientes con este
    comercio se dan por atendidas, para que no queden en el resumen."""
    motivo = " ".join((motivo or "").split())
    if len(motivo) > LARGO_MOTIVO:
        raise ErrorValidacion(f"El motivo admite hasta {LARGO_MOTIVO} caracteres.")
    comprador = consulta.conversacion.comprador
    existente = bloqueo_de(comercio, comprador)
    if existente:
        return existente
    ahora = tiempo.ahora()
    bloqueo = Bloqueo(comercio=comercio, comprador=comprador, motivo=motivo, fecha_alta=ahora)
    db.session.add(bloqueo)
    for conversacion in comprador.conversaciones:
        if conversacion.id_comercio != comercio.id_comercio:
            continue
        for pendiente in conversacion.consultas_pendientes:
            pendiente.marcar_atendida(ahora)
    db.session.commit()
    return bloqueo


def desbloquear(bloqueo: Bloqueo) -> None:
    db.session.delete(bloqueo)
    db.session.commit()


def listado(comercio: Comercio) -> list[Bloqueo]:
    return list(
        db.session.scalars(
            select(Bloqueo).where(Bloqueo.id_comercio == comercio.id_comercio).order_by(Bloqueo.fecha_alta.desc())
        )
    )
