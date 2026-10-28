"""Plataforma de atención automatizada de consultas frecuentes mediante WhatsApp.

Fábrica de la aplicación Flask: configura la base SQLite, registra los módulos
del panel web, el webhook de WhatsApp y el simulador.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from .config import Config

load_dotenv()


def create_app(config_object: type[Config] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _clave_secreta_local(Path(app.instance_path))
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        ruta = Path(app.instance_path) / "plataforma.db"
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{ruta.as_posix()}"

    if app.config.get("CONFIAR_EN_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from .extensiones import csrf, db

    db.init_app(app)
    csrf.init_app(app)

    from . import plantillas
    from .web import registrar_blueprints

    plantillas.registrar(app)
    registrar_blueprints(app)

    from .cli import registrar_comandos

    registrar_comandos(app)

    with app.app_context():
        inicializar_base()

    @app.errorhandler(404)
    def no_encontrado(_error):
        return render_template("errores/404.html"), 404

    @app.errorhandler(500)
    def error_interno(_error):
        return render_template("errores/500.html"), 500

    return app


def _clave_secreta_local(carpeta: Path) -> str:
    """Clave para firmar sesiones, generada una sola vez y guardada fuera del repositorio."""
    archivo = carpeta / "clave_secreta.txt"
    if archivo.exists():
        clave = archivo.read_text(encoding="utf-8").strip()
        if clave:
            return clave
    clave = secrets.token_hex(32)
    archivo.write_text(clave, encoding="utf-8")
    return clave


@event.listens_for(Engine, "connect")
def _activar_claves_foraneas(conexion, _registro):
    """SQLite no aplica las claves foráneas si no se activan en cada conexión."""
    try:
        cursor = conexion.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:  # otros motores no admiten el PRAGMA
        pass


def inicializar_base() -> None:
    """Crea las tablas si no existen y carga el catálogo inicial de palabras clave."""
    from .datos.palabras_clave import items_catalogo
    from .extensiones import db
    from .modelos import PalabraClave

    db.create_all()
    if not db.session.scalar(select(func.count()).select_from(PalabraClave)):
        db.session.add_all(PalabraClave(termino=t, tema=tema) for t, tema in items_catalogo())
        db.session.commit()
