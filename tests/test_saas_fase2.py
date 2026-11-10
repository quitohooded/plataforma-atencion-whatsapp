"""Pruebas de la Fase 2: Canal Web Propio (/t/<slug> y subdominios), Planes Comerciales y Panel de Gestión."""

from sqlalchemy import select

from app.extensiones import db
from app.modelos import Comercio, PlanComercio, SolicitudVentas
from app.utilidades import tiempo
from app.web.activacion import enlaces


def test_canal_web_acceso_y_conversacion_sin_codigo(cliente, comercio):
    """Acceso y flujo completo de conversación en /t/<slug> sin requerir código de acceso."""
    slug = comercio.asegurar_slug()
    db.session.commit()

    # 1. GET /t/<slug>
    r = cliente.get(f"/t/{slug}")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Casa &amp; Detalles" in html or comercio.nombre in html
    assert f"/t/{slug}/mensajes" in html
    assert f"/t/{slug}/reiniciar" in html

    # Verificamos que se generó un teléfono virtual en sesión con formato 5493518XXXXXX
    with cliente.session_transaction() as sess:
        tel = sess.get(f"comprador_web_{comercio.id_comercio}")
        assert tel is not None
        assert tel.startswith("5493518")
        assert len(tel) in (13, 17)

    # 2. POST /t/<slug>/mensajes sin código de acceso en el texto
    r_msg = cliente.post(
        f"/t/{slug}/mensajes",
        json={"texto": "Hola! ¿Hacen envíos a Río Cuarto?"},
    )
    assert r_msg.status_code == 200
    datos = r_msg.get_json()
    assert "respuestas" in datos
    assert len(datos["respuestas"]) > 0
    # Responde directamente con información de envíos de Casa & Detalles
    assert "código postal" in datos["respuestas"][0]["texto"] or "Río Cuarto" in datos["respuestas"][0]["texto"]

    # 3. Respuesta con código postal
    r_cp = cliente.post(f"/t/{slug}/mensajes", json={"texto": "5800"})
    assert r_cp.status_code == 200
    datos_cp = r_cp.get_json()
    assert any("2 a 4 días hábiles" in r["texto"] for r in datos_cp["respuestas"])

    # 4. POST /t/<slug>/reiniciar genera un nuevo teléfono virtual
    with cliente.session_transaction() as sess:
        tel_viejo = sess.get(f"comprador_web_{comercio.id_comercio}")

    r_reset = cliente.post(f"/t/{slug}/reiniciar")
    assert r_reset.status_code == 200
    assert r_reset.get_json() == {"ok": True}

    with cliente.session_transaction() as sess:
        tel_nuevo = sess.get(f"comprador_web_{comercio.id_comercio}")
        assert tel_nuevo.startswith("5493518")
        assert tel_nuevo != tel_viejo


def test_canal_web_acceso_por_codigo_acceso_y_404(cliente, comercio):
    """Acceso alternativo pasando el código de acceso del comercio y 404 para inexistentes."""
    # Acceso por código en minúsculas
    r = cliente.get(f"/t/{comercio.codigo_acceso.lower()}")
    assert r.status_code == 200
    assert "Casa &amp; Detalles" in r.get_data(as_text=True) or comercio.nombre in r.get_data(as_text=True)

    # Inexistente da 404
    r_404 = cliente.get("/t/comercio-inexistente-xyz")
    assert r_404.status_code == 404


def test_canal_web_subdominio(cliente, comercio):
    """Detección automática de subdominios que coinciden con Comercio.slug."""
    slug = comercio.asegurar_slug()
    db.session.commit()

    # Petición a / con Host de subdominio
    r = cliente.get("/", headers={"Host": f"{slug}.localhost:5000"})
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Casa &amp; Detalles" in html or comercio.nombre in html
    assert f"/t/{slug}/mensajes" in html

    # Host sin subdominio sirve la portada pública normal
    r_normal = cliente.get("/", headers={"Host": "localhost:5000"})
    assert r_normal.status_code == 200
    assert "Las consultas de siempre, respondidas al instante" in r_normal.get_data(as_text=True)


def test_canal_web_embed_seguridad_headers(cliente, comercio):
    """Modo ?embed=1 permite SAMEORIGIN y quita la cabecera exterior."""
    slug = comercio.asegurar_slug()
    db.session.commit()

    # Sin embed: X-Frame-Options DENY y cabecera visible
    r_normal = cliente.get(f"/t/{slug}")
    assert r_normal.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r_normal.headers["Content-Security-Policy"]
    assert "Conocé la plataforma" in r_normal.get_data(as_text=True)

    # Con ?embed=1: X-Frame-Options SAMEORIGIN, CSP frame-ancestors *, sin cabecera exterior
    r_embed = cliente.get(f"/t/{slug}?embed=1")
    assert r_embed.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors *" in r_embed.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" not in r_embed.headers["Content-Security-Policy"]
    assert "Conocé la plataforma" not in r_embed.get_data(as_text=True)
    assert "canal-web--embed" in r_embed.get_data(as_text=True)


def test_pagina_publica_planes(cliente):
    """Página pública comparativa de planes."""
    r = cliente.get("/planes")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Plan Gratuito" in html
    assert "Plan Pro Mensual" in html
    assert "Plan a Medida" in html
    assert "250 por semana" in html
    assert "Billetera Prepaga" in html
    assert "/ventas" in html


def test_formulario_contacto_ventas(cliente, app):
    """Formulario de contacto con ventas para Plan a Medida."""
    # GET muestra el formulario
    r_get = cliente.get("/ventas")
    assert r_get.status_code == 200
    assert "Conversemos sobre un Plan a Medida" in r_get.get_data(as_text=True)

    # POST inválido (faltan datos requeridos)
    r_invalido = cliente.post("/ventas", data={"nombre_contacto": ""})
    assert r_invalido.status_code == 400
    assert "complete su nombre y correo" in r_invalido.get_data(as_text=True)

    # POST válido crea SolicitudVentas
    r_post = cliente.post(
        "/ventas",
        data={
            "nombre_contacto": "María Sol Pérez",
            "email": "sol@empresa.com",
            "telefono": "+54 9 351 987-6543",
            "volumen_mensual": "10.000 a 50.000 consultas/mes",
            "sistemas_actuales": "TiendaNube y Tango",
            "mensaje": "Necesitamos 3 líneas de WhatsApp y recarga prepaga.",
        },
        follow_redirects=True,
    )
    assert r_post.status_code == 200
    assert "¡Gracias por contactarnos!" in r_post.get_data(as_text=True)

    with app.app_context():
        solicitud = db.session.scalar(select(SolicitudVentas).where(SolicitudVentas.email == "sol@empresa.com"))
        assert solicitud is not None
        assert solicitud.nombre_contacto == "María Sol Pérez"
        assert solicitud.volumen_mensual == "10.000 a 50.000 consultas/mes"
        assert solicitud.estado == "NUEVA"


def test_panel_gestion_plan_cambio_recarga_y_whatsapp(sesion, comercio, app):
    """Gestión integral del plan en el panel del comercio."""
    # 1. GET /plan con comercio en Plan Gratuito
    r_panel = sesion.get("/plan")
    assert r_panel.status_code == 200
    html = r_panel.get_data(as_text=True)
    assert "Plan Gratuito" in html
    assert "Cuota de Inteligencia Artificial" in html
    assert "Billetera Prepaga" in html
    assert "Línea propia de WhatsApp" in html

    # 2. POST /plan/cambiar activa Plan Pro Mensual
    r_pro = sesion.post("/plan/cambiar", data={"plan": "PRO"}, follow_redirects=True)
    assert r_pro.status_code == 200
    assert "Plan Pro Mensual activado con éxito" in r_pro.get_data(as_text=True)

    with app.app_context():
        c = db.session.get(Comercio, comercio.id_comercio)
        assert c.plan == PlanComercio.PRO
        assert c.ia_cuota_semanal == 250
        assert c.ia_cuota_interna == 100
        assert c.ia_semana_inicio == tiempo.ahora().date()

    # 3. POST /plan/recargar acredita créditos y guarda configuración de billetera
    r_recarga = sesion.post(
        "/plan/recargar",
        data={
            "cantidad": "500",
            "recarga_automatica": "1",
            "umbral_alerta_creditos": "75",
        },
        follow_redirects=True,
    )
    assert r_recarga.status_code == 200
    assert "Se acreditaron 500 créditos" in r_recarga.get_data(as_text=True)

    with app.app_context():
        c = db.session.get(Comercio, comercio.id_comercio)
        assert c.saldo_creditos == 500
        assert c.recarga_automatica is True
        assert c.umbral_alerta_creditos == 75

    # 4. POST /plan/whatsapp guarda credenciales de la línea propia
    r_wsp = sesion.post(
        "/plan/whatsapp",
        data={
            "whatsapp_numero_publico": "+54 9 351 777-8888",
            "whatsapp_phone_number_id": "meta_phone_12345",
            "whatsapp_waba_id": "meta_waba_67890",
            "whatsapp_token": "EAAGsecretToken123",
        },
        follow_redirects=True,
    )
    assert r_wsp.status_code == 200
    assert "Credenciales de su línea propia de WhatsApp guardadas con éxito" in r_wsp.get_data(as_text=True)

    with app.app_context():
        c = db.session.get(Comercio, comercio.id_comercio)
        assert c.whatsapp_numero_publico == "+54 9 351 777-8888"
        assert c.whatsapp_phone_number_id == "meta_phone_12345"
        assert c.whatsapp_waba_id == "meta_waba_67890"
        assert c.whatsapp_token == "EAAGsecretToken123"
        assert c.tiene_whatsapp_propio is True

    # 5. POST /plan/whatsapp con accion="desconectar"
    r_desc = sesion.post(
        "/plan/whatsapp",
        data={"accion": "desconectar"},
        follow_redirects=True,
    )
    assert r_desc.status_code == 200
    assert "Línea de WhatsApp desconectada" in r_desc.get_data(as_text=True)

    with app.app_context():
        c = db.session.get(Comercio, comercio.id_comercio)
        assert c.whatsapp_phone_number_id is None
        assert c.whatsapp_token is None
        assert c.tiene_whatsapp_propio is False


def test_enlaces_activacion_y_menu_panel(app, sesion, comercio):
    """Verifica la presencia del canal web en activacion.html y del enlace en base_panel.html."""
    comercio.activar_bot()
    db.session.commit()

    with app.test_request_context():
        datos_enlaces = enlaces(comercio)
        assert datos_enlaces["canal_web"] is not None
        assert f"/t/{comercio.slug}" in datos_enlaces["canal_web"]

    # Vista activacion muestra el canal web y el embed
    r_act = sesion.get("/activacion")
    assert r_act.status_code == 200
    html_act = r_act.get_data(as_text=True)
    assert "Canal de atención web propio" in html_act
    assert "iframe" in html_act
    assert f"/t/{comercio.slug}" in html_act

    # Menú lateral contiene el enlace a Plan y WhatsApp propio
    assert 'href="/plan"' in html_act
    assert "Plan y WhatsApp propio" in html_act


def test_portada_enlaces_a_planes_y_ventas(cliente):
    """La portada muestra enlaces a ver planes y precios y contactar con ventas."""
    r = cliente.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'href="/planes"' in html
    assert "Ver planes y precios" in html
    assert 'href="/ventas"' in html
    assert "Contactar con ventas" in html


def test_generar_telefono_web_entropia_y_formato():
    """Verifica que el identificador virtual web tenga 10 dígitos aleatorios (17 total) para evitar colisiones."""
    from app.web.canal_web import PREFIJO_WEB, es_telefono_web, generar_telefono_web

    tel = generar_telefono_web()
    assert tel.startswith(PREFIJO_WEB)
    assert len(tel) == 17  # 7 prefijo + 10 dígitos aleatorios
    assert tel.isdigit()
    assert es_telefono_web(tel) is True
    # Soporte hacia atrás para teléfonos web previos de 13 dígitos
    assert es_telefono_web("5493518123456") is True
    # Rechazo de formato no web o inválido
    assert es_telefono_web("5491112345678") is False
    assert es_telefono_web("5493518abc") is False
    assert es_telefono_web(None) is False
