"""Panel de impacto comercial y analítica de valor para el comercio (Pilar 6).

Muestra al dueño del comercio el ROI directo de la plataforma:
- Ventas generadas en el chat ($ARS), pedidos y ticket promedio.
- Tiempo humano ahorrado (horas) por resolución automática 24/7.
- Tasa de resolución sin derivación humana.
- Radar de demanda no satisfecha (temas derivados y productos sin stock).
"""

from __future__ import annotations

import logging

from flask import Blueprint, g, render_template, request

from ..servicios import analitica
from . import requiere_onboarding

log = logging.getLogger(__name__)

bp = Blueprint("analitica", __name__, url_prefix="/panel/analitica")


@bp.get("")
@requiere_onboarding
def inicio():
    comercio = g.comercio
    periodo = request.args.get("periodo", "30")
    try:
        metricas = analitica.metricas_comercio_analitica(comercio, periodo=periodo)
    except Exception:
        log.exception("Error al calcular analítica de negocio para el comercio %s", comercio.id_comercio)
        return render_template(
            "panel/analitica.html",
            error_carga=True,
            metricas=None,
            periodos=analitica.PERIODOS_ANALITICA,
            periodo=periodo,
            seccion="analitica",
        ), 500

    return render_template(
        "panel/analitica.html",
        error_carga=False,
        metricas=metricas,
        periodos=analitica.PERIODOS_ANALITICA,
        periodo=metricas.periodo,
        seccion="analitica",
    )
