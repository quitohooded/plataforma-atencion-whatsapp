"""Comprensión del bot medida contra los corpus de mensajes (``tests/corpus``).

Cada mensaje es una prueba: si el bot deja de entender algo que entendía, falla la
integración continua. Los casos de temas que se implementan en issues posteriores se
marcan como fallas esperadas estrictas: cuando el bot los resuelva, la prueba avisa para
quitar la marca.
"""

import pytest

from app.bot.contexto import ContextoConversacion
from app.bot.motor import MotorConversacional
from tests.corpus import mensajes, validacion
from tests.corpus.evaluacion import acciones, coincide, evaluar, procesar

# Categorías cuyo comportamiento llega en issues siguientes.
PENDIENTES = {"faq": "#5", "seguridad": "#6", "spam": "#7", "insulto": "#7"}
DIALOGOS_PENDIENTES = {"Insultos repetidos": "#7", "Spam y después silencio": "#7"}


def _requiere_respuestas_propias(esperado: str) -> bool:
    return all("FAQ:" in alternativa for alternativa in esperado.split("|"))


def _parametros(casos):
    parametros = []
    for numero, (mensaje, esperado, categoria) in enumerate(casos, start=1):
        issue = PENDIENTES.get(categoria) or ("#5" if _requiere_respuestas_propias(esperado) else None)
        marcas = [pytest.mark.xfail(reason=f"se resuelve en el issue {issue}", strict=True)] if issue else []
        parametros.append(pytest.param(mensaje, esperado, id=f"{categoria}-{numero}", marks=marcas))
    return parametros


def _parametros_dialogos(dialogos):
    parametros = []
    for nombre, pasos in dialogos:
        issue = DIALOGOS_PENDIENTES.get(nombre)
        marcas = [pytest.mark.xfail(reason=f"se resuelve en el issue {issue}", strict=True)] if issue else []
        parametros.append(pytest.param(pasos, id=nombre, marks=marcas))
    return parametros


@pytest.fixture(scope="module")
def motor():
    return MotorConversacional()


def _verificar_dialogo(motor, pasos):
    contexto = ContextoConversacion()
    for numero, (mensaje, esperado) in enumerate(pasos, start=1):
        resultado = procesar(motor, mensaje, contexto)
        obtenidas = acciones(resultado)
        assert coincide(esperado, obtenidas), f"paso {numero} «{mensaje}»: se esperaba {esperado}, hizo {obtenidas}"
        contexto = resultado.contexto


@pytest.mark.parametrize("mensaje,esperado", _parametros(mensajes.CASOS))
def test_corpus_de_desarrollo(motor, mensaje, esperado):
    obtenidas = acciones(procesar(motor, mensaje))
    assert coincide(esperado, obtenidas), f"se esperaba {esperado}, hizo {obtenidas}"


@pytest.mark.parametrize("pasos", _parametros_dialogos(mensajes.DIALOGOS))
def test_dialogos_de_desarrollo(motor, pasos):
    _verificar_dialogo(motor, pasos)


@pytest.mark.parametrize("mensaje,esperado", _parametros(validacion.CASOS))
def test_corpus_de_validacion(motor, mensaje, esperado):
    obtenidas = acciones(procesar(motor, mensaje))
    assert coincide(esperado, obtenidas), f"se esperaba {esperado}, hizo {obtenidas}"


@pytest.mark.parametrize("pasos", _parametros_dialogos(validacion.DIALOGOS))
def test_dialogos_de_validacion(motor, pasos):
    _verificar_dialogo(motor, pasos)


def test_comparador_de_acciones():
    assert coincide("ENVIO+PAGO", ["PAGO", "ENVIO"])
    assert not coincide("ENVIO", ["ENVIO", "PAGO"])
    assert coincide("D:*", ["D:PRODUCTOS"])
    assert not coincide("D:*", ["PAGO"])
    assert coincide("CATALOGO|D:PRODUCTOS", ["D:PRODUCTOS"])
    assert coincide("SILENCIO", ["SILENCIO"])


def test_informe_de_exactitud(motor):
    informe = evaluar(motor)
    assert informe.total == len(mensajes.CASOS)
    assert sum(n for _, n in informe.por_categoria.values()) == informe.total
    # Fuera de las categorías pendientes, el bot no puede fallar ningún mensaje del corpus.
    assert [
        f for f in informe.fallos if f.categoria not in PENDIENTES and not _requiere_respuestas_propias(f.esperado)
    ] == []
