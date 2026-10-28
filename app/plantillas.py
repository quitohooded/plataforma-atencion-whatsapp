"""Filtros y variables globales de las plantillas Jinja."""

from __future__ import annotations

import re

from flask import Flask, current_app, g
from markupsafe import Markup, escape

from .modelos import ALERTAS_QUE_HACER, EstadoComercio, ResultadoConsulta, TemaConsulta, formato_pesos
from .utilidades import tiempo

_URL = re.compile(r"(https?://[^\s<>\"]+[^\s<>\".,;:!?)\]])")
_NEGRITA = re.compile(r"\*([^*\n]+)\*")


def formato_whatsapp(texto: str | None) -> Markup:
    """Muestra un mensaje con el formato de WhatsApp: *negrita* y enlaces. El texto se
    escapa antes de aplicar el formato, así que no puede inyectar HTML."""
    seguro = str(escape(texto or ""))
    seguro = _URL.sub(
        lambda m: f'<a href="{m.group(1)}" target="_blank" rel="noopener noreferrer nofollow">{m.group(1)}</a>', seguro
    )
    seguro = _NEGRITA.sub(r"<strong>\1</strong>", seguro)
    return Markup(seguro)


def registrar(app: Flask) -> None:
    app.jinja_env.filters["fecha_hora"] = tiempo.formato_fecha_hora
    app.jinja_env.filters["fecha_larga"] = tiempo.formato_fecha_larga
    app.jinja_env.filters["relativo"] = tiempo.formato_relativo
    app.jinja_env.filters["miles"] = lambda n: f"{n:,}".replace(",", ".")
    app.jinja_env.filters["pesos"] = formato_pesos
    app.jinja_env.filters["formato_whatsapp"] = formato_whatsapp
    # Globales: también disponibles dentro de las macros importadas.
    app.jinja_env.globals.update(
        plataforma=app.config["PLATAFORMA_NOMBRE"],
        simulador_habilitado=app.config["SIMULADOR_HABILITADO"],
    )
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

    def contar_pendientes() -> int:
        from .servicios.metricas import contar_pendientes as contar

        comercio = getattr(g, "comercio", None)
        return contar(comercio) if comercio else 0

    @app.context_processor
    def variables_globales():
        return {
            "contar_pendientes": contar_pendientes,
            "plataforma": current_app.config["PLATAFORMA_NOMBRE"],
            "simulador_habilitado": current_app.config["SIMULADOR_HABILITADO"],
            "comercio_actual": getattr(g, "comercio", None),
            "EstadoComercio": EstadoComercio,
            "TemaConsulta": TemaConsulta,
            "ResultadoConsulta": ResultadoConsulta,
            "DIAS_SEMANA": tiempo.DIAS_SEMANA,
            "textos_alerta": ALERTAS_QUE_HACER,
        }
