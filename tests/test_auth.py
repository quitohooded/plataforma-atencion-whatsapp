"""CU01 Registrarse en la plataforma y CU02 Iniciar sesión (RF08, RF14, RNF03)."""

from datetime import timedelta

from sqlalchemy import select

from app.extensiones import db
from app.modelos import Comercio, EstadoComercio, Usuario

from .conftest import CONTRASENA, crear_comercio, ingresar

DATOS = {
    "nombre": "Deco Norte",
    "rubro": "Decoración",
    "telefono": "387 012-3344",
    "email": "Hola@DecoNorte.com.ar",
    "contrasena": "decoNorte2026",
    "acepta": "1",
}


def test_cu01_registro_crea_comercio_en_onboarding_e_inicia_sesion(cliente):
    r = cliente.post("/registro", data=DATOS)
    assert r.status_code == 302 and r.headers["Location"].endswith("/onboarding/paso/1")
    usuario = db.session.scalar(select(Usuario))
    assert usuario.email == "hola@deconorte.com.ar"
    assert usuario.hash_contrasena != DATOS["contrasena"]
    assert usuario.comercio.estado == EstadoComercio.EN_ONBOARDING
    # Queda la constancia de la aceptación de los términos y la política de privacidad.
    assert usuario.terminos_aceptados is not None
    assert cliente.get("/onboarding/paso/1").status_code == 200


def test_cu01_registro_exige_aceptar_los_terminos(cliente):
    datos = {k: v for k, v in DATOS.items() if k != "acepta"}
    r = cliente.post("/registro", data=datos)
    html = r.get_data(as_text=True)
    assert r.status_code == 400
    assert "tiene que aceptar los términos de uso y la política de privacidad" in html
    # Se conservan los datos cargados para no tener que escribirlos de nuevo.
    assert 'value="Deco Norte"' in html
    assert db.session.scalar(select(Comercio)) is None


def test_registro_enlaza_los_terminos_y_la_privacidad(cliente):
    html = cliente.get("/registro").get_data(as_text=True)
    assert 'href="/terminos"' in html and 'href="/privacidad"' in html and 'name="acepta"' in html


def test_cu01_excepcion_campos_incompletos(cliente):
    r = cliente.post("/registro", data={**DATOS, "rubro": ""})
    assert r.status_code == 400
    assert "Complete todos los campos obligatorios" in r.get_data(as_text=True)
    assert db.session.scalar(select(Comercio)) is None


def test_cu01_excepcion_contrasena_debil(cliente):
    r = cliente.post("/registro", data={**DATOS, "contrasena": "1234567"})
    assert r.status_code == 400
    assert "al menos ocho caracteres" in r.get_data(as_text=True)


def test_cu01_alternativo_correo_ya_registrado_ofrece_iniciar_sesion(cliente, comercio):
    r = cliente.post("/registro", data={**DATOS, "email": "demo@casaydetalles.com.ar"})
    html = r.get_data(as_text=True)
    assert r.status_code == 400
    assert "Ya existe una cuenta con ese correo" in html
    assert "/ingresar?email=demo" in html and "casaydetalles.com.ar" in html


def test_cu02_ingreso_dirige_segun_el_estado_del_comercio(cliente, app):
    activo = crear_comercio()
    en_onboarding = crear_comercio(
        nombre="Nuevo", email="nuevo@x.com", codigo=None, estado=EstadoComercio.EN_ONBOARDING, con_datos=False, paso=3
    )
    sin_activar = crear_comercio(nombre="Listo", email="listo@x.com", codigo=None, estado=EstadoComercio.EN_ONBOARDING)
    for email, destino in [
        (activo.usuario.email, "/panel"),
        (en_onboarding.usuario.email, "/onboarding/paso/3"),
        (sin_activar.usuario.email, "/activacion"),
    ]:
        r = ingresar(cliente, email)
        assert r.headers["Location"].endswith(destino), email
        cliente.post("/salir")


def test_cu02_registra_el_ultimo_ingreso(cliente, comercio, reloj):
    ingresar(cliente)
    assert comercio.usuario.ultimo_ingreso == reloj.actual


def test_cu02_excepcion_credenciales_invalidas_mensaje_generico(cliente, comercio):
    r1 = ingresar(cliente, contrasena="incorrecta")
    r2 = ingresar(cliente, email="noexiste@x.com")
    for r in (r1, r2):
        assert r.status_code == 401
        assert "Correo o contraseña incorrectos" in r.get_data(as_text=True)


def test_cu02_excepcion_bloqueo_tras_cinco_intentos(cliente, comercio, reloj):
    for _ in range(5):
        ingresar(cliente, contrasena="incorrecta")
    bloqueado = ingresar(cliente)  # contraseña correcta, pero bloqueado
    assert bloqueado.status_code == 401
    assert "bloqueado" in bloqueado.get_data(as_text=True)

    reloj.actual += timedelta(minutes=16)
    assert ingresar(cliente).status_code == 302


def test_cu02_alternativo_cierre_de_sesion(sesion):
    r = sesion.post("/salir")
    assert r.headers["Location"].endswith("/ingresar")
    assert sesion.get("/panel").status_code == 302


def test_paginas_del_panel_requieren_sesion(cliente, comercio):
    for ruta in ["/panel", "/historial", "/zonas", "/medios-de-pago", "/horarios", "/activacion", "/mi-comercio"]:
        r = cliente.get(ruta)
        assert r.status_code == 302 and "/ingresar" in r.headers["Location"], ruta


def test_siguiente_no_permite_redireccion_externa(cliente, comercio):
    r = cliente.post(
        "/ingresar",
        data={
            "email": comercio.usuario.email,
            "contrasena": CONTRASENA,
            "siguiente": "https://sitio-malicioso.example",
        },
    )
    assert r.headers["Location"].endswith("/panel")
