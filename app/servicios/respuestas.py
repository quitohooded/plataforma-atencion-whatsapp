"""Respuestas propias del comercio a preguntas frecuentes (CU15).

El comercio escribe una respuesta fija y las palabras clave con las que el bot la
reconoce. Las palabras se validan para que no le quiten al bot lo que ya resuelve con los
datos cargados (envíos, pagos, horarios, contacto) ni lo que tiene que ver una persona
(reclamos y pagos informados).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, select, update

from ..bot import lexico
from ..bot.ciudades import LOCALIDADES
from ..bot.contexto import RespuestaDatos
from ..bot.intencion import terminos_conversacionales
from ..bot.normalizacion import contiene_termino, normalizar, normalizar_frase
from ..datos.plantillas_respuestas import PLANTILLAS, POR_CLAVE, Plantilla
from ..extensiones import db
from ..modelos import (
    Comercio,
    Consulta,
    Conversacion,
    DireccionMensaje,
    Mensaje,
    PalabraClave,
    RespuestaFrecuente,
    ResultadoConsulta,
    TemaConsulta,
)
from ..utilidades import tiempo
from . import ErrorValidacion

LARGO_TITULO = 60
LARGO_RESPUESTA = 800
MAX_PALABRAS = 20
MAX_PALABRAS_POR_FRASE = 5
MAX_RESPUESTAS = 30
DIAS_METRICA = 30

# Temas cuyas palabras no puede usar una respuesta propia y por qué.
TEMAS_PROTEGIDOS = {
    TemaConsulta.ENVIO: "para responder sobre envíos con las zonas que usted cargó",
    TemaConsulta.MEDIOS_PAGO: "para responder sobre medios de pago",
    TemaConsulta.HORARIOS: "para responder sobre horarios",
    TemaConsulta.CONTACTO: "para compartir su contacto",
    TemaConsulta.RECLAMOS: "para pasarle los reclamos a una persona",
    TemaConsulta.PAGOS_INFORMADOS: "para avisarle de los pagos que informan los compradores",
}

# Sitios compartidos por muchas cuentas: el enlace tiene que ser de la cuenta del comercio.
_SITIOS_COMPARTIDOS = {"instagram.com", "facebook.com", "tiktok.com", "wa.me", "linktr.ee", "x.com", "twitter.com"}
_ENLACE = re.compile(
    r"(?<![@\w.])((?:https?://|www\.)[^\s]+|(?:[a-z0-9-]+\.)+(?:com|net|org|ar|io|me|ly|link|shop|store|app|site|"
    r"online|info|tienda)(?:\.ar)?(?:/[^\s]*)?)",
    re.IGNORECASE,
)


@dataclass
class Borrador:
    """Datos del formulario ya validados. Las palabras clave quedan como las escribió el
    comercio: el bot las compara normalizadas (``normalizar_frase``)."""

    titulo: str
    palabras: list[str]
    respuesta: str
    plantilla: str | None = None


@dataclass
class Sugerencia:
    plantilla: Plantilla
    cantidad: int
    ejemplo: str


@dataclass
class EstadoFormulario:
    valores: dict = field(default_factory=dict)
    error: str | None = None
    campos: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------


_SIGNOS_EXTREMOS = "¿?¡!.,;:\"'«»“”()[] \t"


def separar_palabras(texto: str) -> list[str]:
    """Frases separadas por comas, punto y coma o renglones, como las escribió el comercio
    (sin signos en los extremos ni espacios de más) y sin repetir."""
    vistas: list[str] = []
    for parte in re.split(r"[,;\n]+", texto or ""):
        frase = " ".join(parte.strip(_SIGNOS_EXTREMOS).split())
        if frase and frase not in vistas:
            vistas.append(frase)
    return vistas


def _terminos_protegidos() -> dict[str, TemaConsulta]:
    filas = db.session.execute(
        select(PalabraClave.termino, PalabraClave.tema).where(PalabraClave.tema.in_(list(TEMAS_PROTEGIDOS)))
    ).all()
    return dict(filas)


def _validar_frase(original: str, frase: str, protegidos: dict[str, TemaConsulta], conversacion: set[str]) -> None:
    tokens = frase.split()
    if not any(c.isalpha() for c in frase):
        raise ErrorValidacion(f"«{original}» no es una palabra clave válida: tiene que tener letras.", ["palabras"])
    if len(frase.replace(" ", "")) < 3:
        raise ErrorValidacion(f"«{original}» es muy corta: use palabras de al menos 3 letras.", ["palabras"])
    if len(tokens) > MAX_PALABRAS_POR_FRASE or len(frase) > 40:
        raise ErrorValidacion(
            f"«{original}» es muy larga: use frases cortas, de hasta {MAX_PALABRAS_POR_FRASE} palabras.", ["palabras"]
        )
    if frase in conversacion:
        raise ErrorValidacion(
            f"«{original}» la usa el bot para conversar (saludos, agradecimientos o pedir una persona). Elija otra.",
            ["palabras"],
        )
    if all(t in lexico.VACIAS or t in lexico.INTERROGATIVOS for t in tokens):
        raise ErrorValidacion(
            f"«{original}» es demasiado general: el bot la encontraría en casi cualquier mensaje.", ["palabras"]
        )
    if frase in lexico.PRECIO:
        raise ErrorValidacion(
            f"«{original}» la usa el bot para entender preguntas de precio y de costo del envío. Elija otra.",
            ["palabras"],
        )
    tema = protegidos.get(frase)
    if tema is not None:
        raise ErrorValidacion(f"«{original}» ya la usa el bot {TEMAS_PROTEGIDOS[tema]}. Elija otra.", ["palabras"])
    if frase in LOCALIDADES:
        raise ErrorValidacion(
            f"«{original}» es el nombre de una localidad: el bot lo usa para calcular envíos. Elija otra.",
            ["palabras"],
        )


def _validar_enlaces(comercio: Comercio, texto: str) -> None:
    enlaces = _ENLACE.findall(texto)
    if not enlaces:
        return
    catalogo = urlparse(comercio.enlace_catalogo or "")
    host_catalogo = (catalogo.hostname or "").removeprefix("www.")
    cuenta_catalogo = catalogo.path.strip("/").split("/")[0].lower() if catalogo.path else ""
    for enlace in enlaces:
        completo = enlace if re.match(r"https?://", enlace, re.IGNORECASE) else "https://" + enlace
        destino = urlparse(completo)
        host = (destino.hostname or "").lower().removeprefix("www.")
        cuenta = destino.path.strip("/").split("/")[0].lower() if destino.path else ""
        permitido = bool(host_catalogo) and host == host_catalogo
        if permitido and host in _SITIOS_COMPARTIDOS:
            permitido = cuenta == cuenta_catalogo
        if not permitido:
            if host_catalogo:
                raise ErrorValidacion(
                    f"La respuesta solo puede incluir enlaces a su catálogo ({comercio.enlace_catalogo}). Así los "
                    "compradores no reciben enlaces de otros sitios desde la línea de la plataforma.",
                    ["respuesta"],
                )
            raise ErrorValidacion(
                "La respuesta no puede incluir enlaces. Para compartir su catálogo, cárguelo en Datos del negocio y "
                "el bot lo envía cuando se lo piden.",
                ["respuesta"],
            )


def _limpiar_texto(texto: str) -> str:
    texto = "".join(c for c in (texto or "") if c in "\n\t" or c.isprintable())
    texto = re.sub(r"[ \t]+\n", "\n", texto.replace("\r\n", "\n").replace("\r", "\n"))
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def validar(
    comercio: Comercio,
    titulo: str,
    palabras_texto: str,
    respuesta: str,
    plantilla: str | None = None,
    excluir: RespuestaFrecuente | None = None,
) -> Borrador:
    titulo = " ".join((titulo or "").split())
    respuesta = _limpiar_texto(respuesta)
    plantilla = plantilla if plantilla in POR_CLAVE else None

    if not titulo:
        raise ErrorValidacion("Indique un título, por ejemplo «Cambios y devoluciones».", ["titulo"])
    if len(titulo) > LARGO_TITULO:
        raise ErrorValidacion(f"El título admite hasta {LARGO_TITULO} caracteres.", ["titulo"])
    otras = [r for r in comercio.respuestas_frecuentes if excluir is None or r.id_respuesta != excluir.id_respuesta]
    if any(normalizar(r.titulo) == normalizar(titulo) for r in otras):
        raise ErrorValidacion("Ya tiene una respuesta con ese título.", ["titulo"])

    originales = separar_palabras(palabras_texto)
    if not originales:
        raise ErrorValidacion("Indique al menos una palabra clave. Sepárelas con comas.", ["palabras"])
    if len(originales) > MAX_PALABRAS:
        raise ErrorValidacion(f"Use hasta {MAX_PALABRAS} palabras clave por respuesta.", ["palabras"])
    protegidos = _terminos_protegidos()
    conversacion = terminos_conversacionales()
    de_otras = {normalizar_frase(p): r.titulo for r in otras for p in r.lista_palabras}
    # Se guardan como las escribió el comercio; la comparación es como las lee el bot.
    frases: list[str] = []
    vistas: set[str] = set()
    for original in originales:
        frase = normalizar_frase(original)
        _validar_frase(original, frase, protegidos, conversacion)
        if frase in de_otras:
            raise ErrorValidacion(f"«{original}» ya está en la respuesta «{de_otras[frase]}».", ["palabras"])
        if frase not in vistas:
            vistas.add(frase)
            frases.append(original)

    if not respuesta:
        raise ErrorValidacion("Escriba la respuesta que va a enviar el bot.", ["respuesta"])
    if len(respuesta) > LARGO_RESPUESTA:
        raise ErrorValidacion(f"La respuesta admite hasta {LARGO_RESPUESTA} caracteres.", ["respuesta"])
    _validar_enlaces(comercio, respuesta)
    return Borrador(titulo, frases, respuesta, plantilla)


# ---------------------------------------------------------------------------
# Altas, cambios y bajas
# ---------------------------------------------------------------------------


def crear(
    comercio: Comercio, titulo: str, palabras_texto: str, respuesta: str, plantilla: str | None = None
) -> RespuestaFrecuente:
    if len(comercio.respuestas_frecuentes) >= MAX_RESPUESTAS:
        raise ErrorValidacion(f"Se admiten hasta {MAX_RESPUESTAS} respuestas por comercio.")
    borrador = validar(comercio, titulo, palabras_texto, respuesta, plantilla)
    if borrador.plantilla and any(r.plantilla == borrador.plantilla for r in comercio.respuestas_frecuentes):
        # Una plantilla se usa una vez; la segunda respuesta parecida queda como propia.
        borrador.plantilla = None
    nueva = RespuestaFrecuente(
        comercio=comercio,
        plantilla=borrador.plantilla,
        titulo=borrador.titulo,
        palabras_clave=", ".join(borrador.palabras),
        respuesta=borrador.respuesta,
        activa=True,
        fecha_alta=tiempo.ahora(),
    )
    db.session.add(nueva)
    db.session.commit()
    return nueva


def actualizar(
    comercio: Comercio, respuesta_frecuente: RespuestaFrecuente, titulo: str, palabras_texto: str, respuesta: str
) -> RespuestaFrecuente:
    borrador = validar(comercio, titulo, palabras_texto, respuesta, excluir=respuesta_frecuente)
    respuesta_frecuente.titulo = borrador.titulo
    respuesta_frecuente.palabras_clave = ", ".join(borrador.palabras)
    respuesta_frecuente.respuesta = borrador.respuesta
    db.session.commit()
    return respuesta_frecuente


def cambiar_activa(respuesta_frecuente: RespuestaFrecuente, activa: bool) -> None:
    respuesta_frecuente.activa = activa
    db.session.commit()


def eliminar(respuesta_frecuente: RespuestaFrecuente) -> None:
    """Las consultas que resolvió se conservan en el historial, sin el vínculo a la respuesta."""
    db.session.execute(
        update(Consulta)
        .where(Consulta.id_respuesta == respuesta_frecuente.id_respuesta)
        .values(id_respuesta=None)
        .execution_options(synchronize_session="fetch")
    )
    db.session.delete(respuesta_frecuente)
    db.session.commit()


def valores_de_plantilla(clave: str | None) -> dict:
    plantilla = POR_CLAVE.get(clave or "")
    if plantilla is None:
        return {"titulo": "", "palabras": "", "respuesta": "", "plantilla": ""}
    return {
        "titulo": plantilla.titulo,
        "palabras": ", ".join(plantilla.palabras),
        "respuesta": plantilla.respuesta,
        "plantilla": plantilla.clave,
    }


def valores_de(respuesta_frecuente: RespuestaFrecuente) -> dict:
    return {
        "titulo": respuesta_frecuente.titulo,
        "palabras": ", ".join(respuesta_frecuente.lista_palabras),
        "respuesta": respuesta_frecuente.respuesta,
        "plantilla": respuesta_frecuente.plantilla or "",
    }


def plantillas_disponibles(comercio: Comercio) -> list[Plantilla]:
    usadas = {r.plantilla for r in comercio.respuestas_frecuentes if r.plantilla}
    return [p for p in PLANTILLAS if p.clave not in usadas]


def como_datos(borrador: Borrador, clave: str, id_respuesta: int | None = None) -> RespuestaDatos:
    return RespuestaDatos.con_frases(clave, borrador.titulo, borrador.palabras, borrador.respuesta, id_respuesta)


# ---------------------------------------------------------------------------
# Uso y sugerencias
# ---------------------------------------------------------------------------


def _desde(dias: int) -> datetime:
    return tiempo.ahora() - timedelta(days=dias)


def usos(comercio: Comercio, dias: int = DIAS_METRICA) -> dict[int, int]:
    """Consultas resueltas con cada respuesta en los últimos ``dias`` días."""
    filas = db.session.execute(
        select(Consulta.id_respuesta, func.count(Consulta.id_consulta))
        .join(Conversacion)
        .where(
            Conversacion.id_comercio == comercio.id_comercio,
            Consulta.tema == TemaConsulta.RESPUESTA_PROPIA,
            Consulta.id_respuesta.is_not(None),
            Consulta.fecha_hora >= _desde(dias),
        )
        .group_by(Consulta.id_respuesta)
    ).all()
    return dict(filas)


def sugerencias(comercio: Comercio, dias: int = DIAS_METRICA) -> list[Sugerencia]:
    """Plantillas que todavía no usa y que habrían respondido consultas derivadas recientes.

    Se buscan las palabras de cada plantilla en el mensaje que originó cada derivación (el
    mensaje entrante del mismo momento). Los reclamos y los pagos informados no cuentan:
    esos siempre los tiene que ver una persona.
    """
    disponibles = plantillas_disponibles(comercio)
    if not disponibles:
        return []
    filas = db.session.execute(
        select(Mensaje.texto)
        .select_from(Consulta)
        .join(Conversacion, Consulta.id_conversacion == Conversacion.id_conversacion)
        .join(
            Mensaje,
            (Mensaje.id_conversacion == Consulta.id_conversacion)
            & (Mensaje.fecha_hora == Consulta.fecha_hora)
            & (Mensaje.direccion == DireccionMensaje.ENTRANTE),
        )
        .where(
            Conversacion.id_comercio == comercio.id_comercio,
            Consulta.resultado == ResultadoConsulta.DERIVADA,
            Consulta.tema.not_in([TemaConsulta.RECLAMOS, TemaConsulta.PAGOS_INFORMADOS]),
            Consulta.fecha_hora >= _desde(dias),
        )
        .order_by(Consulta.fecha_hora.desc())
    ).all()
    textos = [texto for (texto,) in filas if texto]
    resultado = []
    for plantilla in disponibles:
        frases = [normalizar_frase(p) for p in plantilla.palabras]
        coincidentes = [t for t in textos if any(contiene_termino(normalizar_frase(t), f) for f in frases)]
        if coincidentes:
            ejemplo = coincidentes[0] if len(coincidentes[0]) <= 90 else coincidentes[0][:87].rstrip() + "…"
            resultado.append(Sugerencia(plantilla, len(coincidentes), ejemplo))
    return sorted(resultado, key=lambda s: -s.cantidad)
