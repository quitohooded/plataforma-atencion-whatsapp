"""Administración de medios de pago (CU05)."""

from __future__ import annotations

from ..bot.normalizacion import normalizar
from ..extensiones import db
from ..modelos import Comercio, MedioPago
from . import ErrorValidacion

MEDIOS_PREDEFINIDOS = [
    "Efectivo",
    "Transferencia bancaria",
    "Tarjeta de débito",
    "Tarjeta de crédito",
    "Billetera virtual",
    "Otro",
]

EJEMPLOS_DETALLE = {
    "Efectivo": "Por ejemplo: solo en retiros por el depósito",
    "Transferencia bancaria": "Por ejemplo: alias casa.detalles.mp",
    "Tarjeta de débito": "Por ejemplo: Visa y Maestro",
    "Tarjeta de crédito": "Por ejemplo: hasta 3 cuotas sin interés",
    "Billetera virtual": "Por ejemplo: Mercado Pago, Ualá o MODO",
    "Otro": "Información que el bot agrega al nombrarlo",
}


def interpretar(tipo: str, nombre_otro: str, detalle: str) -> tuple[str, str]:
    tipo = (tipo or "").strip()
    detalle = (detalle or "").strip()
    if tipo not in MEDIOS_PREDEFINIDOS:
        raise ErrorValidacion("Elija un medio de pago de la lista.")
    nombre = (nombre_otro or "").strip() if tipo == "Otro" else tipo
    if not nombre:
        raise ErrorValidacion("Indique el nombre del medio de pago.")
    if len(nombre) > 60 or len(detalle) > 120:
        raise ErrorValidacion("El nombre admite hasta 60 caracteres y el detalle hasta 120.")
    return nombre, detalle


def _es_duplicado(comercio: Comercio, nombre: str, detalle: str, excluir_id: int | None) -> bool:
    clave = (normalizar(nombre), normalizar(detalle))
    return any(
        (normalizar(m.nombre), normalizar(m.detalle or "")) == clave
        for m in comercio.medios_pago
        if m.id_medio_pago != excluir_id
    )


def crear_medio(comercio: Comercio, tipo: str, nombre_otro: str, detalle: str) -> MedioPago:
    nombre, detalle = interpretar(tipo, nombre_otro, detalle)
    if _es_duplicado(comercio, nombre, detalle, None):
        raise ErrorValidacion("Ese medio de pago ya está cargado.")
    medio = MedioPago(comercio=comercio, nombre=nombre, detalle=detalle, activo=True)
    db.session.add(medio)
    db.session.commit()
    return medio


def actualizar_medio(comercio: Comercio, medio: MedioPago, tipo: str, nombre_otro: str, detalle: str) -> MedioPago:
    nombre, detalle = interpretar(tipo, nombre_otro, detalle)
    if _es_duplicado(comercio, nombre, detalle, medio.id_medio_pago):
        raise ErrorValidacion("Ese medio de pago ya está cargado.")
    medio.nombre, medio.detalle = nombre, detalle
    db.session.commit()
    return medio


def cambiar_activo(medio: MedioPago, activo: bool) -> None:
    medio.activo = activo
    db.session.commit()


def eliminar_medio(medio: MedioPago) -> None:
    db.session.delete(medio)
    db.session.commit()


def tipo_de(medio: MedioPago) -> str:
    return medio.nombre if medio.nombre in MEDIOS_PREDEFINIDOS else "Otro"
