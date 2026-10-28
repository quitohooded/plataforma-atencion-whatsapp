"""CU04 Administrar zonas de envío: alta, edición, eliminación e importación de planilla."""

import json

from flask import Blueprint, Response, flash, g, redirect, render_template, request, url_for

from ..modelos import ZonaEnvio, formato_pesos
from ..servicios import ErrorValidacion
from ..servicios import zonas as srv
from . import del_comercio, destino_seguro, requiere_onboarding, requiere_sesion
from .comunes import CAMPOS_ZONA, alta_zona

bp = Blueprint("zonas", __name__, url_prefix="/zonas")


def _volver() -> str:
    return destino_seguro(request.values.get("siguiente"), url_for("zonas.listado"))


@bp.route("", methods=["GET", "POST"])
@requiere_onboarding
def listado():
    estado = None
    if request.method == "POST":
        estado = alta_zona(g.comercio)
        if estado.exito:
            flash("Zona agregada. El bot la usa desde la próxima consulta.", "exito")
            return redirect(url_for("zonas.listado"))
    return render_template("panel/zonas.html", estado=estado, volver=url_for("zonas.listado")), (
        400 if estado and estado.error else 200
    )


@bp.route("/<int:id_zona>/editar", methods=["GET", "POST"])
@requiere_sesion
def editar(id_zona: int):
    zona = del_comercio(ZonaEnvio, id_zona)
    error = None
    valores = {c: getattr(zona, c) for c in CAMPOS_ZONA}
    if valores["costo"] is None:
        valores["costo"] = ""
    if request.method == "POST":
        valores = {c: request.form.get(c, "").strip() for c in CAMPOS_ZONA}
        try:
            srv.actualizar_zona(g.comercio, zona, valores)
        except ErrorValidacion as e:
            error = e.mensaje
        else:
            flash("Zona actualizada.", "exito")
            return redirect(_volver())
    return render_template("panel/zona_editar.html", zona=zona, valores=valores, error=error, volver=_volver()), (
        400 if error else 200
    )


@bp.route("/<int:id_zona>/eliminar", methods=["GET", "POST"])
@requiere_sesion
def eliminar(id_zona: int):
    zona = del_comercio(ZonaEnvio, id_zona)
    if request.method == "POST":
        descripcion = zona.descripcion
        srv.eliminar_zona(zona)
        flash(f"Zona «{descripcion}» eliminada.", "exito")
        return redirect(_volver())
    return render_template(
        "panel/confirmar_eliminacion.html",
        titulo="Eliminar zona de envío",
        texto=f"¿Eliminar la zona «{zona.descripcion}» ({zona.rango_texto}, {zona.plazo_texto})?",
        detalle="El bot dejará de informar el plazo para esos códigos postales.",
        volver=_volver(),
    )


@bp.post("/envio-gratis")
@requiere_sesion
def envio_gratis():
    """Monto de compra desde el que el envío es gratis (lo informa el bot junto al costo)."""
    try:
        monto = srv.actualizar_envio_gratis(g.comercio, request.form.get("envio_gratis_desde", ""))
    except ErrorValidacion as e:
        flash(e.mensaje, "error")
    else:
        if monto:
            flash(f"Listo: el bot informa envío gratis en compras desde {formato_pesos(monto)}.", "exito")
        else:
            flash("Listo: el bot ya no informa envío gratis.", "exito")
    return redirect(_volver())


@bp.post("/importar")
@requiere_sesion
def importar():
    archivo = request.files.get("planilla")
    volver = _volver()
    if not archivo or not archivo.filename:
        flash("Seleccione un archivo CSV para importar.", "error")
        return redirect(volver)
    if not archivo.filename.lower().endswith((".csv", ".txt")):
        flash("El archivo debe ser una planilla en formato CSV.", "error")
        return redirect(volver)
    try:
        resultado = srv.analizar_csv(g.comercio, archivo.read())
    except ErrorValidacion as e:
        flash(e.mensaje, "error")
        return redirect(volver)
    filas_json = json.dumps([z.como_dict() for z in resultado.validas], ensure_ascii=False)
    return render_template(
        "panel/zonas_importar.html",
        resultado=resultado,
        filas_json=filas_json,
        volver=volver,
        nombre_archivo=archivo.filename,
    )


@bp.post("/importar/confirmar")
@requiere_sesion
def confirmar_importacion():
    try:
        filas = json.loads(request.form.get("filas", "[]"))
        if not isinstance(filas, list):
            raise ValueError
    except ValueError:
        flash("No fue posible leer las filas a importar. Vuelva a cargar la planilla.", "error")
        return redirect(_volver())
    agregadas = srv.importar(g.comercio, [f for f in filas if isinstance(f, dict)])
    if agregadas == 1:
        flash("Se incorporó 1 zona desde la planilla.", "exito")
    elif agregadas:
        flash(f"Se incorporaron {agregadas} zonas desde la planilla.", "exito")
    else:
        flash("No se incorporó ninguna zona: las filas ya no son válidas.", "error")
    return redirect(_volver())


@bp.get("/plantilla.csv")
@requiere_sesion
def plantilla():
    return Response(
        srv.plantilla_csv().encode("utf-8"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=plantilla-zonas-de-envio.csv"},
    )
