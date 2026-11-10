"""Panel de SuperAdmin SaaS (Pilar 6).

Tablero de control global de la plataforma SaaS:
- Monitoreo de MRR estimado, distribución de planes y transacciones aprobadas.
- Flota consolidada de comercios activos, canales (WABA, Web, Simulador) y cuotas IA.
- Operaciones de plataforma: cambio de plan, otorgamiento de créditos de cortesía
  y activación o pausa del bot de cualquier comercio.
"""

from __future__ import annotations

import logging
import os
from functools import wraps

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import select

from ..extensiones import db
from ..modelos import Comercio, Usuario, normalizar_email
from ..servicios import analitica
from . import destino_seguro

log = logging.getLogger(__name__)

bp = Blueprint("superadmin", __name__, url_prefix="/admin-saas")


def es_superadmin_autenticado() -> bool:
    """Verifica si la sesión actual cuenta con privilegios de SuperAdmin."""
    if session.get("superadmin_auth") is True:
        return True

    usuario = getattr(g, "usuario", None)
    if usuario and getattr(usuario, "es_superadmin", False):
        return True

    superadmin_email = (
        current_app.config.get("SUPERADMIN_EMAIL") or os.environ.get("SUPERADMIN_EMAIL") or ""
    ).strip().lower()

    return bool(usuario and superadmin_email and getattr(usuario, "email", "").lower() == superadmin_email)


def requiere_superadmin(vista):
    """Decorador que restringe el acceso al panel SuperAdmin."""

    @wraps(vista)
    def envoltura(*args, **kwargs):
        if not es_superadmin_autenticado():
            return redirect(url_for("superadmin.ingreso", siguiente=request.full_path.rstrip("?")))
        return vista(*args, **kwargs)

    return envoltura


@bp.route("/ingreso", methods=["GET", "POST"])
def ingreso():
    """Autenticación para ingresar al panel SuperAdmin."""
    if es_superadmin_autenticado():
        return redirect(url_for("superadmin.dashboard"))

    siguiente = request.args.get("siguiente") or request.form.get("siguiente") or url_for("superadmin.dashboard")

    if request.method == "POST":
        clave = (request.form.get("clave") or request.form.get("contrasena") or "").strip()
        email = (request.form.get("email") or "").strip()

        superadmin_clave = (
            current_app.config.get("SUPERADMIN_CLAVE") or os.environ.get("SUPERADMIN_CLAVE") or ""
        ).strip()
        superadmin_email = (
            current_app.config.get("SUPERADMIN_EMAIL") or os.environ.get("SUPERADMIN_EMAIL") or ""
        ).strip().lower()

        autenticado = False

        # 1. Clave maestra de SuperAdmin en configuración
        if superadmin_clave and clave == superadmin_clave:
            autenticado = True

        # 2. Email y contraseña de un usuario del sistema con rol superadmin o email designado
        if not autenticado and email and clave:
            usuario = db.session.scalar(select(Usuario).where(Usuario.email == normalizar_email(email)))
            if usuario and usuario.autenticar(email, clave) and (
                usuario.es_superadmin or (superadmin_email and usuario.email.lower() == superadmin_email)
            ):
                autenticado = True

        # 3. Clave de cualquier usuario superadmin existente
        if not autenticado and clave:
            usuarios_super = db.session.scalars(select(Usuario).where(Usuario.es_superadmin.is_(True))).all()
            for u in usuarios_super:
                if u.autenticar(u.email, clave):
                    autenticado = True
                    break

        if autenticado:
            session["superadmin_auth"] = True
            flash("Ingreso exitoso al panel SuperAdmin.", "exito")
            return redirect(destino_seguro(siguiente, url_for("superadmin.dashboard")))

        return render_template(
            "superadmin/ingreso.html",
            error="Credenciales o clave de superadmin incorrectas.",
            siguiente=siguiente,
        ), 401

    return render_template("superadmin/ingreso.html", error=None, siguiente=siguiente)


@bp.post("/salir")
def salir():
    """Cierra la sesión de SuperAdmin."""
    session.pop("superadmin_auth", None)
    flash("Sesión de SuperAdmin finalizada.", "info")
    return redirect(url_for("superadmin.ingreso"))


@bp.get("")
@requiere_superadmin
def dashboard():
    """Tablero principal con métricas SaaS y tabla de flota de comercios."""
    metricas = analitica.metricas_superadmin_saas()
    return render_template("superadmin/dashboard.html", metricas=metricas)


@bp.post("/comercios/<int:id_comercio>/plan")
@requiere_superadmin
def cambiar_plan(id_comercio: int):
    """Cambia el plan comercial de un comercio."""
    comercio = db.session.get(Comercio, id_comercio)
    if not comercio:
        abort(404)

    nuevo_plan = request.form.get("plan", "").strip().upper()
    try:
        analitica.cambiar_plan_comercio(comercio, nuevo_plan)
        flash(f"Plan de «{comercio.nombre}» actualizado a {comercio.plan.etiqueta}.", "exito")
    except ValueError as e:
        flash(str(e), "error")

    return redirect(url_for("superadmin.dashboard"))


@bp.post("/comercios/<int:id_comercio>/creditos")
@requiere_superadmin
def otorgar_creditos(id_comercio: int):
    """Otorga un pack de créditos de cortesía a un comercio."""
    comercio = db.session.get(Comercio, id_comercio)
    if not comercio:
        abort(404)

    try:
        cantidad = int(request.form.get("creditos", 0))
        analitica.otorgar_creditos_comercio(comercio, cantidad)
        flash(f"Se acreditaron +{cantidad} créditos de cortesía a «{comercio.nombre}».", "exito")
    except (ValueError, TypeError) as e:
        flash(f"No fue posible otorgar los créditos: {e}", "error")

    return redirect(url_for("superadmin.dashboard"))


@bp.post("/comercios/<int:id_comercio>/estado")
@requiere_superadmin
def cambiar_estado(id_comercio: int):
    """Pausa o reactiva el bot de un comercio."""
    comercio = db.session.get(Comercio, id_comercio)
    if not comercio:
        abort(404)

    accion = request.form.get("accion", "").strip().lower()
    activar = accion in ("activar", "activa", "1", "true")
    analitica.cambiar_estado_bot_comercio(comercio, activar=activar)

    if activar:
        flash(f"Bot de «{comercio.nombre}» activado correctamente.", "exito")
    else:
        flash(f"Bot de «{comercio.nombre}» pausado.", "alerta")

    return redirect(url_for("superadmin.dashboard"))
