"""Pruebas del módulo de cola de tareas, asincronismo y resiliencia (Sprint 2 / Pilar 5)."""

import json
import threading
import time
from concurrent.futures import Future

import pytest
from flask import current_app

from app import create_app
from app.config import ConfigPruebas
from app.extensiones import db
from app.mensajeria.cloud_api import ClienteWhatsApp
from app.modelos import Comercio, EstadoComercio
from app.servicios.cola import ColaTareas, procesar_webhook_asincrono
from tests.test_webhook_y_simulador import evento, firmar


def test_cola_modo_sincronico(app):
    """En modo sincrónico, la tarea se ejecuta inmediatamente en el mismo hilo."""
    cola = ColaTareas(app)
    cola.sincronica = True

    hilo_principal = threading.get_ident()
    hilos_ejecucion = []

    def tarea(x, y):
        hilos_ejecucion.append(threading.get_ident())
        return x + y

    resultado = cola.encolar(tarea, 3, 4)
    assert resultado == 7
    assert hilos_ejecucion == [hilo_principal]
    assert cola.total_encoladas == 1
    assert cola.total_exitosas == 1
    assert cola.total_fallidas == 0

    # Si la tarea falla en sincrónico, propaga la excepción
    def tarea_fallida():
        raise ValueError("Error sincrónico")

    with pytest.raises(ValueError, match="Error sincrónico"):
        cola.encolar(tarea_fallida)

    assert cola.total_encoladas == 2
    assert cola.total_fallidas == 1


def test_cola_modo_asincronico(app):
    """En modo asíncrono, la tarea se ejecuta en un hilo de trabajo separado."""
    cola = ColaTareas(app)
    cola.sincronica = False

    hilo_principal = threading.get_ident()
    hilos_ejecucion = []

    def tarea(x, y):
        hilos_ejecucion.append(threading.get_ident())
        return x * y

    future = cola.encolar(tarea, 6, 7)
    assert isinstance(future, Future)
    resultado = future.result(timeout=3)

    assert resultado == 42
    assert len(hilos_ejecucion) == 1
    assert hilos_ejecucion[0] != hilo_principal
    assert cola.total_encoladas == 1
    assert cola.total_exitosas == 1
    assert cola.total_fallidas == 0

    cola.shutdown(wait=True)


def test_cola_captura_excepciones_sin_tumbar_worker(app, caplog):
    """Una tarea con excepción no tumba el worker; se registra el error y sigue operativo."""
    cola = ColaTareas(app)
    cola.sincronica = False

    def tarea_falla():
        raise RuntimeError("Fallo simulado en tarea en segundo plano")

    def tarea_exitosa():
        return "recuperado_ok"

    # Encolamos la que falla
    fut_falla = cola.encolar(tarea_falla)
    res_falla = fut_falla.result(timeout=3)
    assert res_falla is None
    assert cola.total_fallidas == 1
    assert "Fallo simulado en tarea en segundo plano" in caplog.text

    # El worker sigue vivo y procesa la siguiente tarea
    fut_ok = cola.encolar(tarea_exitosa)
    res_ok = fut_ok.result(timeout=3)
    assert res_ok == "recuperado_ok"
    assert cola.total_exitosas == 1

    cola.shutdown(wait=True)


def test_cola_ejecuta_con_app_context(app):
    """La función en segundo plano tiene acceso al app_context de Flask."""
    cola = ColaTareas(app)
    cola.sincronica = False

    def tarea_lee_config():
        return current_app.config.get("PLATAFORMA_NOMBRE")

    future = cola.encolar(tarea_lee_config)
    assert future.result(timeout=3) == app.config.get("PLATAFORMA_NOMBRE")

    cola.shutdown(wait=True)


def test_cola_estado_y_reinicio():
    """El método estado() expone métricas y la cola se puede reiniciar tras shutdown."""
    cola = ColaTareas(max_workers=2)
    cola.sincronica = True

    estado_inicial = cola.estado()
    assert estado_inicial["sincronica"] is True
    assert estado_inicial["total_encoladas"] == 0

    cola.encolar(lambda: "ok")
    estado = cola.estado()
    assert estado["total_encoladas"] == 1
    assert estado["total_exitosas"] == 1

    cola.shutdown(wait=True)


def test_webhook_asincrono_responde_200_inmediato_y_procesa(tmp_path, monkeypatch):
    """El webhook asíncrono responde 200 de inmediato a Meta y procesa los mensajes en segundo plano."""
    db_path = tmp_path / "async_webhook.db"

    class ConfigAsync(ConfigPruebas):
        COLA_SINCRONICA = False
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{db_path.as_posix()}"
        SQLITE_WAL = True

    app_async = create_app(ConfigAsync)
    cliente_test = app_async.test_client()

    with app_async.app_context():
        comercio = Comercio(
            nombre="Tienda Online Asíncrona",
            rubro="Accesorios",
            telefono_contacto="351 999-8888",
            codigo_acceso="TIENDA1",
            estado=EstadoComercio.ACTIVO,
            paso_onboarding=Comercio.PASO_COMPLETO,
        )
        db.session.add(comercio)
        db.session.commit()

    enviados = []
    monkeypatch.setattr(ClienteWhatsApp, "enviar", lambda self, tel, resp: enviados.append((tel, resp)))

    cola = app_async.extensions["cola_tareas"]
    total_encoladas_previas = cola.total_encoladas

    payload = evento("Hola, quiero consultar el catálogo", id_mensaje="wamid.async.101")
    cuerpo = json.dumps(payload).encode()

    # 1. Envío del webhook: debe responder de inmediato con procesados=0 y encolado=True
    t0 = time.perf_counter()
    resp = cliente_test.post(
        "/webhook/whatsapp",
        data=cuerpo,
        content_type="application/json",
        headers={"X-Hub-Signature-256": firmar(cuerpo)},
    )
    t_respuesta_ms = (time.perf_counter() - t0) * 1000

    assert resp.status_code == 200
    assert resp.get_json() == {"procesados": 0, "encolado": True}
    assert t_respuesta_ms < 500  # Menos de 500 ms (muy por debajo de los 3000 ms exigidos por Meta)
    assert cola.total_encoladas == total_encoladas_previas + 1

    # 2. El worker en segundo plano procesa el mensaje
    inicio = time.time()
    while time.time() - inicio < 5:
        if len(enviados) >= 1:
            break
        time.sleep(0.05)

    assert len(enviados) >= 1
    assert cola.total_exitosas >= 1

    cola.shutdown(wait=True)


def test_webhook_firma_invalida_rechaza_antes_de_encolar(app):
    """Una firma inválida retorna 401 inmediatamente sin encolar ninguna tarea."""
    cola = app.extensions.get("cola_tareas")
    total_antes = cola.total_encoladas if cola else 0

    cliente_test = app.test_client()
    cuerpo = json.dumps(evento("Mensaje espía")).encode()
    resp = cliente_test.post(
        "/webhook/whatsapp",
        data=cuerpo,
        content_type="application/json",
        headers={"X-Hub-Signature-256": "sha256=firma_falsa"},
    )
    assert resp.status_code == 401
    if cola:
        assert cola.total_encoladas == total_antes


def test_procesar_webhook_asincrono_helper_directo(app, monkeypatch):
    """El helper procesar_webhook_asincrono puede llamarse directamente con (app, payload) o (payload)."""
    llamadas = []
    monkeypatch.setattr(
        "app.web.webhook.procesar_eventos_webhook",
        lambda p: llamadas.append(p) or 1,
    )

    payload = {"entry": []}

    # Llamada con (app, payload)
    res1 = procesar_webhook_asincrono(app, payload)
    assert res1 == 1

    # Llamada con (payload) dentro del app context
    with app.app_context():
        res2 = procesar_webhook_asincrono(payload)
        assert res2 == 1

    assert len(llamadas) == 2
