"""Motor de estados de la conversación (RF06) y resolución de las consultas (CU09 a CU12).

Estados de la conversación (enumeración EstadoConversacion):

    ACTIVA ──consulta de envío sin código postal──▶ ESPERANDO_CP
    ESPERANDO_CP ──código postal dentro de una zona──▶ ACTIVA (consulta resuelta)
    ESPERANDO_CP ──código inválido (1.er intento)──▶ ESPERANDO_CP
    ESPERANDO_CP ──código inválido (2.º intento) o zona no configurada──▶ DERIVADA
    ACTIVA ──pago u horario──▶ ACTIVA (consulta resuelta)
    ACTIVA ──tema no reconocido o sin datos cargados──▶ DERIVADA
    DERIVADA ──cualquier mensaje──▶ DERIVADA (se registra sin responder)
    DERIVADA ──el comercio marca la consulta como atendida──▶ ACTIVA
    cualquier estado ──inactividad prolongada──▶ CERRADA   (lo aplica el servicio)

El motor no accede a la base de datos: recibe el estado y devuelve el nuevo
estado, las respuestas y, si corresponde, la consulta a registrar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..modelos import EstadoConversacion, ResultadoConsulta, TemaConsulta
from . import respuestas
from .contexto import DatosComercio
from .intencion import detectar_tema, es_cortesia, es_saludo, opcion_menu
from .normalizacion import extraer_codigo_postal

__all__ = ["MotorConversacional", "DatosComercio", "ResultadoMotor", "ConsultaARegistrar"]


@dataclass
class ConsultaARegistrar:
    tema: TemaConsulta
    resultado: ResultadoConsulta
    codigo_postal: int | None = None


@dataclass
class ResultadoMotor:
    respuestas: list[str]
    estado: EstadoConversacion
    intentos_cp: int = 0
    consulta: ConsultaARegistrar | None = None
    tema_detectado: TemaConsulta | None = None
    coincidencias: dict = field(default_factory=dict)


class MotorConversacional:
    def __init__(self, max_intentos_cp: int = 2):
        self.max_intentos_cp = max_intentos_cp

    def procesar(
        self,
        datos: DatosComercio,
        estado: EstadoConversacion,
        intentos_cp: int,
        texto: str,
        palabras: list[tuple[str, TemaConsulta]],
        ahora: datetime,
        primer_contacto: bool = False,
    ) -> ResultadoMotor:
        # CU12, flujo alternativo: mientras la conversación está derivada, el
        # mensaje se registra sin respuesta automática.
        if estado == EstadoConversacion.DERIVADA:
            return ResultadoMotor([], EstadoConversacion.DERIVADA, intentos_cp)

        # CU08, paso 3: la conversación espera un dato y el mensaje va al caso en curso.
        if estado == EstadoConversacion.ESPERANDO_CP:
            return self._recibir_codigo_postal(datos, texto, intentos_cp)

        tema = opcion_menu(texto)
        coincidencias: dict = {}
        if tema is None:
            clasificacion = detectar_tema(texto, palabras)
            tema = clasificacion.tema
            coincidencias = clasificacion.coincidencias

        if tema == TemaConsulta.NO_RECONOCIDO:
            if es_cortesia(texto):
                return ResultadoMotor([respuestas.cortesia()], EstadoConversacion.ACTIVA)
            if primer_contacto or es_saludo(texto) or not texto.strip():
                return ResultadoMotor([respuestas.bienvenida(datos)], EstadoConversacion.ACTIVA)
            resultado = self._derivar(datos, TemaConsulta.NO_RECONOCIDO)
        elif tema == TemaConsulta.ENVIO:
            resultado = self._consulta_envio(datos, texto)
        elif tema == TemaConsulta.MEDIOS_PAGO:
            resultado = self._consulta_medios_pago(datos)
        else:
            resultado = self._consulta_horarios(datos, ahora)

        resultado.tema_detectado = tema
        resultado.coincidencias = coincidencias
        return resultado

    # --- CU09: Consultar plazo de envío -----------------------------------

    def _consulta_envio(self, datos: DatosComercio, texto: str) -> ResultadoMotor:
        if not datos.zonas:
            return self._derivar(datos, TemaConsulta.ENVIO)
        cp = extraer_codigo_postal(texto)
        if cp is not None:
            # Flujo alternativo: el código postal llega en el primer mensaje.
            return self._responder_plazo(datos, cp)
        return ResultadoMotor([respuestas.solicitar_codigo_postal()], EstadoConversacion.ESPERANDO_CP, 0)

    def _recibir_codigo_postal(self, datos: DatosComercio, texto: str, intentos: int) -> ResultadoMotor:
        cp = extraer_codigo_postal(texto)
        if cp is not None:
            return self._responder_plazo(datos, cp)
        intentos += 1
        if intentos >= self.max_intentos_cp:
            return self._derivar(datos, TemaConsulta.ENVIO, prefijo="No pude reconocer el código postal.")
        return ResultadoMotor([respuestas.codigo_postal_invalido()], EstadoConversacion.ESPERANDO_CP, intentos)

    def _responder_plazo(self, datos: DatosComercio, cp: int) -> ResultadoMotor:
        zona = datos.zona_para(cp)
        if zona is None:
            return self._derivar(datos, TemaConsulta.ENVIO, cp=cp, prefijo=respuestas.zona_no_configurada(cp))
        return ResultadoMotor(
            [respuestas.plazo_envio(cp, zona)],
            EstadoConversacion.ACTIVA,
            0,
            ConsultaARegistrar(TemaConsulta.ENVIO, ResultadoConsulta.RESUELTA, cp),
        )

    # --- CU10 y CU11 -------------------------------------------------------

    def _consulta_medios_pago(self, datos: DatosComercio) -> ResultadoMotor:
        if not datos.medios:
            return self._derivar(datos, TemaConsulta.MEDIOS_PAGO)
        return ResultadoMotor(
            [respuestas.medios_de_pago(datos)],
            EstadoConversacion.ACTIVA,
            0,
            ConsultaARegistrar(TemaConsulta.MEDIOS_PAGO, ResultadoConsulta.RESUELTA),
        )

    def _consulta_horarios(self, datos: DatosComercio, ahora: datetime) -> ResultadoMotor:
        if not datos.franjas:
            return self._derivar(datos, TemaConsulta.HORARIOS)
        return ResultadoMotor(
            [respuestas.horarios(datos, ahora)],
            EstadoConversacion.ACTIVA,
            0,
            ConsultaARegistrar(TemaConsulta.HORARIOS, ResultadoConsulta.RESUELTA),
        )

    # --- CU12: Derivar a atención humana ------------------------------------

    def _derivar(
        self, datos: DatosComercio, tema: TemaConsulta, cp: int | None = None, prefijo: str | None = None
    ) -> ResultadoMotor:
        texto = respuestas.derivacion(datos)
        if prefijo:
            texto = f"{prefijo} {texto}"
        return ResultadoMotor(
            [texto],
            EstadoConversacion.DERIVADA,
            0,
            ConsultaARegistrar(tema, ResultadoConsulta.DERIVADA, cp),
        )
