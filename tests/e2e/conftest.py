"""Pruebas de punta a punta con un navegador real (#16).

Levantan la aplicación en un hilo, con una base SQLite temporal cargada con la demostración y la
protección CSRF activa, y la recorren con Chromium (Playwright). Si Playwright o Chromium no están
instalados, se omiten: no son parte de las dependencias de la aplicación.

    pip install -r requirements-e2e.txt
    python -m playwright install chromium
    python -m pytest tests/e2e
"""

from __future__ import annotations

import threading

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from werkzeug.serving import make_server  # noqa: E402

from app import create_app  # noqa: E402
from app.config import ConfigPruebas  # noqa: E402
from app.extensiones import db  # noqa: E402

DEMO = ("demo@casaydetalles.com.ar", "demo1234")


@pytest.fixture(scope="session")
def servidor(tmp_path_factory):
    ruta = tmp_path_factory.mktemp("e2e") / "plataforma.db"

    class ConfigE2E(ConfigPruebas):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{ruta}"
        WTF_CSRF_ENABLED = True
        SECRET_KEY = "e2e-" + "x" * 40

    aplicacion = create_app(ConfigE2E)
    with aplicacion.app_context():
        from app.datos.demo import cargar_demo

        cargar_demo()
        db.session.remove()
    servidor_http = make_server("127.0.0.1", 0, aplicacion, threaded=True)
    hilo = threading.Thread(target=servidor_http.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{servidor_http.server_port}"
    servidor_http.shutdown()
    with aplicacion.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture(scope="session")
def navegador():
    with sync_api.sync_playwright() as p:
        try:
            chromium = p.chromium.launch()
        except sync_api.Error as error:  # navegador no instalado
            pytest.skip(f"Chromium no está disponible: {error}")
        yield chromium
        chromium.close()


def _esperado(texto: str) -> bool:
    """Un formulario con errores responde 400 o 401 a propósito: Chromium lo informa en la consola."""
    return texto.startswith("Failed to load resource: the server responded with a status of 40")


def _nueva_pagina(navegador, **opciones):
    contexto = navegador.new_context(locale="es-AR", **opciones)
    pagina = contexto.new_page()
    pagina.set_default_timeout(10_000)
    errores: list[str] = []
    pagina.on("pageerror", lambda e: errores.append(f"error de JavaScript: {e}"))
    pagina.on("console", lambda m: errores.append(m.text) if m.type == "error" and not _esperado(m.text) else None)
    return contexto, pagina, errores


@pytest.fixture
def pagina(navegador):
    """Página de escritorio; al terminar, verifica que no hubo errores de JavaScript ni de consola."""
    contexto, pagina, errores = _nueva_pagina(navegador, viewport={"width": 1360, "height": 900})
    yield pagina
    contexto.close()
    assert errores == []


@pytest.fixture
def movil(navegador):
    contexto, pagina, errores = _nueva_pagina(
        navegador, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
    )
    yield pagina
    contexto.close()
    assert errores == []


def ingresar(pagina, base, email=DEMO[0], contrasena=DEMO[1]):
    pagina.goto(base + "/ingresar")
    pagina.fill("#campo-email", email)
    pagina.fill("#campo-contrasena", contrasena)
    pagina.click("button[type=submit]")
    pagina.wait_for_load_state()


def escribir_en_chat(pagina, texto, formulario=".chat form"):
    """Envía un mensaje en el chat (simulador o chat de prueba) y devuelve la respuesta del bot."""
    burbujas = pagina.locator(".chat__mensajes .burbuja")
    antes = burbujas.count()
    pagina.locator(f"{formulario} input[type=text], {formulario} textarea").first.fill(texto)
    pagina.locator(f"{formulario} button[type=submit]").first.click()
    pagina.wait_for_function(
        "([n]) => document.querySelectorAll('.chat__mensajes .burbuja').length >= n", arg=[antes + 2]
    )
    # Todas las burbujas del bot que siguieron al mensaje (una respuesta puede ocupar varias).
    return "\n\n".join(burbujas.all_inner_texts()[antes + 1 :])
