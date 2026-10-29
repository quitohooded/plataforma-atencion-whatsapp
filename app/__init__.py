"""Plataforma de atención automatizada de consultas frecuentes mediante WhatsApp.

Fábrica de la aplicación Flask: configura la base SQLite, registra los módulos
del panel web, el webhook de WhatsApp y el simulador.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from flask import Flask, render_template, request
from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine

from .config import Config


def create_app(config_object: type[Config] | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config["SECRET_KEY_DEFINIDA"] = bool(app.config.get("SECRET_KEY"))
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

    from . import seguridad_web

    seguridad_web.registrar(app)

    from . import plantillas
    from .web import registrar_blueprints

    plantillas.registrar(app)
    registrar_blueprints(app)

    from .cli import registrar_comandos

    registrar_comandos(app)

    with app.app_context():
        _registro_anticipado(app)
        inicializar_base()

    if not app.testing:
        _informar_configuracion(app)

    @app.before_request
    def depuracion_diaria():
        if not request.path.startswith("/static/"):
            from .servicios.retencion import depurar_si_corresponde

            depurar_si_corresponde(app)

    @app.errorhandler(404)
    def no_encontrado(_error):
        return render_template("errores/404.html"), 404

    @app.errorhandler(500)
    def error_interno(_error):
        return render_template("errores/500.html"), 500

    return app


def _informar_configuracion(app: Flask) -> None:
    """Advierte en el registro las configuraciones inseguras o incompletas (O10)."""
    from .verificacion import problemas_de_configuracion

    log = logging.getLogger("app.configuracion")
    for problema in problemas_de_configuracion(app):
        (log.error if problema.nivel == "error" else log.warning)("%s", problema.texto)


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
    """SQLite no aplica las claves foráneas si no se activan en cada conexión. Con el registro
    anticipado (WAL), la escritura a disco puede ser «normal»: sigue siendo segura ante cortes."""
    try:
        cursor = conexion.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        modo = cursor.execute("PRAGMA journal_mode").fetchone()
        if modo and str(modo[0]).lower() == "wal":
            cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
    except Exception:  # otros motores no admiten el PRAGMA
        pass


def _registro_anticipado(app: Flask) -> None:
    """WAL: las lecturas del panel no esperan a las escrituras del bot y varias conversaciones
    simultáneas se atienden sin bloquearse. Queda guardado en el archivo de la base."""
    from .extensiones import db

    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if not app.config.get("SQLITE_WAL") or not uri.startswith("sqlite") or ":memory:" in uri or uri == "sqlite://":
        return
    with db.engine.connect() as conexion:
        conexion.exec_driver_sql("PRAGMA journal_mode=WAL")


def inicializar_base() -> None:
    """Crea las tablas que falten, aplica las migraciones y carga el catálogo de palabras clave."""
    from . import migraciones
    from .extensiones import db

    base_nueva = not inspect(db.engine).has_table("comercio")
    db.create_all()
    migraciones.aplicar(db, base_nueva=base_nueva)
