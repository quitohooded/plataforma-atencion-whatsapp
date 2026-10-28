"""Información de Casa & Detalles, el comercio del caso de estudio.

Es la única fuente de estos datos: la usan la demostración (``demo.py``), el ejemplo de la
página de inicio y el corpus con el que se mide el bot (``tests/corpus``). Así lo que se
mide es lo mismo que se ve en el simulador.
"""

from __future__ import annotations

from datetime import time

NOMBRE = "Casa & Detalles"
RUBRO = "Artículos para el hogar"
TELEFONO = "351 012-3456"
ENVIO_GRATIS_DESDE = 120000
CATALOGO = "https://casaydetalles.example/catalogo"

# (descripción, cp desde, cp hasta, plazo mínimo, plazo máximo, costo en pesos)
ZONAS = [
    ("Córdoba Capital y Gran Córdoba", 5000, 5099, 1, 2, 4500),
    ("Interior de Córdoba", 5100, 5299, 2, 4, 6900),
    ("Cuyo y La Rioja", 5300, 5799, 3, 5, 8900),
    ("Interior de Córdoba", 5800, 5999, 2, 4, 6900),
    ("Ciudad de Buenos Aires", 1000, 1499, 3, 5, 8900),
    ("Gran Buenos Aires y La Plata", 1500, 1999, 3, 5, 8900),
    ("Santa Fe, este de Córdoba y Litoral", 2000, 3999, 3, 6, 9900),
    ("Noroeste", 4000, 4999, 4, 6, 9900),
    ("Provincia de Buenos Aires y La Pampa", 6000, 7999, 4, 6, 9900),
    ("Sur de Buenos Aires, Neuquén y Río Negro", 8000, 8999, 5, 8, 11900),
    ("Chubut, Santa Cruz y Tierra del Fuego", 9000, 9499, 6, 10, 13900),
]

# (nombre, detalle, activo)
MEDIOS = [
    ("Transferencia bancaria", "alias casa.detalles.demo, 10 % de descuento", True),
    ("Billetera virtual", "Mercado Pago y MODO, con QR o link de pago", True),
    ("Tarjeta de crédito", "Visa y Mastercard, hasta 3 cuotas sin interés", True),
    ("Tarjeta de débito", "Visa Débito y Maestro", True),
    ("Efectivo", "solo al retirar por el depósito", True),
]

# (día de la semana, apertura, cierre); 0 = lunes
HORARIOS = [(d, "09:00", "18:00") for d in range(5)] + [(5, "09:00", "13:00")]


def datos_comercio():
    """Los mismos datos, como los recibe el motor del bot."""
    from ..bot.contexto import DatosComercio, FranjaDatos, MedioDatos, ZonaDatos

    return DatosComercio(
        nombre=NOMBRE,
        telefono_contacto=TELEFONO,
        zonas=tuple(ZonaDatos(d, h, desc, mn, mx, costo) for desc, d, h, mn, mx, costo in ZONAS),
        medios=tuple(MedioDatos(nombre, detalle) for nombre, detalle, activo in MEDIOS if activo),
        franjas=tuple(FranjaDatos(dia, time.fromisoformat(a), time.fromisoformat(c)) for dia, a, c in HORARIOS),
        envio_gratis_desde=ENVIO_GRATIS_DESDE,
        enlace_catalogo=CATALOGO,
    )
