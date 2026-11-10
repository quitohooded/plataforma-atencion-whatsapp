"""Pruebas del Sprint 7: Monitoreo en vivo con Sentry, Términos Comerciales SaaS,
Ley 25.326, automatización de respaldos offsite y verificación de scripts de despliegue.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.config import ConfigPruebas
from app.extensiones import db
from app.verificacion import problemas_de_configuracion


def _obtener_bash() -> str | None:
    """Detecta un intérprete bash funcional en el entorno (Linux o Git Bash en Windows)."""
    ejecutable = shutil.which("bash")
    if ejecutable:
        try:
            res = subprocess.run([ejecutable, "-c", "echo ok"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and "ok" in res.stdout:
                return ejecutable
        except Exception:
            pass

    rutas_posibles = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    for ruta in rutas_posibles:
        if os.path.exists(ruta):
            return ruta
    return None


# ==============================================================================
# 1. Monitoreo en Vivo con Sentry
# ==============================================================================


def test_sentry_no_se_inicializa_en_modo_testing():
    class ConfigConSentry(ConfigPruebas):
        SENTRY_DSN = "https://public@sentry.example.org/1"
        TESTING = True

    with patch("sentry_sdk.init") as mock_init:
        aplicacion = create_app(ConfigConSentry)
        mock_init.assert_not_called()
        with aplicacion.app_context():
            db.session.remove()
            db.engine.dispose()


def test_sentry_no_se_inicializa_sin_dsn():
    class ConfigSinDSN(ConfigPruebas):
        SENTRY_DSN = ""
        TESTING = False

    with patch("sentry_sdk.init") as mock_init:
        aplicacion = create_app(ConfigSinDSN)
        mock_init.assert_not_called()
        with aplicacion.app_context():
            db.session.remove()
            db.engine.dispose()


def test_sentry_se_inicializa_con_dsn_fuera_de_testing():
    class ConfigProduccionSentry(ConfigPruebas):
        SENTRY_DSN = "https://public@sentry.example.org/1"
        TESTING = False

    with patch("sentry_sdk.init") as mock_init:
        aplicacion = create_app(ConfigProduccionSentry)
        mock_init.assert_called_once()
        args, kwargs = mock_init.call_args
        assert kwargs["dsn"] == "https://public@sentry.example.org/1"
        assert kwargs["traces_sample_rate"] == 0.2
        assert kwargs["send_default_pii"] is False
        assert kwargs["environment"] == os.environ.get("SENTRY_ENVIRONMENT", "production")
        assert len(kwargs["integrations"]) >= 1

        with aplicacion.app_context():
            db.session.remove()
            db.engine.dispose()


def test_sentry_falla_defensiva_no_impide_arranque(caplog):
    class ConfigConSentry(ConfigPruebas):
        SENTRY_DSN = "https://public@sentry.example.org/1"
        TESTING = False

    with (
        patch("sentry_sdk.init", side_effect=RuntimeError("Error simulado de conexión Sentry")),
        caplog.at_level(logging.WARNING, logger="app.sentry"),
    ):
        aplicacion = create_app(ConfigConSentry)
        assert "No se pudo inicializar Sentry" in caplog.text
        with aplicacion.app_context():
            db.session.remove()
            db.engine.dispose()


# ==============================================================================
# 2. Términos Comerciales SaaS y Privacidad (Ley 25.326 y Google Gemini)
# ==============================================================================


def test_terminos_comerciales_saas_renderizacion(cliente):
    r = cliente.get("/terminos")
    assert r.status_code == 200
    html = " ".join(r.get_data(as_text=True).split())

    # Estructura comercial SaaS
    assert "Plan Gratuito" in html
    assert "Plan Pro" in html and "$14.900/mes" in html
    assert "Plan a Medida" in html
    assert "/t/&lt;slug&gt;" in html or "/t/<slug>" in html

    # Deslinde de responsabilidad y terceros
    assert "Mercado Pago" in html
    assert "Meta Platforms Inc." in html
    assert "Delimitación y deslinde de responsabilidad" in html

    # Política de créditos e IA transparente
    assert "créditos prepagos" in html
    assert "consumo de IA transparente" in html

    # Ley 25.326 y supresión de datos
    assert "Ley N.º 25.326" in html
    assert "cinco (5) días hábiles" in html


def test_politica_privacidad_ia_y_aislamiento(cliente):
    r = cliente.get("/privacidad")
    assert r.status_code == 200
    html = " ".join(r.get_data(as_text=True).split())

    # Procesamiento con IA (Google Gemini)
    assert "Google Gemini" in html
    assert "Procesamiento mediante Inteligencia Artificial" in html
    assert "no se utilizan para entrenar modelos públicos" in html

    # Aislamiento estricto por comercio
    assert "aislamiento estricto por comercio" in html

    # Ley 25.326
    assert "Ley N.º 25.326" in html
    assert "Agencia de Acceso a la Información Pública" in html


# ==============================================================================
# 3. Auditoría de Sentry en Verificación
# ==============================================================================


def test_verificacion_informa_falta_de_sentry_en_produccion():
    class ConfigProdSinSentry(ConfigPruebas):
        URL_PUBLICA = "https://app.responde.ar"
        SENTRY_DSN = ""

    aplicacion = create_app(ConfigProdSinSentry)
    with aplicacion.app_context():
        problemas = problemas_de_configuracion(aplicacion)
        avisos = [p.texto for p in problemas if p.nivel == "aviso"]
        assert any("Falta SENTRY_DSN" in texto for texto in avisos)
        db.session.remove()
        db.engine.dispose()


def test_verificacion_no_informa_sentry_cuando_esta_configurado():
    class ConfigProdConSentry(ConfigPruebas):
        URL_PUBLICA = "https://app.responde.ar"
        SENTRY_DSN = "https://clave@sentry.example.org/1"

    aplicacion = create_app(ConfigProdConSentry)
    with aplicacion.app_context():
        problemas = problemas_de_configuracion(aplicacion)
        avisos = [p.texto for p in problemas if p.nivel == "aviso"]
        assert not any("Falta SENTRY_DSN" in texto for texto in avisos)
        db.session.remove()
        db.engine.dispose()


def test_verificacion_no_exige_sentry_en_entorno_local():
    class ConfigLocal(ConfigPruebas):
        URL_PUBLICA = "http://localhost:5000"
        WHATSAPP_TOKEN = ""
        SENTRY_DSN = ""

    aplicacion = create_app(ConfigLocal)
    with aplicacion.app_context():
        problemas = problemas_de_configuracion(aplicacion)
        avisos = [p.texto for p in problemas if p.nivel == "aviso"]
        assert not any("Falta SENTRY_DSN" in texto for texto in avisos)
        db.session.remove()
        db.engine.dispose()


# ==============================================================================
# 4. Verificación de Scripts de Respaldos y Despliegue
# ==============================================================================


def test_scripts_de_despliegue_existen_y_tienen_shebang():
    raiz = Path(__file__).resolve().parent.parent
    deploy_dir = raiz / "deploy"

    scripts = [
        deploy_dir / "respaldar.sh",
        deploy_dir / "instalar-cron.sh",
        deploy_dir / "actualizar.sh",
        deploy_dir / "preparar-vm.sh",
    ]

    for script in scripts:
        assert script.exists(), f"El script {script.name} no existe"
        contenido = script.read_text(encoding="utf-8")
        assert contenido.startswith("#!/usr/bin/env bash"), f"{script.name} no tiene shebang bash"
        assert "set -euo pipefail" in contenido, f"{script.name} no define modo estricto bash"


def test_script_respaldar_soporta_ping_url():
    raiz = Path(__file__).resolve().parent.parent
    respaldar_sh = raiz / "deploy" / "respaldar.sh"
    contenido = respaldar_sh.read_text(encoding="utf-8")

    assert "PING_URL" in contenido
    assert "HEALTHCHECK_URL" in contenido
    assert "CHECK_URL=" in contenido
    assert "notificar_error" in contenido


def test_script_instalar_cron_programa_horario_y_es_idempotente():
    raiz = Path(__file__).resolve().parent.parent
    cron_sh = raiz / "deploy" / "instalar-cron.sh"
    contenido = cron_sh.read_text(encoding="utf-8")

    assert "30 3 * * *" in contenido
    assert "respaldar.sh" in contenido
    assert "grep -v" in contenido  # Idempotencia al limpiar entradas previas
    assert "crontab -" in contenido


def test_scripts_deploy_sintaxis_bash_valida():
    bash = _obtener_bash()
    if not bash:
        logging.getLogger(__name__).warning("Bash no disponible en el host; se omite bash -n")
        return

    raiz = Path(__file__).resolve().parent.parent
    scripts = [
        str(raiz / "deploy" / "respaldar.sh"),
        str(raiz / "deploy" / "instalar-cron.sh"),
        str(raiz / "deploy" / "actualizar.sh"),
        str(raiz / "deploy" / "preparar-vm.sh"),
    ]

    resultado = subprocess.run([bash, "-n", *scripts], capture_output=True, text=True)
    assert resultado.returncode == 0, f"Error de sintaxis en scripts bash:\n{resultado.stderr}"
