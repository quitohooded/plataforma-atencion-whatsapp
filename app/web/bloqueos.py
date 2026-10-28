"""Números bloqueados por el comercio (#7)."""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..modelos import Bloqueo
from ..servicios import ErrorValidacion, metricas
from ..servicios import bloqueos as srv
from . import del_comercio, destino_seguro, requiere_onboarding

bp = Blueprint("bloqueos", __name__, url_prefix="/bloqueos")


@bp.get("")
@requiere_onboarding
def listado():
    return render_template("panel/bloqueos.html", bloqueos=srv.listado(g.comercio))


@bp.post("")
@requiere_onboarding
def bloquear():
    try:
        id_consulta = int(request.form.get("id_consulta", ""))
    except ValueError:
        abort(404)
    consulta = metricas.consulta_del_comercio(g.comercio, id_consulta)
    if consulta is None:
        abort(404)
    destino = destino_seguro(
        request.form.get("siguiente"), url_for("historial.detalle", id_consulta=consulta.id_consulta)
    )
    try:
        bloqueo = srv.bloquear(g.comercio, consulta, request.form.get("motivo", ""))
    except ErrorValidacion as e:
        flash(e.mensaje, "error")
        return redirect(destino)
    comprador = bloqueo.comprador
    flash(
        f"Número {comprador.telefono_legible} bloqueado: el bot no le responde y sus mensajes no generan consultas. "
        "Sus consultas pendientes se marcaron como atendidas.",
        "exito",
    )
    return redirect(destino)


@bp.post("/<int:id_bloqueo>/eliminar")
@requiere_onboarding
def desbloquear(id_bloqueo: int):
    bloqueo = del_comercio(Bloqueo, id_bloqueo)
    telefono = bloqueo.comprador.telefono_legible
    srv.desbloquear(bloqueo)
    flash(f"Número {telefono} desbloqueado: el bot vuelve a responderle.", "exito")
    return redirect(destino_seguro(request.form.get("siguiente"), url_for("bloqueos.listado")))
