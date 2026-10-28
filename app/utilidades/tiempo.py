"""Manejo de fecha y hora en la zona horaria del comercio.

Todas las fechas se guardan en hora local de Argentina (sin zona) para que el
historial y los indicadores coincidan con lo que ve el responsable del comercio.
Las pruebas reemplazan `ahora` para fijar el reloj.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app, has_app_context

_ZONA_POR_DEFECTO = "America/Argentina/Cordoba"


def zona_horaria() -> ZoneInfo:
    nombre = _ZONA_POR_DEFECTO
    if has_app_context():
        nombre = current_app.config.get("ZONA_HORARIA", _ZONA_POR_DEFECTO)
    return ZoneInfo(nombre)


def ahora() -> datetime:
    """Fecha y hora actual en la zona configurada, sin información de zona."""
    return datetime.now(zona_horaria()).replace(tzinfo=None, microsecond=0)


DIAS_SEMANA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def formato_fecha_hora(valor: datetime | None) -> str:
    if not valor:
        return ""
    return valor.strftime("%d/%m/%Y %H:%M")


def formato_fecha_larga(valor: datetime | None) -> str:
    if not valor:
        return ""
    return f"{valor.day} de {MESES[valor.month - 1]} de {valor.year}"


def formato_relativo(valor: datetime | None, referencia: datetime | None = None) -> str:
    """Texto breve del tipo «hace 5 min», «ayer 21:40» o «12/10 09:15»."""
    if not valor:
        return ""
    referencia = referencia or ahora()
    delta = referencia - valor
    segundos = int(delta.total_seconds())
    if segundos < 60:
        return "recién"
    if segundos < 3600:
        return f"hace {segundos // 60} min"
    if valor.date() == referencia.date():
        return f"hoy {valor:%H:%M}"
    if (referencia.date() - valor.date()).days == 1:
        return f"ayer {valor:%H:%M}"
    return valor.strftime("%d/%m %H:%M")
