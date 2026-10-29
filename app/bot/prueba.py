"""Chat de prueba del panel (CU07, pasos 2 y 3).

Responde con la información que el comercio tiene cargada usando el mismo motor que la
línea real, pero sin guardar mensajes ni consultas. El contexto de la conversación de
prueba se conserva en la sesión del navegador.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from flask import current_app
from sqlalchemy import select

from ..extensiones import db
from ..modelos import Comercio, EstadoConversacion, PalabraClave, TemaConsulta
from .contexto import ContextoConversacion, DatosComercio, RespuestaDatos
from .intencion import PREFIJO_RESPUESTA
from .motor import MotorConversacional

CLAVE_SESION = "chat_prueba"

NOTA_DERIVACION = (
    "En la línea real, esta consulta quedaría pendiente en su resumen para que la responda desde su WhatsApp. "
    "Mientras tanto, el bot seguiría respondiendo envíos, pagos y horarios a ese comprador."
)


def estado_inicial() -> dict:
    return {"estado": EstadoConversacion.ACTIVA.value, "intentos_cp": 0, "iniciada": False}


def _contexto(estado_sesion: dict) -> ContextoConversacion:
    tema = estado_sesion.get("ultimo_tema")
    return ContextoConversacion(
        estado=EstadoConversacion(estado_sesion.get("estado", EstadoConversacion.ACTIVA.value)),
        intentos_cp=int(estado_sesion.get("intentos_cp", 0) or 0),
        intentos_sin_entender=int(estado_sesion.get("intentos_sin_entender", 0) or 0),
        ultimo_tema=TemaConsulta(tema) if tema else None,
        ultimo_cp=estado_sesion.get("ultimo_cp"),
    )


def responder(
    comercio: Comercio, estado_sesion: dict | None, texto: str, ahora: datetime, boton: str | None = None
) -> tuple[dict, dict]:
    estado_sesion = dict(estado_sesion or estado_inicial())
    motor = MotorConversacional(max_intentos_cp=current_app.config.get("BOT_MAX_INTENTOS_CP", 2))
    palabras = [(p.termino, p.tema, p.peso) for p in db.session.scalars(select(PalabraClave)).all()]

    resultado = motor.procesar(
        datos=DatosComercio.desde_comercio(comercio),
        contexto=_contexto(estado_sesion),
        texto=boton or texto,
        palabras=palabras,
        ahora=ahora,
        primer_contacto=not estado_sesion.get("iniciada", False),
    )

    contexto = resultado.contexto
    nota = None
    if resultado.derivada:
        # En la prueba se vuelve a la atención automática para poder seguir probando.
        nota = NOTA_DERIVACION
        contexto = contexto.con(estado=EstadoConversacion.ACTIVA, intentos_sin_entender=0)
    elif "SILENCIO" in resultado.acciones:
        nota = "El bot no responde: es el tercer mensaje seguido que no entiende."

    estado_sesion.update(
        estado=contexto.estado.value,
        intentos_cp=contexto.intentos_cp,
        intentos_sin_entender=contexto.intentos_sin_entender,
        ultimo_tema=contexto.ultimo_tema.value if contexto.ultimo_tema else None,
        ultimo_cp=contexto.ultimo_cp,
        iniciada=True,
    )
    detalle = {
        "respuestas": [serializar_respuesta(r) for r in resultado.respuestas],
        "nota": nota,
        "tema": resultado.tema_detectado.etiqueta if resultado.tema_detectado else None,
        "estado": contexto.estado.etiqueta,
    }
    return estado_sesion, detalle


_RESPUESTA_DEL_BOT = {
    "ENVIO": "con el plazo de envío",
    "ENVIO?": "pidiendo el código postal para calcular el envío",
    "PAGO": "con los medios de pago",
    "HORARIO": "con los horarios",
    "CONTACTO": "con el contacto del comercio",
    "CATALOGO": "con el enlace al catálogo",
}


def probar_respuesta(comercio: Comercio, borrador: RespuestaDatos, mensaje: str, ahora: datetime) -> dict:
    """CU15: qué haría el bot con un mensaje si la respuesta en edición estuviera guardada.

    No guarda nada. Las demás respuestas activas del comercio se tienen en cuenta, para que
    se vea si otra respuesta o un tema del bot se queda con el mensaje.
    """
    datos = DatosComercio.desde_comercio(comercio)
    otras = tuple(r for r in datos.respuestas if r.id_respuesta is None or r.id_respuesta != borrador.id_respuesta)
    datos = replace(datos, respuestas=(borrador, *otras))
    palabras = [(p.termino, p.tema, p.peso) for p in db.session.scalars(select(PalabraClave)).all()]
    resultado = MotorConversacional().procesar(datos, ContextoConversacion(), mensaje, palabras, ahora)

    propia = PREFIJO_RESPUESTA + borrador.clave
    usa = propia in resultado.acciones
    otras_usadas = [
        r.titulo for r in otras if PREFIJO_RESPUESTA + r.clave in resultado.acciones and r.clave != borrador.clave
    ]
    del_bot = [_RESPUESTA_DEL_BOT[a] for a in resultado.acciones if a in _RESPUESTA_DEL_BOT]
    if usa and (otras_usadas or del_bot or resultado.derivada):
        explicacion = "El bot usa esta respuesta y además responde otra parte del mensaje."
    elif usa:
        explicacion = "El bot responde con esta respuesta."
    elif otras_usadas:
        explicacion = f"El bot no usa esta respuesta: responde con «{otras_usadas[0]}»."
    elif del_bot:
        explicacion = f"El bot no usa esta respuesta: responde {del_bot[0]}."
    elif resultado.derivada:
        explicacion = (
            "El bot no usa esta respuesta: le pasa la consulta a una persona del equipo. Si el mensaje es sobre este "
            "tema, agregue como palabra clave cómo lo escribió el cliente."
        )
    else:
        explicacion = (
            "El bot no usa esta respuesta para este mensaje. Agregue como palabra clave cómo lo escribió el cliente."
        )
    return {
        "usa": usa,
        "explicacion": explicacion,
        "respuestas": [serializar_respuesta(r) for r in resultado.respuestas],
    }


def serializar_respuesta(respuesta) -> dict:
    return {
        "texto": respuesta.texto,
        "botones": [{"id": b.id, "titulo": b.titulo} for b in respuesta.botones],
    }


def vista_previa(comercio: Comercio, ahora: datetime) -> list[dict]:
    """Preguntas de ejemplo respondidas con los datos cargados (#9): el responsable ve cómo va a
    responder el bot antes de confirmar el onboarding. No guarda nada."""
    datos = DatosComercio.desde_comercio(comercio)
    palabras = [(p.termino, p.tema, p.peso) for p in db.session.scalars(select(PalabraClave)).all()]
    preguntas = []
    if datos.zonas:
        preguntas.append(f"Hola! ¿Hacen envíos al {datos.zonas[0].cp_desde}?")
    preguntas += ["¿Cómo se puede pagar?", "¿Qué horario tienen?"]
    motor = MotorConversacional()
    ejemplo = []
    for pregunta in preguntas:
        resultado = motor.procesar(datos, ContextoConversacion(), pregunta, palabras, ahora)
        ejemplo.append({"pregunta": pregunta, "respuestas": [r.texto for r in resultado.respuestas]})
    return ejemplo
