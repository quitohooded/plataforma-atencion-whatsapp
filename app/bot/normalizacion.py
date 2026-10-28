"""Normalización de texto y extracción de datos de los mensajes (CU08, CU09)."""

from __future__ import annotations

import re
import unicodedata

_NO_ALFANUMERICO = re.compile(r"[^a-z0-9ñ]+")
_ESPACIOS = re.compile(r"\s+")

# Código postal argentino: 4 dígitos (formato clásico) o CPA de 8 caracteres (X5000ABC).
_CPA = re.compile(r"\b[a-z](\d{4})[a-z]{3}\b", re.IGNORECASE)
_CP_4_DIGITOS = re.compile(r"(?<![\d$.,])(\d{4})(?![\d.,])")
_MONTO_DESPUES = re.compile(r"^\s*(pesos|mil|\$|ars|usd|dolares|dólares)", re.IGNORECASE)

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


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes ni signos de puntuación y con espacios simples (CU08, paso 4)."""
    texto = quitar_tildes((texto or "").lower())
    texto = _NO_ALFANUMERICO.sub(" ", texto)
    return _ESPACIOS.sub(" ", texto).strip()


def contiene_termino(texto_normalizado: str, termino: str) -> bool:
    """Coincidencia de palabra o frase completa (evita que «pago» coincida con «pagodas»)."""
    termino = normalizar(termino)
    if not termino:
        return False
    return f" {termino} " in f" {texto_normalizado} "


def palabras(texto_normalizado: str) -> list[str]:
    return texto_normalizado.split() if texto_normalizado else []


def extraer_codigo_postal(texto: str) -> int | None:
    """Devuelve el primer código postal válido del texto o None.

    Acepta «5800», «CP 5800», «X5800ABC». Descarta montos («$1500», «1500 pesos»).
    """
    if not texto:
        return None
    coincidencia = _CPA.search(texto)
    if coincidencia:
        valor = int(coincidencia.group(1))
        if CP_MINIMO <= valor <= CP_MAXIMO:
            return valor
    for coincidencia in _CP_4_DIGITOS.finditer(texto):
        if _MONTO_DESPUES.match(texto[coincidencia.end() :]):
            continue
        valor = int(coincidencia.group(1))
        if CP_MINIMO <= valor <= CP_MAXIMO:
            return valor
    return None


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
