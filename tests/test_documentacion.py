"""La documentación de pruebas no puede citar pruebas que no existen."""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _pruebas_definidas() -> set[str]:
    nombres = set()
    for archivo in (RAIZ / "tests").rglob("test_*.py"):
        nombres |= set(re.findall(r"^def (test_\w+)", archivo.read_text(encoding="utf-8"), re.MULTILINE))
    return nombres


def test_casos_de_prueba_citan_pruebas_existentes():
    texto = (RAIZ / "docs" / "casos-de-prueba.md").read_text(encoding="utf-8")
    citadas = set(re.findall(r"`(test_\w+)`", texto))
    assert citadas, "el documento debería citar pruebas"
    assert sorted(citadas - _pruebas_definidas()) == []
