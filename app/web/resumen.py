"""CU13 Consultar resumen y pendientes."""

import logging

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..extensiones import db
from ..servicios import metricas
from ..utilidades import tiempo
from . import destino_seguro, requiere_onboarding

log = logging.getLogger(__name__)

bp = Blueprint("resumen", __name__, url_prefix="/panel")


@bp.get("")
@requiere_onboarding
def inicio():
    comercio = g.comercio
    if not comercio.fue_activado:
        # Precondición de CU13: el bot fue activado al menos una vez.
        return redirect(url_for("activacion.inicio"))
    periodo = request.args.get("periodo", metricas.PERIODO_POR_DEFECTO)
    try:
        ahora = tiempo.ahora()
        datos = metricas.resumen(comercio, periodo, ahora)
        lista = metricas.pendientes(comercio)
        alertas, total_alertas = metricas.alertas_recientes(comercio, ahora)
    except Exception:
        log.exception("Error al calcular el resumen del comercio %s", comercio.id_comercio)
        return render_template(
            "panel/resumen.html",
            error_carga=True,
            periodos=metricas.PERIODOS,
            periodo=periodo,
            resumen=None,
            pendientes=[],
            alertas=[],
            total_alertas=0,
        ), 500
    return render_template(
        "panel/resumen.html",
        resumen=datos,
        pendientes=lista,
        alertas=alertas,
        total_alertas=total_alertas,
        periodos=metricas.PERIODOS,
        periodo=datos.periodo,
        error_carga=False,
    )


@bp.post("/consultas/<int:id_consulta>/atendida")
@requiere_onboarding
def marcar_atendida(id_consulta: int):
    consulta = metricas.consulta_del_comercio(g.comercio, id_consulta)
    destino = destino_seguro(request.form.get("siguiente"), url_for("resumen.inicio"))
    if consulta is None:
        flash("La consulta no existe.", "error")
        return redirect(destino)
    if consulta.pendiente:
        consulta.marcar_atendida(tiempo.ahora())
        db.session.commit()
        flash("Consulta marcada como atendida. El bot vuelve a responder a ese comprador.", "exito")
    return redirect(destino)
