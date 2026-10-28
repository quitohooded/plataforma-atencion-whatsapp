"""Fixtures compartidas por las pruebas.

Cada prueba corre sobre una base SQLite en memoria nueva y con el reloj fijo,
para que los horarios y los indicadores sean reproducibles.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app import create_app
from app.config import ConfigPruebas
from app.extensiones import db
from app.modelos import (
    Comercio,
    EstadoComercio,
    HorarioAtencion,
    MedioPago,
    Usuario,
    ZonaEnvio,
)
from app.utilidades import tiempo

CONTRASENA = "clave-segura-1"
# Martes 27/10/2026 22:30: fuera del horario de lunes a viernes de 9 a 18.
MARTES_NOCHE = datetime(2026, 10, 27, 22, 30)


class Reloj:
    def __init__(self, inicial: datetime):
        self.actual = inicial

    def __call__(self) -> datetime:
        return self.actual


@pytest.fixture
def reloj(monkeypatch):
    r = Reloj(MARTES_NOCHE)
    monkeypatch.setattr(tiempo, "ahora", r)
    return r


@pytest.fixture
def app(reloj):
    aplicacion = create_app(ConfigPruebas)
    with aplicacion.app_context():
        yield aplicacion
        db.session.remove()
        db.drop_all()


@pytest.fixture
def cliente(app):
    return app.test_client()


def crear_comercio(
    nombre: str = "Casa & Detalles",
    email: str = "demo@casaydetalles.com.ar",
    codigo: str | None = "CASA26",
    estado: EstadoComercio = EstadoComercio.ACTIVO,
    con_datos: bool = True,
    paso: int = Comercio.PASO_COMPLETO,
) -> Comercio:
    comercio = Comercio(
        nombre=nombre, rubro="Artículos para el hogar", telefono_contacto="351 012-3456",
        codigo_acceso=codigo, estado=estado, paso_onboarding=paso, fecha_alta=MARTES_NOCHE.date(),
    )
    usuario = Usuario(comercio=comercio, email=email, intentos_fallidos=0)
    usuario.establecer_contrasena(CONTRASENA)
    db.session.add_all([comercio, usuario])
    if con_datos:
        db.session.add_all([
            ZonaEnvio(comercio=comercio, descripcion="Córdoba Capital", cp_desde=5000, cp_hasta=5099,
                      plazo_min_dias=1, plazo_max_dias=2),
            ZonaEnvio(comercio=comercio, descripcion="Interior de Córdoba", cp_desde=5100, cp_hasta=5999,
                      plazo_min_dias=2, plazo_max_dias=4),
            MedioPago(comercio=comercio, nombre="Transferencia bancaria", detalle="alias casa.detalles.demo"),
            MedioPago(comercio=comercio, nombre="Billetera virtual", detalle="Mercado Pago"),
            MedioPago(comercio=comercio, nombre="Efectivo", detalle="solo retiros", activo=False),
        ])
        for dia in range(5):
            db.session.add(HorarioAtencion(comercio=comercio, dia_semana=dia, hora_apertura="09:00", hora_cierre="18:00"))
        db.session.add(HorarioAtencion(comercio=comercio, dia_semana=5, hora_apertura="09:00", hora_cierre="13:00"))
    db.session.commit()
    return comercio


@pytest.fixture
def comercio(app):
    return crear_comercio()


@pytest.fixture
def otro_comercio(app):
    return crear_comercio(nombre="Mundo Textil", email="demo@mundotextil.com.ar", codigo="TEXT42")


def ingresar(cliente, email="demo@casaydetalles.com.ar", contrasena=CONTRASENA):
    return cliente.post("/ingresar", data={"email": email, "contrasena": contrasena})


@pytest.fixture
def sesion(cliente, comercio):
    respuesta = ingresar(cliente)
    assert respuesta.status_code == 302
    return cliente
