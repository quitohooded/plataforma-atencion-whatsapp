"""CU01 Registrarse en la plataforma y CU02 Iniciar sesión."""

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from ..servicios import ErrorValidacion
from ..servicios.cuentas import CorreoYaRegistrado, iniciar_sesion, registrar_comercio
from . import destino_inicial, destino_seguro, iniciar_sesion_usuario

bp = Blueprint("auth", __name__)

RUBROS_SUGERIDOS = [
    "Artículos para el hogar", "Indumentaria", "Accesorios", "Calzado", "Cosmética",
    "Librería y regalería", "Alimentos y bebidas", "Electrónica", "Mascotas",
]


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    if g.get("comercio"):
        return redirect(destino_inicial(g.comercio))

    valores = {}
    error = None
    campos_error: list[str] = []
    correo_existente = False
    if request.method == "POST":
        valores = {c: request.form.get(c, "") for c in ("nombre", "rubro", "telefono", "email")}
        try:
            usuario = registrar_comercio(contrasena=request.form.get("contrasena", ""), **valores)
        except CorreoYaRegistrado as e:
            error, campos_error, correo_existente = e.mensaje, e.campos, True
        except ErrorValidacion as e:
            error, campos_error = e.mensaje, e.campos
        else:
            iniciar_sesion_usuario(usuario)
            flash("Cuenta creada. Complete estos cuatro pasos para dejar listo el bot.", "exito")
            return redirect(url_for("onboarding.paso", numero=1))

    return render_template(
        "auth/registro.html", valores=valores, error=error, campos_error=campos_error,
        correo_existente=correo_existente, rubros=RUBROS_SUGERIDOS,
    ), (400 if error else 200)


@bp.route("/ingresar", methods=["GET", "POST"])
def ingresar():
    siguiente = request.values.get("siguiente")
    if g.get("comercio"):
        return redirect(destino_inicial(g.comercio))

    error = None
    email = request.args.get("email", "")
    if request.method == "POST":
        email = request.form.get("email", "")
        resultado = iniciar_sesion(email, request.form.get("contrasena", ""))
        if resultado.usuario:
            iniciar_sesion_usuario(resultado.usuario)
            comercio = resultado.usuario.comercio
            destino = destino_inicial(comercio)
            if comercio.onboarding_completo:
                destino = destino_seguro(siguiente, destino)
            return redirect(destino)
        error = resultado.error

    return render_template("auth/ingresar.html", error=error, email=email, siguiente=siguiente), (
        401 if error else 200
    )


@bp.post("/salir")
def salir():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.ingresar"))
