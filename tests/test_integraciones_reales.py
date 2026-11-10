"""Pruebas exhaustivas del Pilar 4: Integraciones Reales 1-Clic.

Cubre:
- TiendaNube (OAuth 2.0, intercambio de código, sincronización de catálogo, exportación de pedidos).
- Mercado Pago Connect (OAuth 2.0 vendedores, intercambio de código, Preference API vendedor).
- Google Sheets (sincronización de pedidos y consultas en modo simulación y API).
- Rutas web del panel (iniciar OAuth, callbacks, configuración, sincronización manual, desconexión).
- Flujo bidireccional integrado con el bot conversacional.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from sqlalchemy import select

from app.bot.ia import procesar_flujo_bidireccional
from app.extensiones import db
from app.modelos import (
    Comprador,
    ConexionExterna,
    Consulta,
    Conversacion,
    ItemCatalogo,
    PedidoChat,
    ResultadoConsulta,
    TemaConsulta,
)
from app.servicios import google_sheets, mp_connect, tiendanube
from app.utilidades import tiempo

# ===========================================================================
# 1. Pruebas de TiendaNube (Servicio)
# ===========================================================================


def test_tiendanube_generar_url_autorizacion_dual_mode(app, comercio):
    """Verifica la generación de URL OAuth en modo simulación y modo real."""
    redirect_uri = "http://localhost/operaciones/conexiones/tiendanube/callback"

    # Modo simulación (en tests o sin app_id)
    url_sim = tiendanube.generar_url_autorizacion(comercio.id_comercio, redirect_uri)
    assert url_sim.startswith(redirect_uri)
    assert f"code=sim_tn_code_{comercio.id_comercio}" in url_sim

    # Modo real (simulando app_id configurado y testing deshabilitado)
    with app.test_request_context():
        app.config["TESTING"] = False
        url_real = tiendanube.generar_url_autorizacion(
            comercio.id_comercio, redirect_uri, app_id="tn_app_12345"
        )
        app.config["TESTING"] = True
        assert "https://www.tiendanube.com/apps/authorize/token" in url_real
        assert "client_id=tn_app_12345" in url_real
        assert (
            "request_scope=read_products%2Cwrite_orders" in url_real
            or "request_scope=read_products,write_orders" in url_real
        )


def test_tiendanube_intercambiar_codigo_dual_mode(app):
    """Verifica el intercambio de código OAuth en simulación y con mock real."""
    redirect_uri = "http://localhost/operaciones/conexiones/tiendanube/callback"

    # Simulado
    res_sim = tiendanube.intercambiar_codigo("codigo_abc123", redirect_uri)
    assert res_sim["access_token"] == "tok_tn_codigo_abc123"
    assert res_sim["user_id"] == "123456"
    assert res_sim["token_type"] == "bearer"

    # Real con mock de requests
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "tok_tn_real_999",
        "user_id": 998877,
        "token_type": "bearer",
        "scope": "read_products,write_orders",
    }
    with patch("requests.post", return_value=mock_resp), app.test_request_context():
        app.config["TESTING"] = False
        res_real = tiendanube.intercambiar_codigo(
            "codigo_real",
            redirect_uri,
            app_id="app_123",
            app_secret="sec_456",
        )
        app.config["TESTING"] = True
        assert res_real["access_token"] == "tok_tn_real_999"
        assert res_real["user_id"] == "998877"


def test_tiendanube_sincronizar_catalogo(app, comercio):
    """Verifica la inserción y actualización determinista de productos desde TiendaNube."""
    conexion = ConexionExterna(
        id_comercio=comercio.id_comercio,
        proveedor="tiendanube",
        estado="CONECTADO",
        cuenta_externa="Tienda #123456",
        token_acceso="tok_tn_test",
    )
    db.session.add(conexion)
    db.session.commit()

    # 1. Primera sincronización (crea ítems de catálogo)
    cant = tiendanube.sincronizar_catalogo_tiendanube(comercio, conexion)
    assert cant > 0

    items = db.session.scalars(
        select(ItemCatalogo).where(
            ItemCatalogo.id_comercio == comercio.id_comercio,
            ItemCatalogo.origen == "tiendanube",
        )
    ).all()
    assert len(items) == cant
    nombres = {it.nombre for it in items}
    assert "Remera Algodón Peinado" in nombres
    assert "Buzo Hoodie Frisa" in nombres

    # 2. Segunda sincronización: idempotencia y actualización sin duplicados
    cant_segunda = tiendanube.sincronizar_catalogo_tiendanube(comercio, conexion)
    assert cant_segunda == cant

    items_despues = db.session.scalars(
        select(ItemCatalogo).where(
            ItemCatalogo.id_comercio == comercio.id_comercio,
            ItemCatalogo.origen == "tiendanube",
        )
    ).all()
    assert len(items_despues) == cant


def test_tiendanube_sincronizar_catalogo_api_real(app, comercio):
    """Verifica el mapeo de productos cuando la API externa devuelve datos."""
    conexion = ConexionExterna(
        id_comercio=comercio.id_comercio,
        proveedor="tiendanube",
        estado="CONECTADO",
        cuenta_externa="Tienda #55555",
        token_acceso="tok_real_produccion",
    )
    db.session.add(conexion)
    db.session.commit()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "id": 1,
            "name": {"es": "Camisa Lino Premium"},
            "categories": [{"name": {"es": "Verano"}}],
            "variants": [{"price": "19900.00", "stock": 5}],
            "description": {"es": "100% lino italiano"},
        }
    ]

    with patch("requests.get", return_value=mock_resp), app.test_request_context():
        app.config["TESTING"] = False
        cant = tiendanube.sincronizar_catalogo_tiendanube(comercio, conexion)
        app.config["TESTING"] = True

    assert cant == 1
    item = db.session.scalar(
        select(ItemCatalogo).where(
            ItemCatalogo.id_comercio == comercio.id_comercio,
            ItemCatalogo.nombre == "Camisa Lino Premium",
        )
    )
    assert item is not None
    assert item.precio == 19900
    assert item.categoria == "Verano"
    assert item.stock_disponible is True


def test_tiendanube_exportar_pedido(app, comercio):
    """Verifica la exportación de un PedidoChat hacia TiendaNube."""
    pedido = PedidoChat(
        id_comercio=comercio.id_comercio,
        cliente_nombre="Martín Fierro",
        cliente_telefono="5493519876543",
        detalle="1x Remera Algodón Peinado",
        monto_total=14500,
        estado_pedido="PENDIENTE",
        estado_pago="SIN_PAGAR",
        fecha_hora=tiempo.ahora(),
    )
    db.session.add(pedido)
    db.session.commit()

    order_id = tiendanube.exportar_pedido_tiendanube(comercio, pedido)
    assert order_id.startswith("TN-ORD-")


# ===========================================================================
# 2. Pruebas de Mercado Pago Connect (Servicio)
# ===========================================================================


def test_mp_connect_generar_url_autorizacion_dual_mode(app, comercio):
    """Verifica la generación de URL OAuth para Mercado Pago Connect."""
    redirect_uri = "http://localhost/operaciones/conexiones/mercadopago/callback"

    # Simulación
    url_sim = mp_connect.generar_url_autorizacion_mp_connect(comercio.id_comercio, redirect_uri)
    assert url_sim.startswith(redirect_uri)
    assert f"code=sim_mp_code_{comercio.id_comercio}" in url_sim

    # Real
    with app.test_request_context():
        app.config["TESTING"] = False
        url_real = mp_connect.generar_url_autorizacion_mp_connect(
            comercio.id_comercio, redirect_uri, client_id="mp_client_111"
        )
        app.config["TESTING"] = True
        assert "https://auth.mercadopago.com/authorization" in url_real
        assert "client_id=mp_client_111" in url_real


def test_mp_connect_intercambiar_codigo_dual_mode(app):
    """Verifica el intercambio de código por credenciales de vendedor en MP Connect."""
    redirect_uri = "http://localhost/operaciones/conexiones/mercadopago/callback"

    # Simulación
    res_sim = mp_connect.intercambiar_codigo_mp_connect("code_mp_123", redirect_uri)
    assert res_sim["access_token"] == "APP_USR-sim-code_mp_123"
    assert res_sim["public_key"] == "APP_USR-pub-code_mp_123"
    assert res_sim["user_id"] == 987654321

    # Real con mock
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "APP_USR-real-token",
        "public_key": "APP_USR-real-pub",
        "user_id": 11223344,
        "refresh_token": "TG-real-ref",
        "token_type": "bearer",
    }
    with patch("requests.post", return_value=mock_resp), app.test_request_context():
        app.config["TESTING"] = False
        res_real = mp_connect.intercambiar_codigo_mp_connect(
            "code_real",
            redirect_uri,
            client_id="cid_mp",
            client_secret="sec_mp",
        )
        app.config["TESTING"] = True
        assert res_real["access_token"] == "APP_USR-real-token"
        assert res_real["user_id"] == 11223344


def test_mp_connect_crear_preferencia_vendedor(app, comercio):
    """Verifica la creación de preferencia y enlace de pago para el vendedor."""
    conexion = ConexionExterna(
        id_comercio=comercio.id_comercio,
        proveedor="mercadopago",
        estado="CONECTADO",
        cuenta_externa="Vendedor MP #987654321",
        token_acceso="APP_USR-sim-token123",
    )
    db.session.add(conexion)

    pedido = PedidoChat(
        id_comercio=comercio.id_comercio,
        cliente_nombre="Lucía Gómez",
        cliente_telefono="5491122334455",
        detalle="2x Buzo Hoodie Frisa",
        monto_total=64000,
        estado_pedido="PENDIENTE",
        estado_pago="SIN_PAGAR",
        fecha_hora=tiempo.ahora(),
    )
    db.session.add(pedido)
    db.session.commit()

    link = mp_connect.crear_preferencia_vendedor(comercio, pedido)
    assert "mpago.la/responde-" in link
    assert pedido.enlace_pago == link


# ===========================================================================
# 3. Pruebas de Google Sheets (Servicio)
# ===========================================================================


def test_google_sheets_sincronizar_pedido_y_consulta(app, comercio):
    """Verifica el registro ordenado y determinista de pedidos y consultas en Google Sheets."""
    conexion = ConexionExterna(
        id_comercio=comercio.id_comercio,
        proveedor="google_sheets",
        estado="CONECTADO",
        cuenta_externa="Planilla de Gestión 2026",
        configuracion=json.dumps({"spreadsheet_id": "hoja_123", "filas_pedidos": [], "filas_consultas": []}),
    )
    db.session.add(conexion)

    pedido = PedidoChat(
        id_comercio=comercio.id_comercio,
        cliente_nombre="Roberto Carlos",
        cliente_telefono="5493510001112",
        detalle="1x Gorra Trucker Bordada",
        monto_total=9900,
        estado_pedido="PENDIENTE",
        estado_pago="SIN_PAGAR",
        fecha_hora=tiempo.ahora(),
    )
    db.session.add(pedido)

    comprador = Comprador(telefono="5493510001112", nombre="Roberto Carlos", fecha_primer_contacto=tiempo.ahora())
    conversacion = Conversacion(
        comercio=comercio,
        comprador=comprador,
        fecha_inicio=tiempo.ahora(),
        ultima_actividad=tiempo.ahora(),
    )
    consulta = Consulta(
        conversacion=conversacion,
        tema=TemaConsulta.ENVIO,
        resultado=ResultadoConsulta.RESUELTA,
        codigo_postal=5000,
        fecha_hora=tiempo.ahora(),
        atendida=True,
    )
    db.session.add_all([comprador, conversacion, consulta])
    db.session.commit()

    # Sincronización de pedido
    ok_p = google_sheets.sincronizar_pedido_a_sheets(comercio, pedido)
    assert ok_p is True

    filas_p = google_sheets.obtener_filas_simuladas(conexion, "pedidos")
    assert len(filas_p) == 1
    assert filas_p[0]["id_pedido"] == pedido.id_pedido
    assert filas_p[0]["cliente_nombre"] == "Roberto Carlos"
    assert filas_p[0]["monto_total"] == 9900

    # Sincronización de consulta
    ok_c = google_sheets.sincronizar_consulta_a_sheets(comercio, consulta)
    assert ok_c is True

    filas_c = google_sheets.obtener_filas_simuladas(conexion, "consultas")
    assert len(filas_c) == 1
    assert filas_c[0]["id_consulta"] == consulta.id_consulta
    assert filas_c[0]["tema"] == TemaConsulta.ENVIO.value


# ===========================================================================
# 4. Pruebas de Rutas Web del Panel (Operaciones & OAuth)
# ===========================================================================


def test_web_oauth_tiendanube(sesion, comercio, app):
    """Verifica el flujo web de inicio y callback OAuth de TiendaNube."""
    # 1. Iniciar OAuth
    r_ini = sesion.post("/operaciones/conexiones/tiendanube/iniciar")
    assert r_ini.status_code == 302
    target_url = r_ini.headers.get("Location", "")
    assert "operaciones/conexiones/tiendanube/callback" in target_url

    # 2. Callback con código simulado
    r_cb = sesion.get(
        f"/operaciones/conexiones/tiendanube/callback?code=sim_tn_test_code&state={comercio.id_comercio}",
        follow_redirects=True,
    )
    assert r_cb.status_code == 200
    html = r_cb.get_data(as_text=True)
    assert "TiendaNube conectada exitosamente" in html

    with app.app_context():
        cx = db.session.scalar(
            select(ConexionExterna).where(
                ConexionExterna.id_comercio == comercio.id_comercio,
                ConexionExterna.proveedor == "tiendanube",
            )
        )
        assert cx is not None
        assert cx.estado == "CONECTADO"
        assert "Tienda #" in cx.cuenta_externa

        # Verificamos que se hayan cargado los productos al catálogo
        items = db.session.scalars(
            select(ItemCatalogo).where(
                ItemCatalogo.id_comercio == comercio.id_comercio,
                ItemCatalogo.origen == "tiendanube",
            )
        ).all()
        assert len(items) > 0


def test_web_oauth_mercadopago(sesion, comercio, app):
    """Verifica el flujo web de inicio y callback OAuth de Mercado Pago Connect."""
    # Pre-creamos un pedido sin link de cobro
    with app.app_context():
        p = PedidoChat(
            id_comercio=comercio.id_comercio,
            cliente_nombre="Cliente Sin Link",
            cliente_telefono="549110000000",
            detalle="Combo 1",
            monto_total=12000,
            estado_pedido="PENDIENTE",
            estado_pago="SIN_PAGAR",
            fecha_hora=tiempo.ahora(),
        )
        db.session.add(p)
        db.session.commit()
        id_pedido = p.id_pedido

    # 1. Iniciar OAuth
    r_ini = sesion.post("/operaciones/conexiones/mercadopago/iniciar")
    assert r_ini.status_code == 302
    assert "operaciones/conexiones/mercadopago/callback" in r_ini.headers.get("Location", "")

    # 2. Callback
    r_cb = sesion.get(
        f"/operaciones/conexiones/mercadopago/callback?code=sim_mp_code_test&state={comercio.id_comercio}",
        follow_redirects=True,
    )
    assert r_cb.status_code == 200
    html = r_cb.get_data(as_text=True)
    assert "Mercado Pago Connect activado con éxito" in html

    with app.app_context():
        cx = db.session.scalar(
            select(ConexionExterna).where(
                ConexionExterna.id_comercio == comercio.id_comercio,
                ConexionExterna.proveedor == "mercadopago",
            )
        )
        assert cx is not None
        assert cx.estado == "CONECTADO"

        # El pedido previo debe tener su enlace_pago generado
        ped_act = db.session.get(PedidoChat, id_pedido)
        assert ped_act.enlace_pago is not None
        assert "mpago.la/responde-" in ped_act.enlace_pago


def test_web_google_sheets_configuracion_y_sincronizacion(sesion, comercio, app):
    """Verifica la configuración y sincronización web de Google Sheets."""
    r_conf = sesion.post(
        "/operaciones/conexiones/google_sheets/configurar",
        data={"spreadsheet_id": "Planilla_Ventas_Octubre_2026"},
        follow_redirects=True,
    )
    assert r_conf.status_code == 200
    assert "Google Sheets conectado y sincronizado" in r_conf.get_data(as_text=True)

    with app.app_context():
        cx = db.session.scalar(
            select(ConexionExterna).where(
                ConexionExterna.id_comercio == comercio.id_comercio,
                ConexionExterna.proveedor == "google_sheets",
            )
        )
        assert cx is not None
        assert cx.estado == "CONECTADO"
        assert cx.cuenta_externa == "Planilla_Ventas_Octubre_2026"


def test_web_sincronizar_manual_y_desconectar(sesion, comercio, app):
    """Verifica la sincronización forzada y desconexión manual de conexiones externas."""
    # Conectamos TiendaNube primero
    sesion.post(
        f"/operaciones/conexiones/tiendanube/callback?code=sim_123&state={comercio.id_comercio}",
        follow_redirects=True,
    )

    # 1. Sincronizar TiendaNube
    r_sinc = sesion.post("/operaciones/conexiones/tiendanube/sincronizar", follow_redirects=True)
    assert r_sinc.status_code == 200
    assert "Datos sincronizados correctamente con TiendaNube" in r_sinc.get_data(as_text=True)

    # 2. Desconectar TiendaNube
    r_desc = sesion.post("/operaciones/conexiones/tiendanube/desconectar", follow_redirects=True)
    assert r_desc.status_code == 200
    assert "Conexión con Tiendanube desconectada" in r_desc.get_data(as_text=True)

    with app.app_context():
        cx = db.session.scalar(
            select(ConexionExterna).where(
                ConexionExterna.id_comercio == comercio.id_comercio,
                ConexionExterna.proveedor == "tiendanube",
            )
        )
        assert cx.estado == "DESCONECTADO"

    # 3. Intentar sincronizar cuando está desconectado
    r_fallo = sesion.post("/operaciones/conexiones/tiendanube/sincronizar", follow_redirects=True)
    assert "La aplicación debe estar conectada para poder sincronizar" in r_fallo.get_data(as_text=True)


# ===========================================================================
# 5. Flujo Bidireccional Integrado (Bot -> Pedidos -> Conexiones)
# ===========================================================================


def test_flujo_bidireccional_completo_con_todas_las_conexiones(app, comercio):
    """Prueba integral: el bot detecta un pedido e impacta en TiendaNube, MP Connect y Google Sheets."""
    # 1. Activamos las tres conexiones en el comercio
    cx_tn = ConexionExterna(
        id_comercio=comercio.id_comercio,
        proveedor="tiendanube",
        estado="CONECTADO",
        cuenta_externa="Tienda #123456",
        token_acceso="tok_tn_sim",
    )
    cx_mp = ConexionExterna(
        id_comercio=comercio.id_comercio,
        proveedor="mercadopago",
        estado="CONECTADO",
        cuenta_externa="Vendedor MP #987654321",
        token_acceso="APP_USR-sim-seller",
    )
    cx_gs = ConexionExterna(
        id_comercio=comercio.id_comercio,
        proveedor="google_sheets",
        estado="CONECTADO",
        cuenta_externa="Planilla Principal",
        configuracion=json.dumps({"spreadsheet_id": "test_sheet", "filas_pedidos": [], "filas_consultas": []}),
    )
    db.session.add_all([cx_tn, cx_mp, cx_gs])

    # 2. Agregamos un producto al catálogo
    item = ItemCatalogo(
        id_comercio=comercio.id_comercio,
        nombre="Zapatillas Urbanas",
        categoria="Calzado",
        precio=45000,
        stock_disponible=True,
        origen="tiendanube",
        activo=True,
    )
    db.session.add(item)
    db.session.commit()

    comprador = Comprador(telefono="5493518889999", nombre="Juan Pérez", fecha_primer_contacto=tiempo.ahora())
    conversacion = Conversacion(
        comercio=comercio,
        comprador=comprador,
        fecha_inicio=tiempo.ahora(),
        ultima_actividad=tiempo.ahora(),
    )
    db.session.add_all([comprador, conversacion])
    db.session.commit()

    c_ped = Consulta(
        conversacion=conversacion,
        tema=TemaConsulta.PEDIDOS,
        resultado=ResultadoConsulta.RESUELTA,
        fecha_hora=tiempo.ahora(),
        atendida=True,
    )
    db.session.add(c_ped)
    db.session.commit()
    consultas = [c_ped]

    # 3. Disparamos el flujo bidireccional
    pedido = procesar_flujo_bidireccional(
        comercio=comercio,
        conversacion=conversacion,
        comprador=comprador,
        texto="Quiero comprar 2x Zapatillas Urbanas por favor",
        consultas=consultas,
        ahora=tiempo.ahora(),
    )

    assert pedido is not None
    assert pedido.monto_total == 90000
    assert "2x Zapatillas Urbanas" in pedido.detalle
    # Enlace de pago generado con MP Connect
    assert pedido.enlace_pago is not None
    assert "mpago.la/responde-" in pedido.enlace_pago

    # Fila sincronizada a Google Sheets
    filas_p = google_sheets.obtener_filas_simuladas(cx_gs, "pedidos")
    assert len(filas_p) == 1
    assert filas_p[0]["id_pedido"] == pedido.id_pedido
    assert filas_p[0]["monto_total"] == 90000

    # Consulta sincronizada a Google Sheets
    filas_c = google_sheets.obtener_filas_simuladas(cx_gs, "consultas")
    assert len(filas_c) == 1
    assert filas_c[0]["tema"] == TemaConsulta.PEDIDOS.value
