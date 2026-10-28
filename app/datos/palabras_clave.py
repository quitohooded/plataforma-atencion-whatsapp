"""Catálogo inicial de palabras clave por tema (clase PalabraClave).

Se construyó a partir del vocabulario que usan los compradores al preguntar
(apartado 4 del informe: tercera fuente de información). Los términos se
guardan normalizados: minúsculas y sin tildes. Pueden ser palabras sueltas o
frases. El catálogo se amplía con el comando «flask palabras agregar».
"""

from ..modelos import TemaConsulta

CATALOGO: dict[TemaConsulta, list[str]] = {
    TemaConsulta.ENVIO: [
        "envio", "envios", "enviar", "envian", "envias", "enviarian", "envien",
        "mandan", "mandas", "mandar", "mandarian",
        "despacho", "despachan", "despachar",
        "entrega", "entregas", "entregan",
        "llega", "llegan", "llegaria", "llegue",
        "demora", "demoran", "demoraria",
        "tarda", "tardan", "tardaria",
        "correo", "andreani", "oca", "flete", "encomienda",
        "codigo postal", "cp", "a domicilio",
        "cuanto tarda", "cuanto demora",
    ],
    TemaConsulta.MEDIOS_PAGO: [
        "pago", "pagos", "pagar", "pagan", "paga", "pagas", "pague", "pagaria", "pagarlo",
        "abono", "abonar", "abonas", "cobran", "cobras", "como se paga",
        "medios de pago", "formas de pago", "forma de pago", "medio de pago",
        "transferencia", "transferir", "transfiero",
        "efectivo", "tarjeta", "tarjetas", "credito", "debito", "cuotas",
        "mercado pago", "mercadopago", "alias", "cbu", "cvu",
        "billetera", "uala", "modo", "visa", "mastercard", "naranja",
        "rapipago", "pago facil",
    ],
    TemaConsulta.HORARIOS: [
        "horario", "horarios", "hora", "horas",
        "abren", "abris", "abre", "abierto", "abiertos", "abierta",
        "cierran", "cierra", "cerrado", "cerrados",
        "atienden", "atendes", "atencion",
        "a que hora", "que dias", "hasta que hora",
        "sabado", "sabados", "domingo", "domingos", "feriado", "feriados",
    ],
}


def items_catalogo() -> list[tuple[str, TemaConsulta]]:
    return [(termino, tema) for tema, terminos in CATALOGO.items() for termino in terminos]
