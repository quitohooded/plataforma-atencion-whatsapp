"""Resumen de actividad y consultas pendientes (CU13) e historial de consultas (CU14).

Todas las lecturas se filtran por el comercio de la sesión activa a través de
conversacion.id_comercio (RF13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from math import ceil

from sqlalchemy import func, or_, select

from ..bot.contexto import DatosComercio
from ..extensiones import db
from ..modelos import (
    Comercio,
    Comprador,
    Consulta,
    Conversacion,
    DireccionMensaje,
    Mensaje,
    ResultadoConsulta,
    TemaConsulta,
)

PERIODOS = {
    "hoy": ("Hoy", 0),
    "7": ("Últimos 7 días", 7),
    "30": ("Últimos 30 días", 30),
    "90": ("Últimos 90 días", 90),
}
PERIODO_POR_DEFECTO = "7"


def _consultas_del_comercio(comercio: Comercio):
    return select(Consulta).join(Conversacion).where(Conversacion.id_comercio == comercio.id_comercio)


def rango_periodo(clave: str, ahora: datetime) -> tuple[datetime, datetime]:
    _, dias = PERIODOS.get(clave, PERIODOS[PERIODO_POR_DEFECTO])
    inicio_hoy = datetime.combine(ahora.date(), time.min)
    desde = inicio_hoy - timedelta(days=max(dias - 1, 0)) if dias else inicio_hoy
    return desde, ahora


@dataclass
class TemaResumen:
    tema: TemaConsulta
    cantidad: int
    porcentaje: int


@dataclass
class Resumen:
    periodo: str
    etiqueta_periodo: str
    desde: datetime
    hasta: datetime
    total: int = 0
    resueltas: int = 0
    derivadas: int = 0
    fuera_de_horario: int = 0
    pendientes: int = 0
    por_tema: list[TemaResumen] = field(default_factory=list)

    @property
    def porcentaje_resuelto(self) -> int:
        return round(self.resueltas * 100 / self.total) if self.total else 0

    @property
    def porcentaje_fuera_de_horario(self) -> int:
        return round(self.fuera_de_horario * 100 / self.total) if self.total else 0


def resumen(comercio: Comercio, periodo: str, ahora: datetime) -> Resumen:
    periodo = periodo if periodo in PERIODOS else PERIODO_POR_DEFECTO
    desde, hasta = rango_periodo(periodo, ahora)
    datos = DatosComercio.desde_comercio(comercio)

    consultas = db.session.scalars(
        _consultas_del_comercio(comercio).where(Consulta.fecha_hora >= desde, Consulta.fecha_hora <= hasta)
    ).all()

    r = Resumen(periodo, PERIODOS[periodo][0], desde, hasta)
    r.total = len(consultas)
    r.resueltas = sum(1 for c in consultas if c.resultado == ResultadoConsulta.RESUELTA)
    r.derivadas = r.total - r.resueltas
    # Fuera de horario según el horario del momento en que llegó cada consulta (#11); las
    # consultas anteriores a la versión 1.0 no lo guardaban y se calculan con el horario actual.
    r.fuera_de_horario = sum(
        1
        for c in consultas
        if (
            c.fuera_de_horario
            if c.fuera_de_horario is not None
            else bool(datos.franjas) and not datos.esta_abierto(c.fecha_hora)
        )
    )
    conteo = dict.fromkeys(TemaConsulta, 0)
    for c in consultas:
        conteo[c.tema] += 1
    # Solo los temas con consultas, de mayor a menor (a igual cantidad, en el orden de la enumeración).
    orden = list(TemaConsulta)
    r.por_tema = [
        TemaResumen(tema, n, round(n * 100 / r.total) if r.total else 0)
        for tema, n in sorted(conteo.items(), key=lambda x: (-x[1], orden.index(x[0])))
        if n
    ]
    r.pendientes = contar_pendientes(comercio)
    return r


def contar_pendientes(comercio: Comercio) -> int:
    return (
        db.session.scalar(
            select(func.count(Consulta.id_consulta))
            .join(Conversacion)
            .where(
                Conversacion.id_comercio == comercio.id_comercio,
                Consulta.resultado == ResultadoConsulta.DERIVADA,
                Consulta.atendida.is_(False),
            )
        )
        or 0
    )


@dataclass
class Pendiente:
    consulta: Consulta
    comprador: Comprador
    ultimo_mensaje: str

    @property
    def enlace_respuesta(self) -> str:
        return self.comprador.enlace_whatsapp_con(mensaje_sugerido(self.consulta, self.ultimo_mensaje))


# Primero lo más urgente; a igual prioridad, la consulta que espera hace más tiempo (#8).
_RANGO_PENDIENTE = {
    TemaConsulta.SEGURIDAD: 0,
    TemaConsulta.RECLAMOS: 1,
    TemaConsulta.PAGOS_INFORMADOS: 2,
    TemaConsulta.PEDIDOS: 3,
}

_MOTIVO_SUGERIDO = {
    TemaConsulta.RECLAMOS: "por lo que nos contaste. Lamentamos el inconveniente",
    TemaConsulta.PAGOS_INFORMADOS: "por el pago que nos avisaste",
    TemaConsulta.PEDIDOS: "por tu pedido",
    TemaConsulta.ENVIO: "por tu consulta de envío",
}
_ALERTA_SUGERIDA = {
    "TARJETA": ". Para pagar con tarjeta, te paso un link de pago seguro:",
    "SUPLANTACION": ". Gracias por avisarnos: nuestro único WhatsApp es este.",
    "DEVOLUCION": " por la devolución que nos pediste. Estamos verificando el pago.",
}


def mensaje_sugerido(consulta: Consulta, ultimo_mensaje: str = "") -> str:
    """Primer mensaje que el comercio le manda al comprador desde su WhatsApp. Cita la consulta
    para que el comprador sepa a qué se refiere, porque le escriben desde otro número."""
    conversacion = consulta.conversacion
    nombre = (conversacion.comprador.nombre or "").split(" ")[0]
    saludo = f"Hola{' ' + nombre if nombre else ''}, te escribo de {conversacion.comercio.nombre}"
    if consulta.alerta in _ALERTA_SUGERIDA:
        return saludo + _ALERTA_SUGERIDA[consulta.alerta]
    texto = f"{saludo} {_MOTIVO_SUGERIDO.get(consulta.tema, 'por tu consulta')}."
    cita = " ".join((ultimo_mensaje or "").split())
    if cita:
        cita = cita if len(cita) <= 100 else cita[:97].rstrip() + "…"
        texto += f" Nos escribiste: «{cita}»"
    return texto


def _ultimo_mensaje(consulta: Consulta, hasta_la_consulta: bool = False) -> str:
    consulta_mensaje = select(Mensaje.texto).where(
        Mensaje.id_conversacion == consulta.id_conversacion, Mensaje.direccion == DireccionMensaje.ENTRANTE
    )
    if hasta_la_consulta:
        consulta_mensaje = consulta_mensaje.where(Mensaje.fecha_hora <= consulta.fecha_hora)
    return db.session.scalar(consulta_mensaje.order_by(Mensaje.fecha_hora.desc(), Mensaje.id_mensaje.desc())) or ""


def pendientes(comercio: Comercio) -> list[Pendiente]:
    """Consultas derivadas sin atender: primero las alertas, los reclamos y los pagos informados."""
    consultas = db.session.scalars(
        _consultas_del_comercio(comercio)
        .where(Consulta.resultado == ResultadoConsulta.DERIVADA, Consulta.atendida.is_(False))
        .order_by(Consulta.fecha_hora, Consulta.id_consulta)
    ).all()
    consultas = sorted(consultas, key=lambda c: _RANGO_PENDIENTE.get(c.tema, len(_RANGO_PENDIENTE)))
    return [Pendiente(c, c.conversacion.comprador, _ultimo_mensaje(c)) for c in consultas]


def estado_pendientes(comercio: Comercio) -> dict:
    """Para el aviso en vivo del panel: cuántas hay y cuál es la más reciente (#8)."""
    ultima = db.session.scalar(
        _consultas_del_comercio(comercio)
        .where(Consulta.resultado == ResultadoConsulta.DERIVADA, Consulta.atendida.is_(False))
        .order_by(Consulta.fecha_hora.desc(), Consulta.id_consulta.desc())
    )
    detalle = ""
    if ultima:
        comprador = ultima.conversacion.comprador
        detalle = f"{ultima.etiqueta_tema}: {comprador.nombre or comprador.telefono_legible}"
    return {
        "pendientes": contar_pendientes(comercio),
        "ultima": ultima.id_consulta if ultima else 0,
        "detalle": detalle,
    }


def alertas_recientes(
    comercio: Comercio, ahora: datetime, dias: int = 7, limite: int = 5
) -> tuple[list[Pendiente], int]:
    """Alertas de seguridad de los últimos días (resueltas o no), con el mensaje que las originó."""
    filtro = _consultas_del_comercio(comercio).where(
        Consulta.tema == TemaConsulta.SEGURIDAD, Consulta.fecha_hora >= ahora - timedelta(days=dias)
    )
    total = db.session.scalar(select(func.count()).select_from(filtro.subquery())) or 0
    consultas = db.session.scalars(filtro.order_by(Consulta.fecha_hora.desc()).limit(limite)).all()
    return [Pendiente(c, c.conversacion.comprador, _ultimo_mensaje(c, True)) for c in consultas], total


def consulta_del_comercio(comercio: Comercio, id_consulta: int) -> Consulta | None:
    return db.session.scalar(_consultas_del_comercio(comercio).where(Consulta.id_consulta == id_consulta))


# ---------------------------------------------------------------------------
# CU14: historial
# ---------------------------------------------------------------------------


@dataclass
class FiltrosHistorial:
    desde: date | None = None
    hasta: date | None = None
    tema: TemaConsulta | None = None
    resultado: ResultadoConsulta | None = None
    # Nombre, teléfono o texto de un mensaje de la conversación (#10).
    busqueda: str | None = None

    @classmethod
    def desde_argumentos(cls, args) -> FiltrosHistorial:
        def fecha(valor):
            try:
                return date.fromisoformat(valor) if valor else None
            except ValueError:
                return None

        def enum(tipo, valor):
            try:
                return tipo(valor) if valor else None
            except ValueError:
                return None

        busqueda = " ".join((args.get("q") or "").split())[:80] or None
        return cls(
            desde=fecha(args.get("desde")),
            hasta=fecha(args.get("hasta")),
            tema=enum(TemaConsulta, args.get("tema")),
            resultado=enum(ResultadoConsulta, args.get("resultado")),
            busqueda=busqueda,
        )

    @property
    def activos(self) -> bool:
        return any([self.desde, self.hasta, self.tema, self.resultado, self.busqueda])

    def como_argumentos(self) -> dict:
        return {
            k: v
            for k, v in {
                "desde": self.desde.isoformat() if self.desde else None,
                "hasta": self.hasta.isoformat() if self.hasta else None,
                "tema": self.tema.value if self.tema else None,
                "resultado": self.resultado.value if self.resultado else None,
                "q": self.busqueda,
            }.items()
            if v
        }


@dataclass
class PaginaHistorial:
    items: list[Consulta]
    pagina: int
    paginas: int
    total: int


def _filtrar(comercio: Comercio, filtros: FiltrosHistorial):
    consulta = _consultas_del_comercio(comercio)
    if filtros.busqueda:
        patron = f"%{filtros.busqueda.lower()}%"
        digitos = "".join(c for c in filtros.busqueda if c.isdigit())
        en_mensajes = (
            select(Mensaje.id_mensaje)
            .where(Mensaje.id_conversacion == Consulta.id_conversacion, func.lower(Mensaje.texto).like(patron))
            .exists()
        )
        condiciones = [func.lower(Comprador.nombre).like(patron), en_mensajes]
        if len(digitos) >= 4:
            condiciones.append(Comprador.telefono.like(f"%{digitos}%"))
        consulta = consulta.join(Comprador, Conversacion.id_comprador == Comprador.id_comprador).where(
            or_(*condiciones)
        )
    if filtros.desde:
        consulta = consulta.where(Consulta.fecha_hora >= datetime.combine(filtros.desde, time.min))
    if filtros.hasta:
        consulta = consulta.where(Consulta.fecha_hora <= datetime.combine(filtros.hasta, time.max))
    if filtros.tema:
        consulta = consulta.where(Consulta.tema == filtros.tema)
    if filtros.resultado:
        consulta = consulta.where(Consulta.resultado == filtros.resultado)
    return consulta


def historial(comercio: Comercio, filtros: FiltrosHistorial, pagina: int = 1, por_pagina: int = 25) -> PaginaHistorial:
    consulta = _filtrar(comercio, filtros)
    total = db.session.scalar(select(func.count()).select_from(consulta.subquery())) or 0
    paginas = max(1, ceil(total / por_pagina))
    pagina = min(max(1, pagina), paginas)
    items = db.session.scalars(
        consulta.order_by(Consulta.fecha_hora.desc(), Consulta.id_consulta.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
    ).all()
    return PaginaHistorial(list(items), pagina, paginas, total)


# ---------------------------------------------------------------------------
# Exportación del historial (#10)
# ---------------------------------------------------------------------------

COLUMNAS_EXPORTACION = [
    "Fecha",
    "Hora",
    "Comprador",
    "Teléfono",
    "Tema",
    "Detalle",
    "Código postal",
    "Resultado",
    "Atención",
    "Atendida el",
    "Fuera de horario",
    "Mensaje",
]
MAXIMO_EXPORTACION = 20000


def _celda(valor) -> str:
    """Texto para una planilla, sin fórmulas: una celda que empieza con = + - @ se escapa."""
    texto = "" if valor is None else str(valor)
    texto = " ".join(texto.split())
    return "'" + texto if texto[:1] in {"=", "+", "-", "@"} else texto


def filas_exportacion(comercio: Comercio, filtros: FiltrosHistorial) -> list[list[str]]:
    consultas = db.session.scalars(
        _filtrar(comercio, filtros)
        .order_by(Consulta.fecha_hora.desc(), Consulta.id_consulta.desc())
        .limit(MAXIMO_EXPORTACION)
    ).all()
    filas = []
    for c in consultas:
        comprador = c.conversacion.comprador
        detalle = c.etiqueta_alerta or (c.respuesta.titulo if c.respuesta else "")
        fuera = {True: "Sí", False: "No"}.get(c.fuera_de_horario, "")
        filas.append(
            [
                _celda(v)
                for v in (
                    c.fecha_hora.strftime("%d/%m/%Y"),
                    c.fecha_hora.strftime("%H:%M"),
                    comprador.nombre or "",
                    comprador.telefono_legible,
                    c.tema.etiqueta,
                    detalle,
                    c.codigo_postal or "",
                    c.resultado.etiqueta,
                    c.estado_atencion,
                    c.fecha_atencion.strftime("%d/%m/%Y %H:%M") if c.fecha_atencion else "",
                    fuera,
                    _ultimo_mensaje(c, True),
                )
            ]
        )
    return filas
