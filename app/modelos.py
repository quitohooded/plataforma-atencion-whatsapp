"""Modelo de dominio (diagrama de clases, Figura 6) y su mapeo a SQLite (DER, Figura 7).

Cada clase del diagrama se corresponde con una tabla del DER. Los nombres de
tablas y columnas respetan el DER; los métodos respetan las operaciones del
diagrama de clases, escritos en snake_case según la convención de Python
(por ejemplo, ``estaAbierto`` se implementa como ``esta_abierto``).

Agregados respecto del DER de la Entrega 3 (documentados en docs/arquitectura.md):
- usuario.intentos_fallidos y usuario.bloqueado_hasta: bloqueo de ingreso (CU02).
- comercio.paso_onboarding: retomar el onboarding en el paso pendiente (CU03).
- comercio.envio_gratis_desde y zona_envio.costo: costo del envío por zona (CU04, CU09).
- comercio.enlace_catalogo: enlace al catálogo que el bot comparte.
- conversacion.intentos_cp: contar códigos postales inválidos (CU09).
- conversacion.intentos_sin_entender, ultimo_tema y ultimo_cp: contexto de la conversación
  (aclaraciones antes de dar por perdida una conversación y preguntas encadenadas, como
  «¿y cuánto sale?» después de una respuesta de envío).
- mensaje.id_externo: identificador de WhatsApp para descartar mensajes repetidos.
- mensaje.botones: opciones que acompañaron una respuesta (botones de WhatsApp).
- palabra_clave.peso: peso del término en la identificación del tema (CU08).
- tema de consulta: CONTACTO, PRODUCTOS, PEDIDOS, RECLAMOS y PAGOS_INFORMADOS distinguen lo
  que antes quedaba como «no reconocido», para que el comercio priorice los pendientes.
- respuesta_frecuente y consulta.id_respuesta: respuestas propias del comercio a preguntas
  frecuentes que no son envíos, pagos ni horarios (cambios, factura, retiro), con el tema
  RESPUESTA_PROPIA para medir su uso (CU15).
- tema SEGURIDAD y consulta.alerta: estafas y datos sensibles que el bot advierte (#6).
- consulta.fuera_de_horario: si llegó con el comercio cerrado, guardado al llegar (#11).
- conversacion.silenciada_hasta y conversacion.advertencias: pausa ante spam, insultos o
  ráfagas de mensajes (#7).
- bloqueo: números que el comercio bloqueó (#7).
- comercio.avisos_correo y comercio.ultimo_aviso_correo: aviso por correo de consultas
  pendientes, con un máximo por intervalo (#8).
- usuario.recuperacion_enviada: último correo de recuperación de contraseña (#9).
"""

from __future__ import annotations

import enum
import json
import secrets
from datetime import date, datetime, time
from urllib.parse import quote

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
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
    CONTACTO = "CONTACTO"
    PRODUCTOS = "PRODUCTOS"
    PEDIDOS = "PEDIDOS"
    RECLAMOS = "RECLAMOS"
    PAGOS_INFORMADOS = "PAGOS_INFORMADOS"
    RESPUESTA_PROPIA = "RESPUESTA_PROPIA"
    SEGURIDAD = "SEGURIDAD"
    DATOS_PERSONALES = "DATOS_PERSONALES"
    NO_RECONOCIDO = "NO_RECONOCIDO"

    @property
    def etiqueta(self) -> str:
        return {
            "ENVIO": "Envíos",
            "MEDIOS_PAGO": "Medios de pago",
            "HORARIOS": "Horarios",
            "CONTACTO": "Contacto",
            "PRODUCTOS": "Productos y precios",
            "PEDIDOS": "Pedidos realizados",
            "RECLAMOS": "Reclamos",
            "PAGOS_INFORMADOS": "Pagos informados",
            "RESPUESTA_PROPIA": "Respuestas del comercio",
            "SEGURIDAD": "Alertas de seguridad",
            "DATOS_PERSONALES": "Datos personales",
            "NO_RECONOCIDO": "Otras consultas",
        }[self.value]

    @property
    def prioritario(self) -> bool:
        """Temas que el comercio debería atender primero cuando quedan pendientes."""
        return self in (
            TemaConsulta.SEGURIDAD,
            TemaConsulta.RECLAMOS,
            TemaConsulta.PAGOS_INFORMADOS,
            TemaConsulta.DATOS_PERSONALES,
        )


# Alertas de seguridad (consulta.alerta): qué advirtió el bot.
ALERTAS = {
    "TARJETA": "Datos de tarjeta (ocultos)",
    "CLAVE": "Clave o código compartido (oculto)",
    "CODIGO": "Pedido de un código de verificación",
    "SUPLANTACION": "Alguien usa el nombre del comercio",
    "DEVOLUCION": "Pedido de devolución a una cuenta",
    "ALIAS": "Alias o CBU que no es del comercio",
    "TELEFONO": "Teléfono que no es del comercio",
    "DATOS": "Pedido de datos de otros clientes",
}
# Qué hizo el bot y qué conviene hacer, para el detalle de la consulta en el panel.
ALERTAS_QUE_HACER = {
    "TARJETA": "El comprador envió datos de su tarjeta: el bot le advirtió y no los guardó. Escríbale para ofrecerle "
    "un medio de pago seguro, como un link de pago.",
    "CLAVE": "El comprador compartió una clave o un código: el bot le advirtió y no lo guardó. Si corresponde, "
    "sugiérale cambiarla.",
    "CODIGO": "Alguien pidió un código de verificación, una maniobra habitual para robar cuentas. El bot no lo pasó y "
    "advirtió. No hace falta responder.",
    "SUPLANTACION": "Un comprador avisa que alguien se hizo pasar por su comercio. Conviene avisar en sus redes cuál "
    "es su único número.",
    "DEVOLUCION": "Pidieron una devolución a una cuenta. Antes de devolver, verifique en su cuenta que el pago se "
    "acreditó y devuelva solo a la cuenta desde la que pagaron.",
    "ALIAS": "Un comprador consultó por un alias o CBU que no es suyo y el bot le avisó que no transfiera. Puede ser "
    "un intento de estafa con su nombre.",
    "TELEFONO": "Un comprador consultó por un teléfono que no es suyo y el bot le pasó su número oficial. Puede ser "
    "un intento de estafa con su nombre.",
    "DATOS": "Alguien pidió datos de otros clientes o intentó cambiar el funcionamiento del bot. El bot se negó. No "
    "hace falta responder.",
}


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
    # Monto de compra desde el que el envío es gratis (en pesos). None: no hay envío gratis.
    envio_gratis_desde: Mapped[int | None] = mapped_column(Integer)
    enlace_catalogo: Mapped[str | None] = mapped_column(Text)
    # Aviso por correo de consultas pendientes (opcional) y último envío, para no saturar.
    avisos_correo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ultimo_aviso_correo: Mapped[datetime | None] = mapped_column(DateTime)

    usuario: Mapped[Usuario] = relationship(back_populates="comercio", uselist=False)
    zonas: Mapped[list[ZonaEnvio]] = relationship(
        back_populates="comercio", cascade="all, delete-orphan", order_by="ZonaEnvio.cp_desde"
    )
    medios_pago: Mapped[list[MedioPago]] = relationship(
        back_populates="comercio", cascade="all, delete-orphan", order_by="MedioPago.id_medio_pago"
    )
    horarios: Mapped[list[HorarioAtencion]] = relationship(
        back_populates="comercio",
        cascade="all, delete-orphan",
        order_by="(HorarioAtencion.dia_semana, HorarioAtencion.hora_apertura)",
    )
    respuestas_frecuentes: Mapped[list[RespuestaFrecuente]] = relationship(
        back_populates="comercio", cascade="all, delete-orphan", order_by="RespuestaFrecuente.id_respuesta"
    )
    conversaciones: Mapped[list[Conversacion]] = relationship(back_populates="comercio", cascade="all, delete-orphan")
    bloqueos: Mapped[list[Bloqueo]] = relationship(back_populates="comercio", cascade="all, delete-orphan")

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
    def medios_activos(self) -> list[MedioPago]:
        return [m for m in self.medios_pago if m.activo]

    @property
    def respuestas_activas(self) -> list[RespuestaFrecuente]:
        return [r for r in self.respuestas_frecuentes if r.activa]

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

    def zona_para(self, codigo_postal: int) -> ZonaEnvio | None:
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
    # Último correo de recuperación de contraseña enviado (para limitar los reenvíos).
    recuperacion_enviada: Mapped[datetime | None] = mapped_column(DateTime)
    # Cuándo aceptó los términos de uso y la política de privacidad al registrarse.
    terminos_aceptados: Mapped[datetime | None] = mapped_column(DateTime)

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
    # Costo del envío en pesos. None: no se informa; 0: envío gratis a esa zona.
    costo: Mapped[int | None] = mapped_column(Integer)

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

    @property
    def costo_texto(self) -> str:
        return texto_costo(self.costo)


def texto_plazo(minimo: int, maximo: int) -> str:
    if minimo == maximo:
        if minimo == 0:
            return "el mismo día"
        return f"{minimo} día hábil" if minimo == 1 else f"{minimo} días hábiles"
    if minimo == 0:
        return f"en el día o hasta {maximo} {'día hábil' if maximo == 1 else 'días hábiles'}"
    return f"{minimo} a {maximo} días hábiles"


def formato_pesos(valor: int) -> str:
    """Monto en pesos con separador de miles argentino: 7900 → «$7.900»."""
    return "$" + f"{int(valor):,}".replace(",", ".")


def texto_costo(costo: int | None) -> str:
    if costo is None:
        return "Sin informar"
    return "Gratis" if costo == 0 else formato_pesos(costo)


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


class RespuestaFrecuente(db.Model):
    """Respuesta propia del comercio a una pregunta frecuente (CU15).

    El bot la envía tal como la escribió el comercio cuando el mensaje del comprador
    contiene alguna de sus palabras clave. No hay flujos ni pasos: una pregunta, una
    respuesta fija.
    """

    __tablename__ = "respuesta_frecuente"

    id_respuesta: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_comercio: Mapped[int] = mapped_column(
        ForeignKey("comercio.id_comercio", ondelete="CASCADE"), nullable=False, index=True
    )
    # Plantilla de la que surgió («cambios», «factura»...); None si la escribió desde cero.
    plantilla: Mapped[str | None] = mapped_column(String(20))
    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    # Frases normalizadas separadas por comas: «cambio, cambios, politica de cambios».
    palabras_clave: Mapped[str] = mapped_column(Text, nullable=False)
    respuesta: Mapped[str] = mapped_column(Text, nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fecha_alta: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    comercio: Mapped[Comercio] = relationship(back_populates="respuestas_frecuentes")

    @property
    def lista_palabras(self) -> list[str]:
        return [p.strip() for p in (self.palabras_clave or "").split(",") if p.strip()]

    @property
    def clave(self) -> str:
        """Identificador estable dentro del comercio: la plantilla o «r» y el número."""
        return self.plantilla or f"r{self.id_respuesta}"


# ---------------------------------------------------------------------------
# Atención por WhatsApp
# ---------------------------------------------------------------------------


class Comprador(db.Model):
    __tablename__ = "comprador"

    id_comprador: Mapped[int] = mapped_column(Integer, primary_key=True)
    telefono: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    nombre: Mapped[str | None] = mapped_column(Text)
    fecha_primer_contacto: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    conversaciones: Mapped[list[Conversacion]] = relationship(back_populates="comprador")

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

    def enlace_whatsapp_con(self, texto: str) -> str:
        """Chat de WhatsApp con el comprador y un mensaje inicial sugerido (#8)."""
        return f"https://wa.me/{self.telefono}?text={quote(texto)}"


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
    # Mensajes seguidos que el bot no entendió (o, con la consulta derivada, mensajes que
    # recibieron el recordatorio de que una persona va a responder).
    intentos_sin_entender: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_tema: Mapped[TemaConsulta | None] = mapped_column(_enum(TemaConsulta))
    ultimo_cp: Mapped[int | None] = mapped_column(Integer)
    # Pausa del bot con este comprador (spam, insultos repetidos o ráfaga de mensajes).
    silenciada_hasta: Mapped[datetime | None] = mapped_column(DateTime)
    advertencias: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    comercio: Mapped[Comercio] = relationship(back_populates="conversaciones")
    comprador: Mapped[Comprador] = relationship(back_populates="conversaciones")
    mensajes: Mapped[list[Mensaje]] = relationship(
        back_populates="conversacion",
        cascade="all, delete-orphan",
        order_by="(Mensaje.fecha_hora, Mensaje.id_mensaje)",
    )
    consultas: Mapped[list[Consulta]] = relationship(
        back_populates="conversacion", cascade="all, delete-orphan", order_by="Consulta.fecha_hora"
    )

    @property
    def consultas_pendientes(self) -> list[Consulta]:
        return [c for c in self.consultas if c.pendiente]

    def contexto(self):
        """Estado de la conversación que necesita el motor (sin acceso a la base)."""
        from .bot.contexto import ContextoConversacion

        return ContextoConversacion(
            estado=self.estado,
            intentos_cp=self.intentos_cp or 0,
            intentos_sin_entender=self.intentos_sin_entender or 0,
            ultimo_tema=self.ultimo_tema,
            ultimo_cp=self.ultimo_cp,
            temas_pendientes=frozenset(c.tema for c in self.consultas_pendientes),
            silenciada_hasta=self.silenciada_hasta,
            advertencias=self.advertencias or 0,
        )

    def aplicar_contexto(self, contexto) -> None:
        self.cambiar_estado(contexto.estado)
        self.intentos_cp = contexto.intentos_cp
        self.intentos_sin_entender = contexto.intentos_sin_entender
        self.ultimo_tema = contexto.ultimo_tema
        self.ultimo_cp = contexto.ultimo_cp
        self.silenciada_hasta = contexto.silenciada_hasta
        self.advertencias = contexto.advertencias

    def procesar_mensaje(
        self,
        texto: str,
        palabras: list[PalabraClave],
        fecha_hora: datetime,
        max_intentos_cp: int = 2,
        primer_contacto: bool = False,
        tipo: str = "text",
        rafaga: bool = False,
    ):
        """Aplica el motor de estados al mensaje y actualiza el estado de la conversación.

        Devuelve el resultado del motor (respuestas y consultas a registrar). La
        persistencia de mensajes y consultas queda a cargo del servicio del bot.
        """
        from .bot.motor import DatosComercio, MotorConversacional

        motor = MotorConversacional(max_intentos_cp=max_intentos_cp)
        resultado = motor.procesar(
            datos=DatosComercio.desde_comercio(self.comercio),
            contexto=self.contexto(),
            texto=texto,
            palabras=[(p.termino, p.tema, p.peso) for p in palabras],
            ahora=fecha_hora,
            primer_contacto=primer_contacto,
            tipo=tipo,
            rafaga=rafaga,
        )
        self.aplicar_contexto(resultado.contexto)
        return resultado

    def cambiar_estado(self, estado: EstadoConversacion) -> None:
        self.estado = estado


# Estados de entrega de WhatsApp (webhook «statuses»), de menor a mayor avance. «fallido» va al
# final porque puede llegar después de «enviado» y es el que el comercio necesita ver.
ESTADOS_ENVIO = {
    "enviado": "Enviado",
    "entregado": "Entregado",
    "leido": "Leído",
    "fallido": "No entregado",
}
ORDEN_ESTADOS_ENVIO = list(ESTADOS_ENVIO)


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
    # Opciones que acompañaron la respuesta, como JSON: [{"id": "...", "titulo": "..."}].
    botones: Mapped[str | None] = mapped_column(Text)
    # Estado de entrega que informa WhatsApp para las respuestas del bot (ver ESTADOS_ENVIO).
    # None: no pasó por WhatsApp (simulador o línea sin configurar).
    estado_envio: Mapped[str | None] = mapped_column(String(12))

    conversacion: Mapped[Conversacion] = relationship(back_populates="mensajes")

    def actualizar_estado_envio(self, estado: str) -> bool:
        """Aplica un estado de entrega de WhatsApp. Los estados llegan en cualquier orden, así que
        uno anterior no pisa a uno posterior («entregado» después de «leído»). Devuelve si cambió."""
        if estado not in ESTADOS_ENVIO:
            return False
        if self.estado_envio and ORDEN_ESTADOS_ENVIO.index(estado) <= ORDEN_ESTADOS_ENVIO.index(self.estado_envio):
            return False
        self.estado_envio = estado
        return True

    @property
    def no_entregado(self) -> bool:
        return self.estado_envio == "fallido"

    @property
    def etiqueta_estado_envio(self) -> str | None:
        return ESTADOS_ENVIO.get(self.estado_envio) if self.estado_envio else None

    @property
    def es_entrante(self) -> bool:
        return self.direccion == DireccionMensaje.ENTRANTE

    @property
    def lista_botones(self) -> list[dict]:
        if not self.botones:
            return []
        try:
            valor = json.loads(self.botones)
        except ValueError:
            return []
        return [b for b in valor if isinstance(b, dict) and b.get("titulo")] if isinstance(valor, list) else []


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
    # Respuesta propia con la que se resolvió (tema RESPUESTA_PROPIA).
    id_respuesta: Mapped[int | None] = mapped_column(
        ForeignKey("respuesta_frecuente.id_respuesta", ondelete="SET NULL"), index=True
    )
    # Alerta de seguridad que advirtió el bot (tema SEGURIDAD); ver ALERTAS.
    alerta: Mapped[str | None] = mapped_column(String(20))
    # Si llegó con el comercio cerrado, según el horario de ese momento. None: sin horarios cargados.
    fuera_de_horario: Mapped[bool | None] = mapped_column(Boolean)

    conversacion: Mapped[Conversacion] = relationship(back_populates="consultas")
    respuesta: Mapped[RespuestaFrecuente | None] = relationship()

    @property
    def etiqueta_alerta(self) -> str | None:
        return ALERTAS.get(self.alerta) if self.alerta else None

    @property
    def etiqueta_tema(self) -> str:
        """Tema para mostrar; en una respuesta propia, con su título («Respuestas del comercio: Factura»),
        y en una alerta, con lo que se advirtió."""
        if self.tema == TemaConsulta.RESPUESTA_PROPIA and self.respuesta is not None:
            return f"{self.tema.etiqueta}: {self.respuesta.titulo}"
        if self.etiqueta_alerta:
            return f"{self.tema.etiqueta}: {self.etiqueta_alerta}"
        return self.tema.etiqueta

    @property
    def pendiente(self) -> bool:
        return self.resultado == ResultadoConsulta.DERIVADA and not self.atendida

    @property
    def estado_atencion(self) -> str:
        if self.resultado == ResultadoConsulta.RESUELTA:
            return "No requiere"
        return "Atendida" if self.atendida else "Pendiente"

    def marcar_atendida(self, fecha_hora: datetime) -> None:
        """Registra la atención humana y devuelve la conversación al bot (CU13).

        Si la conversación tiene otra consulta derivada sin atender, sigue derivada.
        """
        if self.resultado != ResultadoConsulta.DERIVADA:
            raise ValueError("Solo las consultas derivadas se marcan como atendidas.")
        self.atendida = True
        self.fecha_atencion = fecha_hora
        conversacion = self.conversacion
        otras_pendientes = [c for c in conversacion.consultas if c is not self and c.pendiente]
        if conversacion.estado == EstadoConversacion.DERIVADA and not otras_pendientes:
            conversacion.cambiar_estado(EstadoConversacion.ACTIVA)
            conversacion.intentos_cp = 0
            conversacion.intentos_sin_entender = 0


class Bloqueo(db.Model):
    """Número bloqueado por un comercio (#7): el bot no le responde y no se registran consultas."""

    __tablename__ = "bloqueo"
    __table_args__ = (UniqueConstraint("id_comercio", "id_comprador", name="uq_bloqueo_comercio_comprador"),)

    id_bloqueo: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_comercio: Mapped[int] = mapped_column(
        ForeignKey("comercio.id_comercio", ondelete="CASCADE"), nullable=False, index=True
    )
    id_comprador: Mapped[int] = mapped_column(
        ForeignKey("comprador.id_comprador", ondelete="CASCADE"), nullable=False, index=True
    )
    motivo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fecha_alta: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    comercio: Mapped[Comercio] = relationship(back_populates="bloqueos")
    comprador: Mapped[Comprador] = relationship()


class PalabraClave(db.Model):
    __tablename__ = "palabra_clave"

    id_palabra: Mapped[int] = mapped_column(Integer, primary_key=True)
    termino: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    tema: Mapped[TemaConsulta] = mapped_column(_enum(TemaConsulta), nullable=False)
    peso: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    def coincide(self, texto: str) -> bool:
        from .bot.normalizacion import contiene_termino, normalizar

        return contiene_termino(normalizar(texto), self.termino)
