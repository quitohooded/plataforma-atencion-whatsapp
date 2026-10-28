"""CU03 Completar onboarding: formulario guiado en cuatro pasos y resumen."""

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..extensiones import db
from ..modelos import Comercio
from ..servicios import ErrorValidacion
from ..servicios import horarios as srv_horarios
from ..servicios.cuentas import validar_datos_negocio
from ..servicios.medios_pago import EJEMPLOS_DETALLE, MEDIOS_PREDEFINIDOS
from . import destino_inicial, requiere_sesion
from .auth import RUBROS_SUGERIDOS
from .comunes import alta_medio, alta_zona, procesar_horarios

bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")

PASOS = [
    (1, "Datos del negocio"),
    (2, "Zonas de envío"),
    (3, "Medios de pago"),
    (4, "Horarios de atención"),
]


def _avanzar(comercio: Comercio, hasta: int) -> None:
    if comercio.paso_onboarding < hasta:
        comercio.paso_onboarding = hasta
    db.session.commit()


def _url_paso(numero: int) -> str:
    if numero >= Comercio.PASO_RESUMEN:
        return url_for("onboarding.resumen")
    return url_for("onboarding.paso", numero=numero)


def _contexto(numero: int, **extra):
    return dict(pasos=PASOS, paso_actual=numero, paso_alcanzado=g.comercio.paso_onboarding, **extra)


@bp.get("")
@requiere_sesion
def paso_actual():
    """Retoma el onboarding en el paso pendiente (CU03, flujo alternativo «Interrupción»)."""
    comercio = g.comercio
    if comercio.onboarding_completo:
        return redirect(destino_inicial(comercio))
    return redirect(_url_paso(comercio.paso_onboarding))


@bp.route("/paso/<int:numero>", methods=["GET", "POST"])
@requiere_sesion
def paso(numero: int):
    comercio = g.comercio
    if comercio.onboarding_completo:
        return redirect(destino_inicial(comercio))
    if numero < 1 or numero > 4:
        return redirect(_url_paso(comercio.paso_onboarding))
    if numero > comercio.paso_onboarding:
        # No se puede saltar pasos: se vuelve al pendiente.
        return redirect(_url_paso(comercio.paso_onboarding))

    return {1: _paso_datos, 2: _paso_zonas, 3: _paso_medios, 4: _paso_horarios}[numero]()


def _paso_datos():
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
            _avanzar(comercio, 2)
            return redirect(_url_paso(2))
    return render_template(
        "onboarding/paso_datos.html",
        **_contexto(1, valores=valores, error=error, campos_error=campos_error, rubros=RUBROS_SUGERIDOS),
    ), (400 if error else 200)


def _paso_zonas():
    comercio = g.comercio
    estado = None
    error_paso = None
    if request.method == "POST":
        if request.form.get("accion") == "continuar":
            if not comercio.zonas:
                error_paso = "Cargue al menos una zona de envío para continuar."
            else:
                _avanzar(comercio, 3)
                return redirect(_url_paso(3))
        else:
            estado = alta_zona(comercio)
            if estado.exito:
                flash("Zona agregada.", "exito")
                return redirect(_url_paso(2))
    return render_template(
        "onboarding/paso_zonas.html",
        **_contexto(2, estado=estado, error_paso=error_paso, volver=_url_paso(2)),
    ), (400 if (error_paso or (estado and estado.error)) else 200)


def _paso_medios():
    comercio = g.comercio
    estado = None
    error_paso = None
    if request.method == "POST":
        if request.form.get("accion") == "continuar":
            if not comercio.medios_activos:
                error_paso = "Cargue al menos un medio de pago activo para continuar."
            else:
                _avanzar(comercio, 4)
                return redirect(_url_paso(4))
        else:
            estado = alta_medio(comercio)
            if estado.exito:
                flash("Medio de pago agregado.", "exito")
                return redirect(_url_paso(3))
    return render_template(
        "onboarding/paso_medios.html",
        **_contexto(
            3,
            estado=estado,
            error_paso=error_paso,
            medios=MEDIOS_PREDEFINIDOS,
            ejemplos=EJEMPLOS_DETALLE,
            volver=_url_paso(3),
        ),
    ), (400 if (error_paso or (estado and estado.error)) else 200)


def _paso_horarios():
    comercio = g.comercio
    dias = srv_horarios.desde_comercio(comercio)
    error = None
    if request.method == "POST":
        resultado = procesar_horarios(comercio)
        dias, error = resultado.dias, resultado.error
        if resultado.guardado:
            if not srv_horarios.tiene_horarios(dias):
                error = "Indique al menos un día y horario de atención para continuar."
            else:
                _avanzar(comercio, Comercio.PASO_RESUMEN)
                return redirect(_url_paso(Comercio.PASO_RESUMEN))
    elif not comercio.horarios:
        # Propuesta inicial editable: lunes a viernes de 9 a 18.
        for d in dias[:5]:
            d.atiende, d.franjas = True, [("09:00", "18:00")]
    return render_template("onboarding/paso_horarios.html", **_contexto(4, dias=dias, error=error)), (
        400 if error else 200
    )


@bp.get("/resumen")
@requiere_sesion
def resumen():
    comercio = g.comercio
    if comercio.onboarding_completo:
        return redirect(destino_inicial(comercio))
    if comercio.paso_onboarding < Comercio.PASO_RESUMEN:
        return redirect(_url_paso(comercio.paso_onboarding))
    from ..bot.contexto import DatosComercio
    from ..bot.respuestas import lineas_horario

    return render_template(
        "onboarding/resumen.html",
        **_contexto(5, lineas_horario=lineas_horario(DatosComercio.desde_comercio(comercio))),
    )


@bp.post("/confirmar")
@requiere_sesion
def confirmar():
    comercio = g.comercio
    faltantes = []
    if not comercio.zonas:
        faltantes.append("zonas de envío")
    if not comercio.medios_activos:
        faltantes.append("medios de pago")
    if not comercio.horarios:
        faltantes.append("horarios de atención")
    if faltantes:
        flash("Falta cargar: " + ", ".join(faltantes) + ".", "error")
        return redirect(url_for("onboarding.paso_actual"))
    _avanzar(comercio, Comercio.PASO_COMPLETO)
    flash("Información confirmada. Pruebe las respuestas y active el bot.", "exito")
    return redirect(url_for("activacion.inicio"))
