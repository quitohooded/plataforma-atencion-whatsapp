"""CU08 Identificar intención: normalización, extracción de datos y palabras clave (RF01)."""

import pytest

from app.bot.intencion import detectar_tema, es_cortesia, es_saludo, opcion_menu
from app.bot.normalizacion import candidatos_codigo, extraer_codigo_postal, normalizar
from app.datos.palabras_clave import items_catalogo
from app.modelos import PalabraClave, TemaConsulta

CATALOGO = items_catalogo()


def test_normaliza_minusculas_tildes_y_signos():
    assert normalizar("¿Hacen ENVÍOS a Río Cuarto?") == "hacen envios a rio cuarto"
    assert normalizar("  Pagás   con   tarjeta!!! ") == "pagas con tarjeta"


def test_conserva_la_enie():
    assert normalizar("Mañana, ¿abren?") == "mañana abren"


@pytest.mark.parametrize("texto,esperado", [
    ("5800", 5800),
    ("mi CP es 5800", 5800),
    ("X5800ABC", 5800),
    ("vivo en el x5000abc", 5000),
    ("Río Cuarto", None),
    ("123", None),
    ("0999", None),
    ("lo pago con $1500", None),
    ("son 2500 pesos?", None),
    ("58000", None),
])
def test_extrae_codigo_postal(texto, esperado):
    assert extraer_codigo_postal(texto) == esperado


def test_candidatos_de_codigo_de_acceso():
    assert candidatos_codigo("Hola, quiero hacer una consulta a Casa & Detalles. Código: CASA26") == ["CASA26"]
    assert candidatos_codigo("#text42") == ["TEXT42"]
    # Palabras sin dígitos no se confunden con códigos.
    assert candidatos_codigo("ENVIOS PAGOS 123456") == []


@pytest.mark.parametrize("texto,tema", [
    ("¿Hacen envíos a Río Cuarto?", TemaConsulta.ENVIO),
    ("cuánto tarda en llegar al 5800", TemaConsulta.ENVIO),
    ("¿Aceptan Mercado Pago?", TemaConsulta.MEDIOS_PAGO),
    ("y cómo se paga?", TemaConsulta.MEDIOS_PAGO),
    ("se puede en cuotas con tarjeta?", TemaConsulta.MEDIOS_PAGO),
    ("¿A qué hora abren?", TemaConsulta.HORARIOS),
    ("atienden los sábados?", TemaConsulta.HORARIOS),
    ("¿Tienen el mantel en otro color?", TemaConsulta.NO_RECONOCIDO),
])
def test_detecta_el_tema_por_palabras_clave(texto, tema):
    assert detectar_tema(texto, CATALOGO).tema == tema


def test_empate_entre_temas_es_no_reconocido():
    # «envío» y «llega» suman 2 para ENVIO; «hora» y «a qué hora» suman 2 para HORARIOS.
    clasificacion = detectar_tema("¿A qué hora llega el envío?", CATALOGO)
    assert clasificacion.tema == TemaConsulta.NO_RECONOCIDO
    assert clasificacion.empate


def test_no_coincide_dentro_de_otra_palabra():
    assert detectar_tema("Me gustan las pagodas", CATALOGO).tema == TemaConsulta.NO_RECONOCIDO


def test_opciones_del_menu():
    assert opcion_menu("1") == TemaConsulta.ENVIO
    assert opcion_menu("opción 2") == TemaConsulta.MEDIOS_PAGO
    assert opcion_menu("3.") == TemaConsulta.HORARIOS
    assert opcion_menu("12") is None


def test_saludos_y_cortesia():
    assert es_saludo("Hola, buenas tardes")
    assert not es_saludo("hola, hacen envíos?")
    assert es_cortesia("gracias!")
    assert es_cortesia("dale, muchas gracias")
    assert es_cortesia("👍")
    assert not es_cortesia("gracias, y cuánto tarda?")


def test_palabra_clave_coincide():
    palabra = PalabraClave(termino="mercado pago", tema=TemaConsulta.MEDIOS_PAGO)
    assert palabra.coincide("¿Aceptan MERCADO PAGO?")
    assert not palabra.coincide("mercado")
