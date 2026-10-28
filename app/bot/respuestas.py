"""Textos que el bot envía al comprador.

El bot habla en nombre del comercio, en el registro habitual de WhatsApp en Argentina
(voseo), y usa el formato de WhatsApp: *negrita* con asteriscos. Las funciones son puras:
reciben los datos y devuelven la respuesta.

Una respuesta puede llevar hasta tres botones (mensaje interactivo de WhatsApp). Cuando
el canal no los admite, ``Respuesta.texto_plano`` agrega la instrucción para escribir la
opción, de modo que la conversación funciona igual.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from ..modelos import formato_pesos
from ..utilidades.tiempo import DIAS_SEMANA
from .contexto import DatosComercio, MedioDatos, ZonaDatos


@dataclass(frozen=True)
class Boton:
    id: str
    titulo: str  # WhatsApp admite hasta 20 caracteres


@dataclass(frozen=True)
class Respuesta:
    texto: str
    botones: tuple[Boton, ...] = ()
    # Cómo elegir las opciones cuando el canal no muestra botones.
    alternativa: str = ""

    def texto_plano(self) -> str:
        if not self.botones:
            return self.texto
        alternativa = self.alternativa or "Opciones: " + ", ".join(b.titulo for b in self.botones) + "."
        return f"{self.texto}\n\n{alternativa}"

    def con_prefijo(self, prefijo: str) -> Respuesta:
        return Respuesta(f"{prefijo}\n\n{self.texto}", self.botones, self.alternativa)

    def con_pie(self, pie: str) -> Respuesta:
        return Respuesta(f"{self.texto}\n\n{pie}", self.botones, self.alternativa)


BOTON_ENVIOS = Boton("op_envio", "Envíos")
BOTON_PAGOS = Boton("op_pago", "Medios de pago")
BOTON_HORARIOS = Boton("op_horario", "Horarios")
BOTON_PERSONA = Boton("op_persona", "Hablar con alguien")
BOTON_MENU = Boton("op_menu", "Ver opciones")

ALTERNATIVA_MENU = "Escribí *1* para envíos, *2* para medios de pago, *3* para horarios o *4* para hablar con alguien."
ALTERNATIVA_AYUDA = "Escribí *menú* para ver las opciones o *persona* para hablar con alguien del equipo."
CIERRE = "¿Te puedo ayudar con algo más?"


def _hora(valor: time) -> str:
    return f"{valor.hour}:{valor.minute:02d}"


def _lista_dias(desde: int, hasta: int) -> str:
    if desde == hasta:
        return DIAS_SEMANA[desde]
    if hasta == desde + 1:
        return f"{DIAS_SEMANA[desde]} y {DIAS_SEMANA[hasta].lower()}"
    return f"{DIAS_SEMANA[desde]} a {DIAS_SEMANA[hasta].lower()}"


def _franjas_texto(franjas) -> str:
    return " y ".join(f"{_hora(f.apertura)} a {_hora(f.cierre)}" for f in franjas)


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


def cuando(destino: datetime, referencia: datetime) -> str:
    """«hoy a las 9:00», «mañana a las 9:00», «el lunes a las 9:00»."""
    dias = (destino.date() - referencia.date()).days
    hora = _hora(destino.time())
    if dias == 0:
        return f"hoy a las {hora}"
    if dias == 1:
        return f"mañana a las {hora}"
    return f"el {DIAS_SEMANA[destino.weekday()].lower()} a las {hora}"


def _cuando_desde(destino: datetime, referencia: datetime) -> str:
    """«hoy desde las 9:00», «mañana desde las 9:00», «el lunes desde las 9:00»."""
    return cuando(destino, referencia).replace(" a las ", " desde las ")


# ---------------------------------------------------------------------------
# Conversación
# ---------------------------------------------------------------------------


def presentacion(datos: DatosComercio) -> str:
    return f"¡Hola! 👋 Soy el asistente automático de *{datos.nombre}*."


def bienvenida(datos: DatosComercio) -> Respuesta:
    catalogo = ", y también te paso el catálogo" if datos.enlace_catalogo else ""
    return Respuesta(
        f"{presentacion(datos)} Te respondo al instante sobre envíos, medios de pago y horarios{catalogo}.\n\n"
        "Elegí una opción o escribime tu consulta. Si necesitás hablar con alguien del equipo, escribí *persona*.",
        (BOTON_ENVIOS, BOTON_PAGOS, BOTON_HORARIOS),
        ALTERNATIVA_MENU,
    )


def cortesia(tipo: str = "gracias") -> Respuesta:
    textos = {
        "gracias": "¡De nada! 😊 Si tenés otra consulta, escribime cuando quieras.",
        "despedida": "¡Gracias por escribirnos! Que tengas un lindo día. 👋",
        "ok": "¡Genial! Si necesitás algo más, acá estoy. 🙂",
        "no": "¡Gracias por escribirnos! Cuando necesites algo, escribime. 👋",
    }
    return Respuesta(textos.get(tipo, textos["gracias"]))


def contame() -> Respuesta:
    return Respuesta("¡Claro! Contame qué necesitás saber. 🙂")


def identidad(datos: DatosComercio) -> Respuesta:
    return Respuesta(
        f"Soy el asistente automático de *{datos.nombre}* 🤖. Respondo al instante consultas sobre envíos, "
        "medios de pago y horarios. Lo que no puedo resolver se lo paso a una persona del equipo.",
        (BOTON_PERSONA, BOTON_MENU),
        "Escribí *persona* si preferís que te atienda alguien del equipo.",
    )


def aclaracion(intento: int) -> Respuesta:
    if intento <= 1:
        return Respuesta(
            "Perdón, no entendí tu mensaje. 🙏 Te puedo responder sobre envíos, medios de pago y horarios. "
            "Si es otra consulta, se la paso a una persona del equipo.",
            (BOTON_MENU, BOTON_PERSONA),
            ALTERNATIVA_AYUDA,
        )
    return Respuesta(
        "Sigo sin entenderte, perdón. 😅 ¿Querés que le pase tu consulta a una persona del equipo?",
        (BOTON_PERSONA, BOTON_MENU),
        "Escribí *persona* para hablar con alguien o *menú* para ver las opciones.",
    )


def audio_no_soportado() -> Respuesta:
    return Respuesta("No puedo escuchar audios, perdón. 🙉 ¿Me escribís tu consulta?")


def ubicacion_recibida() -> Respuesta:
    return Respuesta(
        "Recibí tu ubicación. 📍 Para calcular el envío necesito tu *código postal* (4 números) "
        "o el nombre de tu ciudad."
    )


def cancelado() -> Respuesta:
    return Respuesta("Listo, dejamos la consulta del envío. Si necesitás algo más, escribime. 🙂")


# ---------------------------------------------------------------------------
# CU09: plazo y costo de envío
# ---------------------------------------------------------------------------


def solicitar_codigo_postal(datos: DatosComercio, pide_costo: bool = False) -> Respuesta:
    lineas = []
    if pide_costo and datos.envio_gratis_desde:
        lineas.append(
            f"🎁 El envío es gratis en compras desde *{formato_pesos(datos.envio_gratis_desde)}*. "
            "Para compras menores, el costo depende de la zona."
        )
    que = "cuánto demora y cuánto cuesta" if pide_costo and datos.informa_costos else "cuánto demora"
    lineas.append(
        f"Para decirte si llegamos y {que}, ¿me pasás tu *código postal*? Son 4 números (por ejemplo, 5000). "
        "También me podés escribir el nombre de tu ciudad."
    )
    return Respuesta("\n\n".join(lineas))


def codigo_postal_invalido(no_sabe: bool = False) -> Respuesta:
    if no_sabe:
        return Respuesta("No hay problema. 🙂 Escribime el nombre de tu *ciudad o localidad* y lo busco.")
    return Respuesta(
        "No pude reconocer el código postal. 🤔 Escribí los 4 números (por ejemplo, 5000) o el nombre de tu ciudad."
    )


def localidad_ambigua(nombre: str, opciones: tuple[str, ...]) -> Respuesta:
    if len(opciones) >= 2:
        detalle = f"¿Es {opciones[0]} o {opciones[1]}? "
    else:
        detalle = "El plazo cambia según la localidad. "
    return Respuesta(
        f"Hay más de una zona posible para *{nombre}*. {detalle}Pasame tu *código postal* y te confirmo el plazo."
    )


@dataclass(frozen=True)
class DestinoEnvio:
    cp: int
    zona: ZonaDatos | None
    localidad: str | None = None  # nombre de la localidad si el comprador la nombró
    referencia_provincia: str | None = None  # capital usada como referencia de una provincia

    def lugar(self, negrita: bool = True) -> str:
        z = f", {self.zona.descripcion}" if self.zona else ""
        if self.referencia_provincia:
            nombre = f"*{self.localidad}*" if negrita else self.localidad
            return f"{nombre} (tomando como referencia {self.referencia_provincia}, CP {self.cp}{z})"
        if self.localidad:
            nombre = f"*{self.localidad}*" if negrita else self.localidad
            return f"{nombre} (CP {self.cp}{z})"
        cp = f"*{self.cp}*" if negrita else str(self.cp)
        return f"el código postal {cp}" + (f" ({self.zona.descripcion})" if self.zona else "")


def _costo_frase(zona: ZonaDatos) -> str:
    if zona.costo is None:
        return ""
    if zona.costo == 0:
        return " y el envío es *gratis*"
    return f" y el costo es de *{formato_pesos(zona.costo)}*"


def plazo_envio(destinos: list[DestinoEnvio], datos: DatosComercio) -> Respuesta:
    """Plazo (y costo, si está cargado) para uno o varios destinos cubiertos por una zona."""
    cubiertos = [d for d in destinos if d.zona]
    if len(cubiertos) == 1:
        d = cubiertos[0]
        texto = f"📦 Para {d.lugar()} el plazo estimado de entrega es de *{d.zona.plazo_texto}*{_costo_frase(d.zona)}."
        if d.referencia_provincia:
            texto += "\n\nSi tu localidad es otra, pasame el código postal y te confirmo."
    else:
        lineas = ["📦 Plazos estimados de entrega:"]
        for d in cubiertos:
            costo = ""
            if d.zona.costo == 0:
                costo = ", envío gratis"
            elif d.zona.costo:
                costo = f", {formato_pesos(d.zona.costo)}"
            lineas.append(f"• {d.lugar(negrita=False)}: *{d.zona.plazo_texto}*{costo}")
        texto = "\n".join(lineas)
    if datos.envio_gratis_desde and any(d.zona.costo != 0 for d in cubiertos):
        texto += f"\n\n🎁 Envío gratis en compras desde *{formato_pesos(datos.envio_gratis_desde)}*."
    return Respuesta(texto)


def costo_envio(destino: DestinoEnvio, datos: DatosComercio) -> Respuesta:
    """Respuesta corta a «¿y cuánto sale?» cuando ya se informó el plazo para ese destino."""
    zona = destino.zona
    lugar = destino.lugar()
    lugar = "al " + lugar[3:] if lugar.startswith("el ") else "a " + lugar
    if zona.costo == 0:
        texto = f"💲 El envío {lugar} es *gratis*."
    else:
        texto = f"💲 El envío {lugar} cuesta *{formato_pesos(zona.costo)}*."
        if datos.envio_gratis_desde:
            texto += f" Es gratis en compras desde *{formato_pesos(datos.envio_gratis_desde)}*."
    return Respuesta(texto)


def envio_nacional(zona: ZonaDatos, datos: DatosComercio) -> Respuesta:
    texto = f"📦 Enviamos a todo el país. El plazo estimado de entrega es de *{zona.plazo_texto}*{_costo_frase(zona)}."
    if datos.envio_gratis_desde and zona.costo != 0:
        texto += f"\n\n🎁 Envío gratis en compras desde *{formato_pesos(datos.envio_gratis_desde)}*."
    return Respuesta(texto)


def zona_no_configurada(destino: DestinoEnvio) -> str:
    return f"Para {destino.lugar(negrita=False)} no tengo cargado un plazo de entrega."


def costo_no_cargado() -> str:
    return "El costo del envío para tu zona no lo tengo cargado."


# ---------------------------------------------------------------------------
# CU10: medios de pago
# ---------------------------------------------------------------------------

_NOMBRES_CONCEPTO = {
    "mercado_pago": "Mercado Pago",
    "modo": "MODO",
    "uala": "Ualá",
    "cuenta_dni": "Cuenta DNI",
    "billetera": "billetera virtual",
    "transferencia": "transferencia",
    "credito": "tarjeta de crédito",
    "debito": "tarjeta de débito",
    "tarjeta": "tarjeta",
    "cuotas": "pago en cuotas",
    "efectivo": "efectivo",
    "visa": "Visa",
    "mastercard": "Mastercard",
    "amex": "American Express",
    "naranja": "Naranja",
    "cabal": "Cabal",
    "maestro": "Maestro",
    "rapipago": "Rapipago",
    "pago_facil": "Pago Fácil",
    "dolares": "dólares",
    "contra_entrega": "pago contra entrega",
    "link_pago": "link de pago",
    "cripto": "criptomonedas",
}
# Palabras que indican, en el nombre o el detalle del medio cargado, que lo incluye.
_SENIALES_CONCEPTO = {
    "mercado_pago": ("mercado pago", "mercadopago"),
    "modo": ("modo",),
    "uala": ("uala",),
    "cuenta_dni": ("cuenta dni",),
    "billetera": ("billetera", "mercado pago", "mercadopago", "modo", "uala", "cuenta dni", "qr"),
    "transferencia": ("transferencia", "cbu", "cvu", "alias", "deposito"),
    "credito": ("credito",),
    "debito": ("debito",),
    "tarjeta": ("tarjeta", "credito", "debito", "visa", "mastercard", "naranja", "cabal", "maestro", "amex"),
    "cuotas": ("cuota", "cuotas"),
    "efectivo": ("efectivo",),
    "visa": ("visa",),
    "mastercard": ("mastercard", "master"),
    "amex": ("amex", "american express"),
    "naranja": ("naranja",),
    "cabal": ("cabal",),
    "maestro": ("maestro",),
    "rapipago": ("rapipago",),
    "pago_facil": ("pago facil", "pagofacil"),
    "dolares": ("dolar", "usd", "u$s"),
    "contra_entrega": ("contra entrega", "contraentrega", "contrareembolso", "al recibir"),
    "link_pago": ("link",),
    "cripto": ("cripto", "bitcoin", "usdt"),
}
_MARCAS_TARJETA = {"visa", "mastercard", "amex", "naranja", "cabal", "maestro"}


def _texto_medio(medio: MedioDatos) -> str:
    from .normalizacion import normalizar

    return normalizar(f"{medio.nombre} {medio.detalle}")


def medios_que_incluyen(datos: DatosComercio, concepto: str) -> list[MedioDatos]:
    senales = _SENIALES_CONCEPTO.get(concepto, ())
    return [m for m in datos.medios if any(f" {s} " in f" {_texto_medio(m)} " for s in senales)]


def _linea_medio(medio: MedioDatos) -> str:
    return f"• {medio.nombre}: {medio.detalle}" if medio.detalle else f"• {medio.nombre}"


def _y(nombres: list[str]) -> str:
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def medios_de_pago(datos: DatosComercio, consultados: list[str] | None = None) -> Respuesta:
    """Medios de pago del comercio. Si se preguntó por uno en particular, primero se contesta
    sí o no («¿aceptan Naranja?»): un «no» se dice solo cuando surge de los datos cargados."""
    lineas: list[str] = []
    # Marcas de tarjeta que el comercio nombró en sus medios («Visa y Mastercard»).
    marcas_cargadas = {m for m in _MARCAS_TARJETA if medios_que_incluyen(datos, m)}
    tarjetas = medios_que_incluyen(datos, "tarjeta")
    aceptados: dict[MedioDatos, list[str]] = {}
    no_aceptados: list[str] = []
    for concepto in consultados or []:
        nombre = _NOMBRES_CONCEPTO.get(concepto, concepto)
        incluidos = medios_que_incluyen(datos, concepto)
        if incluidos:
            aceptados.setdefault(incluidos[0], []).append(concepto)
        elif concepto in _MARCAS_TARJETA and tarjetas and not marcas_cargadas:
            lineas.append(
                f"Aceptamos *{tarjetas[0].nombre}*, pero no tengo cargado si incluye *{nombre}*. "
                "Si querés confirmarlo, escribí *persona*."
            )
        else:
            no_aceptados.append(f"*{nombre[0].upper() + nombre[1:]}*")
    for medio, conceptos in aceptados.items():
        if conceptos == ["cuotas"]:
            lineas.insert(0, f"✅ Sí, hay cuotas con *{medio.nombre.lower()}*: {medio.detalle or medio.nombre}.")
        elif len(conceptos) == 1:
            nombre = _NOMBRES_CONCEPTO.get(conceptos[0], conceptos[0])
            lineas.insert(0, f"✅ Sí, aceptamos *{nombre}*: {medio.texto}.")
        else:
            lineas.insert(0, f"✅ Sí: *{medio.nombre}*" + (f" ({medio.detalle})." if medio.detalle else "."))
    if no_aceptados:
        verbo = "no está" if len(no_aceptados) == 1 else "no están"
        lineas.append(f"{_y(no_aceptados)} {verbo} entre los medios de pago de *{datos.nombre}*.")

    encabezado = "Estos son todos los medios de pago:" if lineas else f"💳 Medios de pago de *{datos.nombre}*:"
    cuerpo = [encabezado, ""] + [_linea_medio(m) for m in datos.medios]
    if lineas:
        return Respuesta("\n".join(lineas) + "\n\n" + "\n".join(cuerpo))
    return Respuesta("\n".join(cuerpo))


# ---------------------------------------------------------------------------
# CU11: horarios
# ---------------------------------------------------------------------------


def _estado_actual(datos: DatosComercio, ahora: datetime) -> str:
    franja = datos.franja_actual(ahora)
    if franja:
        return f"Ahora estamos atendiendo, hasta las {_hora(franja.cierre)}."
    proxima = datos.proxima_apertura(ahora)
    if proxima:
        return f"En este momento estamos cerrados. Volvemos a abrir {cuando(proxima, ahora)}."
    return "En este momento estamos cerrados."


def _dia_puntual(datos: DatosComercio, dia: int, etiqueta: str) -> str:
    franjas = datos.franjas_del_dia(dia)
    if not franjas:
        return f"{etiqueta} estamos cerrados."
    return f"{etiqueta} atendemos de {_franjas_texto(franjas)}."


def horarios(datos: DatosComercio, ahora: datetime, dias: list[str] | None = None) -> Respuesta:
    dias = dias or []
    puntuales: list[str] = []
    for dia in dias:
        if dia == "hoy":
            puntuales.append(_dia_puntual(datos, ahora.weekday(), f"Hoy ({DIAS_SEMANA[ahora.weekday()].lower()})"))
        elif dia == "mañana":
            manana = (ahora.weekday() + 1) % 7
            puntuales.append(_dia_puntual(datos, manana, f"Mañana ({DIAS_SEMANA[manana].lower()})"))
        elif dia == "feriado":
            puntuales.append("Los feriados el horario puede cambiar. Si querés confirmarlo, escribí *persona*.")
        elif dia.isdigit():
            nombre = DIAS_SEMANA[int(dia)].lower()
            plural = nombre if nombre.endswith("s") else nombre + "s"
            puntuales.append(_dia_puntual(datos, int(dia), f"Los {plural}"))
    lineas = []
    if puntuales:
        lineas += [" ".join(puntuales).replace(" Los", " Y los", 1) if len(puntuales) == 2 else " ".join(puntuales), ""]
    lineas += ["🕘 Nuestro horario de atención:", ""]
    lineas += lineas_horario(datos)
    lineas += ["", _estado_actual(datos, ahora)]
    return Respuesta("\n".join(lineas))


# ---------------------------------------------------------------------------
# Contacto y catálogo
# ---------------------------------------------------------------------------


def contacto(datos: DatosComercio) -> Respuesta:
    texto = f"📞 Podés comunicarte con *{datos.nombre}* por WhatsApp al *{datos.telefono_contacto}*."
    if datos.enlace_catalogo:
        texto += f"\n\n🛍️ Catálogo: {datos.enlace_catalogo}"
    return Respuesta(texto)


def catalogo(datos: DatosComercio) -> Respuesta:
    return Respuesta(
        f"🛍️ Acá tenés el catálogo de *{datos.nombre}*: {datos.enlace_catalogo}\n\n"
        "Si querés consultar por un producto en particular (stock, precio o medidas), escribime cuál y le paso "
        "la consulta al equipo."
    )


# ---------------------------------------------------------------------------
# CU12: derivación a una persona
# ---------------------------------------------------------------------------

_INTRO_DERIVACION = {
    "PERSONA": "¡Listo! Le aviso al equipo para que te atienda una persona.",
    "PRODUCTOS": "Las consultas sobre productos (stock, precios, medidas o colores) las responde una persona "
    "del equipo.",
    "PEDIDOS": "Para revisar tu pedido le paso la consulta al equipo. Si lo tenés a mano, escribí tu "
    "*número de pedido* o el nombre con el que compraste.",
    "RECLAMOS": "Lamentamos el inconveniente. 🙏 Ya le avisé al equipo para que lo revise con prioridad. Si podés, "
    "contame qué pasó y tu número de pedido.",
    "PAGOS_INFORMADOS": "¡Gracias por avisar! El equipo tiene que verificar el pago antes de confirmarlo.",
    "SIN_DATOS": "Esa información todavía no está cargada, así que le paso tu consulta al equipo.",
    "ENVIO": "Le paso tu consulta al equipo para que te lo confirme.",
    "ARCHIVO": "Igual le aviso al equipo para que lo revise.",
    "NO_RECONOCIDO": "Esa consulta la tiene que responder una persona del equipo.",
}


def _cuando_responden(datos: DatosComercio, ahora: datetime) -> str:
    if not datos.franjas:
        return "Te van a responder a la brevedad."
    if datos.esta_abierto(ahora):
        return "Estamos en horario de atención, así que te responden a la brevedad."
    proxima = datos.proxima_apertura(ahora)
    if proxima:
        return f"Ahora estamos fuera del horario de atención: te responden *{_cuando_desde(proxima, ahora)}*."
    return "Te van a responder a la brevedad."


def linea_contacto(datos: DatosComercio, ahora: datetime) -> str:
    desde = f" desde el WhatsApp *{datos.telefono_contacto}*" if datos.telefono_contacto else ""
    return f"Te va a escribir alguien de *{datos.nombre}*{desde}. {_cuando_responden(datos, ahora)}"


def derivacion(
    datos: DatosComercio,
    motivo: str,
    ahora: datetime,
    prefijo: str | None = None,
    extra: str | None = None,
) -> Respuesta:
    """Mensaje de derivación (CU12). ``motivo`` elige la introducción según el tema."""
    intro = _INTRO_DERIVACION.get(motivo, _INTRO_DERIVACION["NO_RECONOCIDO"])
    partes = [f"{prefijo} {intro}" if prefijo else intro]
    if motivo == "PRODUCTOS" and datos.enlace_catalogo:
        partes.append(f"Mientras tanto, podés ver el catálogo: {datos.enlace_catalogo}")
    if extra:
        partes.append(extra)
    partes.append(linea_contacto(datos, ahora))
    if motivo in {"PERSONA", "PRODUCTOS", "NO_RECONOCIDO", "SIN_DATOS"}:
        partes.append("Si mientras tanto querés saber de envíos, pagos u horarios, preguntame.")
    return Respuesta("\n\n".join(partes))


def recordatorio_derivacion(datos: DatosComercio, ahora: datetime, pidio_datos: bool = False) -> Respuesta:
    """Primer mensaje después de una derivación. Si el bot había pedido datos (número de
    pedido, qué pasó), lo más probable es que sean esos datos: se agradece."""
    if pidio_datos:
        inicio = f"¡Gracias! Lo sumé a tu consulta para el equipo de *{datos.nombre}*."
    else:
        inicio = f"Tu consulta ya está con el equipo de *{datos.nombre}*."
    desde = f" desde el WhatsApp *{datos.telefono_contacto}*" if datos.telefono_contacto else ""
    return Respuesta(
        f"{inicio} Te van a escribir{desde}. {_cuando_responden(datos, ahora)}"
        "\n\nSi mientras tanto querés saber de envíos, pagos u horarios, preguntame."
    )


def archivo_recibido(tipo: str, datos: DatosComercio) -> str:
    nombre = {"image": "imagen", "document": "archivo", "video": "video"}.get(tipo, "archivo")
    return (
        f"Recibí tu {nombre}, pero no puedo ver imágenes ni archivos. 🙈 Si es un comprobante de pago o la foto de "
        f"un producto, mandáselo al equipo de *{datos.nombre}* por WhatsApp al *{datos.telefono_contacto}*, o "
        "contame en un mensaje qué necesitás."
    )


# ---------------------------------------------------------------------------
# Comercio no identificado o en pausa (CU08, excepciones)
# ---------------------------------------------------------------------------


def comercio_no_identificado() -> Respuesta:
    return Respuesta(
        "¡Hola! 👋 Esta es una línea de atención automática que usan varios comercios. Para saber con cuál querés "
        "hablar, entrá desde el enlace que el comercio comparte en su Instagram o catálogo, o escribí su *código de "
        "acceso* (6 letras y números, por ejemplo AB12CD)."
    )


def bot_pausado(nombre: str, telefono_contacto: str) -> Respuesta:
    texto = f"La atención automática de *{nombre}* no está disponible en este momento."
    if telefono_contacto:
        texto += f" Podés escribirle directamente al WhatsApp *{telefono_contacto}*."
    return Respuesta(texto)
