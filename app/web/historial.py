"""CU14 Consultar historial de consultas."""

import logging

from flask import Blueprint, abort, g, render_template, request

from ..modelos import ResultadoConsulta, TemaConsulta
from ..servicios import bloqueos, metricas
from . import requiere_onboarding

log = logging.getLogger(__name__)

bp = Blueprint("historial", __name__, url_prefix="/historial")


@bp.get("")
@requiere_onboarding
def listado():
    filtros = metricas.FiltrosHistorial.desde_argumentos(request.args)
    try:
        pagina = int(request.args.get("pagina", 1))
    except ValueError:
        pagina = 1
    try:
        resultado = metricas.historial(g.comercio, filtros, pagina)
    except Exception:
        log.exception("Error al cargar el historial del comercio %s", g.comercio.id_comercio)
        return render_template(
            "panel/historial.html",
            error_carga=True,
            filtros=filtros,
            resultado=None,
            temas=list(TemaConsulta),
            resultados=list(ResultadoConsulta),
        ), 500
    return render_template(
        "panel/historial.html",
        error_carga=False,
        filtros=filtros,
        resultado=resultado,
        temas=list(TemaConsulta),
        resultados=list(ResultadoConsulta),
        bloqueados=len(bloqueos.listado(g.comercio)),
    )


@bp.get("/<int:id_consulta>")
@requiere_onboarding
def detalle(id_consulta: int):
    consulta = metricas.consulta_del_comercio(g.comercio, id_consulta)
    if consulta is None:
        abort(404)
    conversacion = consulta.conversacion
    return render_template(
        "panel/historial_detalle.html",
        consulta=consulta,
        conversacion=conversacion,
        bloqueo=bloqueos.bloqueo_de(g.comercio, conversacion.comprador),
    )
