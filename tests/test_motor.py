"""Motor de estados y respuestas: CU09 a CU12 sin base de datos (RF02 a RF07)."""

from datetime import datetime, time

import pytest

from app.bot import respuestas
from app.bot.contexto import DatosComercio, FranjaDatos, MedioDatos, ZonaDatos
from app.bot.motor import MotorConversacional
from app.datos.palabras_clave import items_catalogo
from app.modelos import EstadoConversacion as E
from app.modelos import ResultadoConsulta as R
from app.modelos import TemaConsulta as T

CATALOGO = items_catalogo()
MARTES_NOCHE = datetime(2026, 10, 27, 22, 30)

DATOS = DatosComercio(
    nombre="Casa & Detalles",
    telefono_contacto="351 012-3456",
    zonas=(ZonaDatos(5000, 5099, "Córdoba Capital", 1, 2), ZonaDatos(5100, 5999, "Interior de Córdoba", 2, 4)),
    medios=(MedioDatos("Transferencia bancaria", "alias casa.detalles.demo"), MedioDatos("Billetera virtual", "Mercado Pago")),
    franjas=tuple(FranjaDatos(d, time(9), time(18)) for d in range(5)) + (FranjaDatos(5, time(9), time(13)),),
)


@pytest.fixture
def motor():
    return MotorConversacional(max_intentos_cp=2)


def procesar(motor, texto, estado=E.ACTIVA, intentos=0, datos=DATOS, ahora=MARTES_NOCHE, primer=False):
    return motor.procesar(datos, estado, intentos, texto, CATALOGO, ahora, primer)


# --- CU09 -------------------------------------------------------------------

def test_cu09_flujo_principal_solicita_cp_y_responde_plazo(motor):
    r1 = procesar(motor, "¿Hacen envíos a Río Cuarto?")
    assert r1.estado == E.ESPERANDO_CP
    assert r1.consulta is None
    assert "código postal" in r1.respuestas[0]

    r2 = procesar(motor, "5800", estado=r1.estado)
    assert r2.estado == E.ACTIVA
    assert "2 a 4 días hábiles" in r2.respuestas[0]
    assert (r2.consulta.tema, r2.consulta.resultado, r2.consulta.codigo_postal) == (T.ENVIO, R.RESUELTA, 5800)


def test_cu09_alternativo_cp_en_el_primer_mensaje(motor):
    r = procesar(motor, "cuánto tarda el envío al 5000?")
    assert r.estado == E.ACTIVA
    assert "1 a 2 días hábiles" in r.respuestas[0]
    assert r.consulta.resultado == R.RESUELTA


def test_cu09_excepcion_cp_invalido_dos_veces_deriva(motor):
    r1 = procesar(motor, "Río Cuarto", estado=E.ESPERANDO_CP)
    assert (r1.estado, r1.intentos_cp) == (E.ESPERANDO_CP, 1)
    assert "4 números" in r1.respuestas[0]
    assert r1.consulta is None

    r2 = procesar(motor, "no sé", estado=E.ESPERANDO_CP, intentos=1)
    assert r2.estado == E.DERIVADA
    assert (r2.consulta.tema, r2.consulta.resultado) == (T.ENVIO, R.DERIVADA)


def test_cu09_excepcion_zona_no_configurada_deriva(motor):
    r = procesar(motor, "1405", estado=E.ESPERANDO_CP)
    assert r.estado == E.DERIVADA
    assert "1405" in r.respuestas[0]
    assert (r.consulta.resultado, r.consulta.codigo_postal) == (R.DERIVADA, 1405)


def test_cu09_sin_zonas_cargadas_deriva(motor):
    datos = DatosComercio(nombre="X", medios=DATOS.medios, franjas=DATOS.franjas)
    r = procesar(motor, "hacen envíos?", datos=datos)
    assert r.estado == E.DERIVADA


# --- CU10 -------------------------------------------------------------------

def test_cu10_responde_medios_de_pago_con_detalle(motor):
    r = procesar(motor, "¿Aceptan Mercado Pago?")
    assert r.estado == E.ACTIVA
    assert "Transferencia bancaria: alias casa.detalles.demo" in r.respuestas[0]
    assert "Billetera virtual: Mercado Pago" in r.respuestas[0]
    assert (r.consulta.tema, r.consulta.resultado) == (T.MEDIOS_PAGO, R.RESUELTA)


def test_cu10_excepcion_sin_medios_deriva(motor):
    datos = DatosComercio(nombre="X", zonas=DATOS.zonas, franjas=DATOS.franjas)
    r = procesar(motor, "formas de pago?", datos=datos)
    assert r.estado == E.DERIVADA
    assert r.consulta.tema == T.MEDIOS_PAGO


# --- CU11 -------------------------------------------------------------------

def test_cu11_horarios_agrupados_y_abierto_ahora(motor):
    r = procesar(motor, "qué horario tienen?", ahora=datetime(2026, 10, 27, 11, 0))
    texto = r.respuestas[0]
    assert "Lunes a viernes: 9:00 a 18:00" in texto
    assert "Sábado: 9:00 a 13:00" in texto
    assert "Domingo: cerrado" in texto
    assert "Ahora estamos atendiendo, hasta las 18:00" in texto
    assert r.consulta.resultado == R.RESUELTA


def test_cu11_alternativo_cerrado_indica_reapertura(motor):
    assert "Volvemos a abrir mañana a las 9:00" in procesar(motor, "a qué hora abren?").respuestas[0]
    sabado_tarde = datetime(2026, 10, 31, 15, 0)
    assert "el lunes a las 9:00" in procesar(motor, "abren?", ahora=sabado_tarde).respuestas[0]
    madrugada = datetime(2026, 10, 28, 7, 0)
    assert "hoy a las 9:00" in procesar(motor, "abren?", ahora=madrugada).respuestas[0]


def test_cu11_excepcion_sin_horarios_deriva(motor):
    datos = DatosComercio(nombre="X", zonas=DATOS.zonas, medios=DATOS.medios)
    assert procesar(motor, "horarios?", datos=datos).estado == E.DERIVADA


def test_horario_jornada_partida():
    datos = DatosComercio(nombre="X", franjas=(FranjaDatos(0, time(9), time(13)), FranjaDatos(0, time(16), time(20))))
    assert respuestas.lineas_horario(datos)[0] == "Lunes: 9:00 a 13:00 y 16:00 a 20:00"
    assert respuestas.lineas_horario(datos)[1] == "Martes a domingo: cerrado"


# --- CU12 -------------------------------------------------------------------

def test_cu12_tema_no_reconocido_deriva_e_informa_horario(motor):
    r = procesar(motor, "¿Tienen el mantel en otro color?")
    assert r.estado == E.DERIVADA
    assert "351 012-3456" in r.respuestas[0]
    assert "Horario de atención" in r.respuestas[0]
    assert (r.consulta.tema, r.consulta.resultado) == (T.NO_RECONOCIDO, R.DERIVADA)


def test_cu12_alternativo_mensajes_durante_derivacion_sin_respuesta(motor):
    r = procesar(motor, "hola? alguien?", estado=E.DERIVADA)
    assert r.respuestas == []
    assert r.estado == E.DERIVADA
    assert r.consulta is None


# --- Bienvenida, menú y cortesía -----------------------------------------------

def test_primer_contacto_responde_bienvenida_sin_registrar_consulta(motor):
    r = procesar(motor, "Hola, quiero hacer una consulta a . Código:", primer=True)
    assert "asistente automático de Casa & Detalles" in r.respuestas[0]
    assert r.consulta is None and r.estado == E.ACTIVA


def test_menu_numerico(motor):
    assert procesar(motor, "2").consulta.tema == T.MEDIOS_PAGO
    assert procesar(motor, "1").estado == E.ESPERANDO_CP


def test_cortesia_no_deriva(motor):
    r = procesar(motor, "gracias!")
    assert r.estado == E.ACTIVA and r.consulta is None
