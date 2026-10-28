"""Servicio de atención con base de datos: CU08 completo, multi-comercio y persistencia (RF06, RF12, RF13)."""

from datetime import timedelta

from sqlalchemy import func, select

from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.extensiones import db
from app.modelos import (
    Comprador,
    Consulta,
    Conversacion,
    DireccionMensaje,
    EstadoComercio,
    EstadoConversacion,
    Mensaje,
    ResultadoConsulta,
    TemaConsulta,
)

COMPRADOR = "5493510000001"


def enviar(texto, telefono=COMPRADOR, nombre=None, id_externo=None, fecha_hora=None):
    return procesar_mensaje_entrante(
        MensajeEntrante(
            telefono=telefono,
            texto=texto,
            nombre=nombre,
            id_externo=id_externo,
            fecha_hora=fecha_hora,
        )
    )


def contar(modelo):
    return db.session.scalar(select(func.count()).select_from(modelo))


def test_cu08_excepcion_sin_codigo_no_crea_conversacion(comercio):
    r = enviar("Hola, hacen envíos?")
    assert "con qué comercio" in r.respuestas[0]
    assert r.conversacion is None
    assert contar(Comprador) == 0 and contar(Conversacion) == 0


def test_cu08_primer_contacto_con_codigo_registra_comprador_y_conversacion(comercio):
    r = enviar(comercio.texto_primer_mensaje(), nombre="Lucía")
    assert "asistente automático de Casa & Detalles" in r.respuestas[0]
    comprador = db.session.scalar(select(Comprador))
    assert comprador.telefono == COMPRADOR and comprador.nombre == "Lucía"
    assert r.conversacion.id_comercio == comercio.id_comercio
    assert r.conversacion.estado == EstadoConversacion.ACTIVA
    assert r.consulta is None


def test_codigo_escrito_a_mano_tambien_identifica(comercio):
    r = enviar("casa26 hacen envios al 5800?")
    assert "2 a 4 días hábiles" in r.respuestas[0]
    assert r.consulta.resultado == ResultadoConsulta.RESUELTA


def test_cu08_excepcion_comercio_pausado(comercio):
    comercio.estado = EstadoComercio.PAUSADO
    db.session.commit()
    r = enviar(comercio.texto_primer_mensaje())
    assert "no está disponible en este momento" in r.respuestas[0]
    assert contar(Conversacion) == 0


def test_cu09_conversacion_en_varios_pasos_y_mensajes_guardados(comercio):
    enviar(comercio.texto_primer_mensaje())
    r1 = enviar("¿Hacen envíos a Río Cuarto?")
    assert r1.conversacion.estado == EstadoConversacion.ESPERANDO_CP
    r2 = enviar("5800")
    assert r2.conversacion.estado == EstadoConversacion.ACTIVA
    assert r2.consulta.tema == TemaConsulta.ENVIO and r2.consulta.codigo_postal == 5800
    mensajes = r2.conversacion.mensajes
    assert [m.direccion for m in mensajes].count(DireccionMensaje.ENTRANTE) == 3
    assert [m.direccion for m in mensajes].count(DireccionMensaje.SALIENTE) == 3


def test_cu12_derivacion_y_vuelta_a_la_atencion_automatica(comercio, reloj):
    enviar(comercio.texto_primer_mensaje())
    r = enviar("¿Tienen el mantel en otro color?")
    consulta = r.consulta
    assert consulta.pendiente
    assert r.conversacion.estado == EstadoConversacion.DERIVADA

    silencio = enviar("¿hola? ¿alguien?")
    assert silencio.respuestas == []
    assert db.session.scalar(select(func.count()).select_from(Consulta)) == 1

    reloj.actual += timedelta(hours=1)
    consulta.marcar_atendida(reloj.actual)
    db.session.commit()
    assert consulta.fecha_atencion == reloj.actual
    assert consulta.conversacion.estado == EstadoConversacion.ACTIVA
    assert enviar("¿y aceptan transferencia?").consulta.tema == TemaConsulta.MEDIOS_PAGO


def test_multicomercio_mismo_numero_cambia_de_comercio_con_otro_codigo(comercio, otro_comercio):
    enviar(comercio.texto_primer_mensaje())
    enviar("formas de pago?")
    r = enviar(otro_comercio.texto_primer_mensaje())
    assert "Mundo Textil" in r.respuestas[0]
    enviar("atienden los sábados?")

    conversaciones = db.session.scalars(select(Conversacion).order_by(Conversacion.id_conversacion)).all()
    assert [c.estado for c in conversaciones] == [EstadoConversacion.CERRADA, EstadoConversacion.ACTIVA]
    assert conversaciones[0].consultas[0].tema == TemaConsulta.MEDIOS_PAGO
    assert conversaciones[1].id_comercio == otro_comercio.id_comercio
    assert conversaciones[1].consultas[0].tema == TemaConsulta.HORARIOS


def test_inactividad_cierra_la_conversacion_y_el_comprador_retoma_sin_codigo(comercio, reloj):
    enviar(comercio.texto_primer_mensaje())
    enviar("hacen envíos?")  # queda esperando el código postal
    reloj.actual += timedelta(hours=30)
    r = enviar("hola, ¿qué horario tienen?")
    assert r.conversacion.id_comercio == comercio.id_comercio
    assert r.consulta.tema == TemaConsulta.HORARIOS
    estados = db.session.scalars(select(Conversacion.estado).order_by(Conversacion.id_conversacion)).all()
    assert estados == [EstadoConversacion.CERRADA, EstadoConversacion.ACTIVA]


def test_mensaje_repetido_por_whatsapp_se_descarta(comercio):
    enviar(comercio.texto_primer_mensaje(), id_externo="wamid.1")
    repetido = enviar(comercio.texto_primer_mensaje(), id_externo="wamid.1")
    assert repetido.duplicado
    assert (
        db.session.scalar(
            select(func.count()).select_from(Mensaje).where(Mensaje.direccion == DireccionMensaje.ENTRANTE)
        )
        == 1
    )


def test_medio_desactivado_no_se_informa(comercio):
    enviar(comercio.texto_primer_mensaje())
    texto = enviar("formas de pago?").respuestas[0]
    assert "Transferencia bancaria" in texto
    assert "Efectivo" not in texto


def test_cambios_del_panel_se_usan_desde_la_siguiente_consulta(comercio):
    enviar(comercio.texto_primer_mensaje())
    assert "1 a 2 días hábiles" in enviar("envíos al 5000?").respuestas[0]
    comercio.zonas[0].plazo_max_dias = 3
    db.session.commit()
    assert "1 a 3 días hábiles" in enviar("envíos al 5000?").respuestas[0]
