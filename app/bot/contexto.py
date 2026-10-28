"""Datos del comercio y estado de la conversación que el motor necesita para responder.

El motor trabaja sobre estas copias inmutables y no sobre los modelos, de modo que el
mismo código atiende a WhatsApp, al simulador y al chat de prueba del panel (CU07), donde
nada se guarda en la base.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta

from ..modelos import EstadoConversacion, TemaConsulta, texto_plazo
from .normalizacion import normalizar_frase


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
class RespuestaDatos:
    """Respuesta propia del comercio (CU15): palabras clave normalizadas y texto fijo."""

    clave: str  # plantilla («cambios») o «r» y el número de la respuesta
    titulo: str
    terminos: tuple[str, ...]
    texto: str
    id_respuesta: int | None = None

    @classmethod
    def con_frases(cls, clave: str, titulo: str, frases, texto: str, id_respuesta: int | None = None) -> RespuestaDatos:
        """Desde las palabras clave tal como las escribió el comercio («Factura A», «x mayor»)."""
        terminos = tuple(dict.fromkeys(t for t in (normalizar_frase(f) for f in frases) if t))
        return cls(clave, titulo, terminos, texto, id_respuesta)


@dataclass(frozen=True)
class DatosComercio:
    nombre: str
    telefono_contacto: str = ""
    zonas: tuple[ZonaDatos, ...] = field(default_factory=tuple)
    medios: tuple[MedioDatos, ...] = field(default_factory=tuple)
    franjas: tuple[FranjaDatos, ...] = field(default_factory=tuple)
    envio_gratis_desde: int | None = None
    enlace_catalogo: str | None = None
    respuestas: tuple[RespuestaDatos, ...] = field(default_factory=tuple)
    # Número de la línea de la plataforma (también es oficial para el comprador).
    linea_plataforma: str = ""

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
            respuestas=tuple(
                RespuestaDatos.con_frases(r.clave, r.titulo, r.lista_palabras, r.respuesta, r.id_respuesta)
                for r in comercio.respuestas_frecuentes
                if r.activa and r.lista_palabras
            ),
            linea_plataforma=_linea_plataforma(),
        )

    @property
    def datos_pago(self) -> frozenset[str]:
        """Alias y CBU o CVU de los medios de pago activos, para verificar los que menciona un comprador."""
        from .seguridad import datos_de_pago

        encontrados: set[str] = set()
        for medio in self.medios:
            encontrados |= datos_de_pago(f"{medio.nombre} {medio.detalle}")
        return frozenset(encontrados)

    @property
    def telefonos_oficiales(self) -> tuple[str, ...]:
        """Últimos 8 dígitos del WhatsApp del comercio y de la línea de la plataforma."""
        from .seguridad import telefono_comparable

        numeros = ["".join(c for c in n if c.isdigit()) for n in (self.telefono_contacto, self.linea_plataforma)]
        return tuple(telefono_comparable(n) for n in numeros if len(n) >= 8)

    def respuesta(self, clave: str) -> RespuestaDatos | None:
        return next((r for r in self.respuestas if r.clave == clave), None)

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
    # Pausa del bot con este comprador (spam, insultos repetidos o ráfaga de mensajes).
    silenciada_hasta: datetime | None = None
    # Advertencias por spam o insultos en esta conversación.
    advertencias: int = 0

    def silenciada(self, momento: datetime) -> bool:
        return self.silenciada_hasta is not None and momento < self.silenciada_hasta

    def con(self, **cambios) -> ContextoConversacion:
        return replace(self, **cambios)


def _linea_plataforma() -> str:
    try:
        from flask import current_app

        return current_app.config.get("WHATSAPP_NUMERO_PUBLICO", "") or ""
    except RuntimeError:  # fuera de una aplicación (pruebas del motor)
        return ""
