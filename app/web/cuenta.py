"""Cuenta del responsable (#9): contraseña, recuperación por correo, avisos y ayuda."""

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for

from .. import correo
from ..extensiones import db
from ..servicios import ErrorValidacion
from ..servicios import cuentas as srv
from . import destino_inicial, requiere_onboarding, requiere_sesion

bp = Blueprint("cuenta", __name__)


@bp.route("/cuenta", methods=["GET", "POST"])
@requiere_onboarding
def editar():
    error, campos = None, []
    if request.method == "POST":
        accion = request.form.get("accion")
        if accion == "contrasena":
            try:
                srv.cambiar_contrasena(
                    g.usuario,
                    request.form.get("actual", ""),
                    request.form.get("nueva", ""),
                    request.form.get("repetida", ""),
                )
            except ErrorValidacion as e:
                error, campos = e.mensaje, e.campos
            else:
                flash("Contraseña actualizada.", "exito")
                return redirect(url_for("cuenta.editar"))
        elif accion == "avisos":
            g.comercio.avisos_correo = request.form.get("avisos_correo") == "1"
            db.session.commit()
            if g.comercio.avisos_correo:
                flash(
                    f"Avisos activados: le vamos a escribir a {g.usuario.email} cuando quede una consulta pendiente.",
                    "exito",
                )
            else:
                flash("Avisos por correo desactivados.", "info")
            return redirect(url_for("cuenta.editar"))
    return render_template(
        "panel/cuenta.html",
        error=error,
        campos_error=campos,
        correo_disponible=correo.disponible(),
        intervalo=current_app.config.get("AVISOS_CORREO_MINUTOS", 30),
    ), (400 if error else 200)


@bp.get("/ayuda")
@requiere_sesion
def ayuda():
    return render_template("panel/ayuda.html")


@bp.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if g.get("comercio"):
        return redirect(destino_inicial(g.comercio))
    enviado = False
    disponible = correo.disponible()
    if request.method == "POST" and disponible:
        usuario = srv.solicitar_recuperacion(request.form.get("email", ""))
        if usuario is not None:
            enlace = correo.enlace_externo("cuenta.restablecer", token=srv.token_recuperacion(usuario))
            minutos = current_app.config.get("RECUPERACION_MINUTOS", 60)
            plataforma = current_app.config["PLATAFORMA_NOMBRE"]
            correo.enviar(
                usuario.email,
                f"{plataforma}: recuperar la contraseña",
                "\n".join(
                    [
                        "Hola,",
                        "",
                        f"Recibimos un pedido para cambiar la contraseña de {usuario.comercio.nombre} en {plataforma}.",
                        f"Para elegir una nueva, entre en este enlace (vence en {minutos} minutos y sirve una "
                        "sola vez):",
                        "",
                        enlace or "",
                        "",
                        "Si no lo pidió usted, ignore este correo: su contraseña no cambia.",
                        "",
                        plataforma,
                    ]
                ),
            )
        enviado = True
    return render_template("auth/recuperar.html", enviado=enviado, disponible=disponible)


@bp.route("/recuperar/<token>", methods=["GET", "POST"])
def restablecer(token: str):
    usuario = srv.usuario_de_token(token)
    if usuario is None:
        return render_template("auth/restablecer.html", valido=False), 400
    error, campos = None, []
    if request.method == "POST":
        try:
            srv.restablecer_contrasena(usuario, request.form.get("nueva", ""), request.form.get("repetida", ""))
        except ErrorValidacion as e:
            error, campos = e.mensaje, e.campos
        else:
            flash("Contraseña actualizada. Ingrese con la nueva contraseña.", "exito")
            return redirect(url_for("auth.ingresar", email=usuario.email))
    return render_template("auth/restablecer.html", valido=True, error=error, campos_error=campos), (
        400 if error else 200
    )
