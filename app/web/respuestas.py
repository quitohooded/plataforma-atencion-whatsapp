"""CU15 Administrar respuestas propias a preguntas frecuentes."""

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from ..bot.prueba import probar_respuesta
from ..modelos import RespuestaFrecuente
from ..servicios import ErrorValidacion
from ..servicios import respuestas as srv
from ..utilidades import tiempo
from . import del_comercio, destino_seguro, requiere_onboarding

bp = Blueprint("respuestas", __name__, url_prefix="/respuestas")

CAMPOS = ("titulo", "palabras", "respuesta", "plantilla")


def _volver() -> str:
    return destino_seguro(request.values.get("siguiente"), url_for("respuestas.listado"))


def _valores_del_formulario() -> dict:
    return {c: request.form.get(c, "") for c in CAMPOS}


@bp.get("")
@requiere_onboarding
def listado():
    comercio = g.comercio
    return render_template(
        "panel/respuestas.html",
        respuestas=comercio.respuestas_frecuentes,
        usos=srv.usos(comercio),
        dias=srv.DIAS_METRICA,
        plantillas=srv.plantillas_disponibles(comercio),
        sugerencias=srv.sugerencias(comercio),
        maximo=srv.MAX_RESPUESTAS,
    )


@bp.route("/nueva", methods=["GET", "POST"])
@requiere_onboarding
def nueva():
    comercio = g.comercio
    error, campos = None, []
    valores = srv.valores_de_plantilla(request.args.get("plantilla"))
    if request.method == "POST":
        valores = _valores_del_formulario()
        try:
            creada = srv.crear(
                comercio, valores["titulo"], valores["palabras"], valores["respuesta"], valores["plantilla"]
            )
        except ErrorValidacion as e:
            error, campos = e.mensaje, e.campos
        else:
            flash(f"Respuesta «{creada.titulo}» guardada. El bot la usa desde la próxima consulta.", "exito")
            return redirect(url_for("respuestas.listado"))
    return render_template(
        "panel/respuesta_editar.html",
        respuesta_frecuente=None,
        valores=valores,
        error=error,
        campos_error=campos,
        volver=url_for("respuestas.listado"),
    ), (400 if error else 200)


@bp.route("/<int:id_respuesta>/editar", methods=["GET", "POST"])
@requiere_onboarding
def editar(id_respuesta: int):
    comercio = g.comercio
    respuesta_frecuente = del_comercio(RespuestaFrecuente, id_respuesta)
    error, campos = None, []
    valores = srv.valores_de(respuesta_frecuente)
    if request.method == "POST":
        valores = {**_valores_del_formulario(), "plantilla": respuesta_frecuente.plantilla or ""}
        try:
            srv.actualizar(comercio, respuesta_frecuente, valores["titulo"], valores["palabras"], valores["respuesta"])
        except ErrorValidacion as e:
            error, campos = e.mensaje, e.campos
        else:
            flash("Respuesta actualizada. El bot usa los cambios desde la próxima consulta.", "exito")
            return redirect(_volver())
    return render_template(
        "panel/respuesta_editar.html",
        respuesta_frecuente=respuesta_frecuente,
        valores=valores,
        error=error,
        campos_error=campos,
        volver=_volver(),
    ), (400 if error else 200)


@bp.post("/<int:id_respuesta>/estado")
@requiere_onboarding
def cambiar_estado(id_respuesta: int):
    respuesta_frecuente = del_comercio(RespuestaFrecuente, id_respuesta)
    activa = request.form.get("activa") == "1"
    srv.cambiar_activa(respuesta_frecuente, activa)
    if activa:
        flash(f"«{respuesta_frecuente.titulo}» vuelve a responderse.", "exito")
    else:
        flash(f"«{respuesta_frecuente.titulo}» quedó desactivada: se conserva, pero el bot no la usa.", "info")
    return redirect(_volver())


@bp.route("/<int:id_respuesta>/eliminar", methods=["GET", "POST"])
@requiere_onboarding
def eliminar(id_respuesta: int):
    respuesta_frecuente = del_comercio(RespuestaFrecuente, id_respuesta)
    if request.method == "POST":
        titulo = respuesta_frecuente.titulo
        srv.eliminar(respuesta_frecuente)
        flash(f"Respuesta «{titulo}» eliminada.", "exito")
        return redirect(_volver())
    return render_template(
        "panel/confirmar_eliminacion.html",
        titulo="Eliminar respuesta",
        texto=f"¿Eliminar la respuesta «{respuesta_frecuente.titulo}»?",
        detalle="Las consultas que respondió se conservan en el historial. Si solo quiere dejar de usarla por un "
        "tiempo, puede desactivarla.",
        volver=_volver(),
    )


@bp.post("/probar")
@requiere_onboarding
def probar():
    """Prueba la respuesta en edición con un mensaje de ejemplo, sin guardarla."""
    comercio = g.comercio
    datos = request.get_json(silent=True) or {}
    mensaje = str(datos.get("mensaje") or "").strip()[:500]
    if not mensaje:
        return jsonify(error="Escriba un mensaje como lo mandaría un cliente."), 400
    existente = None
    if datos.get("id_respuesta"):
        try:
            existente = del_comercio(RespuestaFrecuente, int(datos["id_respuesta"]))
        except (TypeError, ValueError):
            return jsonify(error="La respuesta no existe."), 404
    try:
        borrador = srv.validar(
            comercio,
            str(datos.get("titulo") or "Respuesta en edición"),
            str(datos.get("palabras") or ""),
            str(datos.get("respuesta") or ""),
            excluir=existente,
        )
    except ErrorValidacion as e:
        return jsonify(error=e.mensaje), 400
    clave = existente.clave if existente else "borrador"
    resultado = probar_respuesta(
        comercio,
        srv.como_datos(borrador, clave, existente.id_respuesta if existente else None),
        mensaje,
        tiempo.ahora(),
    )
    return jsonify(resultado)
