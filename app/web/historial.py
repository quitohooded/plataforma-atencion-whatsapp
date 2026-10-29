"""CU14 Consultar historial de consultas."""

import csv
import io
import logging

from flask import Blueprint, Response, abort, g, render_template, request

from ..modelos import ResultadoConsulta, TemaConsulta
from ..servicios import bloqueos, metricas
from ..utilidades import tiempo
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
    pendiente = metricas.Pendiente(consulta, conversacion.comprador, metricas._ultimo_mensaje(consulta, True))
    return render_template(
        "panel/historial_detalle.html",
        consulta=consulta,
        conversacion=conversacion,
        bloqueo=bloqueos.bloqueo_de(g.comercio, conversacion.comprador),
        enlace_respuesta=pendiente.enlace_respuesta,
    )


@bp.get("/exportar.csv")
@requiere_onboarding
def exportar():
    """Historial con los filtros aplicados, para abrir en una planilla (#10)."""
    filtros = metricas.FiltrosHistorial.desde_argumentos(request.args)
    salida = io.StringIO()
    # Punto y coma y marca de orden de bytes: así lo abre bien una planilla configurada en español.
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(metricas.COLUMNAS_EXPORTACION)
    escritor.writerows(metricas.filas_exportacion(g.comercio, filtros))
    nombre = f"consultas-{tiempo.ahora().strftime('%Y%m%d-%H%M')}.csv"
    return Response(
        "\ufeff" + salida.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"', "Cache-Control": "no-store"},
    )
