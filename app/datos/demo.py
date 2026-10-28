"""Datos de demostración: dos comercios que comparten la línea y tres semanas de actividad.

El historial no se inserta a mano: cada conversación se reproduce mensaje por
mensaje con el mismo servicio que atiende WhatsApp, con fechas en el pasado.
Así los estados, las respuestas y las consultas registradas son exactamente los
que produciría el bot.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from ..bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from ..extensiones import db
from ..modelos import (
    Comercio,
    Consulta,
    Conversacion,
    EstadoComercio,
    HorarioAtencion,
    MedioPago,
    RespuestaFrecuente,
    ResultadoConsulta,
    Usuario,
    ZonaEnvio,
)
from ..utilidades import tiempo
from . import casa_y_detalles

CONTRASENA_DEMO = "demo1234"

# Localidades de los compradores: con nombre (el bot las reconoce) y con barrio (el bot pide el CP).
CIUDADES = [
    ("Río Cuarto", 5800),
    ("Villa María", 5900),
    ("Carlos Paz", 5152),
    ("Rosario", 2000),
    ("Mendoza", 5500),
    ("San Luis", 5700),
    ("Palermo", 1425),
    ("La Plata", 1900),
    ("Mar del Plata", 7600),
    ("Salta", 4400),
    ("Neuquén", 8300),
    ("barrio Alberdi", 5000),
    ("Nueva Córdoba", 5000),
    ("Bahía Blanca", 8000),
    ("Tucumán", 4000),
    ("Comodoro Rivadavia", 9000),
    ("Jesús María", 5220),
    ("Alta Gracia", 5186),
    ("Santa Fe", 3000),
    ("Quilmes", 1878),
]

NOMBRES = [
    "Lucía",
    "Martín",
    "Sofía",
    "Julieta",
    "Agustina",
    "Facundo",
    "Valentina",
    "Camila",
    "Nicolás",
    "Florencia",
    "Rocío",
    "Gonzalo",
    "Micaela",
    "Tomás",
    "Carolina",
    "Paula",
    "Ignacio",
    "Milagros",
    "Belén",
    "Joaquín",
    "Ana",
    "Marcela",
    "Silvia",
    "Patricia",
    None,
    None,
    None,
]

PREGUNTAS_PAGO = [
    "¿Aceptan Mercado Pago?",
    "Formas de pago?",
    "Se puede pagar con tarjeta en cuotas?",
    "Puedo pagar por transferencia?",
    "Hola, cómo se puede pagar?",
    "aceptan tarjeta naranja?",
    "hacen descuento por transferencia?",
]
PREGUNTAS_HORARIO = [
    "A qué hora abren mañana?",
    "Atienden los sábados?",
    "Hasta qué hora están hoy?",
    "Qué horario tienen?",
    "abren el domingo?",
]
PREGUNTAS_PRODUCTO = [
    "Tienen el juego de sábanas de 2 plazas en gris?",
    "Quiero saber si el mantel rectangular viene en 2,5 metros",
    "Hola, ¿el set de frascos de vidrio sigue disponible?",
    "cuánto sale la taza de cerámica?",
    "tienen almohadones de lino?",
    "me pasás fotos de las cortinas?",
]
PREGUNTAS_PEDIDO = [
    "Hola, ¿cuándo llega mi pedido?",
    "ya despacharon mi compra?",
    "me pasás el código de seguimiento?",
]
PREGUNTAS_RECLAMO = [
    "Me llegó una taza rota, ¿cómo hago para cambiarla?",
    "me llegó el mantel manchado",
    "todavía no me llegó el pedido y ya pasó una semana",
]
PAGOS_INFORMADOS = [
    "Listo, ya transferí. Te mando el comprobante",
    "ya pagué por mercado pago",
    "hice la transferencia recién",
]
PREGUNTAS_CATALOGO = ["tenés catálogo?", "¿qué productos venden?", "me pasás la lista de precios?"]
PREGUNTAS_OTRAS = [
    "¿Hacen factura A?",
    "¿Tienen local para ir a ver los productos?",
    "¿Hacen precio por mayor?",
    "¿Puedo regalarlo con una tarjeta de dedicatoria?",
    "Compré una cortina y me quedó corta, ¿se puede cambiar?",
]
GRACIAS = ["gracias!", "Genial, gracias", "dale, muchas gracias", "perfecto", "ok gracias!"]


def _guion(rng: random.Random, enlace: str, comercio: str) -> list[str]:
    """Secuencia de mensajes de un comprador. El primero es el texto del enlace de acceso."""
    ciudad, cp = rng.choice(CIUDADES)
    tipo = rng.choices(
        [
            "envio_ciudad",
            "envio_repregunta",
            "envio_directo",
            "envio_costo",
            "pago",
            "horario",
            "producto",
            "catalogo",
            "pedido",
            "reclamo",
            "pago_informado",
            "otra",
            "combo",
            "cp_invalido",
        ],
        weights=[16, 10, 7, 6, 15, 8, 12, 4, 5, 3, 4, 5, 8, 3],
    )[0]
    if tipo == "envio_ciudad":
        pasos = [rng.choice([f"Hola! hacen envíos a {ciudad}?", f"Llegan a {ciudad}?", f"cuánto tarda a {ciudad}?"])]
    elif tipo == "envio_repregunta":
        pasos = [rng.choice(["Hacen envíos?", "Hola, cuánto tarda el envío?", "envían al interior?"]), str(cp)]
    elif tipo == "envio_directo":
        pasos = [rng.choice([f"Cuánto tarda el envío al {cp}?", f"Hola, envían a CP {cp}?"])]
    elif tipo == "envio_costo":
        pasos = [f"Hola! hacen envíos al {cp}?", "y cuánto sale?"]
    elif tipo == "pago":
        pasos = [rng.choice(PREGUNTAS_PAGO)]
    elif tipo == "horario":
        pasos = [rng.choice(PREGUNTAS_HORARIO)]
    elif tipo == "producto":
        pasos = [rng.choice(PREGUNTAS_PRODUCTO)]
    elif tipo == "catalogo":
        pasos = [rng.choice(PREGUNTAS_CATALOGO)]
    elif tipo == "pedido":
        pasos = [rng.choice(PREGUNTAS_PEDIDO), "Compré el martes a nombre de " + rng.choice(["Lucía", "Martín", "Ana"])]
    elif tipo == "reclamo":
        pasos = [rng.choice(PREGUNTAS_RECLAMO)]
    elif tipo == "pago_informado":
        pasos = [rng.choice(PAGOS_INFORMADOS)]
    elif tipo == "otra":
        pasos = [rng.choice(PREGUNTAS_OTRAS)]
    elif tipo == "combo":
        pasos = [f"Hola! hacen envíos a {ciudad}?", rng.choice(["y aceptan mercado pago?", "y cómo se paga?"])]
    else:
        pasos = ["Hacen envíos?", "no sé cuál es", "ni idea"]
    if rng.random() < 0.45 and tipo not in {"otra", "cp_invalido", "reclamo", "pedido", "producto", "pago_informado"}:
        pasos.append(rng.choice(GRACIAS))
    return [enlace] + pasos


def _momento(rng: random.Random, dia: date, ahora: datetime) -> datetime | None:
    franja = rng.choices(["noche", "madrugada", "dia"], weights=[45, 8, 47])[0]
    if franja == "noche":
        hora = rng.randint(20, 23)
    elif franja == "madrugada":
        hora = rng.randint(0, 7)
    else:
        hora = rng.randint(9, 19)
    momento = datetime.combine(dia, time(hora, rng.randint(0, 59)))
    return momento if momento < ahora - timedelta(minutes=20) else None


def _crear_comercio(
    nombre,
    rubro,
    telefono,
    email,
    codigo,
    fecha_alta,
    zonas,
    medios,
    horarios,
    envio_gratis_desde=None,
    catalogo=None,
    respuestas=(),
) -> Comercio:
    comercio = Comercio(
        nombre=nombre,
        rubro=rubro,
        telefono_contacto=telefono,
        codigo_acceso=codigo,
        estado=EstadoComercio.ACTIVO,
        fecha_alta=fecha_alta,
        paso_onboarding=Comercio.PASO_COMPLETO,
        envio_gratis_desde=envio_gratis_desde,
        enlace_catalogo=catalogo,
    )
    usuario = Usuario(comercio=comercio, email=email, intentos_fallidos=0)
    usuario.establecer_contrasena(CONTRASENA_DEMO)
    db.session.add_all([comercio, usuario])
    for descripcion, desde, hasta, minimo, maximo, costo in zonas:
        db.session.add(
            ZonaEnvio(
                comercio=comercio,
                descripcion=descripcion,
                cp_desde=desde,
                cp_hasta=hasta,
                plazo_min_dias=minimo,
                plazo_max_dias=maximo,
                costo=costo,
            )
        )
    for nombre_medio, detalle, activo in medios:
        db.session.add(MedioPago(comercio=comercio, nombre=nombre_medio, detalle=detalle, activo=activo))
    for dia, apertura, cierre in horarios:
        db.session.add(HorarioAtencion(comercio=comercio, dia_semana=dia, hora_apertura=apertura, hora_cierre=cierre))
    for plantilla, titulo, texto in respuestas:
        db.session.add(
            RespuestaFrecuente(
                comercio=comercio,
                plantilla=plantilla,
                titulo=titulo,
                palabras_clave=", ".join(casa_y_detalles.palabras_de(plantilla)),
                respuesta=texto,
                activa=True,
                fecha_alta=datetime.combine(fecha_alta, time(10, 0)),
            )
        )
    db.session.commit()
    return comercio


def _reproducir_historial(
    rng: random.Random, comercio: Comercio, dias: int, por_dia: tuple[int, int], ahora: datetime, contador: list[int]
) -> None:
    enlace = comercio.texto_primer_mensaje()
    for atras in range(dias, -1, -1):
        dia = ahora.date() - timedelta(days=atras)
        cantidad = rng.randint(*por_dia)
        momentos = sorted(m for m in (_momento(rng, dia, ahora) for _ in range(cantidad)) if m)
        for inicio in momentos:
            contador[0] += 1
            telefono = f"5493510{contador[0]:06d}"
            nombre = rng.choice(NOMBRES)
            momento = inicio
            for texto in _guion(rng, enlace, comercio.nombre):
                procesar_mensaje_entrante(
                    MensajeEntrante(
                        telefono=telefono,
                        texto=texto,
                        nombre=nombre,
                        fecha_hora=momento,
                    )
                )
                momento += timedelta(seconds=rng.randint(25, 140))


# Consultas puntuales de Mundo Textil, que no cargó respuestas propias: el panel le sugiere
# crearlas a partir de estas derivaciones (CU15).
CONSULTAS_MUNDO_TEXTIL = [
    (9, "¿Venden por mayor? Tengo un local de blanquería en Funes"),
    (8, "Necesito factura A para la empresa, ¿hacen?"),
    (6, "precio mayorista de los juegos de sábanas?"),
    (5, "Hola, ¿hacen factura? Es para un regalo empresarial"),
]


def _consultas_puntuales(comercio: Comercio, consultas, ahora: datetime, contador: list[int]) -> None:
    enlace = comercio.texto_primer_mensaje()
    for dias_atras, texto in consultas:
        contador[0] += 1
        momento = datetime.combine(ahora.date() - timedelta(days=dias_atras), time(21, 10 + contador[0] % 40))
        for paso, mensaje in enumerate([enlace, texto]):
            procesar_mensaje_entrante(
                MensajeEntrante(
                    telefono=f"5493510{contador[0]:06d}",
                    texto=mensaje,
                    fecha_hora=momento + timedelta(seconds=40 * paso),
                )
            )


def _atender_derivadas_antiguas(rng: random.Random, ahora: datetime, dejar_pendientes_horas: int = 72) -> None:
    """Las derivaciones viejas figuran atendidas; quedan pendientes las de las últimas horas."""
    for consulta in db.session.scalars(db.select(Consulta).where(Consulta.resultado == ResultadoConsulta.DERIVADA)):
        if ahora - consulta.fecha_hora > timedelta(hours=dejar_pendientes_horas):
            atencion = consulta.fecha_hora + timedelta(hours=rng.randint(1, 14), minutes=rng.randint(0, 59))
            consulta.marcar_atendida(min(atencion, ahora))
    db.session.commit()


def cargar_demo(semilla: int = 2026) -> list[str]:
    from .. import inicializar_base

    db.drop_all()
    inicializar_base()
    rng = random.Random(semilla)
    ahora = tiempo.ahora()

    casa = _crear_comercio(
        nombre=casa_y_detalles.NOMBRE,
        rubro=casa_y_detalles.RUBRO,
        telefono=casa_y_detalles.TELEFONO,
        email="demo@casaydetalles.com.ar",
        codigo="CASA26",
        fecha_alta=(ahora - timedelta(days=24)).date(),
        zonas=casa_y_detalles.ZONAS,
        medios=casa_y_detalles.MEDIOS,
        horarios=casa_y_detalles.HORARIOS,
        envio_gratis_desde=casa_y_detalles.ENVIO_GRATIS_DESDE,
        catalogo=casa_y_detalles.CATALOGO,
        respuestas=casa_y_detalles.RESPUESTAS,
    )

    textil = _crear_comercio(
        nombre="Mundo Textil",
        rubro="Blanquería y textiles",
        telefono="341 012-9876",
        email="demo@mundotextil.com.ar",
        codigo="TEXT42",
        fecha_alta=(ahora - timedelta(days=12)).date(),
        zonas=[
            ("Rosario", 2000, 2099, 1, 2, 3900),
            ("Gran Rosario", 2100, 2199, 1, 3, 5500),
            ("Sur de Santa Fe, norte de Buenos Aires y este de Córdoba", 2200, 2999, 2, 4, 7900),
            ("Ciudad de Buenos Aires y Gran Buenos Aires", 1000, 1999, 3, 6, 8900),
            ("Resto del país", 3000, 9499, 4, 8, 10900),
        ],
        medios=[
            ("Transferencia bancaria", "alias mundo.textil.demo", True),
            ("Efectivo", "contra entrega en Rosario", True),
        ],
        horarios=[(d, "09:00", "13:00") for d in range(5)]
        + [(d, "16:00", "20:00") for d in range(5)]
        + [(5, "09:30", "13:00")],
    )

    contador = [100]
    _reproducir_historial(rng, casa, dias=20, por_dia=(3, 9), ahora=ahora, contador=contador)
    _reproducir_historial(rng, textil, dias=10, por_dia=(1, 4), ahora=ahora, contador=contador)
    _consultas_puntuales(textil, CONSULTAS_MUNDO_TEXTIL, ahora, contador)
    _atender_derivadas_antiguas(rng, ahora)

    def conteo(comercio):
        consultas = db.session.scalars(
            db.select(Consulta).join(Consulta.conversacion).where(Conversacion.id_comercio == comercio.id_comercio)
        ).all()
        return len(consultas), sum(1 for c in consultas if c.pendiente)

    lineas = []
    for comercio in (casa, textil):
        total, pendientes = conteo(comercio)
        lineas.append(
            f"{comercio.nombre}: {comercio.usuario.email} / {CONTRASENA_DEMO} "
            f"(código {comercio.codigo_acceso}, {total} consultas, "
            f"{pendientes} {'pendiente' if pendientes == 1 else 'pendientes'})"
        )
    return lineas
