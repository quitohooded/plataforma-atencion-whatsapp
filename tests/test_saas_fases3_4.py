"""Pruebas de las Fases 3 y 4: Motor de IA Híbrido, Copiloto Interno, Conexiones 1-Clic y Vistas Operativas."""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock

from sqlalchemy import select

from app.bot.ia import resolver_con_ia_comprador
from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.extensiones import db
from app.modelos import (
    Comercio,
    ConexionExterna,
    EstadoConversacion,
    ItemCatalogo,
    MedioPago,
    PedidoChat,
    PlanComercio,
    ResultadoConsulta,
)
from app.utilidades import tiempo


def _activar_plan_pro(comercio: Comercio) -> None:
    comercio.plan = PlanComercio.PRO
    comercio.ia_habilitada = True
    comercio.ia_cuota_semanal = 250
    comercio.ia_usados_semana = 0
    comercio.ia_semana_inicio = date.today()
    comercio.ia_cuota_interna = 100
    comercio.ia_usados_interna = 0
    db.session.commit()


def test_ia_chat_comprador_catalogo_y_descuento_creditos(comercio, app):
    """Comercio PRO con catálogo recibe respuesta de IA y consume 1 crédito semanal."""
    with app.app_context():
        _activar_plan_pro(comercio)

        item = ItemCatalogo(
            id_comercio=comercio.id_comercio,
            nombre="Remera de Lino",
            categoria="Indumentaria",
            precio=16500,
            stock_disponible=True,
            descripcion="100% lino natural lavado",
            origen="nativo",
            activo=True,
        )
        db.session.add(item)
        db.session.commit()

        # Consulta que pregunta por la Remera de Lino
        entrante = MensajeEntrante(
            telefono="5493512345678",
            texto="Hola! ¿Tienen disponible la Remera de Lino y cuánto cuesta?",
            id_comercio_directo=comercio.id_comercio,
        )
        res = procesar_mensaje_entrante(entrante)

        assert len(res.respuestas) > 0
        texto_resp = res.respuestas[0].texto
        assert "Remera de Lino" in texto_resp
        assert "$16.500" in texto_resp

        # Consulta queda RESUELTA por la IA
        assert res.consulta is not None
        assert res.consulta.resultado == ResultadoConsulta.RESUELTA

        # Conversación permanece ACTIVA
        assert res.conversacion is not None
        assert res.conversacion.estado == EstadoConversacion.ACTIVA

        # Verificamos que se descontó 1 crédito semanal
        c_actual = db.session.get(Comercio, comercio.id_comercio)
        assert c_actual.ia_usados_semana == 1


def test_ia_chat_contexto_libre_del_negocio(comercio, app):
    """Comercio PRO responde preguntas comerciales según las reglas cargadas en contexto_ia."""
    with app.app_context():
        _activar_plan_pro(comercio)
        comercio.contexto_ia = "Los cambios se realizan exclusivamente de lunes a miércoles con ticket original."
        db.session.commit()

        entrante = MensajeEntrante(
            telefono="5493512345678",
            texto="Hola, ¿cuál es la política para cambios de mercadería?",
            id_comercio_directo=comercio.id_comercio,
        )
        res = procesar_mensaje_entrante(entrante)

        assert len(res.respuestas) > 0
        texto_resp = res.respuestas[0].texto
        assert "lunes a miércoles" in texto_resp
        assert res.consulta.resultado == ResultadoConsulta.RESUELTA


def test_ia_chat_sin_creditos_degrada_suavemente_a_reglas(comercio, app):
    """Cuando la cuota de IA está agotada, el bot degrada a reglas normales sin fallar."""
    with app.app_context():
        _activar_plan_pro(comercio)
        comercio.ia_usados_semana = 250  # Cuota agotada
        comercio.saldo_creditos = 0
        db.session.commit()

        item = ItemCatalogo(
            id_comercio=comercio.id_comercio,
            nombre="Campera Térmica",
            categoria="Abrigo",
            precio=45000,
            stock_disponible=True,
            origen="nativo",
            activo=True,
        )
        db.session.add(item)
        db.session.commit()

        # Debe responder None en resolver_con_ia_comprador
        ia_res = resolver_con_ia_comprador(comercio, "¿Tienen campera térmica?", tiempo.ahora())
        assert ia_res is None

        # Al procesar mensaje, se deriva normalmente sin error
        entrante = MensajeEntrante(
            telefono="5493512345678",
            texto="¿Tienen campera térmica?",
            id_comercio_directo=comercio.id_comercio,
        )
        res = procesar_mensaje_entrante(entrante)
        assert res.consulta.resultado == ResultadoConsulta.DERIVADA
        # No se incrementan los usados
        c_actual = db.session.get(Comercio, comercio.id_comercio)
        assert c_actual.ia_usados_semana == 250


def test_flujo_bidireccional_crea_pedido_en_tablero_nativo(comercio, app):
    """Mensaje de pedido del comprador genera automáticamente un PedidoChat en la base."""
    with app.app_context():
        _activar_plan_pro(comercio)

        item1 = ItemCatalogo(
            id_comercio=comercio.id_comercio,
            nombre="Hamburguesa Doble",
            categoria="Comida",
            precio=8500,
            stock_disponible=True,
            origen="nativo",
            activo=True,
        )
        item2 = ItemCatalogo(
            id_comercio=comercio.id_comercio,
            nombre="Papas Fritas",
            categoria="Guarnición",
            precio=3000,
            stock_disponible=True,
            origen="nativo",
            activo=True,
        )
        db.session.add_all([item1, item2])
        db.session.commit()

        entrante = MensajeEntrante(
            telefono="5493517778899",
            nombre="Lucas Gómez",
            texto="Hola! Quiero encargar 2 Hamburguesa Doble y 1 Papas Fritas por favor",
            id_comercio_directo=comercio.id_comercio,
        )
        procesar_mensaje_entrante(entrante)

        # Verificamos que se creó el registro PedidoChat
        pedido = db.session.scalar(
            select(PedidoChat).where(
                PedidoChat.id_comercio == comercio.id_comercio,
                PedidoChat.cliente_telefono == "5493517778899",
            )
        )
        assert pedido is not None
        assert pedido.cliente_nombre == "Lucas Gómez"
        assert pedido.monto_total == (8500 * 2 + 3000)
        assert "Hamburguesa Doble" in pedido.detalle
        assert pedido.estado_pedido == "PENDIENTE"
        assert pedido.estado_pago == "SIN_PAGAR"


def test_flujo_bidireccional_pago_informado_actualiza_pedido(comercio, app):
    """Aviso de transferencia/comprobante en el chat actualiza el estado_pago a INFORMADO."""
    with app.app_context():
        _activar_plan_pro(comercio)

        # Pedido previo sin pagar
        pedido_previo = PedidoChat(
            id_comercio=comercio.id_comercio,
            cliente_nombre="Valeria Solís",
            cliente_telefono="5493514443322",
            detalle="Zapatillas Running Talle 38",
            monto_total=52000,
            estado_pedido="PENDIENTE",
            estado_pago="SIN_PAGAR",
            fecha_hora=tiempo.ahora(),
        )
        db.session.add(pedido_previo)
        db.session.commit()

        # Cliente avisa que ya transfirió
        entrante = MensajeEntrante(
            telefono="5493514443322",
            nombre="Valeria Solís",
            texto="Hola, ya transferí el pago, les mando el comprobante.",
            id_comercio_directo=comercio.id_comercio,
        )
        procesar_mensaje_entrante(entrante)

        p_actualizado = db.session.get(PedidoChat, pedido_previo.id_pedido)
        assert p_actualizado.estado_pago == "INFORMADO"


def test_flujo_bidireccional_mercadopago_genera_link_y_sincroniza(comercio, app):
    """Conexión activa de Mercado Pago genera link automático y Google Sheets actualiza última sincro."""
    with app.app_context():
        _activar_plan_pro(comercio)
        comercio.asegurar_slug()

        cx_mp = ConexionExterna(
            id_comercio=comercio.id_comercio,
            proveedor="mercadopago",
            estado="CONECTADO",
            cuenta_externa="mp@comercio.com",
            fecha_alta=tiempo.ahora(),
        )
        cx_sheets = ConexionExterna(
            id_comercio=comercio.id_comercio,
            proveedor="google_sheets",
            estado="CONECTADO",
            cuenta_externa="pedidos-2026@gmail.com",
            fecha_alta=tiempo.ahora(),
        )
        db.session.add_all([cx_mp, cx_sheets])
        db.session.commit()

        entrante = MensajeEntrante(
            telefono="5493511112233",
            nombre="Martín Fierro",
            texto="Quiero hacer un pedido de 1 docena de empanadas",
            id_comercio_directo=comercio.id_comercio,
        )
        procesar_mensaje_entrante(entrante)

        pedido = db.session.scalar(
            select(PedidoChat).where(
                PedidoChat.id_comercio == comercio.id_comercio,
                PedidoChat.cliente_telefono == "5493511112233",
            )
        )
        assert pedido is not None
        assert pedido.enlace_pago is not None
        assert "mpago.la/responde-" in pedido.enlace_pago
        assert comercio.slug in pedido.enlace_pago

        # Verificamos que Google Sheets registró la última sincronización
        cx_s = db.session.get(ConexionExterna, cx_sheets.id_conexion)
        assert cx_s.ultima_sincronizacion is not None


def test_copiloto_ia_asistente_interno_extraccion_local(sesion, comercio, app):
    """Copiloto IA procesa texto libre, carga productos, medios de pago y actualiza contexto_ia."""
    with app.app_context():
        _activar_plan_pro(comercio)

    texto_comerciante = """
    Precios de esta temporada:
    - Buzo Polar: $28.000 (Color negro, talle M y L)
    - Remera Estampada: $14.500 (100% algodón peinado)
    - Gorra Trucker: $8000

    Medios de cobro:
    Aceptamos Mercado Pago y Efectivo con 15% de descuento.
    También Transferencia Bancaria (Alias: indumentaria.cordoba).

    Preguntas comunes:
    ¿Hacen envíos a todo el país? Sí, enviamos por Correo Argentino.
    ¿Tienen local a la calle? No, somos tienda 100% online.
    Para cambios traer la prenda con etiqueta en 30 días.
    """

    r = sesion.post(
        "/operaciones/asistente-ia",
        data={"texto_libre": texto_comerciante},
        follow_redirects=True,
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Copiloto IA: Se cargaron" in html

    with app.app_context():
        c_actual = db.session.get(Comercio, comercio.id_comercio)
        assert c_actual.ia_usados_interna == 1

        # Productos en catálogo
        prods = db.session.scalars(
            select(ItemCatalogo).where(ItemCatalogo.id_comercio == comercio.id_comercio)
        ).all()
        nombres = [p.nombre for p in prods]
        assert "Buzo Polar" in nombres
        assert "Remera Estampada" in nombres
        assert "Gorra Trucker" in nombres

        buzo = next(p for p in prods if p.nombre == "Buzo Polar")
        assert buzo.precio == 28000
        assert buzo.origen == "asistente_ia"

        # Medios de pago detectados
        medios = db.session.scalars(
            select(MedioPago).where(MedioPago.id_comercio == comercio.id_comercio)
        ).all()
        nombres_medios = [m.nombre for m in medios]
        assert any("Mercado Pago" in n for n in nombres_medios)
        assert any("Efectivo" in n for n in nombres_medios)

        # Contexto IA guardado
        assert c_actual.contexto_ia is not None
        assert "etiqueta en 30 días" in c_actual.contexto_ia


def test_copiloto_ia_interaccion_gemini_mock(monkeypatch, comercio, app):
    """Prueba de llamada estructurada a Gemini Interactions API con mock de requests."""
    with app.app_context():
        _activar_plan_pro(comercio)
        app.config["GEMINI_API_KEY"] = "gemini-test-secret-key"

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "steps": [
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "productos": [
                                        {
                                            "nombre": "Café Colombiano 500g",
                                            "categoria": "Cafetería",
                                            "precio": 12000,
                                            "descripcion": "Tueste medio artesanal",
                                        }
                                    ],
                                    "faqs": [
                                        {
                                            "titulo": "¿Hacen envíos?",
                                            "palabras_clave": "envios, entregas",
                                            "respuesta": "Sí, en el día.",
                                        }
                                    ],
                                    "medios_pago": [{"nombre": "Mercado Pago", "detalle": "Link y QR"}],
                                    "resumen_contexto": "Abierto de 8 a 20 hs.",
                                }
                            ),
                        }
                    ],
                }
            ]
        }

        monkeypatch.setattr("requests.post", lambda url, headers, json, timeout: mock_resp)

        from app.bot.ia import extraer_configuracion_negocio_ia

        resultado = extraer_configuracion_negocio_ia(comercio, "Café Colombiano $12.000")
        assert len(resultado["productos"]) == 1
        assert resultado["productos"][0]["nombre"] == "Café Colombiano 500g"
        assert resultado["productos"][0]["precio"] == 12000
        assert resultado["resumen_contexto"] == "Abierto de 8 a 20 hs."


def test_vistas_nativas_operaciones_pedidos_y_catalogo(sesion, comercio, app):
    """Operaciones completas de creación, edición de estados y catálogo en el panel."""
    # 1. GET /operaciones
    r = sesion.get("/operaciones")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Operaciones, Catálogo y Conexiones" in html
    assert "Copiloto IA del Comercio" in html
    assert "Tablero Nativo de Pedidos y Cobros" in html
    assert "Catálogo de Productos para el Bot" in html
    assert "Conexiones 1-Clic con sus Sistemas" in html

    # 2. POST /operaciones/catalogo/nuevo
    r_cat = sesion.post(
        "/operaciones/catalogo/nuevo",
        data={
            "nombre": "Mochila Urbana",
            "categoria": "Accesorios",
            "precio": "32.000",
            "descripcion": "Impermeable con bolsillo para notebook",
            "stock_disponible": "1",
        },
        follow_redirects=True,
    )
    assert r_cat.status_code == 200
    assert "Mochila Urbana" in r_cat.get_data(as_text=True)

    with app.app_context():
        item = db.session.scalar(select(ItemCatalogo).where(ItemCatalogo.nombre == "Mochila Urbana"))
        assert item is not None
        assert item.precio == 32000
        assert item.stock_disponible is True
        id_item = item.id_item

    # 3. POST /operaciones/catalogo/<id_item>/toggle
    r_tog = sesion.post(f"/operaciones/catalogo/{id_item}/toggle", follow_redirects=True)
    assert r_tog.status_code == 200
    with app.app_context():
        item = db.session.get(ItemCatalogo, id_item)
        assert item.stock_disponible is False

    # 4. POST /operaciones/pedidos/nuevo
    r_ped = sesion.post(
        "/operaciones/pedidos/nuevo",
        data={
            "cliente_nombre": "Carolina Herrera",
            "cliente_telefono": "5493519991122",
            "detalle": "1x Mochila Urbana",
            "monto_total": "32000",
            "estado_pedido": "PENDIENTE",
            "estado_pago": "SIN_PAGAR",
        },
        follow_redirects=True,
    )
    assert r_ped.status_code == 200
    assert "Carolina Herrera" in r_ped.get_data(as_text=True)

    with app.app_context():
        pedido = db.session.scalar(select(PedidoChat).where(PedidoChat.cliente_nombre == "Carolina Herrera"))
        assert pedido is not None
        id_pedido = pedido.id_pedido

    # 5. POST /operaciones/pedidos/<id_pedido>/estado
    r_est = sesion.post(
        f"/operaciones/pedidos/{id_pedido}/estado",
        data={
            "estado_pedido": "ENVIADO",
            "estado_pago": "PAGADO",
        },
        follow_redirects=True,
    )
    assert r_est.status_code == 200
    with app.app_context():
        p_act = db.session.get(PedidoChat, id_pedido)
        assert p_act.estado_pedido == "ENVIADO"
        assert p_act.estado_pago == "PAGADO"

    # 6. POST /operaciones/catalogo/<id_item>/eliminar
    r_del = sesion.post(f"/operaciones/catalogo/{id_item}/eliminar", follow_redirects=True)
    assert r_del.status_code == 200
    with app.app_context():
        assert db.session.get(ItemCatalogo, id_item) is None


def test_conexiones_1_clic_flujo_completo(sesion, comercio, app):
    """Conexión, sincronización y desconexión 1-clic con TiendaNube, Google Sheets y Mercado Pago."""
    # 1. Conectar TiendaNube
    r_tn = sesion.post("/operaciones/conexiones/tiendanube/conectar", follow_redirects=True)
    assert r_tn.status_code == 200
    assert "Conexión 1-Clic con TiendaNube activada" in r_tn.get_data(as_text=True)

    with app.app_context():
        cx_tn = db.session.scalar(
            select(ConexionExterna).where(
                ConexionExterna.id_comercio == comercio.id_comercio,
                ConexionExterna.proveedor == "tiendanube",
            )
        )
        assert cx_tn is not None
        assert cx_tn.estado == "CONECTADO"

        # Se importaron productos sincronizados
        prods_tn = db.session.scalars(
            select(ItemCatalogo).where(
                ItemCatalogo.id_comercio == comercio.id_comercio,
                ItemCatalogo.origen == "tiendanube",
            )
        ).all()
        assert len(prods_tn) > 0

    # 2. Conectar Mercado Pago
    r_mp = sesion.post("/operaciones/conexiones/mercadopago/conectar", follow_redirects=True)
    assert r_mp.status_code == 200
    assert "Conexión 1-Clic con Mercado Pago activada" in r_mp.get_data(as_text=True)

    with app.app_context():
        cx_mp = db.session.scalar(
            select(ConexionExterna).where(
                ConexionExterna.id_comercio == comercio.id_comercio,
                ConexionExterna.proveedor == "mercadopago",
            )
        )
        assert cx_mp.estado == "CONECTADO"

    # 3. Sincronizar TiendaNube
    r_sinc = sesion.post("/operaciones/conexiones/tiendanube/sincronizar", follow_redirects=True)
    assert r_sinc.status_code == 200
    assert "Datos sincronizados correctamente" in r_sinc.get_data(as_text=True)

    # 4. Desconectar TiendaNube
    r_desc = sesion.post("/operaciones/conexiones/tiendanube/desconectar", follow_redirects=True)
    assert r_desc.status_code == 200
    with app.app_context():
        cx_tn_act = db.session.get(ConexionExterna, cx_tn.id_conexion)
        assert cx_tn_act.estado == "DESCONECTADO"
