"""Módulos web: panel de administración, webhook de WhatsApp y simulador."""

from __future__ import annotations

from functools import wraps
from urllib.parse import urlparse

from flask import Flask, abort, g, redirect, request, session, url_for

from ..extensiones import db
from ..modelos import Comercio, Usuario

CLAVE_USUARIO = "id_usuario"


def registrar_blueprints(app: Flask) -> None:
    from . import (
        activacion,
        auth,
        bloqueos,
        comercio,
        cuenta,
        historial,
        horarios,
        medios_pago,
        onboarding,
        publico,
        respuestas,
        resumen,
        simulador,
        webhook,
        zonas,
    )

    for modulo in (
        publico,
        auth,
        onboarding,
        zonas,
        medios_pago,
        horarios,
        respuestas,
        activacion,
        resumen,
        historial,
        bloqueos,
        comercio,
        cuenta,
        webhook,
        simulador,
    ):
        app.register_blueprint(modulo.bp)

    @app.before_request
    def cargar_sesion():
        g.usuario = None
        g.comercio = None
        id_usuario = session.get(CLAVE_USUARIO)
        if id_usuario:
            usuario = db.session.get(Usuario, id_usuario)
            if usuario:
                g.usuario = usuario
                g.comercio = usuario.comercio
            else:
                session.pop(CLAVE_USUARIO, None)


def iniciar_sesion_usuario(usuario: Usuario) -> None:
    session.clear()
    session[CLAVE_USUARIO] = usuario.id_usuario
    session.permanent = False


def destino_inicial(comercio: Comercio) -> str:
    """A dónde ir al iniciar sesión (CU02, paso 4)."""
    if not comercio.onboarding_completo:
        if comercio.paso_onboarding >= Comercio.PASO_RESUMEN:
            return url_for("onboarding.resumen")
        return url_for("onboarding.paso", numero=max(1, comercio.paso_onboarding))
    if comercio.fue_activado:
        return url_for("resumen.inicio")
    return url_for("activacion.inicio")


def requiere_sesion(vista):
    """Precondición de los casos de uso del panel: sesión iniciada (CU02)."""

    @wraps(vista)
    def envoltura(*args, **kwargs):
        if g.get("comercio") is None:
            return redirect(url_for("auth.ingresar", siguiente=request.full_path.rstrip("?")))
        return vista(*args, **kwargs)

    return envoltura


def requiere_onboarding(vista):
    """Las secciones del panel se habilitan una vez completado el onboarding (CU03)."""

    @wraps(vista)
    @requiere_sesion
    def envoltura(*args, **kwargs):
        if not g.comercio.onboarding_completo:
            return redirect(url_for("onboarding.paso_actual"))
        return vista(*args, **kwargs)

    return envoltura


def del_comercio(modelo, identificador: int):
    """Obtiene un registro solo si pertenece al comercio de la sesión (RF13). Si no, 404."""
    objeto = db.session.get(modelo, identificador)
    if objeto is None or getattr(objeto, "id_comercio", None) != g.comercio.id_comercio:
        abort(404)
    return objeto


def destino_seguro(valor: str | None, por_defecto: str) -> str:
    """Solo se aceptan rutas internas para evitar redirecciones abiertas."""
    if not valor:
        return por_defecto
    partes = urlparse(valor)
    if partes.scheme or partes.netloc or not valor.startswith("/") or valor.startswith("//"):
        return por_defecto
    return valor
