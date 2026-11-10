"""Pruebas del Sprint 6: Analítica Avanzada de Negocio y Panel SuperAdmin SaaS."""

from app.extensiones import db
from app.modelos import (
    Comprador,
    Consulta,
    Conversacion,
    DireccionMensaje,
    EstadoComercio,
    EstadoConversacion,
    ItemCatalogo,
    Mensaje,
    PedidoChat,
    PlanComercio,
    ResultadoConsulta,
    TemaConsulta,
    TransaccionPago,
)
from app.servicios import analitica
from app.utilidades import tiempo
from tests.conftest import CONTRASENA, crear_comercio, ingresar

_contador_telefono = 1000


def _crear_conversacion_con_consulta(comercio, tema, resultado, fuera_de_horario=False, texto="Consulta de prueba"):
    global _contador_telefono
    _contador_telefono += 1
    ahora = tiempo.ahora()
    comprador = Comprador(
        telefono=f"549351999{_contador_telefono}",
        nombre="Cliente Prueba",
        fecha_primer_contacto=ahora,
    )
    conv = Conversacion(
        comercio=comercio,
        comprador=comprador,
        estado=EstadoConversacion.ACTIVA,
        fecha_inicio=ahora,
        ultima_actividad=ahora,
    )
    db.session.add_all([comprador, conv])
    db.session.flush()

    msg = Mensaje(
        conversacion=conv,
        texto=texto,
        direccion=DireccionMensaje.ENTRANTE,
        fecha_hora=ahora,
        emisor_tipo="COMPRADOR",
    )
    db.session.add(msg)
    db.session.flush()

    cons = Consulta(
        conversacion=conv,
        tema=tema,
        resultado=resultado,
        fecha_hora=ahora,
        fuera_de_horario=fuera_de_horario,
        mensaje=msg,
        id_mensaje=msg.id_mensaje,
    )
    db.session.add(cons)
    db.session.commit()
    return cons


def test_metricas_comercio_analitica_calculos(app, comercio):
    ahora = tiempo.ahora()

    # 1. Crear pedidos en el chat
    p1 = PedidoChat(
        id_comercio=comercio.id_comercio,
        cliente_nombre="Ana",
        cliente_telefono="5493510001",
        detalle="2x Almohadones",
        monto_total=10000,
        estado_pedido="CONFIRMADO",
        estado_pago="PAGADO",
        fecha_hora=ahora,
    )
    p2 = PedidoChat(
        id_comercio=comercio.id_comercio,
        cliente_nombre="Carlos",
        cliente_telefono="5493510002",
        detalle="1x Manta",
        monto_total=5000,
        estado_pedido="PENDIENTE",
        estado_pago="INFORMADO",
        fecha_hora=ahora,
    )
    p3 = PedidoChat(
        id_comercio=comercio.id_comercio,
        cliente_nombre="Laura",
        cliente_telefono="5493510003",
        detalle="1x Espejo",
        monto_total=3000,
        estado_pedido="PENDIENTE",
        estado_pago="SIN_PAGAR",
        fecha_hora=ahora,
    )
    db.session.add_all([p1, p2, p3])

    # 2. Consultas: 3 resueltas, 1 derivada a operador (fuera de horario)
    _crear_conversacion_con_consulta(
        comercio, TemaConsulta.HORARIOS, ResultadoConsulta.RESUELTA, fuera_de_horario=True
    )
    _crear_conversacion_con_consulta(
        comercio, TemaConsulta.MEDIOS_PAGO, ResultadoConsulta.RESUELTA, fuera_de_horario=False
    )
    _crear_conversacion_con_consulta(
        comercio, TemaConsulta.ENVIO, ResultadoConsulta.RESUELTA, fuera_de_horario=False
    )
    _crear_conversacion_con_consulta(
        comercio,
        TemaConsulta.RECLAMOS,
        ResultadoConsulta.DERIVADA,
        fuera_de_horario=True,
        texto="Reclamo por rotura",
    )

    # 3. Item sin stock en catálogo
    item_agotado = ItemCatalogo(
        id_comercio=comercio.id_comercio,
        nombre="Sillón Nórdico",
        precio=85000,
        stock_disponible=False,
        activo=True,
    )
    db.session.add(item_agotado)
    db.session.commit()

    # Ejecutar cálculo de analítica
    m = analitica.metricas_comercio_analitica(comercio, periodo="30", ahora=ahora)

    # Validaciones de ventas
    assert m.pedidos_totales == 3
    assert m.ventas_totales_ars == 18000
    assert m.ventas_pagadas_ars == 15000
    assert m.ventas_sin_pagar_ars == 3000
    assert m.ticket_promedio == 6000.0
    assert m.ventas_desglose["pagado_informado"] == 15000

    # Validaciones de eficiencia y tiempo ahorrado
    assert m.consultas_totales == 4
    assert m.consultas_resueltas == 3
    assert m.consultas_derivadas == 1
    assert m.horas_ahorradas == 0.3  # 3 * 0.1 hs
    assert m.tasa_resolucion_auto == 75.0  # (3/4)*100
    assert m.consultas_fuera_horario == 2

    # Radar de demanda
    conceptos_radar = [item["concepto"] for item in m.radar_demanda]
    assert any("Reclamos" in c for c in conceptos_radar)
    assert any("Sillón Nórdico" in c for c in conceptos_radar)


def test_vista_panel_analitica(cliente, sesion, comercio):
    # GET /panel/analitica para comercio autenticado
    res = cliente.get("/panel/analitica")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Impacto y métricas de negocio" in html
    assert "Ventas originadas en el chat" in html
    assert "Eficiencia y atención 24/7" in html
    assert "Radar de demanda no satisfecha" in html

    # Selector de períodos funciona
    for p in ("hoy", "7", "30", "90"):
        r_p = cliente.get(f"/panel/analitica?periodo={p}")
        assert r_p.status_code == 200


def test_panel_analitica_requiere_autenticacion(cliente):
    # Sin sesión redirige a /ingresar
    res = cliente.get("/panel/analitica")
    assert res.status_code == 302
    assert "/ingresar" in res.headers["Location"]


def test_control_acceso_superadmin(cliente, sesion):
    # Usuario normal logueado intenta entrar a /admin-saas -> redirige a ingreso superadmin
    res = cliente.get("/admin-saas")
    assert res.status_code == 302
    assert "/admin-saas/ingreso" in res.headers["Location"]

    # Acción POST protegida
    res_post = cliente.post("/admin-saas/comercios/1/plan", data={"plan": "PRO"})
    assert res_post.status_code == 302
    assert "/admin-saas/ingreso" in res_post.headers["Location"]


def test_login_superadmin_clave_maestra(cliente, app):
    # GET pantalla de login
    res = cliente.get("/admin-saas/ingreso")
    assert res.status_code == 200
    assert "SuperAdmin SaaS" in res.get_data(as_text=True)

    # Intento fallido
    res_fallido = cliente.post("/admin-saas/ingreso", data={"clave": "clave-erronea"})
    assert res_fallido.status_code == 401
    assert "incorrectas" in res_fallido.get_data(as_text=True)

    # Intento exitoso con SUPERADMIN_CLAVE de ConfigPruebas ("clave-superadmin")
    res_exito = cliente.post("/admin-saas/ingreso", data={"clave": "clave-superadmin"}, follow_redirects=True)
    assert res_exito.status_code == 200
    html = res_exito.get_data(as_text=True)
    assert "Tablero de Control SuperAdmin SaaS" in html
    assert "MRR recurrente estimado" in html

    # Logout
    res_logout = cliente.post("/admin-saas/salir", follow_redirects=True)
    assert res_logout.status_code == 200
    assert "SuperAdmin SaaS" in res_logout.get_data(as_text=True)

    # Comprobamos que quedó deslogueado
    res_dashboard = cliente.get("/admin-saas")
    assert res_dashboard.status_code == 302


def test_login_superadmin_usuario_con_rol(cliente, app, comercio):
    # Marcamos el usuario como superadmin
    usuario = comercio.usuario
    usuario.es_superadmin = True
    db.session.commit()

    # Login en /admin-saas/ingreso con su email y contraseña
    res = cliente.post(
        "/admin-saas/ingreso",
        data={"email": usuario.email, "clave": CONTRASENA},
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert "Tablero de Control SuperAdmin SaaS" in res.get_data(as_text=True)


def test_metricas_globales_superadmin_saas(app):
    ahora = tiempo.ahora()
    # 1. Crear comercios con distintos planes
    c_free = crear_comercio(nombre="Comercio Free", email="free@demo.com", codigo="FREE01")
    c_free.plan = PlanComercio.FREE

    c_pro1 = crear_comercio(nombre="Comercio Pro 1", email="pro1@demo.com", codigo="PRO001")
    c_pro1.plan = PlanComercio.PRO
    c_pro1.ia_usados_semana = 45
    c_pro1.ia_usados_interna = 15

    c_pro2 = crear_comercio(nombre="Comercio Pro 2", email="pro2@demo.com", codigo="PRO002")
    c_pro2.plan = PlanComercio.PRO
    c_pro2.ia_usados_semana = 100
    c_pro2.ia_usados_interna = 20

    c_corp = crear_comercio(nombre="Comercio Corp", email="corp@demo.com", codigo="CORP01")
    c_corp.plan = PlanComercio.ENTERPRISE
    c_corp.saldo_creditos = 500

    # 2. Transacción de recarga de pack aprobada en el mes
    tx = TransaccionPago(
        id_comercio=c_pro1.id_comercio,
        proveedor="mercadopago",
        tipo="RECARGA_CREDITOS",
        monto=4500,
        estado="APROBADO",
        detalle="Pack +200 créditos",
        fecha_creacion=ahora,
        fecha_actualizacion=ahora,
    )
    db.session.add(tx)
    db.session.commit()

    # Cálculo métricas superadmin
    m = analitica.metricas_superadmin_saas()

    assert m.total_comercios == 4
    assert m.comercios_por_plan["GRATIS"] == 1
    assert m.comercios_por_plan["PRO"] == 2
    assert m.comercios_por_plan["A_MEDIDA"] == 1

    # MRR = 2 comercios PRO * 14.900 = 29.800
    assert m.mrr_estimado_ars == 29800
    assert m.facturacion_packs_mes_ars == 4500

    # Total IA = (45+15) + (100+20) = 180
    assert m.total_ia_usados == 180
    assert m.costo_estimado_ia_ars == 0
    assert m.margen_estimado_porcentaje > 95.0

    # Flota
    assert len(m.flota_comercios) == 4
    nombres_flota = [item["nombre"] for item in m.flota_comercios]
    assert "Comercio Pro 1" in nombres_flota
    assert "Comercio Corp" in nombres_flota


def test_acciones_superadmin_flota(cliente, app, comercio):
    # Ingresamos como superadmin
    cliente.post("/admin-saas/ingreso", data={"clave": "clave-superadmin"})

    # 1. Cambiar plan a PRO
    res_plan = cliente.post(
        f"/admin-saas/comercios/{comercio.id_comercio}/plan",
        data={"plan": "PRO"},
        follow_redirects=True,
    )
    assert res_plan.status_code == 200
    db.session.refresh(comercio)
    assert comercio.plan == PlanComercio.PRO
    assert comercio.ia_cuota_semanal == 250

    # Cambiar plan a A_MEDIDA
    cliente.post(
        f"/admin-saas/comercios/{comercio.id_comercio}/plan",
        data={"plan": "A_MEDIDA"},
        follow_redirects=True,
    )
    db.session.refresh(comercio)
    assert comercio.plan == PlanComercio.ENTERPRISE

    # 2. Otorgar créditos de cortesía
    saldo_anterior = comercio.saldo_creditos
    res_creditos = cliente.post(
        f"/admin-saas/comercios/{comercio.id_comercio}/creditos",
        data={"creditos": "200"},
        follow_redirects=True,
    )
    assert res_creditos.status_code == 200
    db.session.refresh(comercio)
    assert comercio.saldo_creditos == saldo_anterior + 200

    # 3. Pausar y activar bot
    assert comercio.estado == EstadoComercio.ACTIVO
    res_pausa = cliente.post(
        f"/admin-saas/comercios/{comercio.id_comercio}/estado",
        data={"accion": "pausar"},
        follow_redirects=True,
    )
    assert res_pausa.status_code == 200
    db.session.refresh(comercio)
    assert comercio.estado == EstadoComercio.PAUSADO

    res_activa = cliente.post(
        f"/admin-saas/comercios/{comercio.id_comercio}/estado",
        data={"accion": "activar"},
        follow_redirects=True,
    )
    assert res_activa.status_code == 200
    db.session.refresh(comercio)
    assert comercio.estado == EstadoComercio.ACTIVO


def test_cli_superadmin(app, comercio):
    runner = app.test_cli_runner()
    usuario = comercio.usuario
    assert usuario.es_superadmin is False

    # Asignar superadmin via CLI
    r = runner.invoke(args=["admin", "superadmin", usuario.email])
    assert r.exit_code == 0, r.output
    assert "ahora es superadmin" in r.output
    db.session.refresh(usuario)
    assert usuario.es_superadmin is True

    # Quitar superadmin via CLI
    r_quitar = runner.invoke(args=["admin", "superadmin", usuario.email, "--remover"])
    assert r_quitar.exit_code == 0, r_quitar.output
    assert "retirado" in r_quitar.output
    db.session.refresh(usuario)
    assert usuario.es_superadmin is False

    # Usuario inexistente
    r_err = runner.invoke(args=["admin", "superadmin", "nadie@ejemplo.com"])
    assert r_err.exit_code != 0
    assert "No existe un usuario" in r_err.output


def test_metricas_comercio_analitica_vacio(app, comercio):
    # Sin pedidos ni consultas
    m = analitica.metricas_comercio_analitica(comercio, periodo="hoy")
    assert m.pedidos_totales == 0
    assert m.ventas_totales_ars == 0
    assert m.ticket_promedio == 0
    assert m.consultas_totales == 0
    assert m.horas_ahorradas == 0.0
    assert m.tasa_resolucion_auto == 0.0
    assert m.radar_demanda == []


def test_superadmin_email_config_permite_acceso(cliente, app, comercio):
    # Configurar SUPERADMIN_EMAIL coincidente con el email de usuario
    usuario = comercio.usuario
    app.config["SUPERADMIN_EMAIL"] = usuario.email

    # Ingresar como comercio normal
    ingresar(cliente, usuario.email)

    # Ahora tiene acceso a /admin-saas directamente por email configurado
    res = cliente.get("/admin-saas")
    assert res.status_code == 200
    assert "Tablero de Control SuperAdmin SaaS" in res.get_data(as_text=True)


def test_superadmin_rutas_inexistentes_404_y_errores(cliente, app):
    # Ingresar como superadmin
    cliente.post("/admin-saas/ingreso", data={"clave": "clave-superadmin"})

    # Comercio inexistente -> 404
    assert cliente.post("/admin-saas/comercios/99999/plan", data={"plan": "PRO"}).status_code == 404
    assert cliente.post("/admin-saas/comercios/99999/creditos", data={"creditos": "50"}).status_code == 404
    assert cliente.post("/admin-saas/comercios/99999/estado", data={"accion": "pausar"}).status_code == 404


def test_enlace_analitica_en_base_panel(cliente, sesion):
    res = cliente.get("/panel")
    html = res.get_data(as_text=True)
    assert 'href="/panel/analitica"' in html
    assert "Impacto y métricas" in html
