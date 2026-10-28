"""Página de inicio pública y verificación de estado del servicio."""

from flask import Blueprint, g, jsonify, redirect, render_template

from . import destino_inicial

bp = Blueprint("publico", __name__)


@bp.get("/")
def inicio():
    if g.get("comercio"):
        return redirect(destino_inicial(g.comercio))
    return render_template("publico/inicio.html")


@bp.get("/salud")
def salud():
    return jsonify(estado="ok")
