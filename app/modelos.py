"""Modelo de dominio (diagrama de clases, Figura 6) y su mapeo a SQLite (DER, Figura 7).

Cada clase del diagrama se corresponde con una tabla del DER. Los nombres de
tablas y columnas respetan el DER; los métodos respetan las operaciones del
diagrama de clases, escritos en snake_case según la convención de Python
(por ejemplo, ``estaAbierto`` se implementa como ``esta_abierto``).

Agregados respecto del DER de la Entrega 3 (documentados en docs/arquitectura.md):
- usuario.intentos_fallidos y usuario.bloqueado_hasta: bloqueo de ingreso (CU02).
- comercio.paso_onboarding: retomar el onboarding en el paso pendiente (CU03).
- conversacion.intentos_cp: contar códigos postales inválidos (CU09).
- mensaje.id_externo: identificador de WhatsApp para descartar mensajes repetidos.
"""

from __future__ import annotations

import enum
import secrets
from datetime import date, datetime, time
from urllib.parse import quote

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from .extensiones import db


# ---------------------------------------------------------------------------
# Enumeraciones (se almacenan como texto con un conjunto acotado de valores)
# ---------------------------------------------------------------------------

class EstadoComercio(str, enum.Enum):
    EN_ONBOARDING = "EN_ONBOARDING"
    ACTIVO = "ACTIVO"
    PAUSADO = "PAUSADO"

    @property
    def etiqueta(self) -> str:
        return {"EN_ONBOARDING": "En onboarding", "ACTIVO": "Activo", "PAUSADO": "Pausado"}[self.value]


class TemaConsulta(str, enum.Enum):
    ENVIO = "ENVIO"
    MEDIOS_PAGO = "MEDIOS_PAGO"
    HORARIOS = "HORARIOS"
    NO_RECONOCIDO = "NO_RECONOCIDO"

    @property
    def etiqueta(self) -> str:
        return {
            "ENVIO": "Envíos",
            "MEDIOS_PAGO": "Medios de pago",
            "HORARIOS": "Horarios",
            "NO_RECONOCIDO": "No reconocido",
        }[self.value]


class EstadoConversacion(str, enum.Enum):
    ACTIVA = "ACTIVA"
    ESPERANDO_CP = "ESPERANDO_CP"
    DERIVADA = "DERIVADA"
    CERRADA = "CERRADA"

    @property
    def etiqueta(self) -> str:
        return {
            "ACTIVA": "Activa",
            "ESPERANDO_CP": "Esperando código postal",
            "DERIVADA": "Derivada",
            "CERRADA": "Cerrada",
        }[self.value]


class ResultadoConsulta(str, enum.Enum):
    RESUELTA = "RESUELTA"
    DERIVADA = "DERIVADA"

    @property
    def etiqueta(self) -> str:
        return {"RESUELTA": "Resuelta", "DERIVADA": "Derivada"}[self.value]


class DireccionMensaje(str, enum.Enum):
    ENTRANTE = "ENTRANTE"
    SALIENTE = "SALIENTE"


def _enum(tipo):
    return SAEnum(tipo, native_enum=False, length=20, validate_strings=True)


# Alfabeto sin caracteres ambiguos (0/O, 1/I/L) para los códigos de acceso.
ALFABETO_CODIGO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LARGO_CODIGO = 6


# ---------------------------------------------------------------------------
# Comercio y su configuración
# ---------------------------------------------------------------------------

class Comercio(db.Model):
    __tablename__ = "comercio"

    id_comercio: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    rubro: Mapped[str] = mapped_column(Text, nullable=False)
    telefono_contacto: Mapped[str] = mapped_column(Text, nullable=False)
    codigo_acceso: Mapped[str | None] = mapped_column(Text, unique=True)
    estado: Mapped[EstadoComercio] = mapped_column(
        _enum(EstadoComercio), nullable=False, default=EstadoComercio.EN_ONBOARDING
    )
    fecha_alta: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    paso_onboarding: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    usuario: Mapped["Usuario"] = relationship(back_populates="comercio", uselist=False)
    zonas: Mapped[list["ZonaEnvio"]] = relationship(
        back_populates="comercio", cascade="all, delete-orphan", order_by="ZonaEnvio.cp_desde"
    )
    medios_pago: Mapped[list["MedioPago"]] = relationship(
        back_populates="comercio", cascade="all, delete-orphan", order_by="MedioPago.id_medio_pago"
    )
    horarios: Mapped[list["HorarioAtencion"]] = relationship(
        back_populates="comercio",
        cascade="all, delete-orphan",
        order_by="(HorarioAtencion.dia_semana, HorarioAtencion.hora_apertura)",
    )
    conversaciones: Mapped[list["Conversacion"]] = relationship(
        back_populates="comercio", cascade="all, delete-orphan"
    )

    # Pasos del onboarding (CU03): 1 a 4 formularios, 5 resumen, 6 completo.
    PASO_RESUMEN = 5
    PASO_COMPLETO = 6

    @property
    def onboarding_completo(self) -> bool:
        return self.paso_onboarding >= self.PASO_COMPLETO

    @property
    def fue_activado(self) -> bool:
        """El bot fue activado al menos una vez (precondición de CU13)."""
        return self.codigo_acceso is not None

    @property
    def medios_activos(self) -> list["MedioPago"]:
        return [m for m in self.medios_pago if m.activo]

    # --- Operaciones del diagrama de clases --------------------------------

    def generar_enlace_acceso(self, numero_linea: str) -> str:
        """Enlace wa.me a la línea de la plataforma con el código del comercio."""
        if not self.codigo_acceso:
            raise ValueError("El comercio todavía no tiene código de acceso.")
        texto = self.texto_primer_mensaje()
        numero = "".join(ch for ch in (numero_linea or "") if ch.isdigit())
        if not numero:
            raise ValueError("La línea de WhatsApp de la plataforma no está configurada.")
        return f"https://wa.me/{numero}?text={quote(texto)}"

    def texto_primer_mensaje(self) -> str:
        return f"Hola, quiero hacer una consulta a {self.nombre}. Código: {self.codigo_acceso}"

    def activar_bot(self) -> None:
        """Genera el código si no existe y deja el bot en estado Activo (CU07)."""
        if not self.onboarding_completo:
            raise ValueError("Complete el onboarding antes de activar el bot.")
        if not self.codigo_acceso:
            self.codigo_acceso = generar_codigo_unico()
        self.estado = EstadoComercio.ACTIVO

    def pausar_bot(self) -> None:
        self.estado = EstadoComercio.PAUSADO

    def esta_abierto(self, fecha_hora: datetime) -> bool:
        dia = fecha_hora.weekday()
        hora = fecha_hora.time()
        return any(h.dia_semana == dia and h.cubre(hora) for h in self.horarios)

    def zona_para(self, codigo_postal: int) -> "ZonaEnvio | None":
        for zona in self.zonas:
            if zona.contiene(codigo_postal):
                return zona
        return None

    def __repr__(self) -> str:
        return f"<Comercio {self.id_comercio} {self.nombre!r}>"


def generar_codigo_unico(intentos: int = 20) -> str:
    for _ in range(intentos):
        codigo = generar_codigo()
        if not db.session.query(Comercio.id_comercio).filter_by(codigo_acceso=codigo).first():
            return codigo
    raise RuntimeError("No fue posible generar un código de acceso único.")


def generar_codigo() -> str:
    """Seis caracteres con al menos una letra y un dígito, para no confundirse con palabras."""
    while True:
        codigo = "".join(secrets.choice(ALFABETO_CODIGO) for _ in range(LARGO_CODIGO))
        if any(c.isdigit() for c in codigo) and any(c.isalpha() for c in codigo):
            return codigo


class Usuario(db.Model):
    __tablename__ = "usuario"

    id_usuario: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_comercio: Mapped[int] = mapped_column(
        ForeignKey("comercio.id_comercio", ondelete="CASCADE"), unique=True, nullable=False
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    hash_contrasena: Mapped[str] = mapped_column(Text, nullable=False)
    ultimo_ingreso: Mapped[datetime | None] = mapped_column(DateTime)
    intentos_fallidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime)

    comercio: Mapped[Comercio] = relationship(back_populates="usuario")

    def establecer_contrasena(self, contrasena: str) -> None:
        self.hash_contrasena = generate_password_hash(contrasena)

    def autenticar(self, email: str, contrasena: str) -> bool:
        return self.email == normalizar_email(email) and check_password_hash(self.hash_contrasena, contrasena)


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


class ZonaEnvio(db.Model):
    __tablename__ = "zona_envio"

    id_zona: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_comercio: Mapped[int] = mapped_column(
        ForeignKey("comercio.id_comercio", ondelete="CASCADE"), nullable=False, index=True
    )
    cp_desde: Mapped[int] = mapped_column(Integer, nullable=False)
    cp_hasta: Mapped[int] = mapped_column(Integer, nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    plazo_min_dias: Mapped[int] = mapped_column(Integer, nullable=False)
    plazo_max_dias: Mapped[int] = mapped_column(Integer, nullable=False)

    comercio: Mapped[Comercio] = relationship(back_populates="zonas")

    def contiene(self, cp: int) -> bool:
        return self.cp_desde <= cp <= self.cp_hasta

    def se_superpone(self, desde: int, hasta: int) -> bool:
        return not (hasta < self.cp_desde or desde > self.cp_hasta)

    @property
    def rango_texto(self) -> str:
        if self.cp_desde == self.cp_hasta:
            return str(self.cp_desde)
        return f"{self.cp_desde} a {self.cp_hasta}"

    @property
    def plazo_texto(self) -> str:
        return texto_plazo(self.plazo_min_dias, self.plazo_max_dias)


def texto_plazo(minimo: int, maximo: int) -> str:
    if minimo == maximo:
        return f"{minimo} día hábil" if minimo == 1 else f"{minimo} días hábiles"
    return f"{minimo} a {maximo} días hábiles"


class MedioPago(db.Model):
    __tablename__ = "medio_pago"

    id_medio_pago: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_comercio: Mapped[int] = mapped_column(
        ForeignKey("comercio.id_comercio", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre: Mapped[str] = mapped_column(Text, nullable=False)
    detalle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    comercio: Mapped[Comercio] = relationship(back_populates="medios_pago")

    @property
    def texto(self) -> str:
        return f"{self.nombre} ({self.detalle})" if self.detalle else self.nombre


class HorarioAtencion(db.Model):
    __tablename__ = "horario_atencion"

    id_horario: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_comercio: Mapped[int] = mapped_column(
        ForeignKey("comercio.id_comercio", ondelete="CASCADE"), nullable=False, index=True
    )
    dia_semana: Mapped[int] = mapped_column(Integer, nullable=False)  # 0 = lunes ... 6 = domingo
    hora_apertura: Mapped[str] = mapped_column(String(5), nullable=False)  # "HH:MM"
    hora_cierre: Mapped[str] = mapped_column(String(5), nullable=False)

    comercio: Mapped[Comercio] = relationship(back_populates="horarios")

    @property
    def apertura(self) -> time:
        return time.fromisoformat(self.hora_apertura)

    @property
    def cierre(self) -> time:
        return time.fromisoformat(self.hora_cierre)

    def cubre(self, hora: time) -> bool:
        return self.apertura <= hora < self.cierre


# ---------------------------------------------------------------------------
# Atención por WhatsApp
# ---------------------------------------------------------------------------

class Comprador(db.Model):
    __tablename__ = "comprador"

    id_comprador: Mapped[int] = mapped_column(Integer, primary_key=True)
    telefono: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    nombre: Mapped[str | None] = mapped_column(Text)
    fecha_primer_contacto: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    conversaciones: Mapped[list["Conversacion"]] = relationship(back_populates="comprador")

    @property
    def es_de_prueba(self) -> bool:
        """Números del simulador y de la demo (549351 0XXXXXX no es un número asignable)."""
        return self.telefono.startswith("5493510")

    @property
    def telefono_legible(self) -> str:
        t = self.telefono
        if t.startswith("549") and len(t) == 13:
            return f"+54 9 {t[3:6]} {t[6:9]}-{t[9:]}"
        return f"+{t}" if t.isdigit() else t

    @property
    def enlace_whatsapp(self) -> str:
        return f"https://wa.me/{self.telefono}"


class Conversacion(db.Model):
    __tablename__ = "conversacion"

    id_conversacion: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_comercio: Mapped[int] = mapped_column(
        ForeignKey("comercio.id_comercio", ondelete="CASCADE"), nullable=False, index=True
    )
    id_comprador: Mapped[int] = mapped_column(
        ForeignKey("comprador.id_comprador", ondelete="CASCADE"), nullable=False, index=True
    )
    estado: Mapped[EstadoConversacion] = mapped_column(
        _enum(EstadoConversacion), nullable=False, default=EstadoConversacion.ACTIVA
    )
    fecha_inicio: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ultima_actividad: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    intentos_cp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    comercio: Mapped[Comercio] = relationship(back_populates="conversaciones")
    comprador: Mapped[Comprador] = relationship(back_populates="conversaciones")
    mensajes: Mapped[list["Mensaje"]] = relationship(
        back_populates="conversacion", cascade="all, delete-orphan",
        order_by="(Mensaje.fecha_hora, Mensaje.id_mensaje)",
    )
    consultas: Mapped[list["Consulta"]] = relationship(
        back_populates="conversacion", cascade="all, delete-orphan", order_by="Consulta.fecha_hora"
    )

    def procesar_mensaje(self, texto: str, palabras: list["PalabraClave"], fecha_hora: datetime,
                         max_intentos_cp: int = 2, primer_contacto: bool = False):
        """Aplica el motor de estados al mensaje y actualiza el estado de la conversación.

        Devuelve el resultado del motor (respuestas y consulta a registrar). La
        persistencia de mensajes y consultas queda a cargo del servicio del bot.
        """
        from .bot.motor import MotorConversacional, DatosComercio

        motor = MotorConversacional(max_intentos_cp=max_intentos_cp)
        resultado = motor.procesar(
            datos=DatosComercio.desde_comercio(self.comercio),
            estado=self.estado,
            intentos_cp=self.intentos_cp,
            texto=texto,
            palabras=[(p.termino, p.tema) for p in palabras],
            ahora=fecha_hora,
            primer_contacto=primer_contacto,
        )
        self.cambiar_estado(resultado.estado)
        self.intentos_cp = resultado.intentos_cp
        return resultado

    def cambiar_estado(self, estado: EstadoConversacion) -> None:
        self.estado = estado


class Mensaje(db.Model):
    __tablename__ = "mensaje"

    id_mensaje: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_conversacion: Mapped[int] = mapped_column(
        ForeignKey("conversacion.id_conversacion", ondelete="CASCADE"), nullable=False, index=True
    )
    texto: Mapped[str] = mapped_column(Text, nullable=False)
    direccion: Mapped[DireccionMensaje] = mapped_column(_enum(DireccionMensaje), nullable=False)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    id_externo: Mapped[str | None] = mapped_column(Text, unique=True)

    conversacion: Mapped[Conversacion] = relationship(back_populates="mensajes")

    @property
    def es_entrante(self) -> bool:
        return self.direccion == DireccionMensaje.ENTRANTE


class Consulta(db.Model):
    __tablename__ = "consulta"

    id_consulta: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_conversacion: Mapped[int] = mapped_column(
        ForeignKey("conversacion.id_conversacion", ondelete="CASCADE"), nullable=False, index=True
    )
    tema: Mapped[TemaConsulta] = mapped_column(_enum(TemaConsulta), nullable=False)
    resultado: Mapped[ResultadoConsulta] = mapped_column(_enum(ResultadoConsulta), nullable=False)
    codigo_postal: Mapped[int | None] = mapped_column(Integer)
    fecha_hora: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    atendida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fecha_atencion: Mapped[datetime | None] = mapped_column(DateTime)

    conversacion: Mapped[Conversacion] = relationship(back_populates="consultas")

    @property
    def pendiente(self) -> bool:
        return self.resultado == ResultadoConsulta.DERIVADA and not self.atendida

    @property
    def estado_atencion(self) -> str:
        if self.resultado == ResultadoConsulta.RESUELTA:
            return "No requiere"
        return "Atendida" if self.atendida else "Pendiente"

    def marcar_atendida(self, fecha_hora: datetime) -> None:
        """Registra la atención humana y devuelve la conversación al bot (CU13)."""
        if self.resultado != ResultadoConsulta.DERIVADA:
            raise ValueError("Solo las consultas derivadas se marcan como atendidas.")
        self.atendida = True
        self.fecha_atencion = fecha_hora
        if self.conversacion.estado == EstadoConversacion.DERIVADA:
            self.conversacion.cambiar_estado(EstadoConversacion.ACTIVA)
            self.conversacion.intentos_cp = 0


class PalabraClave(db.Model):
    __tablename__ = "palabra_clave"

    id_palabra: Mapped[int] = mapped_column(Integer, primary_key=True)
    termino: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    tema: Mapped[TemaConsulta] = mapped_column(_enum(TemaConsulta), nullable=False)

    def coincide(self, texto: str) -> bool:
        from .bot.normalizacion import contiene_termino, normalizar

        return contiene_termino(normalizar(texto), self.termino)
