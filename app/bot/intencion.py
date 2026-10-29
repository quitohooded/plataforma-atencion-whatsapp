"""Identificación de la intención del mensaje por palabras clave (CU08, RF01).

El análisis no usa procesamiento de lenguaje natural ni modelos entrenados (alcance del
informe): combina reglas deterministas que se pueden explicar y probar.

1. **Oraciones.** El mensaje se divide en oraciones por signos («?», «.», «,») y por
   conectores («y», «también»). Así «¿envían a Rosario? ¿y cómo se paga?» son dos
   consultas y se responden las dos.
2. **Normalización.** Cada oración se normaliza y se expanden las abreviaturas
   (``normalizacion.py``).
3. **Corrección de tipeo.** Una palabra que no está en el vocabulario se corrige hacia la
   palabra clave más parecida (una letra de diferencia, o dos en palabras largas): «orario»
   → «horario», «trasferencia» → «transferencia». Las palabras comunes del español nunca se
   corrigen («tarde» no pasa a «tarda»).
4. **Coincidencias.** Se buscan los términos del catálogo y del vocabulario conversacional,
   primero los más largos: «medios de pago» se cuenta una vez y «tarjeta de dedicatoria» no
   suma como medio de pago.
5. **Puntaje por tema.** Cada término suma su peso. En cada oración queda el tema de mayor
   puntaje y los que superan el umbral; algunos temas absorben a otros (un reclamo que
   menciona el pedido es un reclamo; un pago informado que menciona la transferencia no
   pregunta por medios de pago).
6. **Respuestas propias del comercio (CU15).** Las palabras clave de cada respuesta propia
   se suman al léxico como un tema más («FAQ:cambios»), con prioridad sobre las palabras
   genéricas de productos y pedidos: «precio mayorista» se responde con la respuesta de
   ventas por mayor y no se deriva como una consulta de precios.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache

from ..modelos import TemaConsulta
from . import lexico
from .ciudades import PALABRAS_LOCALIDADES, LocalidadEncontrada, buscar_localidades
from .normalizacion import (
    distancia_edicion,
    es_solo_codigo_postal,
    expandir_abreviaturas,
    extraer_codigos_postales,
    normalizar,
    normalizar_frase,
    palabras,
)

# Intenciones de negocio (temas). CATALOGO es un pedido del catálogo completo: se registra
# con el tema PRODUCTOS.
ENVIO = "ENVIO"
MEDIOS_PAGO = "MEDIOS_PAGO"
HORARIOS = "HORARIOS"
CONTACTO = "CONTACTO"
CATALOGO = "CATALOGO"
PRODUCTOS = "PRODUCTOS"
PEDIDOS = "PEDIDOS"
RECLAMOS = "RECLAMOS"
PAGOS_INFORMADOS = "PAGOS_INFORMADOS"

TEMAS_RESOLUBLES = (ENVIO, MEDIOS_PAGO, HORARIOS, CONTACTO, CATALOGO)
TEMAS_DERIVABLES = (PAGOS_INFORMADOS, RECLAMOS, PEDIDOS, PRODUCTOS)
# Orden de prioridad para desempatar y para elegir el tema de una derivación.
PRIORIDAD = (RECLAMOS, PAGOS_INFORMADOS, PEDIDOS, ENVIO, MEDIOS_PAGO, HORARIOS, CONTACTO, PRODUCTOS, CATALOGO)

# Intenciones de control (forma de conversar; no se registran como consulta).
SALUDO = "SALUDO"
CORTESIA = "CORTESIA"
DESPEDIDA = "DESPEDIDA"
PERSONA = "PERSONA"
IDENTIDAD = "IDENTIDAD"
PRIVACIDAD = "PRIVACIDAD"
BORRAR_DATOS = "BORRAR_DATOS"
CONTAME = "CONTAME"
MENU = "MENU"
CANCELAR = "CANCELAR"
SI = "SI"
NO = "NO"
NO_SE = "NO_SE"

# Opciones numéricas del menú de bienvenida.
OPCIONES_MENU = {"1": ENVIO, "2": MEDIOS_PAGO, "3": HORARIOS, "4": PERSONA}

UMBRAL_TEMA = 1.0
UMBRAL_TEMA_DEBIL = 0.5
PESO_FUERTE = 2.0

# Respuestas propias del comercio: la intención es el prefijo más la clave de la respuesta
# («FAQ:factura»). Sus palabras clave cuentan como frases inequívocas.
PREFIJO_RESPUESTA = "FAQ:"
PESO_RESPUESTA = PESO_FUERTE


def es_respuesta(intencion: str) -> bool:
    return intencion.startswith(PREFIJO_RESPUESTA)


def clave_respuesta(intencion: str) -> str:
    return intencion[len(PREFIJO_RESPUESTA) :]


def es_tema(intencion: str) -> bool:
    """Intención de negocio (se registra como consulta), a diferencia de las de control."""
    return intencion in TEMAS_RESOLUBLES or intencion in TEMAS_DERIVABLES or es_respuesta(intencion)


def _orden(tema: str) -> float:
    """Posición en PRIORIDAD; las respuestas propias van antes de productos."""
    if es_respuesta(tema):
        return PRIORIDAD.index(PRODUCTOS) - 0.5
    return PRIORIDAD.index(tema)


def tema_de(intencion: str) -> TemaConsulta:
    """Tema con el que se registra la consulta de una intención de negocio."""
    if intencion == CATALOGO:
        return TemaConsulta.PRODUCTOS
    if es_respuesta(intencion):
        return TemaConsulta.RESPUESTA_PROPIA
    return TemaConsulta(intencion)


# ---------------------------------------------------------------------------
# Léxico: índice de términos y corrector
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Entrada:
    tokens: tuple[str, ...]
    intencion: str  # vacío para las frases neutras
    peso: float = 1.0

    @property
    def termino(self) -> str:
        return " ".join(self.tokens)


@dataclass(frozen=True)
class Coincidencia:
    entrada: Entrada
    inicio: int
    fin: int

    @property
    def termino(self) -> str:
        return self.entrada.termino


def _entradas_control() -> list[Entrada]:
    grupos = [
        ("", [(t, 0.0) for t in lexico.NEUTRAS]),
        (PERSONA, lexico.PERSONA),
        (IDENTIDAD, lexico.IDENTIDAD),
        (BORRAR_DATOS, lexico.BORRAR_DATOS),
        (PRIVACIDAD, lexico.PRIVACIDAD),
        (MENU, lexico.MENU),
        (NO_SE, lexico.NO_SE),
        (CANCELAR, lexico.CANCELAR),
        (CONTAME, lexico.CONTAME),
        (CATALOGO, lexico.CATALOGO),
        (DESPEDIDA, [(t, 1.0) for t in lexico.DESPEDIDA]),
        (CORTESIA, [(t, 1.0) for t in lexico.CORTESIA]),
        (SALUDO, [(t, 1.0) for t in lexico.SALUDO]),
        (NO, lexico.NO),
        (SI, lexico.SI),
    ]
    entradas = []
    for intencion, terminos in grupos:
        for termino, peso in terminos:
            entradas.append(Entrada(tuple(termino.split()), intencion, peso))
    return entradas


def terminos_conversacionales() -> set[str]:
    """Frases del vocabulario conversacional (no se pueden asignar a un tema del catálogo)."""
    return {" ".join(e.tokens) for e in _entradas_control()}


_ENCLITICOS = ("selo", "sela", "melo", "mela", "telo", "tela", "los", "las", "les", "nos", "lo", "la", "le", "me", "te")


class Lexico:
    """Índice de términos (vocabulario conversacional, respuestas propias del comercio y
    catálogo de la base) y corrector.

    Si un mismo término aparece dos veces, vale el primero: la conversación, después las
    respuestas propias y por último el catálogo.
    """

    def __init__(self, catalogo: Iterable[tuple[str, str, float]], propias: Iterable[tuple[str, str, float]] = ()):
        self.indice: dict[str, list[Entrada]] = {}
        vistos: set[tuple[str, ...]] = set()
        entradas = _entradas_control() + [
            Entrada(tuple(normalizar(t).split()), intencion, peso) for t, intencion, peso in [*propias, *catalogo]
        ]
        for entrada in entradas:
            if not entrada.tokens or entrada.tokens in vistos:
                continue
            vistos.add(entrada.tokens)
            self.indice.setdefault(entrada.tokens[0], []).append(entrada)
        for lista in self.indice.values():
            lista.sort(key=lambda e: len(e.tokens), reverse=True)

        palabras_terminos = {t for tokens in vistos for t in tokens}
        self.vocabulario = palabras_terminos | lexico.PALABRAS_COMUNES | PALABRAS_LOCALIDADES
        self.vocabulario |= {p for expansion in lexico.ABREVIATURAS.values() for p in expansion.split()}
        self.vocabulario |= set(lexico.ABREVIATURAS)
        objetivos = {t for t in palabras_terminos if len(t) >= 4 and t.isalpha()}
        objetivos |= {t for t in PALABRAS_LOCALIDADES if len(t) >= 5 and t.isalpha()}
        self._objetivos_por_largo: dict[int, list[str]] = {}
        for objetivo in sorted(objetivos):
            self._objetivos_por_largo.setdefault(len(objetivo), []).append(objetivo)
        self._correcciones: dict[str, str] = {}

    def corregir(self, token: str) -> str:
        """Corrige un error de tipeo hacia una palabra clave, si hay una sola candidata cercana."""
        if token in self.vocabulario or len(token) < 5 or not token.isalpha():
            return token
        if token not in self._correcciones:
            if len(self._correcciones) > 20_000:
                self._correcciones.clear()
            self._correcciones[token] = self._buscar_correccion(token)
        return self._correcciones[token]

    def _buscar_correccion(self, token: str) -> str:
        # Verbo con pronombre pegado: «buscarlo», «enviarte», «retirarla» → el infinitivo, si es una
        # palabra conocida («ir a buscarlo» coincide con «ir a buscar»).
        for pronombre in _ENCLITICOS:
            base = token[: -len(pronombre)]
            if token.endswith(pronombre) and base.endswith(("ar", "er", "ir")) and base in self.vocabulario:
                return base
        limite = 2 if len(token) >= 9 else 1
        mejores: list[str] = []
        mejor = limite + 1
        for largo in range(len(token) - limite, len(token) + limite + 1):
            for objetivo in self._objetivos_por_largo.get(largo, ()):
                # Filtro rápido: un error de tipeo casi nunca cambia a la vez las dos primeras
                # letras (cubre «orario» → «horario» y «targeta» → «tarjeta»).
                if not (
                    token[0] == objetivo[0]
                    or token[1] == objetivo[1]
                    or token[0] == objetivo[1]
                    or token[1] == objetivo[0]
                ):
                    continue
                d = distancia_edicion(token, objetivo, min(limite, mejor))
                if d < mejor:
                    mejor, mejores = d, [objetivo]
                elif d == mejor and d <= limite:
                    mejores.append(objetivo)
        if not mejores or mejor > limite:
            return token
        if len(mejores) > 1:
            misma_inicial = [m for m in mejores if m[0] == token[0]]
            if len(misma_inicial) != 1:
                return token
            return misma_inicial[0]
        return mejores[0]

    def coincidencias(self, tokens: list[str]) -> list[Coincidencia]:
        """Coincidencias de términos sin superponerse, prefiriendo las frases más largas.

        Se elige la combinación que más palabras cubre con frases largas (programación
        dinámica): en «me pasan el número de seguimiento» gana «número de seguimiento»
        (pedidos) sobre «el número» (contacto).
        """
        n = len(tokens)
        mejor: list[tuple[float, list[Coincidencia]]] = [(0.0, [])] * (n + 1)
        for i in range(n - 1, -1, -1):
            candidato = mejor[i + 1]
            for entrada in self.indice.get(tokens[i], ()):
                largo = len(entrada.tokens)
                if tuple(tokens[i : i + largo]) == entrada.tokens:
                    puntaje = largo**2 + mejor[i + largo][0]
                    if puntaje > candidato[0]:
                        candidato = (puntaje, [Coincidencia(entrada, i, i + largo)] + mejor[i + largo][1])
            mejor[i] = candidato
        return mejor[0][1]


# Un léxico por combinación de catálogo y respuestas propias (cada comercio tiene las suyas).
@lru_cache(maxsize=64)
def _lexico_cacheado(
    catalogo: tuple[tuple[str, str, float], ...], propias: tuple[tuple[str, str, float], ...] = ()
) -> Lexico:
    return Lexico(catalogo, propias)


def lexico_para(catalogo: Iterable, respuestas: Iterable = ()) -> Lexico:
    """Léxico para un catálogo de (término, tema, peso) y las respuestas propias de un
    comercio (objetos con ``clave`` y ``terminos``). Se reutiliza mientras no cambien."""
    normalizado = []
    for item in catalogo:
        termino, tema = item[0], item[1]
        peso = float(item[2]) if len(item) > 2 and item[2] is not None else 1.0
        valor = tema.value if isinstance(tema, TemaConsulta) else str(tema)
        if valor == TemaConsulta.NO_RECONOCIDO.value:
            continue
        normalizado.append((termino, valor, peso))
    propias = sorted(
        {(normalizar_frase(t), PREFIJO_RESPUESTA + r.clave, PESO_RESPUESTA) for r in respuestas for t in r.terminos}
    )
    return _lexico_cacheado(tuple(sorted(normalizado)), tuple(propias))


# ---------------------------------------------------------------------------
# Análisis del mensaje
# ---------------------------------------------------------------------------

_SEPARADOR_ORACIONES = re.compile(
    r"[?¿!¡.;,\n]+|\s+(?:y|e|tambien|también|ademas|además|aparte|otra cosa|otra pregunta|otra consulta)\s+",
    re.IGNORECASE,
)
_RISA = re.compile(r"^(?:j+[aeiou]+|[aeiou]+j+|js|sj|xd+|lol|ja|je|ji)+j*$")
# Largo máximo que se analiza: un comprador no escribe más que esto; un texto más largo
# (casi siempre spam copiado) se analiza por su comienzo, con un costo acotado.
LARGO_MAXIMO_ANALISIS = 1000
PALABRAS_MAXIMAS_CORREGIDAS = 120


def _tiene_emoji(texto: str) -> bool:
    return any(unicodedata.category(c) == "So" for c in texto)


@dataclass
class Oracion:
    texto: str
    tokens: list[str]
    coincidencias: list[Coincidencia]
    puntajes: dict[str, float]
    control: dict[str, float]
    temas: list[str]
    pide_precio: bool = False
    es_pregunta: bool = False
    contenido: list[str] = field(default_factory=list)
    # El tema surge solo de palabras que orientan («hora», «llegué»): cede ante un tema
    # firme de otra oración del mismo mensaje.
    tema_debil: bool = False
    # Una palabra interrogativa antes del contenido: «¿hacen factura?», «¿tienen showroom?».
    pregunta_directa: bool = False

    @property
    def tiene_tema(self) -> bool:
        return bool(self.temas)


@dataclass
class Interpretacion:
    texto: str
    oraciones: list[Oracion]
    temas: list[str]
    control: list[str]
    codigos_postales: list[int]
    localidades: list[LocalidadEncontrada]
    pide_costo: bool
    medios_consultados: list[str]
    dias_consultados: list[str]
    es_pregunta: bool
    contenido: list[str]
    sin_sentido: bool
    solo_simbolos: bool
    terminos: dict[str, list[str]]
    pregunta_sin_tema: bool = False
    solo_codigo_postal: bool = False
    opcion_menu: str | None = None
    # La pregunta sin tema empieza con una palabra interrogativa («¿hacen factura?»): es una
    # consulta concreta aunque tenga una sola palabra con contenido.
    pregunta_directa: bool = False

    @property
    def tokens(self) -> list[str]:
        return [t for o in self.oraciones for t in o.tokens]

    @property
    def tiene_ubicacion(self) -> bool:
        return bool(self.codigos_postales or self.localidades)

    def tiene(self, intencion: str) -> bool:
        return intencion in self.temas or intencion in self.control


def _es_risa(token: str) -> bool:
    return bool(_RISA.match(token)) and len(token) >= 2


def _es_tecleo(token: str) -> bool:
    """«asdf», «qwerty», «sdfsdf»: letras al azar sin estructura de palabra."""
    if len(token) < 3 or not token.isalpha():
        return False
    if token in {"asd", "asdf", "asdasd", "qwe", "qwerty", "zxc", "sdf", "dfg", "jkl", "ñlk"}:
        return True
    vocales = sum(1 for c in token if c in "aeiou")
    if vocales == 0:
        return True
    if len(token) >= 5 and vocales / len(token) < 0.2:
        return True
    # Sílaba repetida: «asdasd», «hjhj».
    for n in (2, 3):
        if len(token) >= 2 * n and len(token) % n == 0 and token == token[:n] * (len(token) // n):
            return True
    return "asd" in token or "sdf" in token or "dfg" in token or "qwe" in token


def _es_contenido(token: str) -> bool:
    return (
        len(token) >= 3
        and any(c.isalpha() for c in token)
        and token not in lexico.VACIAS
        and token not in lexico.INTERJECCIONES
        and not _es_risa(token)
        and not _es_tecleo(token)
    )


def _analizar_oracion(texto: str, es_pregunta: bool, lex: Lexico, corregir: bool = True) -> Oracion:
    tokens = expandir_abreviaturas(palabras(normalizar(texto)))
    if corregir:
        tokens = [lex.corregir(t) if i < PALABRAS_MAXIMAS_CORREGIDAS else t for i, t in enumerate(tokens)]
    coincidencias = lex.coincidencias(tokens)

    # «mandame fotos», «te envío el alias»: el verbo de envío no pregunta por un envío.
    anuladas: set[int] = set()
    for indice, c in enumerate(coincidencias):
        if c.entrada.intencion == ENVIO and c.termino in lexico.VERBO_ENVIO:
            siguientes = tokens[c.fin : c.fin + 3]
            if any(t in lexico.INFORMACION_ENVIABLE for t in siguientes):
                anuladas.add(indice)

    hay_envio = any(
        c.entrada.intencion == ENVIO and i not in anuladas and c.termino not in lexico.PRECIO
        for i, c in enumerate(coincidencias)
    )
    pide_precio = any(c.termino in lexico.PRECIO for c in coincidencias)

    puntajes: dict[str, float] = {}
    control: dict[str, float] = {}
    cubiertos: set[int] = set()
    for indice, c in enumerate(coincidencias):
        intencion = c.entrada.intencion
        cubiertos.update(range(c.inicio, c.fin))
        if indice in anuladas or not intencion:
            continue
        if es_tema(intencion):
            # Junto a un término de envío, el precio es el costo del envío.
            if intencion == PRODUCTOS and hay_envio and c.termino in lexico.PRECIO:
                continue
            puntajes[intencion] = puntajes.get(intencion, 0.0) + c.entrada.peso
        else:
            control[intencion] = max(control.get(intencion, 0.0), c.entrada.peso)

    if not es_pregunta and _recepcion_positiva(tokens, puntajes):
        # «Llegó mi pedido, ¡gracias!»: no es una consulta del pedido sino un agradecimiento.
        puntajes.pop(PEDIDOS, None)
        control[CORTESIA] = max(control.get(CORTESIA, 0.0), 1.0)

    posiciones = [i for i, t in enumerate(tokens) if _es_contenido(t) and not _cubierto_por_control(i, coincidencias)]
    contenido = [tokens[i] for i in posiciones]
    directa = bool(posiciones) and any(t in lexico.INTERROGATIVOS for t in tokens[: posiciones[0]])
    temas, debil = _decidir_temas(puntajes)
    return Oracion(
        texto, tokens, coincidencias, puntajes, control, temas, pide_precio, es_pregunta, contenido, debil, directa
    )


_RECIBIO = {"llego", "llegaron", "recibi", "recibimos"}
_NEGACIONES = {"no", "nunca", "todavia", "aun", "tampoco", "ni", "sin"}
_LO_RECIBIDO = {"pedido", "paquete", "compra", "todo", "bien", "perfecto", "joya", "impecable", "rapidisimo"}


def _recepcion_positiva(tokens: list[str], puntajes: dict[str, float]) -> bool:
    """El comprador avisa que recibió su compra sin un problema («ya me llegó el pedido»)."""
    if puntajes.get(RECLAMOS, 0) or puntajes.get(PRODUCTOS, 0) >= UMBRAL_TEMA:
        return False
    for i, token in enumerate(tokens):
        if token in _RECIBIO and not _NEGACIONES & set(tokens[max(0, i - 3) : i]):
            resto = tokens[i + 1 :]
            if not resto or _LO_RECIBIDO & set(resto):
                return True
    return False


def _cubierto_por_control(indice: int, coincidencias: list[Coincidencia]) -> bool:
    """La palabra forma parte de una frase de control («quiero hablar con una persona»)."""
    for c in coincidencias:
        if c.inicio <= indice < c.fin:
            intencion = c.entrada.intencion
            return bool(intencion) and not es_tema(intencion)
    return False


def _decidir_temas(puntajes: dict[str, float]) -> tuple[list[str], bool]:
    """Temas de una oración y si surgen solo de palabras débiles."""
    p = dict(puntajes)
    if p.get(PRODUCTOS, 0) >= UMBRAL_TEMA:
        p.pop(CATALOGO, None)
    elif p.get(CATALOGO, 0) >= UMBRAL_TEMA:
        p.pop(PRODUCTOS, None)

    propias = [t for t, v in p.items() if es_respuesta(t) and v >= UMBRAL_TEMA]
    if propias:
        if p.get(RECLAMOS, 0) >= UMBRAL_TEMA:
            # «Quiero devolverlo porque vino fallado» es un reclamo, no una pregunta por la
            # política de cambios: lo atiende una persona.
            for tema in propias:
                p.pop(tema)
        else:
            # La respuesta del comercio tiene prioridad sobre las palabras genéricas de
            # productos, catálogo y pedidos: «precio mayorista», «¿venden por mayor?»,
            # «¿puedo pasar a buscar el pedido?». Un pedido concreto («mi compra», «número
            # de pedido») se deriva igual.
            # Lo mismo con un envío que solo surge de palabras débiles: «¿cuántos días tengo para
            # devolver algo?» pregunta por los cambios, no por el plazo de entrega.
            for tema in (PRODUCTOS, CATALOGO, PEDIDOS, ENVIO):
                if p.get(tema, 0) < PESO_FUERTE:
                    p.pop(tema, None)

    # Absorciones dentro de la oración.
    if p.get(PAGOS_INFORMADOS, 0) >= UMBRAL_TEMA:
        p.pop(MEDIOS_PAGO, None)
    if p.get(RECLAMOS, 0) >= UMBRAL_TEMA:
        for tema in (PEDIDOS, PRODUCTOS, CATALOGO, MEDIOS_PAGO, CONTACTO):
            p.pop(tema, None)
    if p.get(PEDIDOS, 0) >= UMBRAL_TEMA:
        for tema in (PRODUCTOS, CATALOGO, CONTACTO):
            p.pop(tema, None)
    if p.get(ENVIO, 0) >= UMBRAL_TEMA and p.get(HORARIOS, 0) <= p.get(ENVIO, 0):
        # «¿a qué hora llega el envío?», «¿llegan los sábados?»: es una consulta de envío.
        p.pop(HORARIOS, None)

    fuertes = [t for t, v in p.items() if v >= UMBRAL_TEMA]
    if fuertes:
        return sorted(fuertes, key=lambda t: (-p[t], _orden(t))), False
    debiles = [t for t, v in p.items() if v >= UMBRAL_TEMA_DEBIL]
    if not debiles:
        return [], False
    return [max(debiles, key=lambda t: (p[t], -_orden(t)))], True


def _dividir(texto: str) -> list[tuple[str, bool]]:
    """Oraciones del mensaje con una marca de si son preguntas."""
    partes: list[tuple[str, bool]] = []
    posicion = 0
    for separador in _SEPARADOR_ORACIONES.finditer(texto):
        fragmento = texto[posicion : separador.start()]
        if fragmento.strip():
            pregunta = "?" in separador.group() or "¿" in fragmento
            partes.append((fragmento, pregunta))
        posicion = separador.end()
    resto = texto[posicion:]
    if resto.strip():
        partes.append((resto, "¿" in resto))
    return partes or [(texto, "?" in texto)]


def _solo_precio(oracion: Oracion) -> bool:
    """La oración pregunta un precio sin nombrar un producto («¿y cuánto sale?»)."""
    productos = [c for c in oracion.coincidencias if c.entrada.intencion == PRODUCTOS]
    return oracion.temas == [PRODUCTOS] and bool(productos) and all(c.termino in lexico.PRECIO for c in productos)


def _parece_pregunta(oracion: Oracion) -> bool:
    if oracion.es_pregunta:
        return True
    return bool(oracion.tokens) and oracion.tokens[0] in lexico.INTERROGATIVOS


_CONCEPTOS_PAGO = {
    "mercado_pago": {"mercado pago"},
    "modo": {"modo", "con modo", "por modo"},
    "uala": {"uala"},
    "cuenta_dni": {"cuenta dni"},
    "billetera": {"billetera", "billeteras", "billetera virtual", "qr"},
    "transferencia": {
        "transferencia",
        "transferencias",
        "transferir",
        "transfiero",
        "transferirte",
        "transferencia bancaria",
        "alias",
        "cbu",
        "cvu",
    },
    "credito": {"credito"},
    "debito": {"debito"},
    "tarjeta": {"tarjeta", "tarjetas"},
    "cuotas": {"cuotas", "cuota", "sin interes"},
    "efectivo": {"efectivo", "pago en efectivo"},
    "visa": {"visa"},
    "mastercard": {"mastercard", "master"},
    "amex": {"amex", "american express"},
    "naranja": {"naranja", "tarjeta naranja"},
    "cabal": {"cabal"},
    "maestro": {"maestro"},
    "rapipago": {"rapipago"},
    "pago_facil": {"pago facil", "pagofacil"},
    "dolares": {"dolares", "dolar", "usd", "en dolares", "en dolar", "tipo de cambio"},
    "contra_entrega": {"contra entrega", "pago contra entrega", "contrareembolso", "contra reembolso"},
    "link_pago": {"link de pago"},
    "cripto": {"bitcoin", "cripto", "criptomonedas", "usdt"},
}
_DIAS = {
    "lunes": "0",
    "martes": "1",
    "miercoles": "2",
    "jueves": "3",
    "viernes": "4",
    "sabado": "5",
    "sabados": "5",
    "domingo": "6",
    "domingos": "6",
}


def _dias_consultados(tokens: list[str]) -> list[str]:
    dias: list[str] = []
    for i, token in enumerate(tokens):
        valor = _DIAS.get(token)
        if token == "hoy":
            valor = "hoy"
        elif token == "mañana" and not (i > 0 and tokens[i - 1] in {"la", "las", "a"}):
            valor = "mañana"
        elif token in {"feriado", "feriados"}:
            valor = "feriado"
        elif token == "ahora":
            valor = "ahora"
        elif token == "fin" and tokens[i + 1 : i + 3] == ["de", "semana"]:
            dias += ["5", "6"]
            continue
        if valor and valor not in dias:
            dias.append(valor)
    return dias


def interpretar(
    texto: str,
    catalogo: Iterable,
    esperando_cp: bool = False,
    ultimo_tema: str | None = None,
    respuestas: Iterable = (),
) -> Interpretacion:
    """Analiza un mensaje y devuelve sus temas, intenciones de control y datos extraídos.

    ``respuestas`` son las respuestas propias del comercio (``RespuestaDatos``).
    """
    lex = lexico_para(catalogo, respuestas)
    texto = (texto or "")[:LARGO_MAXIMO_ANALISIS]
    oraciones = [_analizar_oracion(fragmento, pregunta, lex) for fragmento, pregunta in _dividir(texto)]
    for oracion in oraciones:
        oracion.es_pregunta = _parece_pregunta(oracion)

    tokens = [t for o in oraciones for t in o.tokens]
    hay_tema_firme = any(o.temas and not o.tema_debil for o in oraciones)
    temas: list[str] = []
    for oracion in oraciones:
        if oracion.tema_debil and hay_tema_firme:
            continue
        for tema in oracion.temas:
            if tema not in temas:
                temas.append(tema)

    control: list[str] = []
    for oracion in oraciones:
        for intencion, peso in sorted(oracion.control.items(), key=lambda x: -x[1]):
            # Las intenciones de control débiles («sí», «nada», «consulta») solo cuentan si
            # la oración no dice nada más.
            fuerte = peso >= PESO_FUERTE or not oracion.contenido or intencion in {SALUDO, CORTESIA, DESPEDIDA}
            if fuerte and intencion not in control:
                control.append(intencion)

    # Opción numérica del menú («1», «opción 2»).
    opcion = None
    numericos = [t for t in tokens if t not in {"opcion", "la", "el", "numero", "quiero", "elijo", "la opcion"}]
    if len(numericos) == 1 and numericos[0] in OPCIONES_MENU:
        opcion = OPCIONES_MENU[numericos[0]]

    # Código postal y localidades.
    codigos = extraer_codigos_postales(texto)
    solo_cp = es_solo_codigo_postal(texto)
    contexto_envio = ENVIO in temas or esperando_cp or (ultimo_tema == ENVIO and len(tokens) <= 6)
    localidades = buscar_localidades(tokens, solo_inequivocas=not contexto_envio)
    contenido = [t for o in oraciones for t in o.contenido]
    if localidades and not contexto_envio:
        # Una localidad sola («¿y a Mendoza?») es una consulta de envío; dentro de otra
        # frase («soy de Mendoza y quiero el mantel») no alcanza.
        palabras_localidad = {t for loc in localidades for t in loc.texto.split()}
        resto = [t for t in contenido if t not in palabras_localidad]
        if temas or resto:
            localidades = []
    if codigos and ENVIO not in temas:
        pista_cp = any(t in {"cp", "codigo", "postal"} for t in tokens)
        if solo_cp or esperando_cp or pista_cp or not temas or ultimo_tema == ENVIO:
            temas.insert(0, ENVIO)
        else:
            codigos = []
    if localidades and ENVIO not in temas:
        temas.insert(0, ENVIO)

    # Absorciones en todo el mensaje.
    # «Ya pagué, ¿cuándo lo mandan?» y «hice una compra y no me llegó» hablan de un mismo
    # pedido: queda el tema más importante (reclamo, pago informado o pedido).
    del_pedido = [t for t in temas if t in (RECLAMOS, PAGOS_INFORMADOS, PEDIDOS)]
    for tema in sorted(del_pedido, key=PRIORIDAD.index)[1:]:
        temas.remove(tema)
    if ENVIO in temas and not (codigos or localidades) and del_pedido:
        temas.remove(ENVIO)
    if PRODUCTOS in temas and CATALOGO in temas:
        temas.remove(CATALOGO)
    pide_precio = any(o.pide_precio for o in oraciones)
    pide_costo = ENVIO in temas and pide_precio
    # Una oración que solo pregunta un precio («¿cuánto sale?») en un mensaje que habla de
    # envíos, o justo después de una respuesta de envío, pregunta el costo del envío:
    # «¿Mandan a Ushuaia? ¿Cuánto sale?», «¿y cuánto sale? ¿aceptan MP?».
    solo_precio = [o for o in oraciones if _solo_precio(o)]
    if solo_precio and (ENVIO in temas or ultimo_tema == ENVIO):
        otras_con_productos = any(PRODUCTOS in o.temas for o in oraciones if o not in solo_precio)
        if PRODUCTOS in temas and not otras_con_productos:
            temas.remove(PRODUCTOS)
        if ENVIO not in temas:
            temas.insert(0, ENVIO)
        pide_costo = True

    terminos: dict[str, list[str]] = {}
    for oracion in oraciones:
        for c in oracion.coincidencias:
            if c.entrada.intencion:
                terminos.setdefault(c.entrada.intencion, []).append(c.termino)

    medios = []
    for c in (c for o in oraciones for c in o.coincidencias if c.entrada.intencion == MEDIOS_PAGO):
        for concepto, frases in _CONCEPTOS_PAGO.items():
            if c.termino in frases and concepto not in medios:
                medios.append(concepto)

    sin_letras = not any(ch.isalnum() for ch in texto)
    solo_simbolos = sin_letras and _tiene_emoji(texto)
    sin_sentido = not temas and not control and not contenido and not codigos and opcion is None
    # Una oración que pregunta algo que no es ningún tema («¿y hacen envoltorio para regalo?»).
    # Las localidades y los números no cuentan: «¿y a Rosario?» completa la consulta de envío.
    # Los saludos y agradecimientos no le quitan a la oración su pregunta («hola, ¿tienen showroom?»),
    # ni las intenciones de control débiles que acompañan contenido («una pregunta: ...»).
    palabras_ubicacion = {t for loc in localidades for t in loc.texto.split()}
    sin_tema = [
        o
        for o in oraciones
        if o.es_pregunta
        and not o.temas
        and not _control_que_responde(o)
        and [t for t in o.contenido if t not in palabras_ubicacion and not t.isdigit()]
    ]
    pregunta_sin_tema = bool(sin_tema)

    return Interpretacion(
        texto=texto,
        oraciones=oraciones,
        temas=temas,
        control=control,
        codigos_postales=codigos,
        localidades=localidades,
        pide_costo=pide_costo,
        medios_consultados=medios,
        dias_consultados=_dias_consultados(tokens),
        es_pregunta=any(o.es_pregunta for o in oraciones),
        contenido=contenido,
        sin_sentido=sin_sentido,
        solo_simbolos=solo_simbolos,
        terminos=terminos,
        pregunta_sin_tema=pregunta_sin_tema,
        solo_codigo_postal=solo_cp,
        opcion_menu=opcion,
        pregunta_directa=any(o.pregunta_directa for o in sin_tema),
    )


_SOCIALES = {SALUDO, CORTESIA, DESPEDIDA}


def _control_que_responde(oracion: Oracion) -> bool:
    """La oración tiene una intención de control que el bot responde por sí misma (pedir una
    persona, el menú, «no sé»...). Los saludos y las intenciones débiles junto a contenido no cuentan."""
    return any(
        intencion not in _SOCIALES and (peso >= PESO_FUERTE or not oracion.contenido)
        for intencion, peso in oracion.control.items()
    )


# ---------------------------------------------------------------------------
# Compatibilidad con la interfaz de la versión 0.1
# ---------------------------------------------------------------------------


@dataclass
class Clasificacion:
    tema: TemaConsulta
    coincidencias: dict[TemaConsulta, list[str]] = field(default_factory=dict)


def detectar_tema(texto: str, catalogo: Iterable) -> Clasificacion:
    """Tema principal del mensaje (CU08, pasos 4 y 5). NO_RECONOCIDO si no hay ninguno."""
    interpretacion = interpretar(texto, catalogo)
    coincidencias = {tema_de(t): interpretacion.terminos.get(t, []) for t in interpretacion.temas}
    if not interpretacion.temas:
        return Clasificacion(TemaConsulta.NO_RECONOCIDO, coincidencias)
    return Clasificacion(tema_de(interpretacion.temas[0]), coincidencias)
