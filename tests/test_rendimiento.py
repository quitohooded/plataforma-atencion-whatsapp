"""RNF04: el bot responde «en cuestión de segundos». Estas pruebas fijan un techo holgado para
detectar una regresión grave (por ejemplo, una expresión regular que se dispare o una consulta a la
base por cada palabra). Las mediciones detalladas están en docs/rendimiento.md
(scripts/rendimiento.py)."""

from __future__ import annotations

import time

from app.bot.motor import MotorConversacional
from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante

from .corpus.evaluacion import procesar
from .corpus.mensajes import CASOS
from .corpus.validacion import CASOS as CASOS_VALIDACION

MENSAJES = [m for m, _, _ in [*CASOS, *CASOS_VALIDACION] if not m.startswith("[Mensaje de tipo")]
# Techos generosos: en el equipo de desarrollo los valores reales son 20 a 50 veces menores.
TECHO_MOTOR_P95 = 0.05
TECHO_MOTOR_MAXIMO = 1.0
TECHO_SERVICIO_P95 = 0.5


def _p95(tiempos: list[float]) -> float:
    ordenados = sorted(tiempos)
    return ordenados[int(0.95 * (len(ordenados) - 1))]


def test_el_motor_responde_cada_mensaje_de_los_corpus_en_milisegundos():
    motor = MotorConversacional()
    procesar(motor, MENSAJES[0])
    tiempos = []
    for mensaje in MENSAJES:
        inicio = time.perf_counter()
        procesar(motor, mensaje)
        tiempos.append(time.perf_counter() - inicio)
    assert _p95(tiempos) < TECHO_MOTOR_P95
    assert max(tiempos) < TECHO_MOTOR_MAXIMO


def test_el_servicio_completo_con_base_de_datos_responde_rapido(app, comercio):
    tiempos = []
    for i, mensaje in enumerate(MENSAJES[:80]):
        telefono = f"5493510{i:06d}"
        procesar_mensaje_entrante(MensajeEntrante(telefono=telefono, texto=comercio.texto_primer_mensaje()))
        inicio = time.perf_counter()
        procesar_mensaje_entrante(MensajeEntrante(telefono=telefono, texto=mensaje))
        tiempos.append(time.perf_counter() - inicio)
    assert _p95(tiempos) < TECHO_SERVICIO_P95


def test_un_mensaje_muy_largo_no_demora_al_bot():
    motor = MotorConversacional()
    texto = "hola quiero saber si hacen envios a rosario y cuanto sale " * 200
    inicio = time.perf_counter()
    procesar(motor, texto)
    assert time.perf_counter() - inicio < TECHO_MOTOR_MAXIMO
