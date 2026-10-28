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
    ResultadoConsulta,
    Usuario,
    ZonaEnvio,
)
from ..utilidades import tiempo

CONTRASENA_DEMO = "demo1234"

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
]
PREGUNTAS_HORARIO = [
    "A qué hora abren mañana?",
    "Atienden los sábados?",
    "Hasta qué hora están hoy?",
    "Qué horario tienen?",
]
PREGUNTAS_ABIERTAS = [
    "Tienen el juego de sábanas de 2 plazas en gris?",
    "Me llegó una taza rota, ¿cómo hago para cambiarla?",
    "¿Hacen factura A?",
    "Quiero saber si el mantel rectangular viene en 2,5 metros",
    "¿Tienen local para ir a ver los productos?",
    "Hola, ¿el set de frascos de vidrio sigue disponible?",
    "Compré una cortina y me quedó corta, ¿se puede cambiar?",
    "¿Hacen precio por mayor?",
]
GRACIAS = ["gracias!", "Genial, gracias", "dale, muchas gracias", "perfecto", "ok gracias!"]


def _guion(rng: random.Random, enlace: str, comercio: str) -> list[str]:
    """Secuencia de mensajes de un comprador. El primero es el texto del enlace de acceso."""
    ciudad, cp = rng.choice(CIUDADES)
    tipo = rng.choices(
        ["envio_repregunta", "envio_directo", "pago", "horario", "abierta", "combo", "cp_invalido"],
        weights=[26, 10, 18, 12, 16, 12, 6],
    )[0]
    if tipo == "envio_repregunta":
        pasos = [rng.choice([f"Hola! hacen envíos a {ciudad}?", "Hacen envíos?", f"Llegan a {ciudad}?"]), str(cp)]
    elif tipo == "envio_directo":
        pasos = [rng.choice([f"Cuánto tarda el envío al {cp}?", f"Hola, envían a CP {cp}?"])]
    elif tipo == "pago":
        pasos = [rng.choice(PREGUNTAS_PAGO)]
    elif tipo == "horario":
        pasos = [rng.choice(PREGUNTAS_HORARIO)]
    elif tipo == "abierta":
        pasos = [rng.choice(PREGUNTAS_ABIERTAS)]
    elif tipo == "combo":
        pasos = [f"Hola! hacen envíos a {ciudad}?", str(cp), rng.choice(["y aceptan mercado pago?", "y cómo se paga?"])]
    else:
        pasos = ["Hacen envíos?", ciudad, "no sé cuál es"]
    if rng.random() < 0.45 and tipo != "abierta" and tipo != "cp_invalido":
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


def _crear_comercio(nombre, rubro, telefono, email, codigo, fecha_alta, zonas, medios, horarios) -> Comercio:
    comercio = Comercio(
        nombre=nombre,
        rubro=rubro,
        telefono_contacto=telefono,
        codigo_acceso=codigo,
        estado=EstadoComercio.ACTIVO,
        fecha_alta=fecha_alta,
        paso_onboarding=Comercio.PASO_COMPLETO,
    )
    usuario = Usuario(comercio=comercio, email=email, intentos_fallidos=0)
    usuario.establecer_contrasena(CONTRASENA_DEMO)
    db.session.add_all([comercio, usuario])
    for descripcion, desde, hasta, minimo, maximo in zonas:
        db.session.add(
            ZonaEnvio(
                comercio=comercio,
                descripcion=descripcion,
                cp_desde=desde,
                cp_hasta=hasta,
                plazo_min_dias=minimo,
                plazo_max_dias=maximo,
            )
        )
    for nombre_medio, detalle, activo in medios:
        db.session.add(MedioPago(comercio=comercio, nombre=nombre_medio, detalle=detalle, activo=activo))
    for dia, apertura, cierre in horarios:
        db.session.add(HorarioAtencion(comercio=comercio, dia_semana=dia, hora_apertura=apertura, hora_cierre=cierre))
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

    lunes_a_viernes = [(d, "09:00", "18:00") for d in range(5)]
    casa = _crear_comercio(
        nombre="Casa & Detalles",
        rubro="Artículos para el hogar",
        telefono="351 012-3456",
        email="demo@casaydetalles.com.ar",
        codigo="CASA26",
        fecha_alta=(ahora - timedelta(days=24)).date(),
        zonas=[
            ("Córdoba Capital", 5000, 5099, 1, 2),
            ("Interior de Córdoba y región Centro", 5100, 5999, 2, 4),
            ("Ciudad de Buenos Aires", 1000, 1499, 3, 5),
            ("Gran Buenos Aires", 1500, 1999, 3, 5),
            ("Litoral, NOA y NEA", 2000, 4999, 4, 6),
            ("Provincia de Buenos Aires, La Pampa y Cuyo sur", 6000, 8999, 4, 7),
            ("Patagonia", 9000, 9499, 6, 10),
        ],
        medios=[
            ("Transferencia bancaria", "alias casa.detalles.demo", True),
            ("Billetera virtual", "Mercado Pago y MODO", True),
            ("Tarjeta de crédito", "hasta 3 cuotas sin interés", True),
            ("Tarjeta de débito", "Visa y Maestro", True),
            ("Efectivo", "solo en retiros por el depósito", False),
        ],
        horarios=lunes_a_viernes + [(5, "09:00", "13:00")],
    )

    textil = _crear_comercio(
        nombre="Mundo Textil",
        rubro="Blanquería y textiles",
        telefono="341 012-9876",
        email="demo@mundotextil.com.ar",
        codigo="TEXT42",
        fecha_alta=(ahora - timedelta(days=12)).date(),
        zonas=[
            ("Rosario", 2000, 2099, 1, 2),
            ("Provincia de Santa Fe", 2100, 3099, 2, 3),
            ("Resto del país (1000 a 1999)", 1000, 1999, 3, 6),
            ("Resto del país (3100 a 9499)", 3100, 9499, 4, 8),
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
