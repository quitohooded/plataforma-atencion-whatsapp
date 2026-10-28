"""Textos que el bot envía al comprador.

El bot habla en nombre del comercio, en el registro habitual de WhatsApp en
Argentina (voseo). Las funciones son puras: reciben los datos y devuelven texto.
"""

from __future__ import annotations

from datetime import datetime, time

from ..utilidades.tiempo import DIAS_SEMANA
from .contexto import DatosComercio, ZonaDatos


def _hora(valor: time) -> str:
    return f"{valor.hour}:{valor.minute:02d}"


def _lista_dias(desde: int, hasta: int) -> str:
    if desde == hasta:
        return DIAS_SEMANA[desde]
    if hasta == desde + 1:
        return f"{DIAS_SEMANA[desde]} y {DIAS_SEMANA[hasta].lower()}"
    return f"{DIAS_SEMANA[desde]} a {DIAS_SEMANA[hasta].lower()}"


def lineas_horario(datos: DatosComercio) -> list[str]:
    """Agrupa días consecutivos con las mismas franjas: «Lunes a viernes: 9:00 a 18:00»."""
    por_dia: list[tuple[tuple[time, time], ...]] = []
    for dia in range(7):
        franjas = tuple(sorted((f.apertura, f.cierre) for f in datos.franjas if f.dia_semana == dia))
        por_dia.append(franjas)

    lineas: list[str] = []
    inicio = 0
    for dia in range(1, 8):
        if dia == 7 or por_dia[dia] != por_dia[inicio]:
            franjas = por_dia[inicio]
            if franjas:
                texto = " y ".join(f"{_hora(a)} a {_hora(c)}" for a, c in franjas)
            else:
                texto = "cerrado"
            lineas.append(f"{_lista_dias(inicio, dia - 1)}: {texto}")
            inicio = dia
    return lineas


def _cuando(destino: datetime, referencia: datetime) -> str:
    dias = (destino.date() - referencia.date()).days
    hora = _hora(destino.time())
    if dias == 0:
        return f"hoy a las {hora}"
    if dias == 1:
        return f"mañana a las {hora}"
    return f"el {DIAS_SEMANA[destino.weekday()].lower()} a las {hora}"


def bienvenida(datos: DatosComercio) -> str:
    return (
        f"¡Hola! 👋 Soy el asistente automático de {datos.nombre}. "
        "Te respondo al instante sobre:\n\n"
        "1️⃣ Envíos y plazos de entrega\n"
        "2️⃣ Medios de pago\n"
        "3️⃣ Horarios de atención\n\n"
        "Escribí tu consulta o el número de la opción. "
        "Si necesitás otra cosa, escribila igual y le aviso al equipo."
    )


def cortesia() -> str:
    return "¡De nada! Si tenés otra consulta, escribime cuando quieras. 🙂"


def solicitar_codigo_postal() -> str:
    return (
        "Para decirte si llegamos a tu zona y cuánto demora, "
        "¿me pasás tu código postal? Son 4 números, por ejemplo 5000."
    )


def codigo_postal_invalido() -> str:
    return (
        "No pude reconocer el código postal. Escribilo con sus 4 números, "
        "por ejemplo 5000 (o en formato nuevo, X5000ABC)."
    )


def plazo_envio(cp: int, zona: ZonaDatos) -> str:
    return (
        f"📦 Para el código postal {cp} ({zona.descripcion}) el plazo estimado de entrega "
        f"es de {zona.plazo_texto}.\n\n¿Te puedo ayudar con algo más?"
    )


def zona_no_configurada(cp: int) -> str:
    return f"Por ahora no tengo cargado un plazo de entrega para el código postal {cp}."


def medios_de_pago(datos: DatosComercio) -> str:
    lineas = [f"💳 Estos son los medios de pago que acepta {datos.nombre}:", ""]
    for medio in datos.medios:
        lineas.append(f"• {medio.nombre}: {medio.detalle}" if medio.detalle else f"• {medio.nombre}")
    return "\n".join(lineas)


def horarios(datos: DatosComercio, ahora: datetime) -> str:
    lineas = ["🕘 Nuestro horario de atención:", ""]
    lineas += lineas_horario(datos)
    lineas.append("")
    franja = datos.franja_actual(ahora)
    if franja:
        lineas.append(f"Ahora estamos atendiendo, hasta las {_hora(franja.cierre)}.")
    else:
        proxima = datos.proxima_apertura(ahora)
        if proxima:
            lineas.append(f"En este momento estamos cerrados. Volvemos a abrir {_cuando(proxima, ahora)}.")
        else:
            lineas.append("En este momento estamos cerrados.")
    return "\n".join(lineas)


def derivacion(datos: DatosComercio) -> str:
    texto = f"Tu consulta quedó registrada. Una persona de {datos.nombre} te va a responder a la brevedad"
    if datos.telefono_contacto:
        texto += f" desde su WhatsApp ({datos.telefono_contacto})"
    texto += "."
    if datos.franjas:
        texto += "\n\nHorario de atención:\n" + "\n".join(lineas_horario(datos))
    return texto


def comercio_no_identificado() -> str:
    return (
        "¡Hola! Para ayudarte necesito saber con qué comercio querés comunicarte. "
        "Ingresá desde el enlace que el comercio comparte en su Instagram o catálogo, "
        "o escribí su código de acceso."
    )


def bot_pausado(nombre: str, telefono_contacto: str) -> str:
    texto = f"La atención automática de {nombre} no está disponible en este momento."
    if telefono_contacto:
        texto += f" Podés escribirle directamente al {telefono_contacto}."
    return texto
