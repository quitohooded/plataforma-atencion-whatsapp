"""Auditoría de accesibilidad WCAG 2.1 AA con axe-core en todas las pantallas (#16).

Se revisa cada pantalla en escritorio y en celular, con los estados que tienen contenido real: la
demostración cargada, una conversación en el simulador y un comercio nuevo en la carga inicial.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from .conftest import escribir_en_chat, ingresar

pytestmark = pytest.mark.e2e

axe_playwright = pytest.importorskip("axe_playwright_python")
AXE = (Path(axe_playwright.__file__).parent / "axe.min.js").read_text(encoding="utf-8")
REGLAS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]

PUBLICAS = ["/", "/ingresar", "/registro", "/recuperar", "/privacidad", "/terminos", "/simulador", "/no-existe"]
PANEL = [
    "/panel",
    "/historial",
    "/historial?resultado=DERIVADA",
    "/zonas",
    "/medios-de-pago",
    "/horarios",
    "/respuestas",
    "/respuestas/nueva",
    "/activacion",
    "/activacion/cartel",
    "/mi-comercio",
    "/cuenta",
    "/ayuda",
    "/bloqueos",
]
ANCHOS = {"escritorio": {"width": 1360, "height": 900}, "celular": {"width": 390, "height": 844}}


def violaciones(pagina) -> list[str]:
    pagina.wait_for_load_state("networkidle")
    pagina.evaluate(AXE)
    resultado = pagina.evaluate(
        "async (reglas) => (await axe.run(document, {runOnly: {type: 'tag', values: reglas}})).violations"
        ".map(v => `${v.impact} ${v.id}: ${v.help} -> `"
        " + v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(' | '))",
        REGLAS,
    )
    return resultado


@pytest.fixture(params=list(ANCHOS), ids=list(ANCHOS))
def auditor(request, navegador):
    # axe se inyecta como script: el contexto de prueba omite la política de contenido de la aplicación.
    contexto = navegador.new_context(bypass_csp=True, locale="es-AR", viewport=ANCHOS[request.param])
    yield contexto.new_page()
    contexto.close()


def _auditar(pagina, base, rutas) -> dict[str, list[str]]:
    hallazgos = {}
    for ruta in rutas:
        pagina.goto(base + ruta)
        encontradas = violaciones(pagina)
        if encontradas:
            hallazgos[ruta] = encontradas
    return hallazgos


def test_paginas_publicas(auditor, servidor):
    assert _auditar(auditor, servidor, PUBLICAS) == {}


def test_paginas_del_panel(auditor, servidor):
    ingresar(auditor, servidor)
    auditor.goto(servidor + "/historial")
    detalle = auditor.locator("a:has-text('Ver conversación')").first.get_attribute("href")
    assert _auditar(auditor, servidor, [*PANEL, detalle]) == {}


def test_simulador_con_una_conversacion(auditor, servidor):
    auditor.goto(servidor + "/simulador")
    auditor.click("button[data-sim-enlace*='Casa & Detalles']")
    escribir_en_chat(auditor, auditor.input_value(".chat form input[type=text]"))
    escribir_en_chat(auditor, "hacen envíos a Rosario? y cómo se paga?")
    assert violaciones(auditor) == []


def test_carga_inicial_de_un_comercio_nuevo(auditor, servidor):
    correo = f"a11y-{auditor.viewport_size['width']}@ejemplo.com"
    auditor.goto(servidor + "/registro")
    auditor.fill("#campo-nombre", "Comercio Accesible")
    auditor.fill("#campo-rubro", "Regalería")
    auditor.fill("#campo-telefono", "351 012-9999")
    auditor.fill("#campo-email", correo)
    auditor.fill("#campo-contrasena", "accesible2026")
    auditor.click("button[type=submit]")
    # El formulario con errores también tiene que ser accesible.
    assert violaciones(auditor) == []
    auditor.fill("#campo-contrasena", "accesible2026")
    auditor.check("input[name=acepta]")
    auditor.click("button[type=submit]")
    auditor.wait_for_url(re.compile(r"/onboarding/paso/1$"))
    assert _auditar(auditor, servidor, [f"/onboarding/paso/{n}" for n in range(1, 5)]) == {}
