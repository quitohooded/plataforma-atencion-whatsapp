"""CU07 Activar el bot: chat de prueba, activación con código, enlace y QR, pausa."""

import logging

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..bot import prueba
from ..bot.motor import BOTONES
from ..extensiones import db
from ..modelos import EstadoComercio
from ..utilidades import tiempo
from ..utilidades.qr import qr_svg
from . import requiere_onboarding

log = logging.getLogger(__name__)

bp = Blueprint("activacion", __name__, url_prefix="/activacion")


def enlaces(comercio) -> dict:
    """Enlace a la línea real (si está configurada) y enlace al simulador para demos."""
    numero = current_app.config.get("WHATSAPP_NUMERO_PUBLICO", "")
    resultado = {"whatsapp": None, "simulador": None, "qr_destino": None}
    if not comercio.codigo_acceso:
        return resultado
    if numero:
        resultado["whatsapp"] = comercio.generar_enlace_acceso(numero)
    if current_app.config.get("SIMULADOR_HABILITADO"):
        resultado["simulador"] = url_for("simulador.inicio", text=comercio.texto_primer_mensaje(), _external=True)
    resultado["qr_destino"] = resultado["whatsapp"] or resultado["simulador"]
    return resultado


@bp.get("")
@requiere_onboarding
def inicio():
    comercio = g.comercio
    datos_enlace = enlaces(comercio)
    qr = (
        qr_svg(datos_enlace["qr_destino"], titulo=f"Código QR de {comercio.nombre}")
        if datos_enlace["qr_destino"]
        else None
    )
    return render_template(
        "panel/activacion.html",
        enlaces=datos_enlace,
        qr=qr,
        numero_configurado=bool(current_app.config.get("WHATSAPP_NUMERO_PUBLICO")),
    )


@bp.post("/activar")
@requiere_onboarding
def activar():
    comercio = g.comercio
    estado_anterior, codigo_anterior = comercio.estado, comercio.codigo_acceso
    try:
        comercio.activar_bot()
        db.session.commit()
    except Exception as error:  # CU07, excepción: falla al generar el código o el enlace
        db.session.rollback()
        comercio.estado, comercio.codigo_acceso = estado_anterior, codigo_anterior
        log.exception("No fue posible activar el bot del comercio %s", comercio.id_comercio)
        flash(f"No fue posible activar el bot: {error}. Intente nuevamente.", "error")
        return redirect(url_for("activacion.inicio"))
    if codigo_anterior:
        flash("Bot reactivado. Vuelve a responder automáticamente.", "exito")
    else:
        flash("Bot activado. Comparta el enlace con sus compradores.", "exito")
    return redirect(url_for("activacion.inicio"))


@bp.post("/pausar")
@requiere_onboarding
def pausar():
    comercio = g.comercio
    if comercio.estado == EstadoComercio.ACTIVO:
        comercio.pausar_bot()
        db.session.commit()
        flash("Bot pausado. Los compradores reciben un aviso hasta que lo reactive.", "info")
    return redirect(url_for("activacion.inicio"))


@bp.post("/chat-prueba")
@requiere_onboarding
def chat_prueba():
    datos = request.get_json(silent=True) or {}
    texto = str(datos.get("texto", "")).strip()[:1000]
    boton = str(datos.get("boton", "")).strip() or None
    if not texto:
        return jsonify(error="Escriba un mensaje."), 400
    estado, detalle = prueba.responder(
        g.comercio, session.get(prueba.CLAVE_SESION), texto, tiempo.ahora(), boton=boton if boton in BOTONES else None
    )
    session[prueba.CLAVE_SESION] = estado
    return jsonify(detalle)


@bp.post("/chat-prueba/reiniciar")
@requiere_onboarding
def reiniciar_chat():
    session.pop(prueba.CLAVE_SESION, None)
    return jsonify(ok=True)


@bp.get("/qr.svg")
@requiere_onboarding
def qr_descarga():
    destino = enlaces(g.comercio)["qr_destino"]
    if not destino:
        return redirect(url_for("activacion.inicio"))
    return Response(
        qr_svg(destino, titulo=f"Código QR de {g.comercio.nombre}"),
        mimetype="image/svg+xml",
        headers={"Content-Disposition": f"attachment; filename=qr-{g.comercio.codigo_acceso}.svg"},
    )


@bp.get("/cartel")
@requiere_onboarding
def cartel():
    datos_enlace = enlaces(g.comercio)
    if not datos_enlace["qr_destino"]:
        return redirect(url_for("activacion.inicio"))
    return render_template(
        "panel/cartel.html",
        enlaces=datos_enlace,
        qr=qr_svg(datos_enlace["qr_destino"], titulo=f"Código QR de {g.comercio.nombre}"),
    )
