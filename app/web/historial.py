"""CU14 Consultar historial de consultas."""

import csv
import io
import logging

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from ..modelos import ResultadoConsulta, TemaConsulta
from ..servicios import bloqueos, metricas, retencion
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


@bp.route("/<int:id_consulta>/borrar-comprador", methods=["GET", "POST"])
@requiere_onboarding
def borrar_comprador(id_consulta: int):
    """Derecho de supresión (Ley 25.326, art. 16): el comprador pidió que se borren sus datos."""
    consulta = metricas.consulta_del_comercio(g.comercio, id_consulta)
    if consulta is None:
        abort(404)
    comprador = consulta.conversacion.comprador
    nombre = comprador.nombre or comprador.telefono_legible
    volver = url_for("historial.detalle", id_consulta=id_consulta)
    if request.method == "POST":
        cantidad = retencion.borrar_datos_comprador(comprador, g.comercio)
        conversaciones = "1 conversación" if cantidad == 1 else f"{cantidad} conversaciones"
        flash(f"Se borraron los datos de {nombre} con su comercio ({conversaciones}).", "exito")
        return redirect(url_for("historial.listado"))
    bloqueado = bloqueos.bloqueo_de(g.comercio, comprador) is not None
    identificacion = (
        f"{comprador.nombre} ({comprador.telefono_legible})" if comprador.nombre else comprador.telefono_legible
    )
    detalle = (
        "Se borran todas sus conversaciones con su comercio, con sus mensajes y consultas (también las pendientes), "
        "y no se pueden recuperar. Las métricas del resumen dejan de contarlas."
    )
    if bloqueado:
        detalle += " El número sigue bloqueado: para el bloqueo se conserva solo el número."
    return render_template(
        "panel/confirmar_eliminacion.html",
        titulo="Borrar los datos de un comprador",
        texto=f"¿Borrar los datos de {identificacion}? Hágalo cuando el comprador lo pida.",
        detalle=detalle,
        volver=volver,
        boton="Borrar sus datos",
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
