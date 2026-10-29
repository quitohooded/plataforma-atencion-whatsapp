"""Recorridos completos de cada perfil en el navegador: comercio nuevo, comprador y responsable."""

from __future__ import annotations

import re

import pytest

from .conftest import escribir_en_chat, ingresar

pytestmark = pytest.mark.e2e


def test_comercio_nuevo_desde_el_registro_hasta_atender_una_consulta(pagina, navegador, servidor):
    """CU01, CU03 a CU07, CU08 a CU12 y CU13 en un solo recorrido, como lo haría una persona."""
    base = servidor
    # CU01: registro con la aceptación de los términos.
    pagina.goto(base + "/registro")
    pagina.fill("#campo-nombre", "Deco Norte")
    pagina.fill("#campo-rubro", "Decoración")
    pagina.fill("#campo-telefono", "387 012-3344")
    pagina.fill("#campo-email", "hola@deconorte.com.ar")
    pagina.fill("#campo-contrasena", "decoNorte2026")
    pagina.click("button[type=submit]")
    assert "tiene que aceptar los términos" in pagina.inner_text("body")
    assert pagina.input_value("#campo-nombre") == "Deco Norte"
    pagina.fill("#campo-contrasena", "decoNorte2026")
    pagina.check("input[name=acepta]")
    pagina.click("button[type=submit]")
    pagina.wait_for_url(re.compile(r"/onboarding/paso/1$"))

    # CU03: los cuatro pasos.
    pagina.click("text=Confirmar y continuar")
    pagina.fill("#zona-descripcion", "Salta Capital")
    pagina.fill("#zona-cp-desde", "4400")
    pagina.fill("#zona-cp-hasta", "4409")
    pagina.fill("#zona-min", "1")
    pagina.fill("#zona-max", "2")
    pagina.click("text=Guardar zona")
    assert "Salta Capital" in pagina.inner_text("table")
    pagina.click("button[value=continuar]")
    pagina.select_option("#medio-tipo", "Transferencia bancaria")
    pagina.fill("#medio-detalle", "alias deco.norte.demo")
    pagina.click("text=Guardar medio de pago")
    assert "deco.norte.demo" in pagina.inner_text("table")
    pagina.click("button[value=continuar]")
    pagina.click("button[value=guardar]")
    pagina.wait_for_url(re.compile(r"/onboarding/resumen$"))
    vista_previa = pagina.inner_text("body")
    assert "Así va a responder el bot" in vista_previa and "Salta Capital" in vista_previa
    pagina.click("text=Confirmar e ir a la activación")
    pagina.wait_for_url(re.compile(r"/activacion$"))

    # CU07: chat de prueba y activación.
    respuesta = escribir_en_chat(pagina, "¿Hacen envíos a Salta?", "#chat-prueba form")
    assert "4400" in respuesta and "1 a 2 días hábiles" in respuesta
    respuesta = escribir_en_chat(pagina, "¿tienen almohadones?", "#chat-prueba form")
    assert "persona" in respuesta.lower() or "equipo" in respuesta.lower()
    pagina.click("text=Activar bot")
    pagina.wait_for_load_state()
    assert re.fullmatch(r"[A-Z0-9]{6}", pagina.inner_text(".codigo-acceso").strip())

    # CU08 a CU12: un comprador escribe desde el simulador.
    contexto = navegador.new_context(locale="es-AR", viewport={"width": 1360, "height": 900})
    simulador = contexto.new_page()
    simulador.goto(base + "/simulador")
    simulador.click("button[data-sim-enlace*='Deco Norte']")
    bienvenida = escribir_en_chat(simulador, simulador.input_value(".chat form input[type=text]"))
    assert "Deco Norte" in simulador.inner_text(".chat__mensajes") and bienvenida
    assert "Salta Capital" in escribir_en_chat(simulador, "hacen envios al 4400?")
    derivacion = escribir_en_chat(simulador, "¿tienen almohadones en gris?")
    assert "387 012-3344" in derivacion
    contexto.close()

    # CU13: la consulta queda pendiente y se marca como atendida.
    pagina.goto(base + "/panel")
    pendientes = pagina.locator(".pendiente")
    assert pendientes.count() == 1
    assert "almohadones" in pendientes.first.inner_text()
    pagina.click("text=Marcar como atendida")
    pagina.wait_for_load_state()
    assert pagina.locator(".pendiente").count() == 0


def test_comprador_datos_sensibles_y_verificacion_de_alias(pagina, servidor):
    """El simulador muestra lo que vive el comprador; al recargar, se ve lo que quedó guardado."""
    pagina.goto(servidor + "/simulador")
    pagina.click("button[data-sim-enlace*='Casa & Detalles']")
    escribir_en_chat(pagina, pagina.input_value(".chat form input[type=text]"))
    advertencia = escribir_en_chat(pagina, "mi tarjeta es 4509 9535 6623 3704 vence 11/27 cvv 123")
    assert "no compartas los datos de tu tarjeta" in advertencia.lower()
    alias = escribir_en_chat(pagina, "¿este alias es de ustedes? lucas.ventas.mp")
    assert "no" in alias.lower() and "casa.detalles.demo" in alias
    pagina.reload()
    pagina.wait_for_function("() => document.querySelectorAll('.chat__mensajes .burbuja').length > 3")
    historial = pagina.inner_text(".chat__mensajes")
    assert "4509 9535" not in historial and "•••• •••• •••• 3704" in historial


def test_responsable_crea_una_respuesta_frecuente_y_el_bot_la_usa(pagina, navegador, servidor):
    """CU15: plantilla, prueba antes de guardar y uso en el simulador."""
    ingresar(pagina, servidor, "demo@mundotextil.com.ar")
    pagina.goto(servidor + "/respuestas")
    pagina.click(".plantilla:has-text('Garantía') a:has-text('Usar plantilla')")
    pagina.wait_for_load_state()
    pagina.fill("[data-probar-mensaje]", "los productos tienen garantía?")
    pagina.click("[data-probar-formulario] button")
    pagina.wait_for_selector(".probar__veredicto")
    assert "el bot responde con esta respuesta" in pagina.inner_text(".probar__veredicto").lower()
    pagina.click("button:has-text('Guardar respuesta')")
    pagina.wait_for_url(re.compile(r"/respuestas$"))
    assert "Garantía" in pagina.inner_text("main")

    contexto = navegador.new_context(locale="es-AR")
    simulador = contexto.new_page()
    simulador.goto(servidor + "/simulador")
    simulador.click("button[data-sim-enlace*='Mundo Textil']")
    escribir_en_chat(simulador, simulador.input_value(".chat form input[type=text]"))
    respuesta = escribir_en_chat(simulador, "tienen garantía los productos?")
    assert "garantía" in respuesta.lower()
    contexto.close()


def test_panel_en_el_celular_sin_desplazamiento_horizontal(movil, servidor):
    ingresar(movil, servidor)
    for ruta in ["/panel", "/historial", "/zonas", "/medios-de-pago", "/horarios", "/respuestas", "/activacion"]:
        movil.goto(servidor + ruta)
        ancho = movil.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
        assert ancho[0] <= ancho[1], f"{ruta} se desborda: {ancho}"
    # El menú lateral se abre con el botón «Menú».
    movil.click("[data-abrir-menu]")
    assert movil.get_attribute("[data-abrir-menu]", "aria-expanded") == "true"
    assert movil.locator("#lateral a:has-text('Historial de consultas')").is_visible()


def test_aviso_en_vivo_de_una_consulta_nueva(pagina, navegador, servidor):
    """El contador del panel se actualiza solo cuando llega una consulta (#8)."""
    pagina.clock.install()
    ingresar(pagina, servidor)
    pagina.goto(servidor + "/panel")
    contador = pagina.locator("[data-contador-pendientes]").first
    antes = int(contador.inner_text() or 0)
    contexto = navegador.new_context(locale="es-AR")
    simulador = contexto.new_page()
    simulador.goto(servidor + "/simulador")
    simulador.click("button[data-sim-enlace*='Casa & Detalles']")
    escribir_en_chat(simulador, simulador.input_value(".chat form input[type=text]"))
    escribir_en_chat(simulador, "me llegó roto el pedido")
    contexto.close()
    # El panel consulta el estado cada 30 segundos: se adelanta el reloj de la página.
    pagina.clock.fast_forward(31_000)
    pagina.wait_for_function(
        "([n]) => Number(document.querySelector('[data-contador-pendientes]').textContent) > n", arg=[antes]
    )
    assert pagina.title().startswith(f"({antes + 1})")
