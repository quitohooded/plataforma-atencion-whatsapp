"""CU08 Identificar intención: normalización, extracción de datos y palabras clave (RF01)."""

import pytest

from app.bot.ciudades import LocalidadAmbigua, buscar_localidades
from app.bot.intencion import (
    CATALOGO,
    CONTACTO,
    ENVIO,
    HORARIOS,
    IDENTIDAD,
    MEDIOS_PAGO,
    NO_SE,
    PAGOS_INFORMADOS,
    PEDIDOS,
    PERSONA,
    PRODUCTOS,
    RECLAMOS,
    detectar_tema,
    interpretar,
    lexico_para,
)
from app.bot.normalizacion import (
    candidatos_codigo,
    distancia_edicion,
    es_solo_codigo_postal,
    expandir_abreviaturas,
    extraer_codigo_postal,
    extraer_codigos_postales,
    limpiar_texto_enlace,
    normalizar,
)
from app.datos.palabras_clave import items_catalogo
from app.modelos import PalabraClave, TemaConsulta

CATALOGO_BASE = items_catalogo()


def temas(texto, **kw):
    return interpretar(texto, CATALOGO_BASE, **kw).temas


# --- Normalización (CU08, paso 4) ------------------------------------------------------


def test_normaliza_minusculas_tildes_y_signos():
    assert normalizar("¿Hacen ENVÍOS a Río Cuarto?") == "hacen envios a rio cuarto"
    assert normalizar("  Pagás   con   tarjeta!!! ") == "pagas con tarjeta"


def test_conserva_la_enie():
    assert normalizar("Mañana, ¿abren?") == "mañana abren"


@pytest.mark.parametrize(
    "texto,esperado",
    [("holaaa", "hola"), ("graciasss", "gracias"), ("siiii", "si"), ("holaa", "hola"), ("llllega", "llega")],
)
def test_reduce_letras_repetidas(texto, esperado):
    assert normalizar(texto) == esperado


def test_no_reduce_palabras_con_letras_dobles_legitimas():
    assert normalizar("lee") == "lee"
    assert normalizar("carro llega") == "carro llega"


def test_expande_abreviaturas():
    assert expandir_abreviaturas(["q", "onda", "aceptan", "mp"]) == ["que", "onda", "aceptan", "mercado", "pago"]
    assert expandir_abreviaturas(["hasta", "q", "hs"]) == ["hasta", "que", "horas"]
    assert expandir_abreviaturas(["c", "p", "5000"]) == ["cp", "5000"]


def test_distancia_de_edicion_con_transposicion():
    assert distancia_edicion("orario", "horario", 2) == 1
    assert distancia_edicion("trasnferencia", "transferencia", 2) == 1  # letras vecinas invertidas
    assert distancia_edicion("tarde", "tarda", 1) == 1
    assert distancia_edicion("hola", "chau", 1) == 2  # supera el límite: devuelve límite + 1


@pytest.mark.parametrize(
    "palabra,corregida",
    [
        ("orario", "horario"),
        ("trasferencia", "transferencia"),
        ("targeta", "tarjeta"),
        ("enbian", "envian"),
        ("efectibo", "efectivo"),
        ("mendosa", "mendoza"),
    ],
)
def test_corrige_errores_de_tipeo_hacia_el_vocabulario(palabra, corregida):
    assert lexico_para(CATALOGO_BASE).corregir(palabra) == corregida


@pytest.mark.parametrize("palabra", ["tarde", "tardes", "plazas", "cesto", "trabajos", "lleva", "sabanas"])
def test_no_corrige_palabras_comunes(palabra):
    assert lexico_para(CATALOGO_BASE).corregir(palabra) == palabra


# --- Código postal (CU09) ----------------------------------------------------------------


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("5800", [5800]),
        ("mi CP es 5800", [5800]),
        ("C.P. 1425", [1425]),
        ("cp5000", [5000]),
        ("X5800ABC", [5800]),
        ("vivo en el x5000abc", [5000]),
        ("envían al 5000 o al 5001?", [5000, 5001]),
        ("Río Cuarto", []),
        ("123", []),
        ("0999", []),
        ("58000", []),
        ("lo pago con $1500", []),
        ("$ 1500", []),
        ("son 2500 pesos?", []),
        ("1.500", []),
        ("1500 metros", []),
        ("pedido 1234", []),
        ("mi pedido #5531", []),
        ("en enero 2026", []),
        ("mi tarjeta es 4509 9535 6623 3704", []),
        ("llamame al 351 012-3456", []),
        ("15 3456-7890", []),
    ],
)
def test_extrae_codigos_postales(texto, esperado):
    assert extraer_codigos_postales(texto) == esperado


def test_primer_codigo_postal_y_mensaje_solo_con_cp():
    assert extraer_codigo_postal("al 5800 o al 5900") == 5800
    assert extraer_codigo_postal("sin código") is None
    assert es_solo_codigo_postal("5800")
    assert es_solo_codigo_postal("el CP 5800")
    assert not es_solo_codigo_postal("envían al 5800?")


# --- Código de acceso y texto del enlace (CU08) ---------------------------------------------


def test_candidatos_de_codigo_de_acceso():
    assert candidatos_codigo("Hola, quiero hacer una consulta a Casa & Detalles. Código: CASA26") == ["CASA26"]
    assert candidatos_codigo("#text42") == ["TEXT42"]
    # Palabras sin dígitos no se confunden con códigos.
    assert candidatos_codigo("ENVIOS PAGOS 123456") == []


def test_limpia_el_texto_del_enlace_y_conserva_lo_agregado():
    texto = "Hola, quiero hacer una consulta a Casa & Detalles. Código: CASA26 ¿hacen envíos a Rosario?"
    assert limpiar_texto_enlace(texto, "CASA26", "Casa & Detalles") == "¿hacen envíos a Rosario?"
    assert limpiar_texto_enlace("Hola, quiero hacer una consulta a Casa & Detalles. Código: CASA26", "CASA26") == ""


def test_limpia_el_enlace_aunque_el_comercio_haya_cambiado_de_nombre():
    viejo = "Hola, quiero hacer una consulta a Casa y Detalles. Código: CASA26"
    assert limpiar_texto_enlace(viejo, "CASA26", "Casa & Detalles Hogar") == ""


def test_limpia_un_codigo_escrito_a_mano():
    assert limpiar_texto_enlace("casa26 hacen envios al 5800?", "CASA26") == "hacen envios al 5800?"


# --- Temas (CU08, pasos 4 y 5) ---------------------------------------------------------------


@pytest.mark.parametrize(
    "texto,tema",
    [
        ("¿Hacen envíos a Río Cuarto?", ENVIO),
        ("cuánto tarda en llegar al 5800", ENVIO),
        ("¿Aceptan Mercado Pago?", MEDIOS_PAGO),
        ("y cómo se paga?", MEDIOS_PAGO),
        ("¿A qué hora abren?", HORARIOS),
        ("atienden los sábados?", HORARIOS),
        ("cual es su numero de whatsapp?", CONTACTO),
        ("tenés catálogo?", CATALOGO),
        ("¿Tienen el mantel en otro color?", PRODUCTOS),
        ("cuando llega mi pedido?", PEDIDOS),
        ("me llegó roto el plato", RECLAMOS),
        ("ya transferí, te mando el comprobante", PAGOS_INFORMADOS),
    ],
)
def test_detecta_el_tema_por_palabras_clave(texto, tema):
    assert temas(texto)[0] == tema


def test_varias_preguntas_en_un_mensaje():
    assert temas("¿hacen envíos a Rosario? ¿y cómo se paga?") == [ENVIO, MEDIOS_PAGO]
    assert temas("que horario tienen y aceptan mercado pago?") == [HORARIOS, MEDIOS_PAGO]


def test_frases_largas_evitan_falsos_positivos():
    # «tarjeta de dedicatoria» no es un medio de pago; «de qué modo» no es la billetera MODO.
    assert MEDIOS_PAGO not in temas("¿Puedo regalarlo con una tarjeta de dedicatoria?")
    assert temas("de qué modo me lo mandan?") == [ENVIO]
    # «número de seguimiento» (pedido) gana sobre «el número» (contacto).
    assert temas("me pasan el número de seguimiento?") == [PEDIDOS]


def test_un_tema_absorbe_a_otro_cuando_habla_de_lo_mismo():
    # El pago informado menciona el medio pero no pregunta por medios de pago.
    assert temas("acabo de pagar por mercado pago") == [PAGOS_INFORMADOS]
    # Un reclamo por un pedido es un reclamo.
    assert temas("todavía no me llegó el pedido") == [RECLAMOS]
    # «¿cuándo lo mandan?» después de un pago habla del pedido, no de envíos en general.
    assert temas("ya pagué, cuándo lo mandan?") == [PAGOS_INFORMADOS]
    # El precio junto al envío es el costo del envío.
    assert temas("cuánto sale el envío a Mendoza?") == [ENVIO]
    assert interpretar("¿Mandan a Ushuaia? ¿Cuánto sale?", CATALOGO_BASE).pide_costo


def test_mandar_informacion_no_es_un_envio():
    assert temas("me mandás fotos del mantel?") == [PRODUCTOS]
    assert temas("mandame el catálogo") == [CATALOGO]


def test_la_hora_de_un_envio_es_una_consulta_de_envio():
    assert temas("¿A qué hora llega el envío?") == [ENVIO]


def test_no_coincide_dentro_de_otra_palabra():
    assert temas("Me gustan las pagodas") == []


def test_intenciones_de_control():
    assert interpretar("quiero hablar con una persona", CATALOGO_BASE).control == [PERSONA]
    assert interpretar("sos un bot?", CATALOGO_BASE).control == [IDENTIDAD]
    assert NO_SE in interpretar("no sé", CATALOGO_BASE).control


def test_una_intencion_debil_no_tapa_una_consulta():
    # «si» condicional no es una respuesta afirmativa.
    assert interpretar("si no me gusta lo puedo devolver?", CATALOGO_BASE).control == []


def test_detectar_tema_compatible_con_la_version_anterior():
    assert detectar_tema("¿Aceptan Mercado Pago?", CATALOGO_BASE).tema == TemaConsulta.MEDIOS_PAGO
    assert detectar_tema("Me gustan las pagodas", CATALOGO_BASE).tema == TemaConsulta.NO_RECONOCIDO


def test_palabra_clave_coincide():
    palabra = PalabraClave(termino="mercado pago", tema=TemaConsulta.MEDIOS_PAGO)
    assert palabra.coincide("¿Aceptan MERCADO PAGO?")
    assert not palabra.coincide("mercado")


def test_el_catalogo_de_la_base_extiende_el_vocabulario():
    assert temas("tienen zapatillas?") == []
    propio = CATALOGO_BASE + [("zapatillas", TemaConsulta.PRODUCTOS, 1.0)]
    assert interpretar("tienen zapatillas?", propio).temas == [PRODUCTOS]


# --- Localidades -------------------------------------------------------------------------------


def test_localidades_con_el_codigo_postal_de_referencia():
    (encontrada,) = buscar_localidades(normalizar("villa carlos paz").split())
    assert encontrada.localidad.cp == 5152 and encontrada.localidad.nombre == "Villa Carlos Paz"
    (larga,) = buscar_localidades(normalizar("san martín de los andes").split())
    assert larga.localidad.cp == 8370


def test_localidades_ambiguas_y_provincias():
    (ambigua,) = buscar_localidades(["san", "martin"])
    assert isinstance(ambigua.localidad, LocalidadAmbigua)
    (provincia,) = buscar_localidades(["chubut"])
    assert provincia.localidad.es_provincia and provincia.localidad.cp == 9103


def test_nombres_comunes_solo_en_contexto_de_envio():
    assert buscar_localidades(["el", "modelo", "azul"], solo_inequivocas=True) == []
    assert buscar_localidades(["y", "a", "rosario"], solo_inequivocas=True)[0].localidad.cp == 2000
    assert temas("queda el modelo azul?") == [PRODUCTOS]
    assert temas("hacen envíos a Azul?") == [ENVIO]
    assert interpretar("hacen envíos a Azul?", CATALOGO_BASE).localidades[0].localidad.cp == 7300


def test_una_ciudad_sola_es_una_consulta_de_envio():
    assert temas("¿y a Mendoza?") == [ENVIO]
    # Dentro de otra frase no alcanza para suponer que pregunta por un envío.
    assert temas("hola, soy de Rosario") == []
