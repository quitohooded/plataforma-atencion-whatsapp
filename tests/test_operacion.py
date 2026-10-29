"""Operación (#13): estados de entrega del webhook, firma obligatoria, retención de datos,
comandos de administración, verificación de la configuración y estado del servicio."""

import json
import logging
import sqlite3
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import create_app
from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.config import ConfigPruebas
from app.extensiones import db
from app.mensajeria.cloud_api import ClienteWhatsApp, ErrorEnvio, extraer_estados
from app.modelos import (
    Bloqueo,
    Comercio,
    Comprador,
    Consulta,
    Conversacion,
    DireccionMensaje,
    EstadoComercio,
    Mensaje,
    Usuario,
)
from app.servicios import retencion
from app.verificacion import problemas_de_configuracion

from .conftest import CONTRASENA, crear_comercio, ingresar
from .test_webhook_y_simulador import evento, firmar, publicar

# --- Webhook: lectura y estados de entrega (O7) -------------------------------


def estados(*items):
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"field": "messages", "value": {"statuses": list(items)}}]}],
    }


def estado(id_mensaje, nombre, **extra):
    return {"id": id_mensaje, "status": nombre, "recipient_id": "5493511234567", "timestamp": "1793151000", **extra}


FALLA = {
    "errors": [{"code": 131026, "title": "Message undeliverable", "error_data": {"details": "Sin WhatsApp"}}],
}


def test_extraer_estados_con_el_detalle_de_la_falla():
    leidos = extraer_estados(estados(estado("wamid.S1", "read"), estado("wamid.S2", "failed", **FALLA)))
    assert [(e.id_externo, e.estado) for e in leidos] == [("wamid.S1", "leido"), ("wamid.S2", "fallido")]
    assert leidos[1].error == "131026 Message undeliverable: Sin WhatsApp"
    # Estados desconocidos o sin identificador se ignoran.
    assert extraer_estados(estados({"status": "read"}, estado("wamid.S3", "played"))) == []


@pytest.fixture
def api_falsa(monkeypatch):
    """Registra lo que el webhook manda a la Graph API y devuelve identificadores de WhatsApp."""
    llamadas = {"leidos": [], "enviados": []}

    def enviar(self, telefono, respuesta):
        llamadas["enviados"].append(respuesta.texto)
        return f"wamid.R{len(llamadas['enviados'])}"

    monkeypatch.setattr(ClienteWhatsApp, "enviar", enviar)
    monkeypatch.setattr(ClienteWhatsApp, "marcar_leido", lambda self, id_mensaje: llamadas["leidos"].append(id_mensaje))
    return llamadas


def _salientes():
    return db.session.scalars(
        select(Mensaje).where(Mensaje.direccion == DireccionMensaje.SALIENTE).order_by(Mensaje.id_mensaje)
    ).all()


def test_el_webhook_marca_leido_y_guarda_el_id_de_cada_respuesta(cliente, comercio, api_falsa):
    publicar(cliente, evento(comercio.texto_primer_mensaje(), id_mensaje="wamid.E1"))
    assert api_falsa["leidos"] == ["wamid.E1"]
    respuesta = _salientes()[0]
    assert respuesta.id_externo == "wamid.R1" and respuesta.estado_envio == "enviado"


def test_estados_de_entrega_en_cualquier_orden(cliente, comercio, api_falsa):
    publicar(cliente, evento(comercio.texto_primer_mensaje(), id_mensaje="wamid.E1"))
    publicar(cliente, estados(estado("wamid.R1", "read")))
    publicar(cliente, estados(estado("wamid.R1", "delivered")))  # llega tarde: no pisa «leído»
    respuesta = _salientes()[0]
    db.session.refresh(respuesta)
    assert respuesta.estado_envio == "leido" and respuesta.etiqueta_estado_envio == "Leído"


def test_falla_de_entrega_queda_registrada_y_se_ve_en_el_panel(cliente, comercio, api_falsa, caplog):
    publicar(cliente, evento(comercio.texto_primer_mensaje(), id_mensaje="wamid.E1"))
    publicar(cliente, evento("Me llegó roto el pedido", id_mensaje="wamid.E2"))
    with caplog.at_level(logging.WARNING):
        r = publicar(cliente, estados(estado("wamid.R2", "failed", **FALLA)))
    assert r.status_code == 200
    assert "no pudo entregar el mensaje wamid.R2" in caplog.text and "131026" in caplog.text
    # El registro no expone el número completo del comprador.
    assert "5493511234567" not in caplog.text and "…4567" in caplog.text

    ingresar(cliente)
    consulta = db.session.scalar(select(Consulta).where(Consulta.resultado != None))  # noqa: E711
    html = cliente.get(f"/historial/{consulta.id_consulta}").get_data(as_text=True)
    assert "No entregado" in html and "WhatsApp no pudo entregar al menos una respuesta" in html


def test_error_al_enviar_marca_la_respuesta_como_no_entregada(cliente, comercio, monkeypatch):
    def falla(self, telefono, respuesta):
        raise ErrorEnvio("WhatsApp rechazó el envío", 131047)

    monkeypatch.setattr(ClienteWhatsApp, "enviar", falla)
    monkeypatch.setattr(ClienteWhatsApp, "marcar_leido", lambda self, id_mensaje: None)
    publicar(cliente, evento(comercio.texto_primer_mensaje(), id_mensaje="wamid.E1"))
    assert all(m.no_entregado for m in _salientes())


def test_falla_al_marcar_leido_no_impide_responder(cliente, comercio, monkeypatch):
    enviados = []

    def leido(self, id_mensaje):
        raise ErrorEnvio("sin conexión")

    monkeypatch.setattr(ClienteWhatsApp, "marcar_leido", leido)
    monkeypatch.setattr(ClienteWhatsApp, "enviar", lambda self, tel, r: enviados.append(r) or None)
    publicar(cliente, evento(comercio.texto_primer_mensaje(), id_mensaje="wamid.E1"))
    assert len(enviados) == 1


def test_marcar_leido_usa_la_api_de_estados(monkeypatch):
    cuerpos = []
    cliente = ClienteWhatsApp(token="t", phone_number_id="123")
    monkeypatch.setattr(ClienteWhatsApp, "_publicar", lambda self, cuerpo: cuerpos.append(cuerpo))
    cliente.marcar_leido("wamid.X")
    assert cuerpos == [{"messaging_product": "whatsapp", "status": "read", "message_id": "wamid.X"}]
    # Sin la línea configurada no se llama a la API.
    ClienteWhatsApp(token="", phone_number_id="").marcar_leido("wamid.X")
    assert len(cuerpos) == 1


# --- Firma obligatoria (O10) ----------------------------------------------------


class ConfigSinClave(ConfigPruebas):
    WHATSAPP_APP_SECRET = ""


class ConfigSinClavePermitida(ConfigSinClave):
    WHATSAPP_PERMITIR_SIN_FIRMA = True


@pytest.mark.parametrize(("config", "esperado"), [(ConfigSinClave, 401), (ConfigSinClavePermitida, 200)])
def test_sin_clave_secreta_el_webhook_rechaza_salvo_permiso_explicito(reloj, config, esperado):
    aplicacion = create_app(config)
    with aplicacion.app_context():
        comercio = crear_comercio()
        cuerpo = json.dumps(evento(comercio.texto_primer_mensaje())).encode()
        r = aplicacion.test_client().post("/webhook/whatsapp", data=cuerpo, content_type="application/json")
        assert r.status_code == esperado
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def test_firma_correcta_sigue_funcionando(cliente, comercio, api_falsa):
    cuerpo = json.dumps(evento(comercio.texto_primer_mensaje())).encode()
    r = cliente.post(
        "/webhook/whatsapp",
        data=cuerpo,
        content_type="application/json",
        headers={"X-Hub-Signature-256": firmar(cuerpo)},
    )
    assert r.status_code == 200


# --- Retención de datos (O6) ------------------------------------------------------


def _conversacion(comercio, telefono, texto, reloj, dias_atras):
    """Mensaje del comprador hace ``dias_atras`` días (el bot lo atiende con el reloj de ese momento)."""
    actual = reloj.actual
    reloj.actual = actual - timedelta(days=dias_atras)
    try:
        procesar_mensaje_entrante(MensajeEntrante(telefono=telefono, texto=comercio.texto_primer_mensaje()))
        resultado = procesar_mensaje_entrante(MensajeEntrante(telefono=telefono, texto=texto))
    finally:
        reloj.actual = actual
    return resultado


def _contar(modelo):
    return db.session.scalar(select(func.count()).select_from(modelo))


def test_depurar_borra_lo_viejo_y_conserva_lo_pendiente(app, comercio, reloj):
    _conversacion(comercio, "5493511110001", "¿Aceptan Mercado Pago?", reloj, 400)  # vieja y resuelta
    _conversacion(comercio, "5493511110002", "Me llegó roto el pedido", reloj, 400)  # vieja y pendiente
    _conversacion(comercio, "5493511110003", "¿Hacen envíos a Córdoba?", reloj, 10)  # reciente

    resultado = retencion.depurar(retencion.limite_de_retencion(365))
    assert resultado.compradores == 1 and resultado.conversaciones == 1
    telefonos = set(db.session.scalars(select(Comprador.telefono)))
    assert telefonos == {"5493511110002", "5493511110003"}
    # La consulta pendiente conserva sus mensajes: el comercio todavía tiene que responder.
    pendiente = db.session.scalar(select(Consulta).where(Consulta.atendida.is_(False), Consulta.resultado != None))  # noqa: E711
    assert pendiente.conversacion.mensajes
    # Volver a depurar no borra nada más.
    assert retencion.depurar(retencion.limite_de_retencion(365)).total == 0


def test_depurar_conserva_el_numero_bloqueado(app, comercio, reloj):
    _conversacion(comercio, "5493511110009", "hola", reloj, 400)
    comprador = db.session.scalar(select(Comprador))
    db.session.add(Bloqueo(comercio=comercio, comprador=comprador, motivo="spam", fecha_alta=reloj.actual))
    db.session.commit()
    retencion.depurar(retencion.limite_de_retencion(365))
    assert _contar(Conversacion) == 0 and _contar(Comprador) == 1 and _contar(Bloqueo) == 1


class ConfigConDepuracion(ConfigPruebas):
    DEPURACION_AUTOMATICA = True
    RETENCION_DIAS = 30


def test_depuracion_automatica_una_vez_por_dia(reloj):
    aplicacion = create_app(ConfigConDepuracion)
    with aplicacion.app_context():
        comercio = crear_comercio()
        _conversacion(comercio, "5493511110004", "¿Aceptan Mercado Pago?", reloj, 40)
        cliente = aplicacion.test_client()
        cliente.get("/ingresar")
        assert _contar(Comprador) == 0
        # Dentro del mismo día no vuelve a correr.
        _conversacion(comercio, "5493511110005", "¿Aceptan Mercado Pago?", reloj, 40)
        cliente.get("/ingresar")
        assert _contar(Comprador) == 1
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


def test_borrar_datos_de_un_comprador_con_un_comercio_o_con_todos(app, comercio, otro_comercio, reloj):
    telefono = "5493511110006"
    _conversacion(comercio, telefono, "hola", reloj, 1)
    _conversacion(otro_comercio, telefono, "hola", reloj, 0)
    comprador = db.session.scalar(select(Comprador))
    assert retencion.borrar_datos_comprador(comprador, comercio) == 1
    assert _contar(Conversacion) == 1 and _contar(Comprador) == 1
    assert retencion.borrar_datos_comprador(db.session.scalar(select(Comprador))) == 1
    assert _contar(Conversacion) == 0 and _contar(Comprador) == 0 and _contar(Mensaje) == 0


# --- Comandos de administración (O1) ---------------------------------------------


@pytest.fixture
def consola(app):
    return app.test_cli_runner()


def test_admin_comercios(consola, comercio):
    salida = consola.invoke(args=["admin", "comercios"]).output
    assert "Casa & Detalles" in salida and "demo@casaydetalles.com.ar" in salida and "CASA26" in salida


def test_admin_restablecer_clave_generada(consola, app, comercio):
    sesion_vieja = app.test_client()
    ingresar(sesion_vieja)
    r = consola.invoke(args=["admin", "restablecer-clave", "demo@casaydetalles.com.ar", "--generar"])
    assert r.exit_code == 0
    nueva = r.output.split("Contraseña temporal: ")[1].split()[0]
    assert ingresar(app.test_client(), contrasena=nueva).status_code == 302
    assert ingresar(app.test_client(), contrasena=CONTRASENA).status_code == 401
    # La sesión abierta con la contraseña anterior se cerró.
    assert sesion_vieja.get("/panel").status_code == 302


def test_admin_restablecer_clave_pedida_y_validada(consola, comercio):
    r = consola.invoke(args=["admin", "restablecer-clave", "1"], input="corta\ncorta\n")
    assert r.exit_code != 0 and "al menos ocho caracteres" in r.output
    r = consola.invoke(args=["admin", "restablecer-clave", "1"], input="una-clave-larga\nuna-clave-larga\n")
    assert r.exit_code == 0


def test_admin_desbloquear(consola, app, comercio, reloj):
    usuario = db.session.scalar(select(Usuario))
    usuario.intentos_fallidos = 5
    usuario.bloqueado_hasta = reloj.actual + timedelta(minutes=15)
    db.session.commit()
    assert "ingreso bloqueado" in consola.invoke(args=["admin", "comercios"]).output
    assert consola.invoke(args=["admin", "desbloquear", "demo@casaydetalles.com.ar"]).exit_code == 0
    assert ingresar(app.test_client()).status_code == 302


def test_admin_pausar_y_activar(consola, comercio):
    assert consola.invoke(args=["admin", "pausar", "demo@casaydetalles.com.ar"]).exit_code == 0
    assert db.session.get(Comercio, comercio.id_comercio).estado == EstadoComercio.PAUSADO
    r = consola.invoke(args=["admin", "activar", str(comercio.id_comercio)])
    assert r.exit_code == 0 and "CASA26" in r.output
    assert db.session.get(Comercio, comercio.id_comercio).estado == EstadoComercio.ACTIVO


def test_admin_activar_exige_el_onboarding(consola, app):
    crear_comercio(email="nuevo@ejemplo.com", codigo=None, estado=EstadoComercio.EN_ONBOARDING, paso=2)
    r = consola.invoke(args=["admin", "activar", "nuevo@ejemplo.com"])
    assert r.exit_code != 0 and "onboarding" in r.output


def test_admin_comercio_inexistente(consola, app):
    r = consola.invoke(args=["admin", "pausar", "nadie@ejemplo.com"])
    assert r.exit_code != 0 and "No hay un comercio" in r.output


def test_admin_borrar_comprador(consola, comercio, reloj):
    _conversacion(comercio, "5493511110007", "hola", reloj, 0)
    r = consola.invoke(args=["admin", "borrar-comprador", "+54 9 351 111-0007", "--si"])
    assert r.exit_code == 0 and "Conversaciones borradas: 1" in r.output
    assert _contar(Comprador) == 0
    assert consola.invoke(args=["admin", "borrar-comprador", "5493511110007", "--si"]).exit_code != 0


def test_admin_depurar(consola, comercio, reloj):
    _conversacion(comercio, "5493511110008", "¿Aceptan Mercado Pago?", reloj, 100)
    r = consola.invoke(args=["admin", "depurar", "--dias", "90", "--si"])
    assert r.exit_code == 0 and "1 compradores" in r.output


def test_admin_respaldar(consola, comercio, tmp_path):
    destino = tmp_path / "copia.db"
    r = consola.invoke(args=["admin", "respaldar", str(destino)])
    assert r.exit_code == 0 and destino.exists()
    with sqlite3.connect(destino) as copia:
        assert copia.execute("SELECT nombre FROM comercio").fetchone() == ("Casa & Detalles",)


def test_admin_verificar_en_local(consola):
    r = consola.invoke(args=["admin", "verificar"])
    # La clave de las pruebas es corta: se avisa, pero no es un error.
    assert r.exit_code == 0 and "local o demostración" in r.output
    assert "[aviso] SECRET_KEY es corta" in r.output and "[error]" not in r.output


# --- Verificación de la configuración (O10) ---------------------------------------


class ConfigProduccionIncompleta(ConfigPruebas):
    WHATSAPP_TOKEN = "token"
    WHATSAPP_APP_SECRET = ""
    WHATSAPP_PHONE_NUMBER_ID = ""
    WHATSAPP_VERIFY_TOKEN = "un-texto-secreto-para-verificar-el-webhook"
    SIMULADOR_HABILITADO = True
    MAIL_MODO = "smtp"
    MAIL_SERVIDOR = ""
    CONTACTO_PLATAFORMA = ""


def test_configuracion_insegura_se_informa(reloj):
    aplicacion = create_app(ConfigProduccionIncompleta)
    with aplicacion.app_context():
        textos = [(p.nivel, p.texto) for p in problemas_de_configuracion(aplicacion)]
        errores = " ".join(t for n, t in textos if n == "error")
        avisos = " ".join(t for n, t in textos if n == "aviso")
        assert "WHATSAPP_APP_SECRET" in errores and "WHATSAPP_PHONE_NUMBER_ID" in errores
        assert "MAIL_SERVIDOR" in errores
        assert "simulador está habilitado" in avisos and "WHATSAPP_VERIFY_TOKEN" in avisos
        assert "CONTACTO_PLATAFORMA" in avisos
        r = aplicacion.test_cli_runner().invoke(args=["admin", "verificar"])
        assert r.exit_code == 1 and "despliegue real" in r.output and "[error]" in r.output
        db.session.remove()
        db.engine.dispose()


class ConfigProduccionCompleta(ConfigPruebas):
    WHATSAPP_TOKEN = "token"
    WHATSAPP_PHONE_NUMBER_ID = "123"
    WHATSAPP_VERIFY_TOKEN = "otro-texto-largo"
    SIMULADOR_HABILITADO = False
    SECRET_KEY = "x" * 40
    URL_PUBLICA = "https://respondé.example"
    COOKIES_SEGURAS = True
    SESSION_COOKIE_SECURE = True
    LIMITES_POR_IP = True
    MAIL_MODO = "smtp"
    MAIL_SERVIDOR = "smtp.gmail.com"
    MAIL_REMITENTE = "Respondé <avisos@example.com>"
    CONTACTO_PLATAFORMA = "privacidad@example.com"


def test_configuracion_completa_sin_observaciones(reloj):
    aplicacion = create_app(ConfigProduccionCompleta)
    with aplicacion.app_context():
        assert problemas_de_configuracion(aplicacion) == []
        db.session.remove()
        db.engine.dispose()


def test_se_informa_al_iniciar_fuera_de_las_pruebas(reloj, caplog):
    class Config(ConfigProduccionIncompleta):
        TESTING = False

    with caplog.at_level(logging.WARNING, logger="app.configuracion"):
        aplicacion = create_app(Config)
    assert "WHATSAPP_APP_SECRET" in caplog.text
    with aplicacion.app_context():
        db.session.remove()
        db.engine.dispose()


# --- Estado del servicio ------------------------------------------------------------


def test_salud_informa_la_base(cliente, monkeypatch):
    assert cliente.get("/salud").get_json() == {"estado": "ok", "base": "ok"}

    def caida(*args, **kwargs):
        raise RuntimeError("sin base")

    monkeypatch.setattr(db.session, "execute", caida)
    r = cliente.get("/salud")
    assert r.status_code == 503 and r.get_json()["estado"] == "error"
