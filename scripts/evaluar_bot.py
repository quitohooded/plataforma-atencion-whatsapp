"""Informe de exactitud del bot sobre los corpus de evaluación.

Uso:
    python scripts/evaluar_bot.py              resumen por categoría de ambos corpus
    python scripts/evaluar_bot.py --fallos     agrega cada mensaje que el bot no resolvió como se esperaba

El corpus de desarrollo (``tests/corpus/mensajes.py``) se usó para construir el
vocabulario; el de validación (``tests/corpus/validacion.py``) se escribió aparte para
medir si el bot generaliza. Ver ``docs/evaluacion-del-bot.md``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.corpus import mensajes, validacion  # noqa: E402
from tests.corpus.evaluacion import Informe, evaluar  # noqa: E402

NOMBRES = {
    "envio": "Envíos",
    "pago": "Medios de pago",
    "horario": "Horarios",
    "contacto": "Contacto",
    "catalogo": "Catálogo",
    "faq": "Respuestas del comercio",
    "productos": "Productos y precios",
    "pedidos": "Pedidos",
    "reclamos": "Reclamos",
    "pagos_informados": "Pagos informados",
    "persona": "Pedido de una persona",
    "saludo": "Saludos y menú",
    "cortesia": "Cortesía",
    "identidad": "Identidad del asistente",
    "contame": "Anuncia una consulta",
    "aclaracion": "Mensajes sin sentido",
    "otra": "Otras preguntas",
    "seguridad": "Seguridad y estafas",
    "spam": "Spam",
    "insulto": "Insultos",
    "multiple": "Varias preguntas juntas",
    "ambiguo": "Casos que se prestan a confusión",
}


def porcentaje(aciertos: int, total: int) -> str:
    return f"{aciertos * 100 / total:.1f} %".replace(".", ",") if total else "-"


def imprimir(titulo: str, informe: Informe, fallos: bool) -> None:
    print(f"\n## {titulo}\n")
    print(
        f"Mensajes: **{porcentaje(informe.aciertos, informe.total)}** ({informe.aciertos} de {informe.total}). "
        f"Diálogos: {informe.dialogos_ok} de {informe.dialogos_total}.\n"
    )
    print("| Categoría | Aciertos | Exactitud |")
    print("|---|---|---|")
    for categoria, (aciertos, total) in sorted(informe.por_categoria.items(), key=lambda x: -x[1][0] / x[1][1]):
        print(f"| {NOMBRES.get(categoria, categoria)} | {aciertos} de {total} | {porcentaje(aciertos, total)} |")
    if fallos and (informe.fallos or informe.fallos_dialogos):
        print("\nMensajes no resueltos como se esperaba:\n")
        for f in informe.fallos:
            print(f"- «{f.mensaje}» ({f.categoria}): se esperaba {f.esperado}, hizo {', '.join(f.obtenido) or 'nada'}")
        for nombre, paso, mensaje, esperado, obtenido in informe.fallos_dialogos:
            print(f"- Diálogo «{nombre}», paso {paso} «{mensaje}»: se esperaba {esperado}, hizo {', '.join(obtenido)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fallos", action="store_true", help="Listar los mensajes que fallaron")
    args = parser.parse_args()
    print("# Exactitud del bot")
    imprimir("Corpus de desarrollo", evaluar(), args.fallos)
    imprimir("Corpus de validación", evaluar(casos=validacion.CASOS, dialogos=validacion.DIALOGOS), args.fallos)
    originales = evaluar(casos=mensajes.CASOS[:215], dialogos=[])
    print(
        f"\nSobre los 215 mensajes con los que se midió la versión 0.1: "
        f"{porcentaje(originales.aciertos, originales.total)} (0.1: 36,3 %)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
