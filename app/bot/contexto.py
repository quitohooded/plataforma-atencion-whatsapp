"""Datos del comercio y estado de la conversación que el motor necesita para responder.

El motor trabaja sobre estas copias inmutables y no sobre los modelos, de modo que el
mismo código atiende a WhatsApp, al simulador y al chat de prueba del panel (CU07), donde
nada se guarda en la base.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta

from ..modelos import EstadoConversacion, TemaConsulta, texto_plazo


@dataclass(frozen=True)
class ZonaDatos:
    cp_desde: int
    cp_hasta: int
    descripcion: str
    plazo_min_dias: int
    plazo_max_dias: int
    costo: int | None = None

    def contiene(self, cp: int) -> bool:
        return self.cp_desde <= cp <= self.cp_hasta

    @property
    def plazo_texto(self) -> str:
        return texto_plazo(self.plazo_min_dias, self.plazo_max_dias)


@dataclass(frozen=True)
class MedioDatos:
    nombre: str
    detalle: str = ""

    @property
    def texto(self) -> str:
        return f"{self.nombre} ({self.detalle})" if self.detalle else self.nombre


@dataclass(frozen=True)
class FranjaDatos:
    dia_semana: int  # 0 = lunes
    apertura: time
    cierre: time

    def cubre(self, momento: datetime) -> bool:
        return momento.weekday() == self.dia_semana and self.apertura <= momento.time() < self.cierre


@dataclass(frozen=True)
class DatosComercio:
    nombre: str
    telefono_contacto: str = ""
    zonas: tuple[ZonaDatos, ...] = field(default_factory=tuple)
    medios: tuple[MedioDatos, ...] = field(default_factory=tuple)
    franjas: tuple[FranjaDatos, ...] = field(default_factory=tuple)
    envio_gratis_desde: int | None = None
    enlace_catalogo: str | None = None

    @classmethod
    def desde_comercio(cls, comercio) -> DatosComercio:
        return cls(
            nombre=comercio.nombre,
            telefono_contacto=comercio.telefono_contacto,
            zonas=tuple(
                ZonaDatos(z.cp_desde, z.cp_hasta, z.descripcion, z.plazo_min_dias, z.plazo_max_dias, z.costo)
                for z in comercio.zonas
            ),
            medios=tuple(MedioDatos(m.nombre, m.detalle or "") for m in comercio.medios_pago if m.activo),
            franjas=tuple(
                FranjaDatos(h.dia_semana, h.apertura, h.cierre)
                for h in sorted(comercio.horarios, key=lambda h: (h.dia_semana, h.hora_apertura))
            ),
            envio_gratis_desde=comercio.envio_gratis_desde,
            enlace_catalogo=comercio.enlace_catalogo or None,
        )

    def zona_para(self, cp: int) -> ZonaDatos | None:
        return next((z for z in self.zonas if z.contiene(cp)), None)

    @property
    def zona_nacional(self) -> ZonaDatos | None:
        """Única zona que cubre todos los códigos postales: no hace falta pedir el CP."""
        if len(self.zonas) == 1 and self.zonas[0].cp_desde <= 1000 and self.zonas[0].cp_hasta >= 9999:
            return self.zonas[0]
        return None

    @property
    def informa_costos(self) -> bool:
        return any(z.costo is not None for z in self.zonas)

    def esta_abierto(self, momento: datetime) -> bool:
        return any(f.cubre(momento) for f in self.franjas)

    def franja_actual(self, momento: datetime) -> FranjaDatos | None:
        return next((f for f in self.franjas if f.cubre(momento)), None)

    def franjas_del_dia(self, dia_semana: int) -> list[FranjaDatos]:
        return sorted((f for f in self.franjas if f.dia_semana == dia_semana), key=lambda f: f.apertura)

    def proxima_apertura(self, momento: datetime) -> datetime | None:
        """Primer inicio de franja posterior a `momento`, dentro de los próximos 7 días."""
        if not self.franjas:
            return None
        for desplazamiento in range(0, 8):
            dia = (momento + timedelta(days=desplazamiento)).date()
            candidatas = sorted(
                datetime.combine(dia, f.apertura) for f in self.franjas if f.dia_semana == dia.weekday()
            )
            for inicio in candidatas:
                if inicio > momento:
                    return inicio
        return None


@dataclass(frozen=True)
class ContextoConversacion:
    """Estado de una conversación entre un mensaje y el siguiente."""

    estado: EstadoConversacion = EstadoConversacion.ACTIVA
    intentos_cp: int = 0
    intentos_sin_entender: int = 0
    ultimo_tema: TemaConsulta | None = None
    ultimo_cp: int | None = None
    # Temas de las consultas derivadas que el comercio todavía no atendió.
    temas_pendientes: frozenset[TemaConsulta] = field(default_factory=frozenset)

    def con(self, **cambios) -> ContextoConversacion:
        return replace(self, **cambios)
