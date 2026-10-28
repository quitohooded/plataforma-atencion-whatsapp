"""Datos del comercio que el motor necesita para responder.

El motor trabaja sobre esta copia inmutable y no sobre los modelos, de modo que
el mismo código atiende a WhatsApp, al simulador y al chat de prueba del panel
(CU07), donde nada se guarda en la base.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from ..modelos import texto_plazo


@dataclass(frozen=True)
class ZonaDatos:
    cp_desde: int
    cp_hasta: int
    descripcion: str
    plazo_min_dias: int
    plazo_max_dias: int

    def contiene(self, cp: int) -> bool:
        return self.cp_desde <= cp <= self.cp_hasta

    @property
    def plazo_texto(self) -> str:
        return texto_plazo(self.plazo_min_dias, self.plazo_max_dias)


@dataclass(frozen=True)
class MedioDatos:
    nombre: str
    detalle: str = ""


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

    @classmethod
    def desde_comercio(cls, comercio) -> DatosComercio:
        return cls(
            nombre=comercio.nombre,
            telefono_contacto=comercio.telefono_contacto,
            zonas=tuple(
                ZonaDatos(z.cp_desde, z.cp_hasta, z.descripcion, z.plazo_min_dias, z.plazo_max_dias)
                for z in comercio.zonas
            ),
            medios=tuple(MedioDatos(m.nombre, m.detalle or "") for m in comercio.medios_pago if m.activo),
            franjas=tuple(
                FranjaDatos(h.dia_semana, h.apertura, h.cierre)
                for h in sorted(comercio.horarios, key=lambda h: (h.dia_semana, h.hora_apertura))
            ),
        )

    def zona_para(self, cp: int) -> ZonaDatos | None:
        return next((z for z in self.zonas if z.contiene(cp)), None)

    def esta_abierto(self, momento: datetime) -> bool:
        return any(f.cubre(momento) for f in self.franjas)

    def franja_actual(self, momento: datetime) -> FranjaDatos | None:
        return next((f for f in self.franjas if f.cubre(momento)), None)

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
