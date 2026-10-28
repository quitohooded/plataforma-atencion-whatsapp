"""Manejo de formularios compartido entre el onboarding (CU03) y las secciones del panel.

El onboarding reutiliza los mismos formularios de zonas, medios de pago y
horarios (CU04 a CU06) en forma secuencial, tal como lo modela la relación de
inclusión del diagrama de casos de uso.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from flask import request

from ..modelos import Comercio
from ..servicios import ErrorValidacion
from ..servicios import horarios as srv_horarios
from ..servicios import medios_pago as srv_medios
from ..servicios import zonas as srv_zonas


@dataclass
class EstadoFormulario:
    exito: bool = False
    error: str | None = None
    valores: dict = field(default_factory=dict)


CAMPOS_ZONA = ["descripcion", "cp_desde", "cp_hasta", "plazo_min_dias", "plazo_max_dias"]


def alta_zona(comercio: Comercio) -> EstadoFormulario:
    valores = {c: request.form.get(c, "").strip() for c in CAMPOS_ZONA}
    try:
        srv_zonas.crear_zona(comercio, valores)
    except ErrorValidacion as e:
        return EstadoFormulario(False, e.mensaje, valores)
    return EstadoFormulario(True)


def alta_medio(comercio: Comercio) -> EstadoFormulario:
    valores = {c: request.form.get(c, "").strip() for c in ("tipo", "nombre_otro", "detalle")}
    try:
        srv_medios.crear_medio(comercio, valores["tipo"], valores["nombre_otro"], valores["detalle"])
    except ErrorValidacion as e:
        return EstadoFormulario(False, e.mensaje, valores)
    return EstadoFormulario(True)


@dataclass
class EstadoHorarios:
    dias: list
    guardado: bool = False
    error: str | None = None
    accion: str = "guardar"


def procesar_horarios(comercio: Comercio) -> EstadoHorarios:
    """Procesa el formulario semanal: copiar un día a los hábiles o guardar (CU06)."""
    dias = srv_horarios.leer_formulario(request.form)
    accion = request.form.get("accion", "guardar")
    partes = accion.split("_")
    try:
        dia = max(0, min(int(partes[1]), 6)) if len(partes) > 1 else 0
        indice = int(partes[2]) if len(partes) > 2 else -1
    except ValueError:
        dia, indice = 0, -1

    if partes[0] == "copiar":
        srv_horarios.copiar_a_habiles(dias, dia)
        return EstadoHorarios(dias, accion="copiar")
    if partes[0] == "agregar":
        # Jornada partida: segunda franja para el mismo día (CU06, flujo alternativo).
        dias[dia].atiende = True
        dias[dia].franjas.append(("", ""))
        return EstadoHorarios(dias, accion="agregar")
    if partes[0] == "quitar":
        if 0 <= indice < len(dias[dia].franjas):
            dias[dia].franjas.pop(indice)
        return EstadoHorarios(dias, accion="quitar")

    if not srv_horarios.validar(dias):
        return EstadoHorarios(dias, error="Revise los días marcados: hay horarios con errores.")
    srv_horarios.guardar(comercio, dias)
    return EstadoHorarios(dias, guardado=True)
