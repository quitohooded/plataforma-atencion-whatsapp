"""Seguridad de la conversación: datos sensibles, estafas y abuso del canal (#6, #7).

Funciones puras, como el resto del bot. ``ocultar`` se aplica a cada mensaje antes de
guardarlo: los datos de tarjeta, los códigos de seguridad y las claves no quedan en la
base. ``analizar`` le dice al motor qué riesgo trae el mensaje para que responda primero
con la advertencia que corresponde.

Los riesgos salen del modelo de amenazas de la revisión por perfiles: estafas contra el
comprador que usan el nombre del comercio (alias, teléfonos o códigos falsos), estafas
contra el comercio (devoluciones a otra cuenta), filtración de datos (tarjetas, claves,
pedidos de datos de otros clientes) y abuso del canal (spam, insultos).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .normalizacion import expandir_abreviaturas, normalizar, palabras

OCULTO = "•••"

# ---------------------------------------------------------------------------
# Números: tarjetas, CBU y teléfonos
# ---------------------------------------------------------------------------

# Una corrida de dígitos con separadores habituales (espacios, guiones, puntos, paréntesis).
_GRUPO_NUMERICO = re.compile(r"\+?\d[\d \-().]*\d")


def _digitos(texto: str) -> str:
    return "".join(c for c in texto if c.isdigit())


def luhn(numero: str) -> bool:
    """Dígito verificador de las tarjetas de pago (algoritmo de Luhn)."""
    suma = 0
    for posicion, caracter in enumerate(reversed(numero)):
        valor = int(caracter)
        if posicion % 2 == 1:
            valor *= 2
            if valor > 9:
                valor -= 9
        suma += valor
    return suma % 10 == 0


def es_tarjeta(numero: str) -> bool:
    """Número de tarjeta plausible: Luhn y largo según la marca (16 la mayoría, 15 American
    Express, 13 o 19 algunas Visa). Así un teléfono con 54 9 no se confunde con una tarjeta."""
    if not numero.isdigit() or not luhn(numero):
        return False
    largo = len(numero)
    return largo == 16 or (largo == 15 and numero[:2] in {"34", "37"}) or (largo in {13, 19} and numero[0] == "4")


@dataclass(frozen=True)
class Numero:
    texto: str  # como se escribió
    digitos: str
    inicio: int
    fin: int


def numeros(texto: str) -> list[Numero]:
    resultado = []
    for m in _GRUPO_NUMERICO.finditer(texto or ""):
        bruto = m.group().strip(" -().")
        if not bruto:
            continue
        inicio = m.start() + m.group().index(bruto)
        resultado.append(Numero(bruto, _digitos(bruto), inicio, inicio + len(bruto)))
    return resultado


_BLOQUE = re.compile(r"\d+")


def tarjetas(texto: str) -> list[Numero]:
    """Números de tarjeta, aunque estén pegados a otro número («4509-9535-6623-3704 12/28»):
    se prueban las secuencias de bloques de dígitos de cada grupo."""
    encontradas: list[Numero] = []
    for grupo in numeros(texto):
        bloques = [(m.start() + grupo.inicio, m.end() + grupo.inicio) for m in _BLOQUE.finditer(grupo.texto)]
        i = 0
        while i < len(bloques):
            for j in range(len(bloques), i, -1):
                inicio, fin = bloques[i][0], bloques[j - 1][1]
                digitos = _digitos(texto[inicio:fin])
                if 13 <= len(digitos) <= 19 and es_tarjeta(digitos):
                    encontradas.append(Numero(texto[inicio:fin], digitos, inicio, fin))
                    i = j - 1
                    break
            i += 1
    return encontradas


def es_cbu(digitos: str) -> bool:
    return len(digitos) == 22


def telefono_comparable(digitos: str) -> str:
    """Últimos 8 dígitos: alcanzan para comparar un número argentino escrito con o sin 54, 9,
    0, característica o 15."""
    return digitos[-8:]


# Palabras antes de un número que indican que no es un teléfono.
_NO_TELEFONO = {"dni", "cuit", "cuil", "pedido", "orden", "factura", "compra", "nro", "n", "numero de pedido", "cp"}


def telefonos(texto: str) -> list[Numero]:
    """Números de 8 a 13 dígitos que pueden ser un teléfono (no tarjetas, CBU ni documentos)."""
    resultado = []
    for n in numeros(texto):
        if not 8 <= len(n.digitos) <= 13 or es_tarjeta(n.digitos):
            continue
        anterior = palabras(normalizar(texto[max(0, n.inicio - 25) : n.inicio]))[-3:]
        if set(anterior) & _NO_TELEFONO:
            continue
        resultado.append(n)
    return resultado


# ---------------------------------------------------------------------------
# Alias de transferencia
# ---------------------------------------------------------------------------

# Alias con puntos o guiones («casa.detalles.demo», «juan-perez»); se descartan los dominios web.
_ALIAS_CON_PUNTOS = re.compile(r"(?<![\w@./])([a-z0-9]+(?:[.-][a-z0-9]+){1,4})(?![\w@/])", re.IGNORECASE)
# Después de la palabra «alias»: «alias CASADETALLES», «alias: casa.detalles».
_ALIAS_DESPUES_DE_LA_PALABRA = re.compile(
    r"\balias\s*(?:es|:|=)?\s*[:=]?\s*([a-z0-9][a-z0-9.\-]{4,19})(?![\w@])", re.IGNORECASE
)
# Un alias precedido por «mi» es del comprador («mi alias es juan.perez.mp»), no uno que le pasaron.
_PROPIO_DEL_COMPRADOR = re.compile(r"\bmis?\s+(?:alias|cbu|cvu|cuenta)\b[^.?!\n]{0,12}$", re.IGNORECASE)
_DOMINIOS = {
    "com",
    "ar",
    "net",
    "org",
    "ly",
    "xyz",
    "io",
    "me",
    "gob",
    "edu",
    "info",
    "site",
    "online",
    "app",
    "link",
    "shop",
    "store",
    "example",
    "co",
    "tk",
    "top",
    "click",
}


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _alias_valido(candidato: str) -> bool:
    candidato = candidato.strip(".-")
    if not 6 <= len(candidato) <= 20:
        return False
    if sum(c.isalpha() for c in candidato) < 3:  # medidas («1.50x2.20») o montos
        return False
    partes = re.split(r"[.-]", candidato)
    return not (candidato.startswith("www.") or partes[-1] in _DOMINIOS)


def alias(texto: str, sin_los_del_comprador: bool = False) -> list[str]:
    """Alias de transferencia mencionados, en minúsculas y sin tildes. Después de la palabra
    «alias» se acepta uno sin puntos solo si tiene números o está en mayúsculas («alias
    CASADETALLES»): «¿a qué alias transfiero?» no menciona ningún alias."""
    limpio = _sin_tildes(texto or "")
    encontrados: list[str] = []

    def agregar(m: re.Match, candidato: str) -> None:
        candidato = candidato.strip(".-")
        if sin_los_del_comprador and _PROPIO_DEL_COMPRADOR.search(limpio[: m.start(1)]):
            return
        if _alias_valido(candidato.lower()) and candidato.lower() not in encontrados:
            encontrados.append(candidato.lower())

    for m in _ALIAS_DESPUES_DE_LA_PALABRA.finditer(limpio):
        candidato = m.group(1)
        marcado = any(c in candidato for c in ".-") or any(c.isdigit() for c in candidato) or candidato.isupper()
        if marcado:
            agregar(m, candidato)
    for m in _ALIAS_CON_PUNTOS.finditer(limpio):
        if any(c in m.group(1) for c in ".-"):
            agregar(m, m.group(1))
    return encontrados


def datos_de_pago(texto: str, sin_los_del_comprador: bool = False) -> set[str]:
    """Alias y CBU o CVU que aparecen en un texto (los del comercio salen de sus medios de pago)."""
    cbu = set()
    for n in numeros(texto):
        if es_cbu(n.digitos) and not (
            sin_los_del_comprador and _PROPIO_DEL_COMPRADOR.search(_sin_tildes(texto[: n.inicio]))
        ):
            cbu.add(n.digitos)
    return set(alias(texto, sin_los_del_comprador)) | cbu


# ---------------------------------------------------------------------------
# Ocultar datos sensibles antes de guardar
# ---------------------------------------------------------------------------

_CVV = re.compile(
    r"\b(cvv|cvc|cod\.? ?seg|c[oó]d(?:igo)? de seguridad|c[oó]digo verificador)\s*[:=]?\s*(?:es\s*)?(\d{3,4})\b",
    re.IGNORECASE,
)
_VENCIMIENTO = re.compile(
    r"\b(vence|venc\.?|vencimiento|vto\.?|exp)\s*[:=]?\s*(\d{1,2}\s*/\s*\d{2,4})\b", re.IGNORECASE
)
_FECHA_CORTA = re.compile(r"(?<![\d/])(0?[1-9]|1[0-2])\s*/\s*(\d{2}|20\d{2})(?![\d/])")
# «Mi contraseña de Mercado Pago es …», «la clave del home banking: …», «PIN 1234». Con un
# calificador («de Mercado Pago»), el separador («es», «:») es obligatorio.
_CALIFICADOR = r"\s+(?:de|del|de la|de mi|para)\s+[a-zñáéíóú ]{2,25}?"
_SEPARADOR = r"\s*(?:es|era|:|=)"
_CLAVE_FUERTE = re.compile(
    r"\b(contrase[ñn]a|password|pin|token|clave fiscal)\b"
    r"(?:" + _CALIFICADOR + _SEPARADOR + r"|" + _SEPARADOR + r"?)\s*[:=]?\s*(\S{3,})",
    re.IGNORECASE,
)
# «Clave» sola es una palabra común («la clave es que llegue rápido»): se oculta si el valor
# tiene números o si dice de qué es la clave.
_CLAVE_DEBIL = re.compile(r"\b(clave)\b(" + _CALIFICADOR + r")?" + _SEPARADOR + r"\s*(\S{3,})", re.IGNORECASE)
# Códigos de verificación de 6 dígitos («123456», «123-456»), no códigos postales ni de pedidos.
_CODIGO_VERIFICACION = re.compile(
    r"\b(c[oó]digo|pin)\b"
    r"(?!\s*(?:postal|de seguimiento|de [aá]rea|del producto|de descuento|de barras|del pedido|"
    r"de (?:mi |la |el |tu )?(?:pedido|compra|orden|env[ií]o|producto|art[ií]culo|cup[oó]n)))"
    r"[^\d\n]{0,25}?(\d{3}[ -]?\d{3})(?![\d-])",
    re.IGNORECASE,
)
_PALABRAS_NO_CLAVE = {"de", "del", "es", "que", "para", "y", "o", "con", "la", "el", "un", "una", "lo"}


@dataclass
class DatosOcultos:
    texto: str
    tarjeta: bool = False
    codigo_seguridad: bool = False
    clave: bool = False
    codigo_verificacion: bool = False

    @property
    def algo(self) -> bool:
        return self.tarjeta or self.codigo_seguridad or self.clave or self.codigo_verificacion


def _reemplazar_grupo(m: re.Match, grupo: int, reemplazo: str) -> str:
    inicio, fin = m.span(grupo)
    return m.group(0)[: inicio - m.start()] + reemplazo + m.group(0)[fin - m.start() :]


def ocultar(texto: str) -> DatosOcultos:
    """Texto con los datos sensibles ocultos: el número de la tarjeta (quedan los últimos 4
    dígitos), el vencimiento y el código de seguridad, las claves y los códigos de
    verificación. Es lo que se guarda en la base y se muestra en el panel."""
    resultado = DatosOcultos(texto or "")
    if not texto:
        return resultado
    nuevo = texto
    encontradas = tarjetas(nuevo)
    for numero in sorted(encontradas, key=lambda n: -n.inicio):
        nuevo = nuevo[: numero.inicio] + f"•••• •••• •••• {numero.digitos[-4:]}" + nuevo[numero.fin :]
    resultado.tarjeta = bool(encontradas)

    def cvv(m: re.Match) -> str:
        resultado.codigo_seguridad = True
        return _reemplazar_grupo(m, 2, OCULTO)

    nuevo = _CVV.sub(cvv, nuevo)
    if resultado.tarjeta or resultado.codigo_seguridad:
        nuevo = _VENCIMIENTO.sub(lambda m: _reemplazar_grupo(m, 2, "••/••"), nuevo)
        if resultado.tarjeta:
            nuevo = _FECHA_CORTA.sub("••/••", nuevo)

    def clave(m: re.Match) -> str:
        if normalizar(m.group(2)) in _PALABRAS_NO_CLAVE:
            return m.group(0)
        resultado.clave = True
        return _reemplazar_grupo(m, 2, OCULTO)

    def clave_debil(m: re.Match) -> str:
        valor = m.group(3)
        if normalizar(valor) in _PALABRAS_NO_CLAVE or not (m.group(2) or any(c.isdigit() for c in valor)):
            return m.group(0)
        resultado.clave = True
        return _reemplazar_grupo(m, 3, OCULTO)

    nuevo = _CLAVE_FUERTE.sub(clave, nuevo)
    nuevo = _CLAVE_DEBIL.sub(clave_debil, nuevo)

    def codigo(m: re.Match) -> str:
        resultado.codigo_verificacion = True
        return _reemplazar_grupo(m, 2, OCULTO)

    nuevo = _CODIGO_VERIFICACION.sub(codigo, nuevo)
    resultado.texto = nuevo
    return resultado


# ---------------------------------------------------------------------------
# Análisis del mensaje
# ---------------------------------------------------------------------------


def _frases(*grupos: str) -> tuple[str, ...]:
    return tuple(f for grupo in grupos for f in grupo.split("|") if f)


_EXCLUSIONES_CODIGO = {
    "postal",
    "seguimiento",
    "descuento",
    "area",
    "producto",
    "articulo",
    "acceso",
    "cupon",
    "barras",
}
_PEDIR = _frases(
    "pasame|pasas|pasarme|me lo pasas|me lo pasarias|mandame|mandas|mandarme|me lo mandas|decime|me decis|",
    "dame|reenviame|reenvias|enviame|me lo envias|compartime|copiame|me lo das|necesito el codigo|",
    "me pasarias|me podes pasar",
)
# El comprador ofrece pasar un código que le llegó («me llegó un SMS con un código, ¿te lo paso?»).
_OFRECER = _frases(
    "te lo paso|te lo mando|te lo envio|te lo doy|te lo reenvio|te lo comparto|te paso el codigo|",
    "les paso el codigo|se los paso|se lo paso|te mando el codigo|les mando el codigo",
)
_CONTEXTO_CODIGO = _frases(
    "por error|te llego|te mande|te envie|te envio|sms|digitos|verificacion|whatsapp|de seguridad|",
    "a tu numero|a tu celular|un mensaje con un codigo|me llego un codigo|me llego un mensaje",
)
_SUPLANTACION = _frases(
    "diciendo que era de ustedes|diciendo que eran de ustedes|diciendo que eran ustedes|diciendo que era ustedes|",
    "dice ser de ustedes|dicen ser de ustedes|dijo ser de ustedes|dijeron ser de ustedes|dice que es de ustedes|",
    "dicen que son de ustedes|dijo que era de ustedes|dijeron que eran de ustedes|se hizo pasar|se hacen pasar|",
    "se hicieron pasar|haciendose pasar|en nombre de ustedes|de parte de ustedes|diciendo ser|",
    "me pidio un codigo|me pidieron un codigo|me piden un codigo|me pidio el codigo|me pidieron el codigo|",
    "me pidieron la clave|me pidio la clave|me pidieron los datos de la tarjeta|me pidio los datos de la tarjeta|",
    "me pidieron la tarjeta|me pidio la tarjeta",
)
# «Me dijo que es vendedor de ustedes», «dicen que trabajan para ustedes»: alguien que dice ser del
# comercio. Sin el «dijo» no alcanza: «la chica que trabaja con ustedes me atendió bien».
_DICE_SER_DEL_COMERCIO = re.compile(
    r"\b(?:dijo|dijeron|dice|dicen|decia|decian|aseguro|asegura)(?: ser| que)?(?: es| era| son| eran)?"
    r" (?:vendedor|vendedora|vendedores|empleado|empleada|empleados|del equipo|de ustedes|"
    r"(?:que )?trabaja(?:n|ba|ban)? (?:con|para|en) ustedes)"
)
# Pedido de devolución («devolveme», «me devolvés») y mención («devolver», «devolución»).
_PIDE_DEVOLUCION = _frases(
    "devolveme|devolves|devolvas|devolvermelo|devuelvan|devuelvas|devolverme|me devuelven|me devolves|",
    "reintegren|reintegrame|reintegrenme|reembolsen|reembolsame|transferime la diferencia|",
    "pasame la diferencia|mandame la diferencia|devolvenme",
)
_MENCIONA_DEVOLUCION = _frases("devolver|devolucion|reintegro|reintegrar|reembolso|reembolsar")
_DESTINO_DEVOLUCION = _frases("alias|cbu|cvu|a esta cuenta|a este numero|a mi cuenta|a la cuenta|a este")
_PAGO_DE_MAS = _frases(
    "transferi de mas|pague de mas|pague dos veces|pague doble|te pague de mas|les pague de mas|",
    "les transferi de mas|te transferi de mas|deposite de mas|transferi dos veces|pago duplicado",
)
_PERTENENCIA = _frases(
    "es de ustedes|es el de ustedes|es el numero de ustedes|son ustedes|es suyo|es suya|es tuyo|es tuya|",
    "es el oficial|es oficial|es real|es confiable|es correcto|es correcta|es valido|es valida|pertenece|",
    "es su numero|es su alias|es el alias de|es de casa|es el suyo|son de ustedes|es verdadero|",
    "whatsapp oficial|numero oficial|telefono oficial|celular oficial|es el whatsapp de ustedes|",
    "puedo transferir a|puedo pagar a|me pasaron|me dieron|me mandaron|este alias|este cbu|este numero",
)
_CONTACTO_AJENO = _frases(
    "me escribieron del|me escribio el|me escribieron desde|me escribio alguien del|me llamaron del|me llamo el|",
    "me hablaron del|me hablo el|me contactaron del|me contacto el|me mandaron un mensaje del|me escribe el|",
    "me escriben del|me llaman del|me llama el",
)
_CONTEXTO_PAGO = _frases(
    "alias|cbu|cvu|transferi|transfiero|transferir|transferencia|pague|pago|pagar|deposite|depositar|cuenta|",
    "es de ustedes|es correcto|es suyo|me pasaron",
)
_INYECCION = _frases(
    "ignora tus instrucciones|ignora las instrucciones|olvida tus instrucciones|olvida las instrucciones|",
    "ignora todo lo anterior|olvida todo lo anterior|nuevas instrucciones|modo desarrollador|tu prompt|",
    "el prompt|system prompt|actua como|sos un modelo de lenguaje|datos de otros clientes|",
    "lista de clientes|los clientes que les escribieron|clientes que les escribieron|telefonos de los clientes|",
    "telefonos de clientes|numeros de los clientes|base de datos|datos de los clientes|contraseña del panel|",
    "acceso al panel|usuario y contraseña del",
)
_SPAM_FUERTE = _frases(
    "ganaste un premio|felicitaciones ganaste|fuiste seleccionado|fuiste seleccionada|fuiste elegido|",
    "fuiste elegida|reclama tu premio|reclamar tu premio|para reclamarlo|gana dinero|ganar dinero|",
    "dinero facil|plata facil|trabajo desde casa|trabaja desde casa|trabajar desde casa|ingresos extra|",
    "ingreso extra|inverti en|invertir en cripto|inversion en cripto|inversiones en cripto|rentabilidad|",
    "multiplica tu dinero|duplica tu dinero|tu cuenta sera suspendida|tu cuenta fue suspendida|",
    "cuenta suspendida|cuenta bloqueada|verifica tu cuenta|verificar tu cuenta|actualiza tus datos|",
    "te ofrezco seguidores|seguidores para tu|compra seguidores|comprar seguidores|aumenta tus seguidores|",
    "aumenta tus ventas|posicionamiento web|marketing digital|agencia de marketing|pagina web para tu|",
    "prestamo aprobado|prestamos sin requisitos|credito aprobado|gana desde tu casa|gana plata|",
    "prestamos rapidos|prestamo rapido|prestamos al instante|sin requisitos|duplica tus ventas|",
    "triplica tus ventas|mas clientes para tu|link en bio|link en la bio|gana un iphone|ganate un|",
    "participa del sorteo|participa en nuestro sorteo|participando en nuestro sorteo|participando del sorteo",
)
_SPAM_DEBIL = _frases(
    "premio|ganaste|ganador|ganadora|click|urgente|suspendida|suspension|verifica|cripto|bitcoin|forex|",
    "trading|inversion|invertir|ganancias|seguidores|ofrezco|ofrecemos|oferta exclusiva|promocion exclusiva|",
    "soy de mercado pago|soy del banco|soy de whatsapp|equipo de soporte|por mes|por dia|escribime|",
    "desde tu casa|desde casa|escribinos|sorteo|iphone",
)
_ENLACE = re.compile(r"https?://|www\.|\bbit\.ly\b|\.xyz\b|tinyurl|\b[a-z0-9-]+\.(?:com|net|ar|io|ly|link)\b", re.I)
_INSULTOS = _frases(
    "pelotudo|pelotuda|pelotudos|pelotudas|boludo|boluda|boludos|boludas|idiota|idiotas|imbecil|imbeciles|",
    "estupido|estupida|estupidos|forro|forra|forros|hdp|hijo de puta|hija de puta|hijos de puta|la concha de|",
    "concha de tu|conchudo|conchuda|andate a la mierda|a la mierda|mierda|la puta|puta madre|puto|puta|",
    "inutil|inutiles|tarado|tarada|tarados|mogolico|mogolica|retrasado|retrasada|gil|giles|choto|sorete|",
    "basura|lacra|malparido|chupame|cagon|cagones|bot de mierda|bot inutil",
)


@dataclass
class AnalisisSeguridad:
    tarjeta: bool = False
    clave: bool = False
    # El comprador escribió un código de verificación («el código es 482913»).
    comparte_codigo: bool = False
    pide_codigo: bool = False
    suplantacion: bool = False
    devolucion_a_cuenta: bool = False
    pregunta_pertenencia: bool = False
    alias_ajenos: list[str] = field(default_factory=list)
    alias_propios: list[str] = field(default_factory=list)
    telefonos_ajenos: list[str] = field(default_factory=list)
    telefonos_propios: list[str] = field(default_factory=list)
    inyeccion: bool = False
    spam: bool = False
    insulto: bool = False

    @property
    def riesgo(self) -> bool:
        """Algo que el bot tiene que advertir antes de responder la consulta."""
        return bool(
            self.tarjeta
            or self.clave
            or self.comparte_codigo
            or self.pide_codigo
            or self.suplantacion
            or self.devolucion_a_cuenta
            or self.alias_ajenos
            or self.telefonos_ajenos
            or self.inyeccion
        )


def _contiene(texto: str, frases: tuple[str, ...]) -> list[str]:
    envuelto = f" {texto} "
    return [f for f in frases if f" {f} " in envuelto]


def _texto_analizable(texto: str) -> str:
    return " ".join(expandir_abreviaturas(palabras(normalizar(texto))))


def analizar(
    texto: str, datos_pago_comercio: set[str] = frozenset(), telefonos_oficiales: tuple[str, ...] = ()
) -> AnalisisSeguridad:
    """Riesgos del mensaje. ``datos_pago_comercio`` son los alias y CBU de los medios de pago
    del comercio; ``telefonos_oficiales``, los últimos 8 dígitos de sus números."""
    a = AnalisisSeguridad()
    if not texto:
        return a
    normal = _texto_analizable(texto)
    ocultos = ocultar(texto)
    a.tarjeta = ocultos.tarjeta or (ocultos.codigo_seguridad and "tarjeta" in normal)
    a.clave = ocultos.clave

    # Pedido de un código de verificación (robo de cuentas).
    tokens = set(normal.split())
    a.pide_codigo = bool(
        "codigo" in tokens
        and not tokens & _EXCLUSIONES_CODIGO
        and (_contiene(normal, _PEDIR) or _contiene(normal, _OFRECER))
        and (_contiene(normal, _CONTEXTO_CODIGO) or ocultos.codigo_verificacion)
    )
    a.suplantacion = bool(_contiene(normal, _SUPLANTACION) or _DICE_SER_DEL_COMERCIO.search(normal))
    if a.suplantacion:
        a.pide_codigo = False  # lo cuenta el comprador: le pidieron un código a él
    a.comparte_codigo = ocultos.codigo_verificacion and not a.pide_codigo

    # Datos de pago: se comparan con los del comercio. Los del propio comprador no se advierten.
    mencionados = datos_de_pago(texto, sin_los_del_comprador=True)
    a.pregunta_pertenencia = bool(_contiene(normal, _PERTENENCIA))
    if mencionados and (_contiene(normal, _CONTEXTO_PAGO) or a.pregunta_pertenencia):
        a.alias_propios = sorted(m for m in mencionados if m in datos_pago_comercio)
        a.alias_ajenos = sorted(m for m in mencionados if m not in datos_pago_comercio)

    # Estafa de la devolución: pide que le devuelvan plata a una cuenta («devolveme la diferencia
    # a este alias»). Si solo deja su alias «por si hay que devolver», es un pago informado.
    pide = bool(_contiene(normal, _PIDE_DEVOLUCION))
    pago_de_mas = bool(_contiene(normal, _PAGO_DE_MAS))
    destino = bool(_contiene(normal, _DESTINO_DEVOLUCION) or datos_de_pago(texto))
    a.devolucion_a_cuenta = destino and (pide or (pago_de_mas and bool(_contiene(normal, _MENCIONA_DEVOLUCION))))

    # Teléfonos: solo si pregunta si es del comercio o cuenta que lo contactaron desde ese número.
    if a.pregunta_pertenencia or a.suplantacion or _contiene(normal, _CONTACTO_AJENO):
        for numero in telefonos(texto):
            comparable = telefono_comparable(numero.digitos)
            destino = a.telefonos_propios if comparable in telefonos_oficiales else a.telefonos_ajenos
            if numero.texto not in destino:
                destino.append(numero.texto)

    a.inyeccion = bool(_contiene(normal, _INYECCION))

    fuertes = _contiene(normal, _SPAM_FUERTE)
    debiles = _contiene(normal, _SPAM_DEBIL)
    enlace = bool(_ENLACE.search(texto))
    a.spam = (
        len(fuertes) >= 2 or (len(fuertes) >= 1 and (len(debiles) >= 1 or enlace)) or (enlace and len(debiles) >= 2)
    )

    a.insulto = bool(_contiene(normal, _INSULTOS))
    return a
