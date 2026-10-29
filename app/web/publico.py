"""Página de inicio pública y verificación de estado del servicio."""

from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, redirect, render_template
from sqlalchemy import select, text

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


# Fecha desde la que rigen la política de privacidad y los términos de uso.
VIGENCIA_LEGALES = "29 de octubre de 2026"


def plazo_retencion(dias: int) -> str:
    """«al año», «a los 2 años», «a los 180 días»."""
    if dias % 365 == 0:
        anios = dias // 365
        return "al año" if anios == 1 else f"a los {anios} años"
    return f"a los {dias} días"


def _datos_legales() -> dict:
    dias = current_app.config.get("RETENCION_DIAS") or 0
    return {
        "vigencia": VIGENCIA_LEGALES,
        "contacto": current_app.config.get("CONTACTO_PLATAFORMA", ""),
        "retencion_dias": dias,
        "plazo_retencion": plazo_retencion(dias) if dias > 0 else "",
    }


@bp.get("/privacidad")
def privacidad():
    return render_template("publico/privacidad.html", **_datos_legales())


@bp.get("/terminos")
def terminos():
    return render_template("publico/terminos.html", **_datos_legales())


@bp.get("/salud")
def salud():
    """Estado del servicio para monitores externos (por ejemplo, uno gratuito que avise si se cae)."""
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        db.session.rollback()
        return jsonify(estado="error", base="sin conexión"), 503
    return jsonify(estado="ok", base="ok")
