"""Retención de datos personales (O6) y derecho de supresión (Ley 25.326, art. 16).

- ``depurar``: borra los mensajes y las consultas con más de ``RETENCION_DIAS`` días, las
  conversaciones que quedan vacías y los compradores sin conversaciones. Se conservan las
  consultas pendientes y los mensajes de sus conversaciones, porque el comercio todavía
  tiene que responderlas. La aplicación la ejecuta sola una vez por día
  (``DEPURACION_AUTOMATICA``) y también se puede ejecutar a mano
  (``flask --app app admin depurar``).
- ``borrar_datos_comprador``: borra lo que un comercio (o la plataforma) guarda de un
  comprador cuando él lo pide.
- ``borrar_comercio``: baja de un comercio con todos sus datos.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from flask import Flask
from sqlalchemy import and_, delete, exists, not_, select

from ..extensiones import db
from ..modelos import Bloqueo, Comercio, Comprador, Consulta, Conversacion, Mensaje, ResultadoConsulta
from ..utilidades import tiempo

log = logging.getLogger(__name__)

INTERVALO_AUTOMATICO = 24 * 60 * 60  # segundos


@dataclass
class ResultadoDepuracion:
    mensajes: int = 0
    consultas: int = 0
    conversaciones: int = 0
    compradores: int = 0

    @property
    def total(self) -> int:
        return self.mensajes + self.consultas + self.conversaciones + self.compradores

    def __str__(self) -> str:
        return (
            f"{self.mensajes} mensajes, {self.consultas} consultas, {self.conversaciones} conversaciones y "
            f"{self.compradores} compradores"
        )


def _pendiente():
    return and_(Consulta.resultado == ResultadoConsulta.DERIVADA, Consulta.atendida.is_(False))


def limite_de_retencion(dias: int, ahora: datetime | None = None) -> datetime:
    return (ahora or tiempo.ahora()) - timedelta(days=dias)


def depurar(limite: datetime) -> ResultadoDepuracion:
    """Borra lo anterior a ``limite`` salvo las consultas pendientes y sus conversaciones."""
    resultado = ResultadoDepuracion()
    con_pendientes = select(Consulta.id_conversacion).where(_pendiente())

    resultado.consultas = _borrar(delete(Consulta).where(Consulta.fecha_hora < limite, not_(_pendiente())))
    resultado.mensajes = _borrar(
        delete(Mensaje).where(Mensaje.fecha_hora < limite, Mensaje.id_conversacion.not_in(con_pendientes))
    )
    resultado.conversaciones = _borrar(
        delete(Conversacion).where(
            Conversacion.ultima_actividad < limite,
            ~exists().where(Consulta.id_conversacion == Conversacion.id_conversacion),
            ~exists().where(Mensaje.id_conversacion == Conversacion.id_conversacion),
        )
    )
    resultado.compradores = _borrar_compradores_sin_datos()
    db.session.commit()
    db.session.expire_all()
    return resultado


def _borrar(sentencia) -> int:
    # Borrado directo en la base; después se expiran los objetos de la sesión.
    return db.session.execute(sentencia.execution_options(synchronize_session=False)).rowcount


def _borrar_compradores_sin_datos() -> int:
    """Compradores sin conversaciones; los bloqueados se conservan para que el bloqueo siga valiendo."""
    return _borrar(
        delete(Comprador).where(
            ~exists().where(Conversacion.id_comprador == Comprador.id_comprador),
            ~exists().where(Bloqueo.id_comprador == Comprador.id_comprador),
        )
    )


def borrar_datos_comprador(comprador: Comprador, comercio: Comercio | None = None) -> int:
    """Borra las conversaciones del comprador (con sus mensajes y consultas) con un comercio o, si no se
    indica, con todos. Si no le quedan conversaciones ni bloqueos, se borra también su número.

    Devuelve la cantidad de conversaciones borradas."""
    condicion = Conversacion.id_comprador == comprador.id_comprador
    if comercio is not None:
        condicion = and_(condicion, Conversacion.id_comercio == comercio.id_comercio)
    conversaciones = db.session.scalars(select(Conversacion).where(condicion)).all()
    for conversacion in conversaciones:
        db.session.delete(conversacion)
    db.session.flush()
    _borrar_compradores_sin_datos()
    db.session.commit()
    db.session.expire_all()
    return len(conversaciones)


def borrar_comercio(comercio: Comercio) -> None:
    """Baja de un comercio: su usuario, su información, sus conversaciones y los números que solo le
    escribieron a él."""
    if comercio.usuario is not None:
        db.session.delete(comercio.usuario)
    db.session.delete(comercio)
    db.session.flush()
    _borrar_compradores_sin_datos()
    db.session.commit()
    db.session.expire_all()


def depurar_si_corresponde(app: Flask) -> ResultadoDepuracion | None:
    """Depuración automática: como máximo una vez por día y por proceso, sin demorar a los demás pedidos."""
    dias = app.config.get("RETENCION_DIAS") or 0
    if not app.config.get("DEPURACION_AUTOMATICA") or dias <= 0:
        return None
    estado = app.extensions.setdefault("depuracion", {"ultima": None, "candado": threading.Lock()})
    ahora = time.monotonic()
    if estado["ultima"] is not None and ahora - estado["ultima"] < INTERVALO_AUTOMATICO:
        return None
    if not estado["candado"].acquire(blocking=False):
        return None
    try:
        estado["ultima"] = ahora
        resultado = depurar(limite_de_retencion(dias))
        if resultado.total:
            log.info("Depuración de datos con más de %s días: %s.", dias, resultado)
        return resultado
    except Exception:
        db.session.rollback()
        log.exception("No fue posible depurar los datos antiguos")
        return None
    finally:
        estado["candado"].release()
