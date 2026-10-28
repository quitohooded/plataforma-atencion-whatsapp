"""Resumen de actividad y consultas pendientes (CU13) e historial de consultas (CU14).

Todas las lecturas se filtran por el comercio de la sesión activa a través de
conversacion.id_comercio (RF13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from math import ceil

from sqlalchemy import func, select

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
    r.fuera_de_horario = sum(1 for c in consultas if datos.franjas and not datos.esta_abierto(c.fecha_hora))
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


def pendientes(comercio: Comercio) -> list[Pendiente]:
    consultas = db.session.scalars(
        _consultas_del_comercio(comercio)
        .where(Consulta.resultado == ResultadoConsulta.DERIVADA, Consulta.atendida.is_(False))
        .order_by(Consulta.fecha_hora.desc())
    ).all()
    lista = []
    for consulta in consultas:
        ultimo = db.session.scalar(
            select(Mensaje.texto)
            .where(Mensaje.id_conversacion == consulta.id_conversacion, Mensaje.direccion == DireccionMensaje.ENTRANTE)
            .order_by(Mensaje.fecha_hora.desc(), Mensaje.id_mensaje.desc())
        )
        lista.append(Pendiente(consulta, consulta.conversacion.comprador, ultimo or ""))
    return lista


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

        return cls(
            desde=fecha(args.get("desde")),
            hasta=fecha(args.get("hasta")),
            tema=enum(TemaConsulta, args.get("tema")),
            resultado=enum(ResultadoConsulta, args.get("resultado")),
        )

    @property
    def activos(self) -> bool:
        return any([self.desde, self.hasta, self.tema, self.resultado])

    def como_argumentos(self) -> dict:
        return {
            k: v
            for k, v in {
                "desde": self.desde.isoformat() if self.desde else None,
                "hasta": self.hasta.isoformat() if self.hasta else None,
                "tema": self.tema.value if self.tema else None,
                "resultado": self.resultado.value if self.resultado else None,
            }.items()
            if v
        }


@dataclass
class PaginaHistorial:
    items: list[Consulta]
    pagina: int
    paginas: int
    total: int


def historial(comercio: Comercio, filtros: FiltrosHistorial, pagina: int = 1, por_pagina: int = 25) -> PaginaHistorial:
    consulta = _consultas_del_comercio(comercio)
    if filtros.desde:
        consulta = consulta.where(Consulta.fecha_hora >= datetime.combine(filtros.desde, time.min))
    if filtros.hasta:
        consulta = consulta.where(Consulta.fecha_hora <= datetime.combine(filtros.hasta, time.max))
    if filtros.tema:
        consulta = consulta.where(Consulta.tema == filtros.tema)
    if filtros.resultado:
        consulta = consulta.where(Consulta.resultado == filtros.resultado)

    total = db.session.scalar(select(func.count()).select_from(consulta.subquery())) or 0
    paginas = max(1, ceil(total / por_pagina))
    pagina = min(max(1, pagina), paginas)
    items = db.session.scalars(
        consulta.order_by(Consulta.fecha_hora.desc(), Consulta.id_consulta.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
    ).all()
    return PaginaHistorial(list(items), pagina, paginas, total)
