"""Pruebas de la Fase 1: SaaS, multi-línea WhatsApp, cuotas IA y billetera prepaga."""

from datetime import date, timedelta

from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.extensiones import db
from app.mensajeria.cloud_api import ClienteWhatsApp, extraer_mensajes
from app.modelos import Comercio, EstadoConversacion, PlanComercio
from app.web.activacion import enlaces


def test_plan_comercio_enum():
    assert PlanComercio.FREE.value == "FREE"
    assert PlanComercio.PRO.value == "PRO"
    assert PlanComercio.ENTERPRISE.value == "ENTERPRISE"
    assert PlanComercio.FREE.etiqueta == "Plan Gratuito"
    assert PlanComercio.PRO.etiqueta == "Plan Pro Mensual"
    assert PlanComercio.ENTERPRISE.etiqueta == "Plan a Medida"


def test_asegurar_slug_y_activar_bot(comercio):
    # Inicialmente slug es None
    assert comercio.slug is None
    slug = comercio.asegurar_slug()
    assert slug == "casa-y-detalles"
    assert comercio.slug == "casa-y-detalles"
    # Llamar de nuevo devuelve el mismo slug
    assert comercio.asegurar_slug() == "casa-y-detalles"

    # Otro comercio con el mismo nombre genera slug sufijado
    otro = Comercio(
        nombre="Casa & Detalles",
        rubro="Bazar",
        telefono_contacto="351 999-9999",
        paso_onboarding=6,
    )
    db.session.add(otro)
    db.session.flush()
    slug_otro = otro.asegurar_slug()
    assert slug_otro == "casa-y-detalles-2"

    # activar_bot asegura el slug
    comercio.slug = None
    comercio.activar_bot()
    assert comercio.slug is not None


def test_tiene_whatsapp_propio_y_generar_enlace(comercio):
    comercio.plan = PlanComercio.FREE
    comercio.whatsapp_phone_number_id = "phone_123"
    comercio.whatsapp_token = "token_abc"
    comercio.whatsapp_numero_publico = "54 9 351 111-2222"

    # En FREE no se considera WhatsApp propio
    assert not comercio.tiene_whatsapp_propio

    # En PRO sí
    comercio.plan = PlanComercio.PRO
    assert comercio.tiene_whatsapp_propio

    # En ENTERPRISE sí
    comercio.plan = PlanComercio.ENTERPRISE
    assert comercio.tiene_whatsapp_propio

    enlace = comercio.generar_enlace_whatsapp_propio()
    assert "https://wa.me/5493511112222" in enlace
    assert "Hola%20Casa%20%26%20Detalles%2C%20quiero%20hacer%20una%20consulta." in enlace
    # Sin código de acceso en el enlace propio
    assert "CASA26" not in enlace


def test_cliente_whatsapp_para_comercio(app, comercio):
    with app.app_context():
        # Comercio sin línea propia -> cae a configuración por defecto
        comercio.whatsapp_phone_number_id = None
        comercio.whatsapp_token = None
        cliente_def = ClienteWhatsApp.para_comercio(comercio)
        assert cliente_def.phone_number_id == app.config.get("WHATSAPP_PHONE_NUMBER_ID", "")

        # Comercio con línea propia
        comercio.whatsapp_phone_number_id = "phone_propio_999"
        comercio.whatsapp_token = "token_propio_secret"
        cliente_propio = ClienteWhatsApp.para_comercio(comercio)
        assert cliente_propio.phone_number_id == "phone_propio_999"
        assert cliente_propio.token == "token_propio_secret"


def test_extraer_mensajes_con_phone_number_id():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "phone_meta_555"},
                            "messages": [
                                {"from": "5493510000001", "id": "w1", "type": "text", "text": {"body": "hola"}}
                            ],
                        }
                    }
                ]
            }
        ]
    }
    eventos = extraer_mensajes(payload)
    assert len(eventos) == 1
    assert eventos[0].phone_number_id == "phone_meta_555"


def test_enrutamiento_directo_por_phone_number_id(comercio):
    comercio.plan = PlanComercio.PRO
    comercio.whatsapp_phone_number_id = "phone_dedicado_1"
    comercio.whatsapp_token = "tok_1"
    db.session.commit()

    tel = "5493519998888"
    # El mensaje entra por la línea del comercio, sin código de acceso en el texto
    resultado = procesar_mensaje_entrante(
        MensajeEntrante(
            telefono=tel,
            texto="Hola qué horarios tienen?",
            phone_number_id="phone_dedicado_1",
            id_externo="wam_ded_1",
        )
    )

    # Reconoce al comercio sin código
    assert resultado.conversacion is not None
    assert resultado.conversacion.id_comercio == comercio.id_comercio
    assert any("horario" in r.texto.lower() or "abierto" in r.texto.lower() for r in resultado.respuestas)

    # Segundo mensaje al mismo comercio continúa la conversación
    resultado2 = procesar_mensaje_entrante(
        MensajeEntrante(
            telefono=tel,
            texto="Y qué medios de pago aceptan?",
            phone_number_id="phone_dedicado_1",
            id_externo="wam_ded_2",
        )
    )
    assert resultado2.conversacion.id_conversacion == resultado.conversacion.id_conversacion


def test_enrutamiento_directo_cierra_conversacion_con_otro_comercio(comercio):
    # Comercio A (el del fixture, con código CASA26)
    # Comercio B (con línea dedicada)
    comercio_b = Comercio(
        nombre="Boutique B",
        rubro="Ropa",
        telefono_contacto="351 888-7777",
        paso_onboarding=6,
        plan=PlanComercio.PRO,
        whatsapp_phone_number_id="phone_dedicado_b",
        whatsapp_token="tok_b",
    )
    comercio_b.activar_bot()
    db.session.add(comercio_b)
    db.session.commit()

    tel = "5493517776666"

    # Comprador habla primero con Comercio A usando código
    res_a = procesar_mensaje_entrante(
        MensajeEntrante(telefono=tel, texto=f"Hola {comercio.codigo_acceso}", id_externo="msg_a1")
    )
    assert res_a.conversacion.id_comercio == comercio.id_comercio
    assert res_a.conversacion.estado == EstadoConversacion.ACTIVA

    # Ahora el comprador envía mensaje a la línea de Comercio B
    res_b = procesar_mensaje_entrante(
        MensajeEntrante(
            telefono=tel,
            texto="Hola tienen stock?",
            phone_number_id="phone_dedicado_b",
            id_externo="msg_b1",
        )
    )
    # La conversación con A se cerró y ahora está con B
    assert res_b.conversacion.id_comercio == comercio_b.id_comercio
    assert res_a.conversacion.estado == EstadoConversacion.CERRADA


def test_enrutamiento_directo_por_id_comercio_directo(comercio):
    # Caso canal web /t/<slug>
    tel = "5493515554444"
    res = procesar_mensaje_entrante(
        MensajeEntrante(
            telefono=tel,
            texto="Hacen envíos a Nueva Córdoba?",
            id_comercio_directo=comercio.id_comercio,
            id_externo="web_msg_1",
        )
    )
    assert res.conversacion.id_comercio == comercio.id_comercio
    assert res.conversacion.comercio.nombre == comercio.nombre


def test_cuotas_ia_plan_free(comercio):
    hoy = date(2026, 11, 10)
    comercio.plan = PlanComercio.FREE
    comercio.ia_habilitada = True
    comercio.saldo_creditos = 0

    assert not comercio.puede_usar_ia_chat(hoy)
    assert not comercio.consumir_ia_chat(hoy)

    # Con saldo prepago sí puede
    comercio.saldo_creditos = 3
    assert comercio.puede_usar_ia_chat(hoy)
    assert comercio.consumir_ia_chat(hoy)
    assert comercio.saldo_creditos == 2


def test_cuotas_ia_plan_pro_semanal_y_reinicio(comercio):
    hoy = date(2026, 11, 1)
    comercio.plan = PlanComercio.PRO
    comercio.ia_habilitada = True
    comercio.ia_cuota_semanal = 2  # cuota chica para el test
    comercio.ia_usados_semana = 0
    comercio.ia_semana_inicio = hoy
    comercio.saldo_creditos = 1

    # 1er uso
    assert comercio.puede_usar_ia_chat(hoy)
    assert comercio.consumir_ia_chat(hoy)
    assert comercio.ia_usados_semana == 1
    assert comercio.saldo_creditos == 1

    # 2do uso (agota cuota semanal)
    assert comercio.puede_usar_ia_chat(hoy)
    assert comercio.consumir_ia_chat(hoy)
    assert comercio.ia_usados_semana == 2
    assert comercio.saldo_creditos == 1

    # 3er uso: cuota semanal agotada, usa saldo_creditos
    assert comercio.puede_usar_ia_chat(hoy)
    assert comercio.consumir_ia_chat(hoy)
    assert comercio.ia_usados_semana == 2
    assert comercio.saldo_creditos == 0

    # 4to uso: sin cuota y sin créditos
    assert not comercio.puede_usar_ia_chat(hoy)
    assert not comercio.consumir_ia_chat(hoy)

    # Pasan 7 días (reinicio semanal)
    semana_siguiente = hoy + timedelta(days=7)
    assert comercio.puede_usar_ia_chat(semana_siguiente)
    assert comercio.ia_semana_inicio == semana_siguiente
    assert comercio.ia_usados_semana == 0
    assert comercio.consumir_ia_chat(semana_siguiente)
    assert comercio.ia_usados_semana == 1


def test_cuotas_ia_plan_enterprise_prepago_estricto(comercio):
    hoy = date(2026, 11, 10)
    comercio.plan = PlanComercio.ENTERPRISE
    comercio.ia_habilitada = True
    comercio.saldo_creditos = 0

    # Sin saldo no puede
    assert not comercio.puede_usar_ia_chat(hoy)
    assert not comercio.consumir_ia_chat(hoy)

    # Con saldo sí descuenta
    comercio.saldo_creditos = 2
    assert comercio.puede_usar_ia_chat(hoy)
    assert comercio.consumir_ia_chat(hoy)
    assert comercio.saldo_creditos == 1


def test_cuota_ia_interna(comercio):
    comercio.ia_habilitada = True
    comercio.ia_cuota_interna = 2
    comercio.ia_usados_interna = 0
    comercio.saldo_creditos = 1

    assert comercio.puede_usar_ia_interna()
    assert comercio.consumir_ia_interna()
    assert comercio.ia_usados_interna == 1

    assert comercio.puede_usar_ia_interna()
    assert comercio.consumir_ia_interna()
    assert comercio.ia_usados_interna == 2

    # Agotó cuota interna, usa crédito
    assert comercio.puede_usar_ia_interna()
    assert comercio.consumir_ia_interna()
    assert comercio.saldo_creditos == 0

    # Sin crédito ni cuota
    assert not comercio.puede_usar_ia_interna()
    assert not comercio.consumir_ia_interna()


def test_ia_deshabilitada_globalmente(comercio):
    hoy = date(2026, 11, 10)
    comercio.ia_habilitada = False
    comercio.plan = PlanComercio.PRO
    comercio.ia_cuota_semanal = 500
    comercio.saldo_creditos = 100

    assert not comercio.puede_usar_ia_chat(hoy)
    assert not comercio.consumir_ia_chat(hoy)
    assert not comercio.puede_usar_ia_interna()
    assert not comercio.consumir_ia_interna()


def test_enlaces_activacion(app, comercio):
    with app.test_request_context():
        # Comercio sin línea propia usa número público de plataforma si existe
        app.config["WHATSAPP_NUMERO_PUBLICO"] = "5493510000000"
        app.config["SIMULADOR_HABILITADO"] = True
        datos = enlaces(comercio)
        assert datos["whatsapp"] is not None
        assert "wa.me/5493510000000" in datos["whatsapp"]
        assert datos["qr_destino"] == datos["whatsapp"]

        # Comercio con línea propia en PRO prioriza su línea propia
        comercio.plan = PlanComercio.PRO
        comercio.whatsapp_phone_number_id = "phone_111"
        comercio.whatsapp_token = "tok_111"
        comercio.whatsapp_numero_publico = "54 9 351 222-3333"
        datos_propio = enlaces(comercio)
        assert "wa.me/5493512223333" in datos_propio["whatsapp"]
        assert datos_propio["qr_destino"] == datos_propio["whatsapp"]
