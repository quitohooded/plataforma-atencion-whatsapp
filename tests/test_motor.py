"""Motor de estados y respuestas: CU08 a CU12 sin base de datos (RF02 a RF07)."""

from dataclasses import replace
from datetime import datetime, time

import pytest

from app.bot import respuestas
from app.bot.contexto import ContextoConversacion, DatosComercio, FranjaDatos, MedioDatos, ZonaDatos
from app.bot.motor import MotorConversacional
from app.datos.palabras_clave import items_catalogo
from app.modelos import EstadoConversacion as E
from app.modelos import ResultadoConsulta as R
from app.modelos import TemaConsulta as T

CATALOGO = items_catalogo()
MARTES_NOCHE = datetime(2026, 10, 27, 22, 30)
MARTES_MANANA = datetime(2026, 10, 27, 11, 0)

DATOS = DatosComercio(
    nombre="Casa & Detalles",
    telefono_contacto="351 012-3456",
    zonas=(
        ZonaDatos(5000, 5099, "Córdoba Capital", 1, 2, 4500),
        ZonaDatos(5100, 5999, "Interior de Córdoba", 2, 4, 6900),
        ZonaDatos(1000, 1999, "Buenos Aires", 3, 5, None),
    ),
    medios=(
        MedioDatos("Transferencia bancaria", "alias casa.detalles.demo"),
        MedioDatos("Billetera virtual", "Mercado Pago"),
        MedioDatos("Tarjeta de crédito", "hasta 3 cuotas sin interés"),
    ),
    franjas=tuple(FranjaDatos(d, time(9), time(18)) for d in range(5)) + (FranjaDatos(5, time(9), time(13)),),
    envio_gratis_desde=120000,
    enlace_catalogo="https://casaydetalles.example/catalogo",
)


@pytest.fixture
def motor():
    return MotorConversacional(max_intentos_cp=2)


def procesar(motor, texto, ctx=None, datos=DATOS, ahora=MARTES_NOCHE, primer=False, tipo="text"):
    return motor.procesar(datos, ctx or ContextoConversacion(), texto, CATALOGO, ahora, primer, tipo)


def texto(resultado) -> str:
    return "\n".join(resultado.textos)


# --- CU09: plazo y costo de envío ----------------------------------------------------------


def test_cu09_flujo_principal_solicita_cp_y_responde_plazo_y_costo(motor):
    r1 = procesar(motor, "¿Hacen envíos?")
    assert r1.estado == E.ESPERANDO_CP and r1.consultas == []
    assert "código postal" in texto(r1) and r1.acciones == ["ENVIO?"]

    r2 = procesar(motor, "5800", r1.contexto)
    assert r2.estado == E.ACTIVA
    assert "2 a 4 días hábiles" in texto(r2) and "$6.900" in texto(r2)
    assert "gratis en compras desde *$120.000*" in texto(r2)
    assert (r2.consulta.tema, r2.consulta.resultado, r2.consulta.codigo_postal) == (T.ENVIO, R.RESUELTA, 5800)
    assert r2.contexto.ultimo_cp == 5800


def test_cu09_alternativo_cp_en_el_primer_mensaje(motor):
    r = procesar(motor, "cuánto tarda el envío al 5000?")
    assert r.estado == E.ACTIVA and r.acciones == ["ENVIO"]
    assert "1 a 2 días hábiles" in texto(r)
    assert r.consulta.resultado == R.RESUELTA


def test_cu09_ciudad_en_lugar_del_codigo_postal(motor):
    r = procesar(motor, "¿Hacen envíos a Río Cuarto?")
    assert "*Río Cuarto* (CP 5800, Interior de Córdoba)" in texto(r)
    assert r.consulta.codigo_postal == 5800

    esperando = procesar(motor, "hacen envíos?").contexto
    assert procesar(motor, "Villa Carlos Paz", esperando).consulta.codigo_postal == 5152


def test_cu09_localidad_repetida_pide_el_cp_sin_contar_un_intento(motor):
    r = procesar(motor, "hacen envíos a San Martín?")
    assert r.estado == E.ESPERANDO_CP and r.intentos_cp == 0
    assert "más de una zona posible" in texto(r)
    assert procesar(motor, "1650", r.contexto).consulta.codigo_postal == 1650


def test_cu09_provincia_toma_la_capital_como_referencia(motor):
    datos = replace(DATOS, zonas=DATOS.zonas + (ZonaDatos(9000, 9499, "Patagonia", 6, 10, 13900),))
    r = procesar(motor, "envían a Chubut?", datos=datos)
    assert "tomando como referencia Rawson" in texto(r) and "Si tu localidad es otra" in texto(r)


def test_cu09_varios_destinos_en_un_mensaje(motor):
    r = procesar(motor, "hacen envíos a Córdoba y a Río Cuarto?")
    assert "Plazos estimados de entrega" in texto(r)
    assert "Córdoba (CP 5000" in texto(r) and "Río Cuarto (CP 5800" in texto(r)
    assert len(r.consultas) == 1


def test_cu09_excepcion_dato_invalido_dos_veces_deriva(motor):
    esperando = procesar(motor, "hacen envíos?").contexto
    r1 = procesar(motor, "no sé", esperando)
    assert (r1.estado, r1.intentos_cp) == (E.ESPERANDO_CP, 1)
    assert "ciudad o localidad" in texto(r1) and r1.consultas == []

    r2 = procesar(motor, "ni idea", r1.contexto)
    assert r2.estado == E.DERIVADA and r2.acciones == ["D:ENVIO"]
    assert "No pude reconocer el código postal" in texto(r2)
    assert (r2.consulta.tema, r2.consulta.resultado) == (T.ENVIO, R.DERIVADA)


def test_cu09_excepcion_zona_no_configurada_deriva(motor):
    r = procesar(motor, "hacen envíos al 9410?")
    assert r.estado == E.DERIVADA
    assert "9410" in texto(r) and "no tengo cargado un plazo" in texto(r)
    assert (r.consulta.resultado, r.consulta.codigo_postal) == (R.DERIVADA, 9410)


def test_cu09_costo_preguntado_y_no_cargado_responde_el_plazo_y_deriva(motor):
    r = procesar(motor, "cuánto sale el envío al 1425?")
    assert "3 a 5 días hábiles" in texto(r) and "no lo tengo cargado" in texto(r)
    assert r.acciones == ["ENVIO", "D:ENVIO"]
    assert (r.consulta.tema, r.consulta.resultado, r.consulta.codigo_postal) == (T.ENVIO, R.DERIVADA, 1425)


def test_cu09_el_costo_se_pregunta_despues_del_plazo(motor):
    r1 = procesar(motor, "hacen envíos al 5800?")
    r2 = procesar(motor, "¿y cuánto sale?", r1.contexto)
    assert r2.acciones == ["ENVIO"]
    assert texto(r2).startswith("💲 El envío al código postal *5800*") and "$6.900" in texto(r2)


def test_cu09_envio_gratis_a_una_zona(motor):
    datos = replace(DATOS, zonas=(ZonaDatos(5000, 5099, "Córdoba Capital", 0, 1, 0),))
    r = procesar(motor, "envían al 5000?", datos=datos)
    assert "el envío es *gratis*" in texto(r) and "en el día o hasta 1 día hábil" in texto(r)
    assert "Envío gratis en compras desde" not in texto(r)


def test_cu09_zona_unica_nacional_no_pide_cp(motor):
    datos = replace(DATOS, zonas=(ZonaDatos(1000, 9999, "Todo el país", 3, 7, 9900),))
    r = procesar(motor, "hacen envíos?", datos=datos)
    assert r.estado == E.ACTIVA and "Enviamos a todo el país" in texto(r)


def test_cu09_sin_zonas_cargadas_deriva(motor):
    datos = replace(DATOS, zonas=())
    r = procesar(motor, "hacen envíos?", datos=datos)
    assert r.estado == E.DERIVADA and "todavía no está cargada" in texto(r)


def test_cu09_otra_consulta_mientras_espera_el_cp(motor):
    esperando = procesar(motor, "hacen envíos?").contexto
    r = procesar(motor, "y cómo se paga?", esperando)
    assert r.estado == E.ACTIVA and r.acciones == ["PAGO"]


def test_cu09_cancelar_la_espera(motor):
    esperando = procesar(motor, "hacen envíos?").contexto
    r = procesar(motor, "dejalo", esperando)
    assert r.estado == E.ACTIVA and r.acciones == ["CANCELAR"] and r.consultas == []


# --- CU10: medios de pago -----------------------------------------------------------------------


def test_cu10_responde_medios_de_pago_con_detalle(motor):
    r = procesar(motor, "formas de pago?")
    assert r.estado == E.ACTIVA
    assert "• Transferencia bancaria: alias casa.detalles.demo" in texto(r)
    assert "• Billetera virtual: Mercado Pago" in texto(r)
    assert (r.consulta.tema, r.consulta.resultado) == (T.MEDIOS_PAGO, R.RESUELTA)


def test_cu10_si_o_no_para_un_medio_en_particular(motor):
    assert texto(procesar(motor, "¿Aceptan Mercado Pago?")).startswith("✅ Sí, aceptamos *Mercado Pago*")
    assert "*Efectivo* no está entre los medios de pago" in texto(procesar(motor, "puedo pagar en efectivo?"))
    cuotas = texto(procesar(motor, "tienen cuotas sin interés?"))
    assert cuotas.startswith("✅ Sí, hay cuotas con *tarjeta de crédito*")


def test_cu10_marca_de_tarjeta_sin_dato_no_se_niega(motor):
    # El comercio no nombró las marcas: el bot no puede afirmar que Naranja no se acepta.
    assert "no tengo cargado si incluye *Naranja*" in texto(procesar(motor, "aceptan naranja?"))
    con_marcas = replace(DATOS, medios=(MedioDatos("Tarjeta de crédito", "Visa y Mastercard"),))
    assert "*Naranja* no está" in texto(procesar(motor, "aceptan naranja?", datos=con_marcas))


def test_cu10_excepcion_sin_medios_deriva(motor):
    r = procesar(motor, "formas de pago?", datos=replace(DATOS, medios=()))
    assert r.estado == E.DERIVADA and r.consulta.tema == T.MEDIOS_PAGO


# --- CU11: horarios -------------------------------------------------------------------------------


def test_cu11_horarios_agrupados_y_abierto_ahora(motor):
    r = procesar(motor, "qué horario tienen?", ahora=MARTES_MANANA)
    assert "Lunes a viernes: 9:00 a 18:00" in texto(r)
    assert "Sábado: 9:00 a 13:00" in texto(r)
    assert "Domingo: cerrado" in texto(r)
    assert "Ahora estamos atendiendo, hasta las 18:00" in texto(r)
    assert r.consulta.resultado == R.RESUELTA


def test_cu11_alternativo_cerrado_indica_reapertura(motor):
    assert "Volvemos a abrir mañana a las 9:00" in texto(procesar(motor, "a qué hora abren?"))
    sabado_tarde = datetime(2026, 10, 31, 15, 0)
    assert "el lunes a las 9:00" in texto(procesar(motor, "abren?", ahora=sabado_tarde))
    madrugada = datetime(2026, 10, 28, 7, 0)
    assert "hoy a las 9:00" in texto(procesar(motor, "abren?", ahora=madrugada))


def test_cu11_dia_puntual(motor):
    assert texto(procesar(motor, "abren los sábados?")).startswith("Los sábados atendemos de 9:00 a 13:00.")
    assert texto(procesar(motor, "atienden los domingos?")).startswith("Los domingos estamos cerrados.")
    assert texto(procesar(motor, "abren mañana?")).startswith("Mañana (miércoles) atendemos de 9:00 a 18:00.")
    assert "Los feriados el horario puede cambiar" in texto(procesar(motor, "trabajan los feriados?"))


def test_cu11_excepcion_sin_horarios_deriva(motor):
    assert procesar(motor, "horarios?", datos=replace(DATOS, franjas=())).estado == E.DERIVADA


def test_horario_jornada_partida():
    datos = DatosComercio(nombre="X", franjas=(FranjaDatos(0, time(9), time(13)), FranjaDatos(0, time(16), time(20))))
    assert respuestas.lineas_horario(datos)[0] == "Lunes: 9:00 a 13:00 y 16:00 a 20:00"
    assert respuestas.lineas_horario(datos)[1] == "Martes a domingo: cerrado"


# --- Contacto y catálogo -------------------------------------------------------------------------


def test_contacto_y_catalogo(motor):
    r = procesar(motor, "cual es su numero de whatsapp?")
    assert "*351 012-3456*" in texto(r) and r.consulta.tema == T.CONTACTO
    c = procesar(motor, "tenés catálogo?")
    assert "https://casaydetalles.example/catalogo" in texto(c)
    assert (c.consulta.tema, c.consulta.resultado) == (T.PRODUCTOS, R.RESUELTA)


def test_catalogo_sin_enlace_deriva(motor):
    r = procesar(motor, "tenés catálogo?", datos=replace(DATOS, enlace_catalogo=None))
    assert r.acciones == ["D:PRODUCTOS"]


# --- CU12: derivación ---------------------------------------------------------------------------


def test_cu12_producto_deriva_con_el_catalogo_y_cuando_responden(motor):
    r = procesar(motor, "¿Tienen el mantel en otro color?")
    assert r.estado == E.DERIVADA and r.acciones == ["D:PRODUCTOS"]
    assert "stock, precios, medidas o colores" in texto(r)
    assert "podés ver el catálogo" in texto(r)
    assert "desde el WhatsApp *351 012-3456*" in texto(r)
    assert "fuera del horario de atención: te responden *mañana desde las 9:00*" in texto(r)
    assert (r.consulta.tema, r.consulta.resultado) == (T.PRODUCTOS, R.DERIVADA)


def test_cu12_en_horario_avisa_que_responden_a_la_brevedad(motor):
    r = procesar(motor, "quiero hablar con una persona", ahora=MARTES_MANANA)
    assert "Estamos en horario de atención" in texto(r)


@pytest.mark.parametrize(
    "mensaje,tema,frase",
    [
        ("me llegó roto el plato", T.RECLAMOS, "Lamentamos el inconveniente"),
        ("ya transferí", T.PAGOS_INFORMADOS, "tiene que verificar el pago"),
        ("cuándo llega mi pedido?", T.PEDIDOS, "*número de pedido*"),
        ("quiero hablar con una persona", T.NO_RECONOCIDO, "te atienda una persona"),
        ("¿Hacen trabajos personalizados con nombre?", T.NO_RECONOCIDO, "la tiene que responder una persona"),
    ],
)
def test_cu12_cada_tema_tiene_su_mensaje(motor, mensaje, tema, frase):
    r = procesar(motor, mensaje)
    assert r.estado == E.DERIVADA and r.consulta.tema == tema
    assert frase in texto(r)


def test_cu12_pedir_una_persona_sobre_un_tema_respeta_el_pedido(motor):
    r = procesar(motor, "quiero hablar con alguien sobre los medios de pago")
    assert r.acciones == ["D:PAGO"] and r.consulta.tema == T.MEDIOS_PAGO
    assert "Medios de pago de" not in texto(r)


def test_cu12_derivada_sigue_respondiendo_lo_que_resuelve(motor):
    derivada = procesar(motor, "tienen el mantel en gris?").contexto
    assert derivada.estado == E.DERIVADA and derivada.temas_pendientes == {T.PRODUCTOS}
    r = procesar(motor, "y envían a Río Cuarto?", derivada)
    assert r.acciones == ["ENVIO"] and r.estado == E.DERIVADA
    assert (r.consulta.tema, r.consulta.resultado) == (T.ENVIO, R.RESUELTA)


def test_cu12_derivada_recordatorio_una_vez_y_despues_silencio(motor):
    derivada = procesar(motor, "quiero hablar con una persona").contexto
    r1 = procesar(motor, "hola?", derivada)
    assert r1.acciones == ["RECORDATORIO"] and "ya está con el equipo" in texto(r1)
    r2 = procesar(motor, "hola??", r1.contexto)
    assert r2.respuestas == [] and r2.acciones == ["SILENCIO"] and r2.estado == E.DERIVADA


def test_cu12_derivada_agradece_los_datos_pedidos(motor):
    derivada = procesar(motor, "cuándo llega mi pedido?").contexto
    r = procesar(motor, "compré el martes a nombre de Lucía", derivada)
    assert texto(r).startswith("¡Gracias! Lo sumé a tu consulta")


def test_cu12_derivada_registra_un_tema_nuevo_y_no_repite_el_mismo(motor):
    derivada = procesar(motor, "tienen stock del mantel?").contexto
    r = procesar(motor, "ya te transferí", derivada)
    assert r.acciones == ["D:PAGOS"] and r.consulta.tema == T.PAGOS_INFORMADOS
    mismo = procesar(motor, "y el plato?", derivada)
    assert mismo.consultas == [] and mismo.acciones == ["RECORDATORIO"]


def test_cu12_cortesia_con_la_consulta_derivada(motor):
    derivada = procesar(motor, "quiero hablar con una persona").contexto
    r = procesar(motor, "gracias!", derivada)
    assert r.acciones == ["CORTESIA"] and r.estado == E.DERIVADA


# --- Varias consultas en un mensaje --------------------------------------------------------------


def test_responde_cada_consulta_y_registra_una_por_tema(motor):
    r = procesar(motor, "hacen envíos a Río Cuarto? y aceptan mercado pago?")
    assert r.acciones == ["ENVIO", "PAGO"] and len(r.respuestas) == 2
    assert [c.tema for c in r.consultas] == [T.ENVIO, T.MEDIOS_PAGO]
    assert r.respuestas[-1].texto.endswith(respuestas.CIERRE)


def test_responde_lo_que_sabe_y_deriva_el_resto(motor):
    r = procesar(motor, "envían al 5000? también quería saber si tienen stock del mantel")
    assert r.acciones == ["ENVIO", "D:PRODUCTOS"] and r.estado == E.DERIVADA
    assert [(c.tema, c.resultado) for c in r.consultas] == [(T.ENVIO, R.RESUELTA), (T.PRODUCTOS, R.DERIVADA)]


# --- Bienvenida, menú, botones, aclaración --------------------------------------------------------


def test_primer_contacto_responde_bienvenida_con_botones_sin_registrar_consulta(motor):
    r = procesar(motor, "", primer=True)
    assert "asistente automático de *Casa & Detalles*" in texto(r)
    assert [b.id for b in r.respuestas[0].botones] == ["op_envio", "op_pago", "op_horario"]
    assert r.consultas == [] and r.estado == E.ACTIVA
    # Sin botones (canal de solo texto) se explica cómo elegir la opción.
    assert "Escribí *1* para envíos" in r.respuestas[0].texto_plano()


def test_primer_contacto_con_una_consulta_se_presenta_y_responde(motor):
    r = procesar(motor, "¿aceptan mercado pago?", primer=True)
    assert texto(r).startswith("¡Hola! 👋 Soy el asistente automático de *Casa & Detalles*.")
    assert r.acciones == ["PAGO"]


def test_botones_y_opciones_numericas(motor):
    assert procesar(motor, "op_pago").acciones == ["PAGO"]
    assert procesar(motor, "op_envio").estado == E.ESPERANDO_CP
    assert procesar(motor, "op_persona").acciones == ["D:OTRA"]
    assert procesar(motor, "2").consulta.tema == T.MEDIOS_PAGO
    assert procesar(motor, "opción 3").consulta.tema == T.HORARIOS
    assert procesar(motor, "4").acciones == ["D:OTRA"]


def test_aclaracion_dos_veces_y_despues_silencio(motor):
    r1 = procesar(motor, "jajaja")
    assert r1.acciones == ["ACLARA"] and r1.consultas == []
    assert [b.id for b in r1.respuestas[0].botones] == ["op_menu", "op_persona"]
    r2 = procesar(motor, "asdf", r1.contexto)
    assert r2.acciones == ["ACLARA2"]
    r3 = procesar(motor, "jsjs", r2.contexto)
    assert r3.respuestas == [] and r3.acciones == ["SILENCIO"]
    # Un mensaje que se entiende vuelve a la normalidad.
    r4 = procesar(motor, "formas de pago?", r3.contexto)
    assert r4.acciones == ["PAGO"] and r4.contexto.intentos_sin_entender == 0


def test_si_despues_de_ofrecer_una_persona_deriva(motor):
    ctx = ContextoConversacion(intentos_sin_entender=2)
    assert procesar(motor, "si", ctx).acciones == ["D:OTRA"]


def test_identidad_contame_y_cortesia(motor):
    assert procesar(motor, "sos un bot?").acciones == ["IDENTIDAD"]
    assert "asistente automático" in texto(procesar(motor, "estoy hablando con una persona?"))
    assert procesar(motor, "una consulta").acciones == ["CONTAME"]
    assert texto(procesar(motor, "gracias!")).startswith("¡De nada!")
    assert texto(procesar(motor, "chau")).startswith("¡Gracias por escribirnos!")
    assert procesar(motor, "👍").acciones == ["CORTESIA"]


# --- Mensajes que no son texto ---------------------------------------------------------------------


def test_imagen_deriva_y_explica_que_no_puede_verla(motor):
    r = procesar(motor, "", tipo="image")
    assert r.estado == E.DERIVADA and r.consulta.tema == T.NO_RECONOCIDO
    assert "no puedo ver imágenes" in texto(r) and "351 012-3456" in texto(r)


def test_imagen_con_texto_se_entiende_por_el_texto(motor):
    r = procesar(motor, "este es el comprobante de la transferencia", tipo="image")
    assert r.consulta.tema == T.PAGOS_INFORMADOS
    assert "No puedo ver imágenes ni archivos" in texto(r)


def test_audio_ubicacion_sticker_y_reaccion(motor):
    assert "No puedo escuchar audios" in texto(procesar(motor, "", tipo="audio"))
    ubicacion = procesar(motor, "", tipo="location")
    assert ubicacion.estado == E.ESPERANDO_CP and "código postal" in texto(ubicacion)
    assert procesar(motor, "", tipo="sticker").acciones == ["CORTESIA"]
    assert procesar(motor, "👍", tipo="reaction").respuestas == []


# --- Robustez ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mensaje",
    ["", " ", "😀" * 500, "a" * 5000, "1234 5678 9012 3456 7890", "¿¿¿???", "<script>alert(1)</script>", "\x00\x01"],
)
def test_mensajes_extremos_no_rompen_el_motor(motor, mensaje):
    r = procesar(motor, mensaje)
    assert r.acciones and r.estado in (E.ACTIVA, E.DERIVADA, E.ESPERANDO_CP)


def test_un_texto_largo_se_analiza_con_costo_acotado(motor):
    import random
    import string
    import time

    aleatorio = random.Random(7)
    texto = " ".join(
        "".join(aleatorio.choice(string.ascii_lowercase) for _ in range(aleatorio.randint(5, 11))) for _ in range(700)
    )
    inicio = time.perf_counter()
    procesar(motor, texto)
    assert time.perf_counter() - inicio < 1.0
