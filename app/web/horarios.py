"""CU06 Administrar horarios de atención."""

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..servicios import horarios as srv
from . import requiere_onboarding
from .comunes import procesar_horarios

bp = Blueprint("horarios", __name__, url_prefix="/horarios")


@bp.route("", methods=["GET", "POST"])
@requiere_onboarding
def editar():
    dias = srv.desde_comercio(g.comercio)
    error = None
    if request.method == "POST":
        resultado = procesar_horarios(g.comercio)
        dias, error = resultado.dias, resultado.error
        if resultado.guardado:
            flash("Horarios actualizados. El bot los informa desde la próxima consulta.", "exito")
            return redirect(url_for("horarios.editar"))
        if not error and resultado.accion == "copiar":
            flash("Horario copiado al resto de los días hábiles. Revise y guarde los cambios.", "info")
    return render_template("panel/horarios.html", dias=dias, error=error), (400 if error else 200)
