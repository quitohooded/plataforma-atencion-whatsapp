"""Identificación del tema de la consulta por coincidencia de palabras clave (CU08, RF01)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..modelos import TemaConsulta
from .normalizacion import contiene_termino, normalizar, palabras

# Palabras que forman saludos o mensajes de cortesía. No son temas de consulta:
# el bot responde con la bienvenida o con un cierre amable, sin registrar consulta.
_SALUDO_NUCLEO = {"hola", "holi", "holis", "holaa", "buenas", "buen", "buenos", "hey", "saludos"}
_CORTESIA_NUCLEO = {
    "gracias", "graciass", "ok", "oka", "okey", "okay", "dale", "perfecto", "genial",
    "buenisimo", "barbaro", "joya", "listo", "chau", "adios", "excelente", "entendido",
    "espectacular", "impecable", "mil",
}
_RELLENO = {
    "dia", "dias", "tarde", "tardes", "noche", "noches", "que", "tal", "como", "estas", "andas",
    "va", "che", "muchas", "muchisimas", "nos", "vemos", "de", "nada", "bueno", "bien", "todo",
    "un", "saludo", "abrazo", "te", "les", "agradezco", "ahi", "ya", "esta", "y", "gente", "a",
    "vos", "ustedes",
}

# Opciones numéricas del menú de bienvenida.
OPCIONES_MENU = {
    "1": TemaConsulta.ENVIO,
    "2": TemaConsulta.MEDIOS_PAGO,
    "3": TemaConsulta.HORARIOS,
}


@dataclass
class Clasificacion:
    tema: TemaConsulta
    coincidencias: dict[TemaConsulta, list[str]] = field(default_factory=dict)

    @property
    def empate(self) -> bool:
        conteo = sorted((len(v) for v in self.coincidencias.values()), reverse=True)
        return len(conteo) > 1 and conteo[0] == conteo[1] and conteo[0] > 0


def detectar_tema(texto: str, catalogo: list[tuple[str, TemaConsulta]]) -> Clasificacion:
    """Determina el tema con mayor cantidad de coincidencias (CU08, pasos 4 y 5).

    Si ninguna palabra coincide o hay empate entre temas, el resultado es
    NO_RECONOCIDO y la conversación continúa por la derivación (CU12).
    """
    normalizado = normalizar(texto)
    coincidencias: dict[TemaConsulta, list[str]] = {}
    for termino, tema in catalogo:
        if contiene_termino(normalizado, termino):
            coincidencias.setdefault(tema, []).append(termino)

    if not coincidencias:
        return Clasificacion(TemaConsulta.NO_RECONOCIDO, coincidencias)

    conteo = Counter({tema: len(terminos) for tema, terminos in coincidencias.items()})
    (tema_1, cantidad_1), *resto = conteo.most_common()
    if resto and resto[0][1] == cantidad_1:
        return Clasificacion(TemaConsulta.NO_RECONOCIDO, coincidencias)
    return Clasificacion(tema_1, coincidencias)


def opcion_menu(texto: str) -> TemaConsulta | None:
    tokens = palabras(normalizar(texto))
    tokens = [t for t in tokens if t not in {"opcion", "la", "el", "numero", "nro", "quiero"}]
    if len(tokens) == 1 and tokens[0] in OPCIONES_MENU:
        return OPCIONES_MENU[tokens[0]]
    return None


def _solo_vocabulario_social(tokens: list[str]) -> bool:
    permitido = _SALUDO_NUCLEO | _CORTESIA_NUCLEO | _RELLENO
    return bool(tokens) and all(t in permitido for t in tokens)


def es_cortesia(texto: str) -> bool:
    """«Gracias», «ok», «dale», «chau», o un mensaje sin letras (por ejemplo, un emoji)."""
    normalizado = normalizar(texto)
    if not normalizado:
        return bool((texto or "").strip())
    tokens = palabras(normalizado)
    return _solo_vocabulario_social(tokens) and any(t in _CORTESIA_NUCLEO for t in tokens)


def es_saludo(texto: str) -> bool:
    tokens = palabras(normalizar(texto))
    return _solo_vocabulario_social(tokens) and any(t in _SALUDO_NUCLEO for t in tokens)
