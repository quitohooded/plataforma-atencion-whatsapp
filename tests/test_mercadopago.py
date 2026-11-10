"""Pruebas integrales de Monetización Real con Mercado Pago (Sprint 1 - Pilar 1).

Verifica precios de packs, checkouts duales (modo simulación y real), acreditación
idempotente de suscripciones y créditos prepagos, cancelación, webhooks y el
simulador de pago para desarrollo.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.extensiones import db
from app.modelos import Comercio, PlanComercio, TransaccionPago
from app.servicios.pagos_mp import (
    acreditar_transaccion_aprobada,
    cancelar_suscripcion_comercio,
    crear_checkout_recarga,
    crear_checkout_suscripcion_pro,
    obtener_precio_pack,
    procesar_webhook_mp,
)
from app.utilidades import tiempo


def test_obtener_precio_pack():
    """Cálculo de precios de packs fijos y proporcionales."""
    assert obtener_precio_pack(200) == 4500
    assert obtener_precio_pack(500) == 9900
    assert obtener_precio_pack(2000) == 32000
    assert obtener_precio_pack(100) == 2000
    assert obtener_precio_pack(350) == 7000
    assert obtener_precio_pack(0) == 0
    assert obtener_precio_pack(-50) == 0


def test_crear_checkout_recarga_modo_simulacion(app, comercio):
    """En ausencia de token de MP, genera una URL al simulador local."""
    app.config["MERCADOPAGO_ACCESS_TOKEN"] = ""
    resultado = crear_checkout_recarga(comercio, 500, "/pago-confirmado")

    assert resultado["modo"] == "simulacion"
    assert "/plan/simulador-pago?id_transaccion=" in resultado["url_checkout"]

    transaccion = db.session.get(TransaccionPago, resultado["id_transaccion"])
    assert transaccion is not None
    assert transaccion.id_comercio == comercio.id_comercio
    assert transaccion.tipo == "RECARGA_CREDITOS"
    assert transaccion.monto == 9900
    assert transaccion.estado == "PENDIENTE"
    assert "+500 créditos" in transaccion.detalle


def test_crear_checkout_recarga_modo_real(app, comercio):
    """Con token de MP configurado, interactúa con la API de preferencias de MP."""
    app.config["MERCADOPAGO_ACCESS_TOKEN"] = "TEST_TOKEN_MP"

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "id": "PREF-REC-9999",
        "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=PREF-REC-9999",
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        resultado = crear_checkout_recarga(comercio, 200, "https://misitio.ar/retorno")

        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert "https://api.mercadopago.com/checkout/preferences" in args[0]
        assert kwargs["json"]["items"][0]["unit_price"] == 4500.0
        assert kwargs["headers"]["Authorization"] == "Bearer TEST_TOKEN_MP"

        assert resultado["modo"] == "real"
        assert resultado["id_externo"] == "PREF-REC-9999"
        assert "https://www.mercadopago.com.ar/checkout/v1/redirect" in resultado["url_checkout"]

        transaccion = db.session.get(TransaccionPago, resultado["id_transaccion"])
        assert transaccion.id_externo == "PREF-REC-9999"
        assert transaccion.monto == 4500


def test_crear_checkout_suscripcion_pro_modo_simulacion(app, comercio):
    """En ausencia de token de MP, la suscripción genera una URL de simulación."""
    app.config["MERCADOPAGO_ACCESS_TOKEN"] = ""
    resultado = crear_checkout_suscripcion_pro(comercio, "dueno@negocio.com", "/retorno")

    assert resultado["modo"] == "simulacion"
    assert "/plan/simulador-pago?id_transaccion=" in resultado["url_checkout"]

    transaccion = db.session.get(TransaccionPago, resultado["id_transaccion"])
    assert transaccion is not None
    assert transaccion.tipo == "SUSCRIPCION"
    assert transaccion.monto == 14900
    assert transaccion.estado == "PENDIENTE"


def test_crear_checkout_suscripcion_pro_modo_real(app, comercio):
    """Con token de MP configurado, llama al endpoint /preapproval de suscripción recurrente."""
    app.config["MERCADOPAGO_ACCESS_TOKEN"] = "TEST_TOKEN_MP"
    app.config["PLAN_PRO_PRECIO_MENSUAL"] = 14900

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "id": "PREAPP-777",
        "init_point": "https://www.mercadopago.com.ar/subscriptions/checkout?preapproval_id=PREAPP-777",
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        resultado = crear_checkout_suscripcion_pro(comercio, "socio@tienda.com", "https://app.ar/pago")

        assert mock_post.called
        args, kwargs = mock_post.call_args
        assert "https://api.mercadopago.com/preapproval" in args[0]
        assert kwargs["json"]["auto_recurring"]["transaction_amount"] == 14900.0
        assert kwargs["json"]["payer_email"] == "socio@tienda.com"

        assert resultado["modo"] == "real"
        assert resultado["id_externo"] == "PREAPP-777"
        transaccion = db.session.get(TransaccionPago, resultado["id_transaccion"])
        assert transaccion.id_externo == "PREAPP-777"


def test_acreditar_recarga_e_idempotencia(app, comercio):
    """Acredita créditos al saldo del comercio y garantiza que no se duplica en reintentos."""
    ahora = datetime(2026, 11, 10, 12, 0)
    transaccion = TransaccionPago(
        id_comercio=comercio.id_comercio,
        proveedor="mercadopago",
        tipo="RECARGA_CREDITOS",
        monto=9900,
        estado="PENDIENTE",
        detalle="Pack +500 créditos IA",
        fecha_creacion=ahora,
        fecha_actualizacion=ahora,
    )
    db.session.add(transaccion)
    db.session.commit()

    saldo_inicial = comercio.saldo_creditos
    acreditar_transaccion_aprobada(transaccion, ahora)

    assert transaccion.estado == "APROBADO"
    assert comercio.saldo_creditos == saldo_inicial + 500

    # Segunda llamada idempotente (ej: reenvío de webhook)
    acreditar_transaccion_aprobada(transaccion, ahora)
    assert comercio.saldo_creditos == saldo_inicial + 500


def test_acreditar_suscripcion_pro(app, comercio):
    """Acredita suscripción Pro, asigna 250 respuestas semanales e id externo."""
    ahora = datetime(2026, 11, 10, 14, 0)
    transaccion = TransaccionPago(
        id_comercio=comercio.id_comercio,
        proveedor="mercadopago",
        tipo="SUSCRIPCION",
        monto=14900,
        estado="PENDIENTE",
        detalle="Plan Pro Mensual - 1.000 respuestas IA/mes",
        id_externo="SUB-EXTERNAL-1234",
        fecha_creacion=ahora,
        fecha_actualizacion=ahora,
    )
    db.session.add(transaccion)
    db.session.commit()

    acreditar_transaccion_aprobada(transaccion, ahora)

    assert transaccion.estado == "APROBADO"
    assert comercio.plan == PlanComercio.PRO
    assert comercio.ia_cuota_semanal == 250
    assert comercio.ia_cuota_interna == 100
    assert comercio.ia_usados_semana == 0
    assert comercio.ia_semana_inicio == ahora.date()
    assert comercio.id_suscripcion_externa == "SUB-EXTERNAL-1234"


def test_cancelar_suscripcion_comercio(app, comercio):
    """Cancela la suscripción Pro, pasa a Free, resetea cuota pero conserva saldo prepago y slug."""
    ahora = datetime(2026, 11, 10, 15, 0)
    comercio.plan = PlanComercio.PRO
    comercio.ia_cuota_semanal = 250
    comercio.ia_usados_semana = 50
    comercio.saldo_creditos = 350
    comercio.id_suscripcion_externa = "SUB-TO-CANCEL"
    slug_original = comercio.asegurar_slug()
    db.session.commit()

    with patch("requests.put") as mock_put:
        mock_put.return_value.status_code = 200
        cancelar_suscripcion_comercio(comercio, ahora)

    assert comercio.plan == PlanComercio.FREE
    assert comercio.ia_cuota_semanal == 0
    assert comercio.ia_usados_semana == 0
    assert comercio.saldo_creditos == 350  # Conserva saldo prepago
    assert comercio.slug == slug_original  # Conserva canal web
    assert comercio.id_suscripcion_externa is None


def test_procesar_webhook_mp_simulado(app, comercio):
    """El webhook procesa eventos directos del simulador aprobando y rechazando transacciones."""
    ahora = tiempo.ahora()
    transaccion = TransaccionPago(
        id_comercio=comercio.id_comercio,
        proveedor="mercadopago",
        tipo="RECARGA_CREDITOS",
        monto=4500,
        estado="PENDIENTE",
        detalle="Pack +200 créditos IA",
        fecha_creacion=ahora,
        fecha_actualizacion=ahora,
    )
    db.session.add(transaccion)
    db.session.commit()

    # 1. Aprobación simulada
    payload_ok = {
        "id_transaccion": transaccion.id_transaccion,
        "estado": "approved",
        "id_externo": "SIM-PAY-001",
    }
    resultado_ok = procesar_webhook_mp(payload_ok, {}, ahora)
    assert resultado_ok is True
    assert transaccion.estado == "APROBADO"
    assert comercio.saldo_creditos == 200

    # 2. Rechazo simulado de otra transacción
    t2 = TransaccionPago(
        id_comercio=comercio.id_comercio,
        proveedor="mercadopago",
        tipo="RECARGA_CREDITOS",
        monto=4500,
        estado="PENDIENTE",
        detalle="Pack +200 créditos IA",
        fecha_creacion=ahora,
        fecha_actualizacion=ahora,
    )
    db.session.add(t2)
    db.session.commit()

    payload_fail = {
        "id_transaccion": t2.id_transaccion,
        "estado": "rejected",
        "id_externo": "SIM-PAY-002",
    }
    resultado_fail = procesar_webhook_mp(payload_fail, {}, ahora)
    assert resultado_fail is True
    assert t2.estado == "RECHAZADO"


def test_procesar_webhook_mp_con_firma_valida(app, comercio):
    """Valida la firma HMAC x-signature cuando MERCADOPAGO_WEBHOOK_SECRET está configurado."""
    app.config["MERCADOPAGO_WEBHOOK_SECRET"] = "secreto_webhook_super_seguro"
    ahora = tiempo.ahora()

    transaccion = TransaccionPago(
        id_comercio=comercio.id_comercio,
        proveedor="mercadopago",
        tipo="RECARGA_CREDITOS",
        monto=9900,
        estado="PENDIENTE",
        detalle="Pack +500 créditos IA",
        id_externo="987654321",
        fecha_creacion=ahora,
        fecha_actualizacion=ahora,
    )
    db.session.add(transaccion)
    db.session.commit()

    data_id = "987654321"
    ts = "1762770000"
    x_request_id = "req-uuid-12345"
    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    firma = hmac.new(
        b"secreto_webhook_super_seguro",
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    encabezados = {
        "x-signature": f"ts={ts},v1={firma}",
        "x-request-id": x_request_id,
    }
    datos = {
        "type": "payment",
        "data": {"id": data_id, "status": "approved"},
    }

    procesado = procesar_webhook_mp(datos, encabezados, ahora)
    assert procesado is True
    assert transaccion.estado == "APROBADO"

    # Intento con firma inválida debe ser rechazado
    encabezados_truchos = {
        "x-signature": f"ts={ts},v1=firma_invalida_totalmente",
        "x-request-id": x_request_id,
    }
    procesado_invalido = procesar_webhook_mp(datos, encabezados_truchos, ahora)
    assert procesado_invalido is False


def test_flujo_web_monetizacion_completo(sesion, comercio, app):
    """Flujo web integral de compra de créditos, suscripción Pro, simulador y cancelación."""
    # 1. Comprar créditos (+200 créditos) redirige al simulador
    r_comprar = sesion.post("/plan/comprar-creditos", data={"cantidad": "200"}, follow_redirects=False)
    assert r_comprar.status_code == 302
    assert "/plan/simulador-pago?id_transaccion=" in r_comprar.headers["Location"]

    # Extraer id_transaccion de la Location
    location = r_comprar.headers["Location"]
    id_t = int(location.split("id_transaccion=")[1])

    # 2. Visitar el simulador de pago con GET
    r_sim = sesion.get(location)
    assert r_sim.status_code == 200
    html_sim = r_sim.get_data(as_text=True)
    assert "Simulador de Pago de Mercado Pago" in html_sim
    assert "Aprobar pago de prueba" in html_sim
    assert "Rechazar pago de prueba" in html_sim
    assert "Pack +200 créditos IA" in html_sim

    # 3. Aprobar el pago en el simulador mediante POST
    r_aprobar = sesion.post(
        "/plan/simulador-pago",
        data={"id_transaccion": id_t, "accion": "aprobar"},
        follow_redirects=True,
    )
    assert r_aprobar.status_code == 200
    html_plan = r_aprobar.get_data(as_text=True)
    assert "¡Pago de prueba aprobado con éxito!" in html_plan

    with app.app_context():
        c = db.session.get(Comercio, comercio.id_comercio)
        assert c.saldo_creditos == 200
        t = db.session.get(TransaccionPago, id_t)
        assert t.estado == "APROBADO"

    # 4. Suscribirse al Plan Pro mediante POST /plan/suscribir-pro
    r_sub = sesion.post("/plan/suscribir-pro", follow_redirects=False)
    assert r_sub.status_code == 302
    assert "/plan/simulador-pago?id_transaccion=" in r_sub.headers["Location"]
    id_sub_t = int(r_sub.headers["Location"].split("id_transaccion=")[1])

    # 5. Aprobar suscripción en el simulador
    r_sub_apr = sesion.post(
        "/plan/simulador-pago",
        data={"id_transaccion": id_sub_t, "accion": "aprobar"},
        follow_redirects=True,
    )
    assert r_sub_apr.status_code == 200
    html_sub = r_sub_apr.get_data(as_text=True)
    assert "Suscripción activa" in html_sub

    with app.app_context():
        c = db.session.get(Comercio, comercio.id_comercio)
        assert c.plan == PlanComercio.PRO
        assert c.ia_cuota_semanal == 250
        assert c.saldo_creditos == 200

    # 6. Historial de transacciones visible en el panel
    assert "Últimos pagos y recargas" in html_sub
    assert "#" + str(id_t) in html_sub
    assert "#" + str(id_sub_t) in html_sub

    # 7. Cancelar suscripción mediante POST /plan/cancelar-suscripcion
    r_canc = sesion.post("/plan/cancelar-suscripcion", follow_redirects=True)
    assert r_canc.status_code == 200
    html_canc = r_canc.get_data(as_text=True)
    assert "Suscripción al Plan Pro cancelada con éxito" in html_canc
    assert "Suscribirme con Mercado Pago" in html_canc

    with app.app_context():
        c = db.session.get(Comercio, comercio.id_comercio)
        assert c.plan == PlanComercio.FREE
        assert c.ia_cuota_semanal == 0
        assert c.saldo_creditos == 200  # Saldo conservado


def test_endpoint_webhook_mercadopago(cliente):
    """El webhook /api/pagos/mercadopago/webhook está exento de CSRF y responde 200 OK."""
    # GET (salud / verificación)
    r_get = cliente.get("/api/pagos/mercadopago/webhook")
    assert r_get.status_code == 200
    assert r_get.get_json() == {"status": "ok"}

    # POST sin CSRF
    r_post = cliente.post("/api/pagos/mercadopago/webhook", json={"action": "test.ping"})
    assert r_post.status_code == 200
    assert r_post.get_json()["status"] == "ok"


def test_retornos_mercado_pago(sesion):
    """Las rutas de retorno de MP informan el estado y redirigen al panel."""
    r_ok = sesion.get("/plan/pago-confirmado", follow_redirects=True)
    assert r_ok.status_code == 200
    assert "¡Pago confirmado!" in r_ok.get_data(as_text=True)

    r_pend = sesion.get("/plan/pago-pendiente", follow_redirects=True)
    assert r_pend.status_code == 200
    assert "pendiente de acreditación" in r_pend.get_data(as_text=True)


def test_checkouts_ajax_devuelven_json(sesion):
    """Si la petición es AJAX, devuelve JSON con la URL en vez de redirección 302."""
    r_ajax_recarga = sesion.post(
        "/plan/comprar-creditos",
        data={"cantidad": "500"},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r_ajax_recarga.status_code == 200
    datos = r_ajax_recarga.get_json()
    assert "url" in datos
    assert "id_transaccion" in datos

    r_ajax_sub = sesion.post(
        "/plan/suscribir-pro",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert r_ajax_sub.status_code == 200
    datos_sub = r_ajax_sub.get_json()
    assert "url" in datos_sub
    assert "id_transaccion" in datos_sub


def test_simulador_aislamiento_multinquilino(sesion, app):
    """Un comercio no puede ver ni operar transacciones ajenas en el simulador."""
    with app.app_context():
        otro_comercio = Comercio(
            nombre="Tienda Vecina",
            rubro="Indumentaria",
            telefono_contacto="3519998888",
            estado="ACTIVO",
            paso_onboarding=6,
        )
        db.session.add(otro_comercio)
        db.session.commit()

        transaccion_ajena = TransaccionPago(
            id_comercio=otro_comercio.id_comercio,
            proveedor="mercadopago",
            tipo="SUSCRIPCION",
            monto=14900,
            estado="PENDIENTE",
            fecha_creacion=tiempo.ahora(),
            fecha_actualizacion=tiempo.ahora(),
        )
        db.session.add(transaccion_ajena)
        db.session.commit()
        id_ajeno = transaccion_ajena.id_transaccion

    # Intento de acceso a transacción ajena debe ser rechazado
    r_get = sesion.get(f"/plan/simulador-pago?id_transaccion={id_ajeno}", follow_redirects=True)
    assert "Transacción de pago no encontrada" in r_get.get_data(as_text=True)

    r_post = sesion.post(
        "/plan/simulador-pago",
        data={"id_transaccion": id_ajeno, "accion": "aprobar"},
        follow_redirects=True,
    )
    assert "Transacción de pago no encontrada" in r_post.get_data(as_text=True)

