"""Normalización de texto y extracción de datos de los mensajes (CU08, CU09).

Pasos de la normalización (CU08, paso 4):

1. minúsculas, sin tildes ni diéresis (se conserva la ñ) y sin signos de puntuación;
2. las letras repetidas para enfatizar se reducen («holaaa» → «hola», «graciasss» → «gracias»);
3. las abreviaturas de WhatsApp se expanden palabra por palabra («q» → «que», «mp» →
   «mercado pago»; ver ``lexico.ABREVIATURAS``).

La corrección de errores de tipeo contra el vocabulario del bot se hace en
``intencion.py``, que es donde se conoce el catálogo de palabras clave.
"""

from __future__ import annotations

import re
import unicodedata

from .lexico import ABREVIATURAS

_NO_ALFANUMERICO = re.compile(r"[^a-z0-9ñ]+")
_ESPACIOS = re.compile(r"\s+")
# Tres o más letras iguales seguidas: énfasis («holaaa», «siiii»).
_REPETIDAS = re.compile(r"([a-zñ])\1{2,}")
# Vocal duplicada al final de una palabra («holaa», «graciaa»), salvo «ee» («lee», «cree»).
_VOCAL_FINAL_DOBLE = re.compile(r"([aiou])\1\b")

CP_MINIMO = 1000
CP_MAXIMO = 9999


def quitar_tildes(texto: str) -> str:
    """Quita tildes y diéresis, pero conserva la ñ."""
    resultado = []
    for caracter in unicodedata.normalize("NFD", texto):
        if unicodedata.category(caracter) == "Mn":
            # La tilde de la ñ (U+0303) sobre una n se conserva recomponiendo.
            if caracter == "̃" and resultado and resultado[-1] in "nN":
                resultado[-1] = "ñ" if resultado[-1] == "n" else "Ñ"
            continue
        resultado.append(caracter)
    return "".join(resultado)


def _reducir_repeticiones(texto: str) -> str:
    def reemplazo(coincidencia: re.Match) -> str:
        letra = coincidencia.group(1)
        # «ll» y «rr» son dígrafos del español: se dejan dos.
        return letra * 2 if letra in "lr" else letra

    texto = _REPETIDAS.sub(reemplazo, texto)
    return _VOCAL_FINAL_DOBLE.sub(r"\1", texto)


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni signos, sin letras repetidas y con espacios simples (CU08, paso 4)."""
    texto = quitar_tildes((texto or "").lower())
    texto = _NO_ALFANUMERICO.sub(" ", texto)
    texto = _reducir_repeticiones(texto)
    return _ESPACIOS.sub(" ", texto).strip()


def palabras(texto_normalizado: str) -> list[str]:
    return texto_normalizado.split() if texto_normalizado else []


def expandir_abreviaturas(tokens: list[str]) -> list[str]:
    """Reemplaza las abreviaturas habituales («q» → «que», «mp» → «mercado pago»)."""
    resultado: list[str] = []
    for token in tokens:
        expansion = ABREVIATURAS.get(token)
        if expansion:
            resultado.extend(expansion.split())
        else:
            resultado.append(token)
    # «c p» (de «C.P.») equivale a «cp».
    unidos: list[str] = []
    for token in resultado:
        if token == "p" and unidos and unidos[-1] == "c":
            unidos[-1] = "cp"
        else:
            unidos.append(token)
    return unidos


def normalizar_frase(frase: str) -> str:
    """Una frase como la lee el bot: normalizada y con las abreviaturas expandidas
    («x mayor» → «por mayor»). Se usa para las palabras clave de las respuestas propias."""
    return " ".join(expandir_abreviaturas(palabras(normalizar(frase))))


def contiene_termino(texto_normalizado: str, termino: str) -> bool:
    """Coincidencia de palabra o frase completa (evita que «pago» coincida con «pagodas»)."""
    termino = normalizar(termino)
    if not termino:
        return False
    return f" {termino} " in f" {texto_normalizado} "


def distancia_edicion(a: str, b: str, limite: int) -> int:
    """Distancia de Damerau-Levenshtein (con transposición de letras vecinas), acotada.

    Devuelve ``limite + 1`` apenas se sabe que la distancia supera el límite.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limite:
        return limite + 1
    anterior_previa: list[int] | None = None
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        actual = [i] + [0] * len(b)
        minimo = actual[0]
        for j, cb in enumerate(b, start=1):
            costo = 0 if ca == cb else 1
            actual[j] = min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + costo)
            if anterior_previa is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                actual[j] = min(actual[j], anterior_previa[j - 2] + 1)
            minimo = min(minimo, actual[j])
        if minimo > limite:
            return limite + 1
        anterior_previa, anterior = anterior, actual
    return anterior[-1] if anterior[-1] <= limite else limite + 1


# ---------------------------------------------------------------------------
# Código postal (CU09)
# ---------------------------------------------------------------------------

# CPA: letra de provincia (no se usan I, O ni Ñ), 4 dígitos y 3 letras de la manzana.
_CPA = re.compile(r"(?<![a-z0-9])([a-hj-np-z])\s?(\d{4})\s?([a-z]{3})(?![a-z0-9])", re.IGNORECASE)
_PREFIJO_CP = re.compile(r"(?<![a-z])c\.?\s?p\.?\s*(?=\d{4}(?!\d))", re.IGNORECASE)
_PALABRA = re.compile(r"[a-zñ°º#$%]+|\d+", re.IGNORECASE)

# Palabras que, antes del número, indican que no es un código postal («pedido 1234»).
_ANTES_NO_CP = {
    "pedido",
    "orden",
    "nro",
    "numero",
    "num",
    "n",
    "nº",
    "n°",
    "#",
    "factura",
    "comprobante",
    "operacion",
    "transaccion",
    "id",
    "ref",
    "referencia",
    "año",
    "anio",
    "dni",
    "cuit",
    "cuil",
    "tarjeta",
    "seguimiento",
    "clave",
    "pin",
    "codigo de verificacion",
    "verificacion",
    # «enero 2026», «marzo del 2025»: un año, no un código postal.
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "setiembre",
    "octubre",
    "noviembre",
    "diciembre",
}
# Palabras que, después del número, indican un monto, una cantidad o una medida.
_DESPUES_NO_CP = {
    "pesos",
    "peso",
    "pe",
    "mil",
    "ars",
    "usd",
    "dolares",
    "dolar",
    "k",
    "cuotas",
    "unidades",
    "u",
    "metros",
    "mts",
    "m",
    "cm",
    "mm",
    "kg",
    "gr",
    "g",
    "ml",
    "lts",
    "litros",
    "hs",
    "horas",
    "minutos",
    "dias",
    "%",
    "x",
    "veces",
    "mangos",
    "pesitos",
}


def _contexto_palabras(texto: str, inicio: int, fin: int) -> tuple[list[str], list[str]]:
    antes = [p.lower() for p in _PALABRA.findall(quitar_tildes(texto[:inicio]))][-3:]
    despues = [p.lower() for p in _PALABRA.findall(quitar_tildes(texto[fin:]))][:2]
    return antes, despues


def _numero_aislado(texto: str, inicio: int, fin: int) -> bool:
    """El grupo de dígitos no forma parte de un número mayor (teléfono, tarjeta, monto)."""
    izquierda = texto[inicio - 1] if inicio > 0 else " "
    derecha = texto[fin] if fin < len(texto) else " "
    if izquierda.isalnum() or derecha.isalnum():
        return False
    if izquierda in "$#":
        return False
    # «1.500», «351-1234», «12/2025»: separador pegado a otro dígito.
    if izquierda in ".-/,:" and inicio >= 2 and texto[inicio - 2].isdigit():
        return False
    if derecha in ".-/,:" and fin + 1 < len(texto) and texto[fin + 1].isdigit():
        return False
    # «4509 9535 6623 3704», «351 012 3456»: grupos de dígitos separados por espacios.
    previo = texto[:inicio].rstrip()
    if previo and previo[-1].isdigit() and len(texto[:inicio]) - len(previo) <= 2:
        return False
    siguiente = texto[fin:].lstrip()
    if siguiente and siguiente[0].isdigit() and len(texto[fin:]) - len(siguiente) <= 2:
        return False
    # «$ 1500»
    return not previo.endswith("$")


def extraer_codigos_postales(texto: str) -> list[int]:
    """Códigos postales válidos del texto, sin repetir y en orden de aparición.

    Acepta «5800», «CP 5800», «C.P. 5800» y el formato CPA «X5800ABC». Descarta montos
    («$1500», «1500 pesos», «1.500»), teléfonos, números de tarjeta, números de pedido
    («pedido 1234», «#5531») y medidas («1500 metros»).
    """
    if not texto:
        return []
    texto = _PREFIJO_CP.sub(" cp ", texto)
    encontrados: list[tuple[int, int]] = []
    ocupados: list[tuple[int, int]] = []

    for coincidencia in _CPA.finditer(texto):
        valor = int(coincidencia.group(2))
        if CP_MINIMO <= valor <= CP_MAXIMO:
            encontrados.append((coincidencia.start(), valor))
            ocupados.append(coincidencia.span())

    for coincidencia in re.finditer(r"\d+", texto):
        inicio, fin = coincidencia.span()
        if any(a <= inicio < b for a, b in ocupados):
            continue
        digitos = coincidencia.group()
        if len(digitos) != 4 or not _numero_aislado(texto, inicio, fin):
            continue
        valor = int(digitos)
        if not CP_MINIMO <= valor <= CP_MAXIMO:
            continue
        antes, despues = _contexto_palabras(texto, inicio, fin)
        if antes and (antes[-1] in _ANTES_NO_CP or " ".join(antes[-2:]) in _ANTES_NO_CP):
            continue
        if despues and despues[0] in _DESPUES_NO_CP:
            continue
        encontrados.append((inicio, valor))

    resultado: list[int] = []
    for _, valor in sorted(encontrados):
        if valor not in resultado:
            resultado.append(valor)
    return resultado


def extraer_codigo_postal(texto: str) -> int | None:
    """Primer código postal válido del texto o None."""
    codigos = extraer_codigos_postales(texto)
    return codigos[0] if codigos else None


def es_solo_codigo_postal(texto: str) -> bool:
    """El mensaje no tiene más que un código postal («5800», «CP 5800», «el 5000»)."""
    resto = _CPA.sub(" ", texto or "")
    resto = re.sub(r"\d{4}", " ", resto)
    tokens = palabras(normalizar(resto))
    return bool(extraer_codigos_postales(texto)) and all(
        t in {"cp", "c", "p", "el", "al", "es", "mi", "codigo", "postal", "y", "para", "a", "de", "o", "en"}
        for t in tokens
    )


# ---------------------------------------------------------------------------
# Código de acceso del comercio y texto del enlace (CU08)
# ---------------------------------------------------------------------------

_TOKEN_CODIGO = re.compile(r"#?\b([A-Za-z0-9]{6})\b")


def candidatos_codigo(texto: str) -> list[str]:
    """Posibles códigos de acceso presentes en el texto (seis caracteres alfanuméricos
    con al menos una letra y un dígito). La validación final se hace contra la base."""
    candidatos = []
    for coincidencia in _TOKEN_CODIGO.finditer(texto or ""):
        token = coincidencia.group(1).upper()
        if any(c.isdigit() for c in token) and any(c.isalpha() for c in token):
            candidatos.append(token)
    return candidatos


def quitar_texto(texto: str, fragmento: str) -> str:
    """Elimina un fragmento sin distinguir mayúsculas (se usa para sacar el código o el nombre)."""
    if not fragmento:
        return texto
    return re.sub(re.escape(fragmento), " ", texto, flags=re.IGNORECASE)


def limpiar_texto_enlace(texto: str, codigo: str, nombre: str | None = None) -> str:
    """Quita del mensaje el texto que precarga el enlace de acceso y el código del comercio.

    El enlace precarga «Hola, quiero hacer una consulta a {nombre}. Código: {código}». Se
    quita completo aunque el nombre del comercio haya cambiado desde que se compartió el
    enlace, y lo que el comprador agregue antes o después se conserva como consulta.
    """
    if not texto:
        return ""
    plantilla = re.compile(
        r"(?:hola[\s,.!¡]*)?quiero hacer una consulta a\b.*?c[oó]digo\s*:?\s*#?" + re.escape(codigo) + r"\b",
        re.IGNORECASE | re.DOTALL,
    )
    resultado = plantilla.sub(" ", texto, count=1)
    if resultado == texto:
        resultado = re.sub(r"c[oó]digo\s*:?\s*#?" + re.escape(codigo) + r"\b", " ", resultado, flags=re.IGNORECASE)
        resultado = quitar_texto(quitar_texto(resultado, f"#{codigo}"), codigo)
        resultado = re.sub(r"quiero hacer una consulta a\b", " ", resultado, flags=re.IGNORECASE)
    if nombre:
        resultado = quitar_texto(resultado, nombre)
    resultado = _ESPACIOS.sub(" ", resultado).strip()
    return resultado.strip(" .,;:-")
