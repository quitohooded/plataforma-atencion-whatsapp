"""Seguridad web (#12): encabezados, CSP sin scripts en línea, caché del panel, cookies y límites por IP."""

import re

import pytest

from app import create_app
from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.config import ConfigPruebas
from app.extensiones import db
from app.seguridad_web import LIMITES, ContadorPorIP, Limite

from .conftest import CONTRASENA, crear_comercio, ingresar

SCRIPT_EN_LINEA = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)
MANEJADOR_EN_LINEA = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)


class ConfigConLimites(ConfigPruebas):
    LIMITES_POR_IP = True


class ConfigHttps(ConfigPruebas):
    COOKIES_SEGURAS = True
    SESSION_COOKIE_SECURE = True


def _app(config):
    aplicacion = create_app(config)
    contexto = aplicacion.app_context()
    contexto.push()
    return aplicacion, contexto


def _cerrar(contexto):
    db.session.remove()
    db.drop_all()
    db.engine.dispose()
    contexto.pop()


@pytest.fixture
def app_limites(reloj):
    aplicacion, contexto = _app(ConfigConLimites)
    yield aplicacion
    _cerrar(contexto)


# --- Encabezados -------------------------------------------------------------


def test_encabezados_de_seguridad_en_paginas_publicas(cliente):
    r = cliente.get("/ingresar")
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in r.headers["Permissions-Policy"]
    # Sin HTTPS no se envía HSTS (el navegador lo ignoraría y en local molestaría).
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_solo_por_https(cliente):
    r = cliente.get("/ingresar", base_url="https://localhost")
    assert r.headers["Strict-Transport-Security"].startswith("max-age=31536000")


def test_el_panel_no_se_guarda_en_cache(sesion):
    assert sesion.get("/panel").headers["Cache-Control"] == "no-store"
    assert sesion.get("/historial").headers["Cache-Control"] == "no-store"


def test_las_paginas_publicas_y_estaticas_se_pueden_cachear(cliente, comercio):
    assert "no-store" not in cliente.get("/ingresar").headers.get("Cache-Control", "")
    ingresar(cliente)
    assert "no-store" not in cliente.get("/static/css/app.css").headers.get("Cache-Control", "")


PAGINAS_PUBLICAS = ["/", "/ingresar", "/registro", "/recuperar", "/simulador"]
PAGINAS_DEL_PANEL = [
    "/panel",
    "/historial",
    "/zonas",
    "/medios-de-pago",
    "/horarios",
    "/respuestas",
    "/respuestas/nueva",
    "/activacion",
    "/activacion/cartel",
    "/mi-comercio",
    "/cuenta",
    "/ayuda",
    "/bloqueos",
    "/simulador",
]


def _sin_codigo_en_linea(cliente, ruta):
    """La CSP no admite scripts en línea: si una página los tuviera, dejaría de funcionar."""
    r = cliente.get(ruta)
    assert r.status_code == 200, ruta
    html = r.get_data(as_text=True)
    assert not SCRIPT_EN_LINEA.search(html), ruta
    assert not MANEJADOR_EN_LINEA.search(re.sub(r"<svg.*?</svg>", "", html, flags=re.S)), ruta


@pytest.mark.parametrize("ruta", PAGINAS_PUBLICAS)
def test_paginas_publicas_sin_scripts_ni_manejadores_en_linea(cliente, comercio, ruta):
    _sin_codigo_en_linea(cliente, ruta)


@pytest.mark.parametrize("ruta", PAGINAS_DEL_PANEL)
def test_paginas_del_panel_sin_scripts_ni_manejadores_en_linea(sesion, ruta):
    _sin_codigo_en_linea(sesion, ruta)


def test_el_simulador_pasa_sus_datos_en_atributos(cliente, comercio):
    html = cliente.get("/simulador").get_data(as_text=True)
    assert 'data-simulador-historial="/simulador/api/mensajes"' in html
    assert re.search(r'data-simulador-numero="5493510\d{6}"', html)
    assert "window.SIMULADOR" not in html


# --- Cookies y sesiones ------------------------------------------------------


def test_cookie_de_sesion_segura_con_https(reloj):
    aplicacion, contexto = _app(ConfigHttps)
    try:
        crear_comercio()
        cliente = aplicacion.test_client()
        r = ingresar(cliente)
        cookie = r.headers["Set-Cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    finally:
        _cerrar(contexto)


def test_cambiar_la_contrasena_cierra_las_otras_sesiones(app, comercio):
    otra = app.test_client()
    ingresar(otra)
    actual = app.test_client()
    ingresar(actual)
    r = actual.post(
        "/cuenta",
        data={"accion": "contrasena", "actual": CONTRASENA, "nueva": "otra-clave-9", "repetida": "otra-clave-9"},
    )
    assert r.status_code == 302
    assert actual.get("/panel").status_code == 200
    r = otra.get("/panel")
    assert r.status_code == 302 and "/ingresar" in r.headers["Location"]


# --- Simulador: nunca muestra la conversación de un comprador real ----------


def test_el_historial_del_simulador_solo_admite_numeros_de_prueba(cliente, comercio):
    real = "5493515551234"
    procesar_mensaje_entrante(MensajeEntrante(telefono=real, texto=comercio.texto_primer_mensaje()))
    assert cliente.get(f"/simulador/api/mensajes?telefono={real}").get_json() == {"mensajes": []}

    prueba = "5493510000123"
    procesar_mensaje_entrante(MensajeEntrante(telefono=prueba, texto=comercio.texto_primer_mensaje()))
    assert cliente.get(f"/simulador/api/mensajes?telefono={prueba}").get_json()["mensajes"]


# --- Límites por IP ----------------------------------------------------------


def test_contador_por_ip_ventana_deslizante():
    contador = ContadorPorIP()
    limite = Limite(3, 60)
    assert [contador.registrar("x", "1.1.1.1", limite, ahora=t) for t in (0, 1, 2)] == [0, 0, 0]
    assert contador.registrar("x", "1.1.1.1", limite, ahora=10) == 50
    # Otra IP u otra clave cuentan por separado.
    assert contador.registrar("x", "2.2.2.2", limite, ahora=10) == 0
    assert contador.registrar("y", "1.1.1.1", limite, ahora=10) == 0
    # Pasada la ventana del primer intento, vuelve a admitir.
    assert contador.registrar("x", "1.1.1.1", limite, ahora=60) == 0


def test_limite_de_ingresos_por_ip(app_limites):
    crear_comercio()
    cliente = app_limites.test_client()
    maximo = LIMITES["ingreso"].pedidos
    for _ in range(maximo):
        r = cliente.post("/ingresar", data={"email": "nadie@ejemplo.com", "contrasena": "x"})
        assert r.status_code == 401
    r = cliente.post("/ingresar", data={"email": "nadie@ejemplo.com", "contrasena": "x"})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert "Demasiados intentos" in r.get_data(as_text=True)
    # Ver la página no cuenta y otra conexión puede ingresar.
    assert cliente.get("/ingresar").status_code == 200
    otro = app_limites.test_client()
    r = otro.post(
        "/ingresar",
        data={"email": "demo@casaydetalles.com.ar", "contrasena": CONTRASENA},
        environ_base={"REMOTE_ADDR": "10.0.0.2"},
    )
    assert r.status_code == 302


def test_limite_de_registros_y_recuperaciones(app_limites):
    cliente = app_limites.test_client()
    for _ in range(LIMITES["registro"].pedidos):
        assert cliente.post("/registro", data={"email": "x"}).status_code == 400
    assert cliente.post("/registro", data={"email": "x"}).status_code == 429
    for _ in range(LIMITES["recuperacion"].pedidos):
        assert cliente.post("/recuperar", data={"email": "x@ejemplo.com"}).status_code in {200, 302}
    assert cliente.post("/recuperar", data={"email": "x@ejemplo.com"}).status_code == 429


def test_limite_del_simulador_responde_json(app_limites):
    crear_comercio()
    cliente = app_limites.test_client()
    datos = {"telefono": "5493510000077", "texto": "hola"}
    for _ in range(LIMITES["simulador"].pedidos):
        assert cliente.post("/simulador/api/mensajes", json=datos).status_code == 200
    r = cliente.post("/simulador/api/mensajes", json=datos)
    assert r.status_code == 429 and "Demasiados intentos" in r.get_json()["error"]
