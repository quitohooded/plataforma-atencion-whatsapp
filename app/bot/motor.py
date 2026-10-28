"""Motor de estados de la conversación (RF06) y resolución de las consultas (CU08 a CU12).

Estados de la conversación (enumeración EstadoConversacion):

    ACTIVA ──consulta de envío sin código postal ni ciudad──▶ ESPERANDO_CP
    ESPERANDO_CP ──código postal o ciudad dentro de una zona──▶ ACTIVA (consulta resuelta)
    ESPERANDO_CP ──dato inválido (1.er intento)──▶ ESPERANDO_CP
    ESPERANDO_CP ──dato inválido (2.º intento) o zona no configurada──▶ DERIVADA
    ESPERANDO_CP ──otra consulta, «menú» o «cancelar»──▶ ACTIVA
    ACTIVA ──pago, horario, contacto o catálogo──▶ ACTIVA (consulta resuelta)
    ACTIVA ──producto, pedido, reclamo, pago informado, pedido de una persona,
             pregunta no reconocida o tema sin datos cargados──▶ DERIVADA
    DERIVADA ──consulta que el bot resuelve──▶ DERIVADA (la responde igual)
    DERIVADA ──otro mensaje──▶ DERIVADA (un recordatorio y después silencio)
    DERIVADA ──el comercio marca la consulta como atendida──▶ ACTIVA
    cualquier estado ──inactividad prolongada──▶ CERRADA   (lo aplica el servicio)

Un mensaje puede traer varias consultas («¿envían a Rosario? ¿y cómo se paga?»): se
responden todas y se registra una consulta por tema.

El motor no accede a la base de datos: recibe los datos del comercio y el contexto de la
conversación y devuelve las respuestas, el nuevo contexto y las consultas a registrar.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from ..modelos import EstadoConversacion, ResultadoConsulta, TemaConsulta
from . import respuestas
from .contexto import ContextoConversacion, DatosComercio
from .intencion import (
    CANCELAR,
    CATALOGO,
    CONTACTO,
    CONTAME,
    CORTESIA,
    DESPEDIDA,
    ENVIO,
    HORARIOS,
    IDENTIDAD,
    MEDIOS_PAGO,
    MENU,
    NO,
    NO_SE,
    PERSONA,
    PRIORIDAD,
    SALUDO,
    SI,
    TEMAS_DERIVABLES,
    TEMAS_RESOLUBLES,
    Interpretacion,
    interpretar,
    tema_de,
)
from .respuestas import DestinoEnvio, Respuesta

__all__ = ["MotorConversacional", "DatosComercio", "ContextoConversacion", "ResultadoMotor", "ConsultaARegistrar"]

E = EstadoConversacion

# Identificadores de los botones (llegan como texto cuando el comprador los toca).
BOTONES = {
    "op_envio": ENVIO,
    "op_pago": MEDIOS_PAGO,
    "op_horario": HORARIOS,
    "op_catalogo": CATALOGO,
    "op_persona": PERSONA,
    "op_menu": MENU,
}

# Etiqueta corta de cada tema en la traza de acciones («D:RECLAMOS»).
ETIQUETA_ACCION = {
    TemaConsulta.ENVIO: "ENVIO",
    TemaConsulta.MEDIOS_PAGO: "PAGO",
    TemaConsulta.HORARIOS: "HORARIO",
    TemaConsulta.CONTACTO: "CONTACTO",
    TemaConsulta.PRODUCTOS: "PRODUCTOS",
    TemaConsulta.PEDIDOS: "PEDIDOS",
    TemaConsulta.RECLAMOS: "RECLAMOS",
    TemaConsulta.PAGOS_INFORMADOS: "PAGOS",
    TemaConsulta.NO_RECONOCIDO: "OTRA",
}
# Orden de los motivos para elegir el texto de una derivación.
_ORDEN_MOTIVOS = [
    "PERSONA",
    "RECLAMOS",
    "PAGOS_INFORMADOS",
    "PEDIDOS",
    "PRODUCTOS",
    "ENVIO",
    "SIN_DATOS",
    "ARCHIVO",
    "NO_RECONOCIDO",
]
TIPOS_ARCHIVO = {"image", "document", "video"}
ACCIONES_RESUELTAS = {"ENVIO", "PAGO", "HORARIO", "CONTACTO", "CATALOGO"}
# Mensajes seguidos sin entender: al tercero el bot deja de responder.
MAX_SIN_ENTENDER = 3


@dataclass
class ConsultaARegistrar:
    tema: TemaConsulta
    resultado: ResultadoConsulta
    codigo_postal: int | None = None


@dataclass
class _Derivacion:
    motivo: str
    tema: TemaConsulta
    codigo_postal: int | None = None
    prefijo: str | None = None


@dataclass
class ResultadoMotor:
    respuestas: list[Respuesta]
    contexto: ContextoConversacion
    consultas: list[ConsultaARegistrar] = field(default_factory=list)
    acciones: list[str] = field(default_factory=list)
    interpretacion: Interpretacion | None = None

    @property
    def estado(self) -> EstadoConversacion:
        return self.contexto.estado

    @property
    def intentos_cp(self) -> int:
        return self.contexto.intentos_cp

    @property
    def consulta(self) -> ConsultaARegistrar | None:
        return self.consultas[0] if self.consultas else None

    @property
    def tema_detectado(self) -> TemaConsulta | None:
        return self.consultas[0].tema if self.consultas else None

    @property
    def textos(self) -> list[str]:
        return [r.texto for r in self.respuestas]

    @property
    def derivada(self) -> bool:
        return any(c.resultado == ResultadoConsulta.DERIVADA for c in self.consultas)


@dataclass
class _Plan:
    """Lo que el motor decide hacer con un mensaje, antes de armar el resultado."""

    respuestas: list[Respuesta] = field(default_factory=list)
    acciones: list[str] = field(default_factory=list)
    resueltas: list[ConsultaARegistrar] = field(default_factory=list)
    derivaciones: list[_Derivacion] = field(default_factory=list)
    pide_cp: bool = False
    silencio: bool = False
    # None: el contador vuelve a cero.
    intentos_cp: int | None = None
    intentos_sin_entender: int | None = None
    ultimo_tema: TemaConsulta | None = None
    ultimo_cp: int | None = None
    aviso_archivo: bool = False

    def responder(self, respuesta: Respuesta, accion: str) -> None:
        self.respuestas.append(respuesta)
        self.acciones.append(accion)

    def resolver(self, tema: TemaConsulta, cp: int | None = None) -> None:
        self.resueltas.append(ConsultaARegistrar(tema, ResultadoConsulta.RESUELTA, cp))
        self.ultimo_tema = tema
        if cp:
            self.ultimo_cp = cp

    def derivar(self, motivo: str, tema: TemaConsulta, cp: int | None = None, prefijo: str | None = None) -> None:
        self.derivaciones.append(_Derivacion(motivo, tema, cp, prefijo))


class MotorConversacional:
    def __init__(self, max_intentos_cp: int = 2):
        self.max_intentos_cp = max_intentos_cp

    # ------------------------------------------------------------------
    # Punto de entrada
    # ------------------------------------------------------------------

    def procesar(
        self,
        datos: DatosComercio,
        contexto: ContextoConversacion,
        texto: str,
        palabras: list,
        ahora: datetime,
        primer_contacto: bool = False,
        tipo: str = "text",
    ) -> ResultadoMotor:
        ctx = contexto
        texto = (texto or "").strip()
        tipo = tipo or "text"
        plan = _Plan()

        if tipo == "reaction":
            # Una reacción (👍 sobre un mensaje) no pide respuesta.
            plan.silencio = True
            plan.intentos_sin_entender = ctx.intentos_sin_entender
            return self._armar(plan, datos, ahora, ctx, None)
        if tipo != "text" and not texto:
            self._archivo_sin_texto(plan, datos, ctx, tipo)
            return self._armar(plan, datos, ahora, ctx, None)

        interp = interpretar(
            texto,
            palabras,
            esperando_cp=ctx.estado == E.ESPERANDO_CP,
            ultimo_tema=ctx.ultimo_tema.value if ctx.ultimo_tema else None,
        )
        forzada = BOTONES.get(texto) or interp.opcion_menu
        if forzada:
            interp = replace(
                interp,
                temas=[forzada] if forzada in TEMAS_RESOLUBLES else [],
                control=[] if forzada in TEMAS_RESOLUBLES else [forzada],
                pide_costo=False,
                pregunta_sin_tema=False,
            )
        if not interp.temas and SI in interp.control and ctx.intentos_sin_entender >= 2:
            # «Sí» a «¿Querés que le pase tu consulta a una persona del equipo?».
            interp = replace(interp, control=[PERSONA])
        plan.aviso_archivo = tipo in TIPOS_ARCHIVO

        esperando = ctx.estado == E.ESPERANDO_CP
        if ctx.estado == E.DERIVADA:
            self._en_derivacion(plan, datos, ahora, ctx, interp)
        elif esperando and NO_SE in interp.control and not interp.tiene_ubicacion:
            # «No sé mi código postal»: cuenta como intento y se sugiere escribir la ciudad.
            self._dato_invalido(plan, ctx, no_sabe=True)
        elif interp.temas:
            self._atender_temas(plan, datos, ahora, ctx, interp)
            # Otra pregunta del mismo mensaje que el bot no reconoce: la ve una persona.
            if interp.pregunta_sin_tema and not plan.derivaciones and PERSONA not in interp.control:
                plan.derivar("NO_RECONOCIDO", TemaConsulta.NO_RECONOCIDO)
        elif interp.control:
            self._atender_control(plan, datos, ctx, interp, primer_contacto)
        elif interp.solo_simbolos:
            plan.responder(respuestas.cortesia("ok"), "CORTESIA")
        elif esperando:
            self._dato_invalido(plan, ctx)
        elif primer_contacto and not interp.contenido:
            plan.responder(respuestas.bienvenida(datos), "BIENVENIDA")
        elif self._es_consulta_real(interp):
            plan.derivar("NO_RECONOCIDO", TemaConsulta.NO_RECONOCIDO)
        else:
            self._no_entendido(plan, ctx)

        return self._armar(plan, datos, ahora, ctx, interp, primer_contacto=primer_contacto)

    # ------------------------------------------------------------------
    # Temas de consulta
    # ------------------------------------------------------------------

    def _atender_temas(self, plan: _Plan, datos, ahora, ctx, interp: Interpretacion) -> None:
        resolubles = [t for t in interp.temas if t in TEMAS_RESOLUBLES]
        derivables = sorted((t for t in interp.temas if t in TEMAS_DERIVABLES), key=PRIORIDAD.index)

        if PERSONA in interp.control:
            # Pidió hablar con una persona sobre un tema: se respeta, sin respuesta automática.
            tema = tema_de((derivables or resolubles)[0])
            plan.derivar("PERSONA", tema, interp.codigos_postales[0] if interp.codigos_postales else None)
            return

        for tema in resolubles:
            if tema == ENVIO:
                self._envio(plan, datos, ctx, interp)
            elif tema == MEDIOS_PAGO:
                if datos.medios:
                    plan.responder(respuestas.medios_de_pago(datos, interp.medios_consultados), "PAGO")
                    plan.resolver(TemaConsulta.MEDIOS_PAGO)
                else:
                    plan.derivar("SIN_DATOS", TemaConsulta.MEDIOS_PAGO)
            elif tema == HORARIOS:
                if datos.franjas:
                    plan.responder(respuestas.horarios(datos, ahora, interp.dias_consultados), "HORARIO")
                    plan.resolver(TemaConsulta.HORARIOS)
                else:
                    plan.derivar("SIN_DATOS", TemaConsulta.HORARIOS)
            elif tema == CONTACTO:
                plan.responder(respuestas.contacto(datos), "CONTACTO")
                plan.resolver(TemaConsulta.CONTACTO)
            elif tema == CATALOGO:
                if datos.enlace_catalogo:
                    plan.responder(respuestas.catalogo(datos), "CATALOGO")
                    plan.resolver(TemaConsulta.PRODUCTOS)
                else:
                    plan.derivar("PRODUCTOS", TemaConsulta.PRODUCTOS)

        for tema in derivables:
            plan.derivar(tema, tema_de(tema))

        if IDENTIDAD in interp.control:
            plan.responder(respuestas.identidad(datos), "IDENTIDAD")

    def _envio(self, plan: _Plan, datos: DatosComercio, ctx: ContextoConversacion, interp: Interpretacion) -> None:
        """CU09: plazo (y costo) de envío para los códigos postales o localidades del mensaje."""
        if not datos.zonas:
            plan.derivar("SIN_DATOS", TemaConsulta.ENVIO)
            return

        destinos = [DestinoEnvio(cp, datos.zona_para(cp)) for cp in interp.codigos_postales]
        ambiguas = []
        for encontrada in interp.localidades:
            if encontrada.ambigua:
                ambiguas.append(encontrada.localidad)
                continue
            loc = encontrada.localidad
            if any(d.cp == loc.cp for d in destinos):
                continue
            if loc.es_provincia:
                destinos.append(DestinoEnvio(loc.cp, datos.zona_para(loc.cp), loc.provincia, loc.nombre))
            else:
                destinos.append(DestinoEnvio(loc.cp, datos.zona_para(loc.cp), loc.nombre))

        if not destinos and not ambiguas:
            if ctx.ultimo_cp and ctx.ultimo_tema == TemaConsulta.ENVIO and interp.pide_costo:
                # «¿Y cuánto sale?» después de responder el plazo: se usa el último código postal.
                destino = DestinoEnvio(ctx.ultimo_cp, datos.zona_para(ctx.ultimo_cp))
                if destino.zona and destino.zona.costo is not None:
                    plan.responder(respuestas.costo_envio(destino, datos), "ENVIO")
                    plan.resolver(TemaConsulta.ENVIO, destino.cp)
                    return
                destinos = [destino]
            elif datos.zona_nacional:
                zona = datos.zona_nacional
                plan.responder(respuestas.envio_nacional(zona, datos), "ENVIO")
                if interp.pide_costo and zona.costo is None:
                    plan.derivar("ENVIO", TemaConsulta.ENVIO, prefijo=respuestas.costo_no_cargado())
                else:
                    plan.resolver(TemaConsulta.ENVIO)
                return
            else:
                plan.responder(respuestas.solicitar_codigo_postal(datos, interp.pide_costo), "ENVIO?")
                self._esperar_cp(plan, ctx)
                return

        if ambiguas and not destinos:
            ambigua = ambiguas[0]
            plan.responder(respuestas.localidad_ambigua(ambigua.nombre, ambigua.opciones), "ENVIO?")
            self._esperar_cp(plan, ctx, contar=False)
            return

        cubiertos = [d for d in destinos if d.zona]
        sin_zona = [d for d in destinos if not d.zona]
        if cubiertos:
            plan.responder(respuestas.plazo_envio(cubiertos, datos), "ENVIO")
            if interp.pide_costo and any(d.zona.costo is None for d in cubiertos):
                plan.derivar("ENVIO", TemaConsulta.ENVIO, cubiertos[0].cp, respuestas.costo_no_cargado())
            else:
                plan.resolver(TemaConsulta.ENVIO, cubiertos[0].cp)
        if sin_zona:
            destino = sin_zona[0]
            plan.derivar("ENVIO", TemaConsulta.ENVIO, destino.cp, respuestas.zona_no_configurada(destino))

    @staticmethod
    def _esperar_cp(plan: _Plan, ctx: ContextoConversacion, contar: bool = False) -> None:
        plan.pide_cp = True
        plan.ultimo_tema = TemaConsulta.ENVIO
        if ctx.estado == E.ESPERANDO_CP:
            plan.intentos_cp = ctx.intentos_cp + (1 if contar else 0)

    # ------------------------------------------------------------------
    # Intenciones de control
    # ------------------------------------------------------------------

    def _atender_control(self, plan: _Plan, datos, ctx, interp: Interpretacion, primer_contacto: bool) -> None:
        control = interp.control
        esperando = ctx.estado == E.ESPERANDO_CP

        if PERSONA in control:
            plan.derivar("PERSONA", TemaConsulta.ENVIO if esperando else TemaConsulta.NO_RECONOCIDO)
        elif IDENTIDAD in control:
            plan.responder(respuestas.identidad(datos), "IDENTIDAD")
        elif MENU in control or (SALUDO in control and (primer_contacto or CONTAME in control or esperando)):
            plan.responder(respuestas.bienvenida(datos), "BIENVENIDA")
        elif esperando and (CANCELAR in control or NO in control):
            plan.responder(respuestas.cancelado(), "CANCELAR")
        elif esperando and NO_SE in control:
            self._dato_invalido(plan, ctx, no_sabe=True)
        elif esperando and SI in control:
            plan.responder(respuestas.codigo_postal_invalido(), "ENVIO?")
            self._esperar_cp(plan, ctx)
        elif CONTAME in control or SI in control:
            plan.responder(respuestas.contame(), "CONTAME")
        elif DESPEDIDA in control:
            plan.responder(respuestas.cortesia("despedida"), "CORTESIA")
        elif NO in control or CANCELAR in control:
            plan.responder(respuestas.cortesia("no"), "CORTESIA")
        elif CORTESIA in control:
            plan.responder(respuestas.cortesia("gracias" if "gracias" in interp.tokens else "ok"), "CORTESIA")
        elif SALUDO in control:
            plan.responder(respuestas.bienvenida(datos), "BIENVENIDA")
        else:
            # «No sé» fuera de contexto: no hay nada que responder.
            self._no_entendido(plan, ctx)

    # ------------------------------------------------------------------
    # Mensajes que el bot no entiende
    # ------------------------------------------------------------------

    @staticmethod
    def _es_consulta_real(interp: Interpretacion) -> bool:
        """Una pregunta con contenido o un mensaje largo: lo tiene que ver una persona."""
        contenido = len(interp.contenido)
        return contenido >= 2 if interp.es_pregunta else contenido >= 4

    @staticmethod
    def _no_entendido(plan: _Plan, ctx: ContextoConversacion) -> None:
        intentos = ctx.intentos_sin_entender + 1
        plan.intentos_sin_entender = intentos
        if intentos >= MAX_SIN_ENTENDER:
            # Tercer mensaje seguido sin sentido: no se responde para no alimentar un intercambio inútil.
            plan.silencio = True
            return
        plan.responder(respuestas.aclaracion(intentos), "ACLARA" if intentos == 1 else "ACLARA2")

    def _dato_invalido(self, plan: _Plan, ctx: ContextoConversacion, no_sabe: bool = False) -> None:
        """CU09, excepción: el mensaje no trae un código postal ni una localidad reconocible."""
        intentos = ctx.intentos_cp + 1
        if intentos >= self.max_intentos_cp:
            plan.derivar("ENVIO", TemaConsulta.ENVIO, prefijo="No pude reconocer el código postal.")
            return
        plan.responder(respuestas.codigo_postal_invalido(no_sabe), "ENVIO?")
        plan.pide_cp = True
        plan.ultimo_tema = TemaConsulta.ENVIO
        plan.intentos_cp = intentos

    def _archivo_sin_texto(self, plan: _Plan, datos: DatosComercio, ctx: ContextoConversacion, tipo: str) -> None:
        if ctx.estado == E.DERIVADA:
            if ctx.intentos_sin_entender >= 1:
                plan.silencio = True
                plan.intentos_sin_entender = ctx.intentos_sin_entender
            else:
                plan.responder(Respuesta(respuestas.archivo_recibido(tipo, datos)), "RECORDATORIO")
                plan.intentos_sin_entender = 1
            return
        if tipo in TIPOS_ARCHIVO:
            plan.derivar("ARCHIVO", TemaConsulta.NO_RECONOCIDO, prefijo=respuestas.archivo_recibido(tipo, datos))
        elif tipo == "location":
            plan.responder(respuestas.ubicacion_recibida(), "ENVIO?")
            self._esperar_cp(plan, ctx)
        elif tipo == "sticker":
            plan.responder(respuestas.cortesia("ok"), "CORTESIA")
        else:
            # Audio, contactos u otros: se pide escribir la consulta.
            intentos = ctx.intentos_sin_entender + 1
            plan.intentos_sin_entender = intentos
            if intentos >= MAX_SIN_ENTENDER:
                plan.silencio = True
            else:
                respuesta = respuestas.audio_no_soportado() if tipo == "audio" else respuestas.aclaracion(intentos)
                plan.responder(respuesta, "ACLARA")

    # ------------------------------------------------------------------
    # Conversación derivada (CU12)
    # ------------------------------------------------------------------

    def _en_derivacion(self, plan: _Plan, datos, ahora, ctx, interp: Interpretacion) -> None:
        """Con una consulta derivada, el bot responde lo que sabe resolver y no insiste con el resto.

        Una consulta nueva de otro tema (por ejemplo, un pago informado después de una
        pregunta de stock) se registra como otra derivación para que el comercio la vea.
        """
        resolubles = [t for t in interp.temas if t in TEMAS_RESOLUBLES]
        nuevos = [t for t in interp.temas if t in TEMAS_DERIVABLES and tema_de(t) not in ctx.temas_pendientes]

        if resolubles and PERSONA not in interp.control:
            self._atender_temas(plan, datos, ahora, ctx, replace(interp, temas=resolubles))
            # El dato que falta para el envío llega como un código postal suelto, que se
            # entiende igual: la conversación sigue derivada.
            plan.pide_cp = False
            plan.derivaciones = [d for d in plan.derivaciones if d.tema not in ctx.temas_pendientes]
        for tema in sorted(nuevos, key=PRIORIDAD.index):
            plan.derivar(tema, tema_de(tema))
        if plan.respuestas or plan.derivaciones:
            return

        solo_cortesia = interp.control and all(c in {CORTESIA, DESPEDIDA, NO} for c in interp.control)
        if solo_cortesia and not interp.contenido:
            plan.responder(respuestas.cortesia("gracias" if "gracias" in interp.tokens else "ok"), "CORTESIA")
            plan.intentos_sin_entender = ctx.intentos_sin_entender
        elif ctx.intentos_sin_entender == 0:
            pidio_datos = bool(ctx.temas_pendientes & {TemaConsulta.PEDIDOS, TemaConsulta.RECLAMOS})
            plan.responder(respuestas.recordatorio_derivacion(datos, ahora, pidio_datos), "RECORDATORIO")
            plan.intentos_sin_entender = 1
        else:
            plan.silencio = True
            plan.intentos_sin_entender = ctx.intentos_sin_entender

    # ------------------------------------------------------------------
    # Armado del resultado
    # ------------------------------------------------------------------

    def _armar(
        self,
        plan: _Plan,
        datos: DatosComercio,
        ahora: datetime,
        ctx: ContextoConversacion,
        interp: Interpretacion | None,
        primer_contacto: bool = False,
    ) -> ResultadoMotor:
        consultas = list(plan.resueltas)
        ultimo_tema = plan.ultimo_tema
        ultimo_cp = plan.ultimo_cp

        if plan.silencio:
            plan.acciones.append("SILENCIO")
        elif plan.derivaciones:
            # Una sola respuesta de derivación aunque haya varios motivos: el texto es el del
            # motivo más importante y se registra una consulta por tema.
            principal = min(plan.derivaciones, key=lambda d: _ORDEN_MOTIVOS.index(d.motivo))
            prefijo = " ".join(dict.fromkeys(d.prefijo for d in plan.derivaciones if d.prefijo)) or None
            extra = None
            if plan.aviso_archivo:
                extra = (
                    "No puedo ver imágenes ni archivos: si es un comprobante o una foto, mandáselo al equipo por "
                    f"WhatsApp al *{datos.telefono_contacto}*."
                )
            plan.responder(
                respuestas.derivacion(datos, principal.motivo, ahora, prefijo=prefijo, extra=extra),
                "D:" + ETIQUETA_ACCION[principal.tema],
            )
            registrados: set[TemaConsulta] = set()
            for d in plan.derivaciones:
                etiqueta = "D:" + ETIQUETA_ACCION[d.tema]
                if etiqueta not in plan.acciones:
                    plan.acciones.append(etiqueta)
                if d.tema in registrados or d.tema in ctx.temas_pendientes:
                    continue
                registrados.add(d.tema)
                consultas.append(ConsultaARegistrar(d.tema, ResultadoConsulta.DERIVADA, d.codigo_postal))
                ultimo_cp = d.codigo_postal or ultimo_cp
            ultimo_tema = principal.tema

        if plan.derivaciones or ctx.estado == E.DERIVADA:
            estado = E.DERIVADA
        elif plan.pide_cp:
            estado = E.ESPERANDO_CP
        else:
            estado = E.ACTIVA
        nuevo = ctx.con(
            estado=estado,
            intentos_cp=(plan.intentos_cp or 0) if estado == E.ESPERANDO_CP else 0,
            intentos_sin_entender=plan.intentos_sin_entender or 0,
            ultimo_tema=ultimo_tema or ctx.ultimo_tema,
            ultimo_cp=ultimo_cp or ctx.ultimo_cp,
            temas_pendientes=ctx.temas_pendientes
            | {c.tema for c in consultas if c.resultado == ResultadoConsulta.DERIVADA},
        )

        # Cierre amable cuando todo quedó resuelto.
        resuelto = any(a in ACCIONES_RESUELTAS for a in plan.acciones)
        if plan.respuestas and resuelto and not plan.derivaciones and not plan.pide_cp:
            plan.respuestas[-1] = plan.respuestas[-1].con_pie(respuestas.CIERRE)

        # Primer contacto con una consulta: el bot se presenta antes de responder.
        if primer_contacto and plan.respuestas and plan.acciones[0] not in {"BIENVENIDA", "IDENTIDAD"}:
            plan.respuestas[0] = plan.respuestas[0].con_prefijo(respuestas.presentacion(datos))

        return ResultadoMotor(plan.respuestas, nuevo, consultas, plan.acciones, interp)
