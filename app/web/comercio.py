"""Datos del negocio después del onboarding (paso 1 de CU03, editable desde el panel)."""

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..extensiones import db
from ..servicios import ErrorValidacion
from ..servicios.cuentas import validar_datos_negocio
from . import requiere_onboarding
from .auth import RUBROS_SUGERIDOS

bp = Blueprint("comercio", __name__, url_prefix="/mi-comercio")


@bp.route("", methods=["GET", "POST"])
@requiere_onboarding
def editar():
    comercio = g.comercio
    error, campos_error = None, []
    valores = {"nombre": comercio.nombre, "rubro": comercio.rubro, "telefono": comercio.telefono_contacto}
    if request.method == "POST":
        valores = {c: request.form.get(c, "") for c in ("nombre", "rubro", "telefono")}
        try:
            nombre, rubro, telefono = validar_datos_negocio(**valores)
        except ErrorValidacion as e:
            error, campos_error = e.mensaje, e.campos
        else:
            comercio.nombre, comercio.rubro, comercio.telefono_contacto = nombre, rubro, telefono
            db.session.commit()
            flash("Datos del negocio actualizados.", "exito")
            return redirect(url_for("comercio.editar"))
    return render_template("panel/mi_comercio.html", valores=valores, error=error,
                           campos_error=campos_error, rubros=RUBROS_SUGERIDOS), (400 if error else 200)
