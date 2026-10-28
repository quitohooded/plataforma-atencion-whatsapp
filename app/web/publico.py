"""Página de inicio pública y verificación de estado del servicio."""

from datetime import datetime

from flask import Blueprint, g, jsonify, redirect, render_template
from sqlalchemy import select

from ..bot.contexto import ContextoConversacion
from ..bot.motor import MotorConversacional
from ..extensiones import db
from ..modelos import PalabraClave
from . import destino_inicial

bp = Blueprint("publico", __name__)

# Conversación de ejemplo de la portada. Se genera con el motor real, así el ejemplo
# siempre muestra lo que el bot responde.
EJEMPLO = [
    ("23:47", "Hola! ¿Hacen envíos a Río Cuarto?"),
    ("23:48", "Genial. ¿Tienen el mantel rectangular en gris?"),
]


def conversacion_de_ejemplo() -> list[dict]:
    from ..datos.casa_y_detalles import datos_comercio

    datos = datos_comercio()
    palabras = [(p.termino, p.tema, p.peso) for p in db.session.scalars(select(PalabraClave))]
    motor = MotorConversacional()
    contexto = ContextoConversacion()
    mensajes = []
    for hora, texto in EJEMPLO:
        momento = datetime(2026, 10, 27, int(hora[:2]), int(hora[3:]))
        resultado = motor.procesar(datos, contexto, texto, palabras, momento, primer_contacto=not mensajes)
        contexto = resultado.contexto
        mensajes.append({"texto": texto, "propio": True, "hora": hora})
        mensajes += [{"texto": r.texto, "propio": False, "hora": hora} for r in resultado.respuestas]
    return mensajes


@bp.get("/")
def inicio():
    if g.get("comercio"):
        return redirect(destino_inicial(g.comercio))
    return render_template("publico/inicio.html", ejemplo=conversacion_de_ejemplo())


@bp.get("/salud")
def salud():
    return jsonify(estado="ok")
