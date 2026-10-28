"""Evaluación del bot contra el corpus: compara lo que hizo el motor con lo esperado.

Lo usan las pruebas (``tests/test_corpus.py``) y el informe de exactitud
(``scripts/evaluar_bot.py``).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from app.bot.contexto import ContextoConversacion
from app.bot.motor import MotorConversacional, ResultadoMotor
from app.datos.palabras_clave import items_catalogo

from .comercio import AHORA, CASA_Y_DETALLES
from .mensajes import CASOS, DIALOGOS

CATALOGO = items_catalogo()
_TIPO_ARCHIVO = re.compile(r"^\[Mensaje de tipo (\w+)\]$")
_TIPOS = {"imagen": "image", "audio": "audio", "video": "video", "documento": "document", "sticker": "sticker"}
# Acciones que no cambian lo que el comprador recibe como respuesta a su consulta.
_IGNORADAS = {"PRESENTACION"}


def procesar(motor: MotorConversacional, mensaje: str, contexto: ContextoConversacion | None = None) -> ResultadoMotor:
    tipo = "text"
    coincidencia = _TIPO_ARCHIVO.match(mensaje)
    if coincidencia:
        tipo, mensaje = _TIPOS.get(coincidencia.group(1), coincidencia.group(1)), ""
    return motor.procesar(
        CASA_Y_DETALLES, contexto or ContextoConversacion(), mensaje, CATALOGO, AHORA, primer_contacto=False, tipo=tipo
    )


def acciones(resultado: ResultadoMotor) -> list[str]:
    return [a for a in resultado.acciones if a not in _IGNORADAS]


def coincide(esperado: str, obtenidas: list[str]) -> bool:
    """«ENVIO+PAGO» exige exactamente esas acciones; «|» separa alternativas; «D:*» es cualquier derivación."""
    conjunto = set(obtenidas)
    for alternativa in esperado.split("|"):
        partes = set(alternativa.split("+"))
        if "SILENCIO" in partes and not conjunto - {"SILENCIO"}:
            return True
        comodin = "D:*" in partes
        partes.discard("D:*")
        resto = set(conjunto)
        if comodin:
            derivaciones = {a for a in resto if a.startswith("D:")}
            if not derivaciones:
                continue
            resto -= derivaciones
        if partes == resto:
            return True
    return False


@dataclass
class Fallo:
    categoria: str
    mensaje: str
    esperado: str
    obtenido: list[str]


@dataclass
class Informe:
    aciertos: int
    total: int
    por_categoria: dict[str, tuple[int, int]]
    fallos: list[Fallo]
    dialogos_ok: int
    dialogos_total: int
    fallos_dialogos: list[tuple[str, int, str, str, list[str]]]

    @property
    def exactitud(self) -> float:
        return self.aciertos * 100 / self.total if self.total else 0.0


def evaluar(motor: MotorConversacional | None = None, casos=None, dialogos=None) -> Informe:
    """Evalúa el motor sobre un corpus (por defecto, el de desarrollo)."""
    motor = motor or MotorConversacional()
    casos = CASOS if casos is None else casos
    dialogos = DIALOGOS if dialogos is None else dialogos
    por_categoria: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    fallos: list[Fallo] = []
    aciertos = 0
    for mensaje, esperado, categoria in casos:
        obtenidas = acciones(procesar(motor, mensaje))
        por_categoria[categoria][1] += 1
        if coincide(esperado, obtenidas):
            aciertos += 1
            por_categoria[categoria][0] += 1
        else:
            fallos.append(Fallo(categoria, mensaje, esperado, obtenidas))

    dialogos_ok = 0
    fallos_dialogos = []
    for nombre, pasos in dialogos:
        contexto = ContextoConversacion()
        bien = True
        for numero, (mensaje, esperado) in enumerate(pasos, start=1):
            resultado = procesar(motor, mensaje, contexto)
            contexto = resultado.contexto
            obtenidas = acciones(resultado)
            if not coincide(esperado, obtenidas):
                bien = False
                fallos_dialogos.append((nombre, numero, mensaje, esperado, obtenidas))
                break
        dialogos_ok += bien

    return Informe(
        aciertos,
        len(casos),
        {c: (v[0], v[1]) for c, v in por_categoria.items()},
        fallos,
        dialogos_ok,
        len(dialogos),
        fallos_dialogos,
    )
