"""CU05 Administrar medios de pago."""

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..modelos import MedioPago
from ..servicios import ErrorValidacion
from ..servicios import medios_pago as srv
from . import del_comercio, destino_seguro, requiere_onboarding, requiere_sesion
from .comunes import alta_medio

bp = Blueprint("medios_pago", __name__, url_prefix="/medios-de-pago")


def _volver() -> str:
    return destino_seguro(request.values.get("siguiente"), url_for("medios_pago.listado"))


@bp.route("", methods=["GET", "POST"])
@requiere_onboarding
def listado():
    estado = None
    if request.method == "POST":
        estado = alta_medio(g.comercio)
        if estado.exito:
            flash("Medio de pago agregado. El bot lo informa desde la próxima consulta.", "exito")
            return redirect(url_for("medios_pago.listado"))
    return render_template(
        "panel/medios.html",
        estado=estado,
        medios=srv.MEDIOS_PREDEFINIDOS,
        ejemplos=srv.EJEMPLOS_DETALLE,
        volver=url_for("medios_pago.listado"),
    ), (400 if estado and estado.error else 200)


@bp.route("/<int:id_medio>/editar", methods=["GET", "POST"])
@requiere_sesion
def editar(id_medio: int):
    medio = del_comercio(MedioPago, id_medio)
    error = None
    tipo = srv.tipo_de(medio)
    valores = {"tipo": tipo, "nombre_otro": medio.nombre if tipo == "Otro" else "", "detalle": medio.detalle}
    if request.method == "POST":
        valores = {c: request.form.get(c, "").strip() for c in ("tipo", "nombre_otro", "detalle")}
        try:
            srv.actualizar_medio(g.comercio, medio, valores["tipo"], valores["nombre_otro"], valores["detalle"])
        except ErrorValidacion as e:
            error = e.mensaje
        else:
            flash("Medio de pago actualizado.", "exito")
            return redirect(_volver())
    return render_template(
        "panel/medio_editar.html",
        medio=medio,
        valores=valores,
        error=error,
        medios=srv.MEDIOS_PREDEFINIDOS,
        ejemplos=srv.EJEMPLOS_DETALLE,
        volver=_volver(),
    ), (400 if error else 200)


@bp.post("/<int:id_medio>/estado")
@requiere_sesion
def cambiar_estado(id_medio: int):
    medio = del_comercio(MedioPago, id_medio)
    activar = request.form.get("activo") == "1"
    srv.cambiar_activo(medio, activar)
    if activar:
        flash(f"«{medio.nombre}» vuelve a informarse a los compradores.", "exito")
    else:
        flash(f"«{medio.nombre}» quedó desactivado: se conserva, pero el bot no lo informa.", "info")
    return redirect(_volver())


@bp.route("/<int:id_medio>/eliminar", methods=["GET", "POST"])
@requiere_sesion
def eliminar(id_medio: int):
    medio = del_comercio(MedioPago, id_medio)
    if request.method == "POST":
        nombre = medio.nombre
        srv.eliminar_medio(medio)
        flash(f"Medio de pago «{nombre}» eliminado.", "exito")
        return redirect(_volver())
    return render_template(
        "panel/confirmar_eliminacion.html",
        titulo="Eliminar medio de pago",
        texto=f"¿Eliminar «{medio.texto}»?",
        detalle="Si solo quiere dejar de informarlo por un tiempo, puede desactivarlo.",
        volver=_volver(),
    )
