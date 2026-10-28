"""Plantillas de respuestas propias que el panel sugiere al comercio (CU15).

Surgen de la revisión por perfiles (hallazgo C5): las consultas que más se derivaban en
la demostración, aparte de productos y pedidos, eran sobre cambios, factura, retiro y
ventas por mayor. Las palabras clave son frases como las escribe un comprador (el bot las
compara sin tildes ni mayúsculas); el texto es un ejemplo que el comercio completa con sus
condiciones antes de guardarlo.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plantilla:
    clave: str
    titulo: str
    descripcion: str
    palabras: tuple[str, ...]
    respuesta: str


PLANTILLAS: tuple[Plantilla, ...] = (
    Plantilla(
        clave="cambios",
        titulo="Cambios y devoluciones",
        descripcion="Plazo y condiciones para cambiar o devolver una compra.",
        palabras=(
            "cambio",
            "cambios",
            "cambiar",
            "cambiarlo",
            "cambiarla",
            "hacer un cambio",
            "política de cambios",
            "devolver",
            "devolverlo",
            "devolverla",
            "devolución",
            "devoluciones",
            "no me gustó",
        ),
        respuesta=(
            "🔄 Podés cambiar o devolver tu compra dentro de los *30 días* de recibida, sin uso y en su empaque "
            "original. Escribinos tu *número de pedido* y coordinamos el cambio."
        ),
    ),
    Plantilla(
        clave="factura",
        titulo="Factura",
        descripcion="Si emite factura, de qué tipo y qué datos necesita.",
        palabras=(
            "factura",
            "facturas",
            "factura A",
            "factura B",
            "factura C",
            "facturan",
            "facturar",
            "facturación",
            "IVA",
            "con IVA",
            "CUIT",
            "razón social",
        ),
        respuesta=(
            "🧾 Sí, hacemos *factura A o B*. Cuando confirmes el pedido, pasanos tu CUIT y la razón social (o tu DNI "
            "para factura B). Los precios publicados incluyen IVA."
        ),
    ),
    Plantilla(
        clave="retiro",
        titulo="Retiro en persona",
        descripcion="Si se puede retirar el pedido, dónde y cómo se coordina.",
        palabras=(
            "retirar",
            "retiro",
            "retirarlo",
            "retirarla",
            "retiro en persona",
            "en persona",
            "pasar a buscar",
            "paso a buscar",
            "pasarlo a buscar",
            "ir a buscar",
            "voy a buscar",
            "tienen local",
            "tenés local",
            "local físico",
            "local a la calle",
            "ir al local",
            "showroom",
            "punto de retiro",
        ),
        respuesta=(
            "📍 Podés *retirar tu pedido sin costo* por nuestro local, en el horario de atención. Avisanos antes por "
            "este medio para tenerlo listo."
        ),
    ),
    Plantilla(
        clave="mayorista",
        titulo="Ventas por mayor",
        descripcion="Si vende por mayor, desde qué cantidad y cómo pedir la lista.",
        palabras=(
            "por mayor",
            "al por mayor",
            "mayorista",
            "mayoristas",
            "precio mayorista",
            "precios mayoristas",
            "lista mayorista",
            "venta mayorista",
            "reventa",
            "revender",
            "para revender",
        ),
        respuesta=(
            "📦 Sí, vendemos por mayor a partir de *12 unidades* (pueden ser artículos combinados). Para recibir la "
            "lista de precios mayorista, escribí *persona* y te la pasa alguien del equipo."
        ),
    ),
    Plantilla(
        clave="garantia",
        titulo="Garantía",
        descripcion="Qué cubre la garantía y por cuánto tiempo.",
        palabras=(
            "garantía",
            "tiene garantía",
            "tienen garantía",
            "con garantía",
            "cuánto dura la garantía",
        ),
        respuesta=(
            "🛡️ Todos nuestros productos tienen *garantía de 6 meses* por fallas de fabricación. Si tenés un "
            "problema, escribinos con tu número de pedido y una foto del producto."
        ),
    ),
    Plantilla(
        clave="regalo",
        titulo="Envoltorio para regalo",
        descripcion="Si arma paquetes de regalo y si tienen costo.",
        palabras=(
            "envoltorio",
            "envoltorio para regalo",
            "envoltorio de regalo",
            "papel de regalo",
            "paquete de regalo",
            "para regalo",
            "envolver para regalo",
            "envuelven",
        ),
        respuesta=(
            "🎁 Sí, armamos el paquete de regalo *sin cargo*. Avisanos al hacer el pedido y, si querés, agregamos "
            "una tarjeta con tu dedicatoria."
        ),
    ),
)

POR_CLAVE = {p.clave: p for p in PLANTILLAS}
