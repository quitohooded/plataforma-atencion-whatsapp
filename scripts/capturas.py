"""Genera las capturas de pantalla de la interfaz (docs/capturas) para el informe.

Requiere Playwright (no es una dependencia de la aplicación); Pillow es opcional y reduce el peso:
    pip install playwright pillow
    python -m playwright install chromium

Uso, con el servidor corriendo y la demo cargada (flask --app app demo):
    python scripts/capturas.py
    python scripts/capturas.py --url http://localhost:5000 --salida docs/capturas
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent
DEMO = ("demo@casaydetalles.com.ar", "demo1234")
NUEVO = {
    "nombre": "Deco Norte",
    "rubro": "Decoración",
    "telefono": "387 012-3344",
    "email": "hola@deconorte.com.ar",
    "contrasena": "decoNorte2026",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5000")
    parser.add_argument("--salida", default=str(RAIZ / "docs" / "capturas"))
    args = parser.parse_args()
    base = args.url.rstrip("/")
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        # El idioma del proceso define el formato de hora de los campos (24 h en es-AR).
        entorno = {**os.environ, "LANG": "es_AR.UTF-8", "LANGUAGE": "es_AR:es"}
        navegador = p.chromium.launch(args=["--lang=es-AR"], env=entorno)
        contexto = navegador.new_context(viewport={"width": 1440, "height": 900}, locale="es-AR", device_scale_factor=2)
        pagina = contexto.new_page()

        def foto(nombre, completa=True):
            pagina.wait_for_timeout(250)
            pagina.screenshot(path=str(salida / f"{nombre}.png"), full_page=completa)
            print("  ", nombre)

        # Público y acceso
        pagina.goto(base + "/")
        foto("01-inicio")
        pagina.goto(base + "/registro")
        foto("02-registro", False)
        pagina.goto(base + "/ingresar")
        foto("03-ingreso", False)
        pagina.goto(base + "/privacidad")
        foto("29-politica-de-privacidad")

        # Onboarding de un comercio nuevo (CU01 y CU03)
        pagina.goto(base + "/registro")
        for campo, valor in NUEVO.items():
            pagina.fill(f"#campo-{campo}", valor)
        pagina.check("input[name=acepta]")
        pagina.click("button[type=submit]")
        pagina.wait_for_load_state()
        if "/registro" in pagina.url:  # ya existía: ingresar
            pagina.goto(base + "/ingresar")
            pagina.fill("#campo-email", NUEVO["email"])
            pagina.fill("#campo-contrasena", NUEVO["contrasena"])
            pagina.click("button[type=submit]")
            pagina.wait_for_load_state()
        if "/onboarding" in pagina.url:
            pagina.goto(base + "/onboarding/paso/1")
            foto("04-onboarding-1-datos")
            pagina.click("text=Confirmar y continuar")
            pagina.wait_for_load_state()
            if not pagina.locator("table").count():
                pagina.fill("#zona-descripcion", "Salta Capital")
                pagina.fill("#zona-cp-desde", "4400")
                pagina.fill("#zona-cp-hasta", "4409")
                pagina.fill("#zona-min", "1")
                pagina.fill("#zona-max", "2")
                pagina.click("text=Guardar zona")
                pagina.wait_for_load_state()
                pagina.fill("#zona-descripcion", "Interior de Salta")
                pagina.fill("#zona-cp-desde", "4410")
                pagina.fill("#zona-cp-hasta", "4599")
                pagina.fill("#zona-min", "2")
                pagina.fill("#zona-max", "4")
                pagina.click("text=Guardar zona")
                pagina.wait_for_load_state()
            foto("05-onboarding-2-zonas")
            planilla = Path(tempfile.mkdtemp()) / "zonas-de-envio.csv"
            planilla.write_text(
                "descripcion;cp_desde;cp_hasta;plazo_min_dias;plazo_max_dias\n"
                "Jujuy;4600;4699;2;4\nTucumán;4000;4199;2;4\nMal cargada;4800;4700;1;2\n"
                "Repetida;4405;4410;1;1\n",
                encoding="utf-8",
            )
            pagina.set_input_files("#planilla", str(planilla))
            pagina.click("text=Importar planilla")
            pagina.wait_for_load_state()
            foto("06-importar-planilla")
            pagina.click("button:has-text('Incorporar')")
            pagina.wait_for_load_state()
            pagina.click("button[value=continuar]")
            pagina.wait_for_load_state()
            if not pagina.locator("table").count():
                pagina.select_option("#medio-tipo", "Transferencia bancaria")
                pagina.fill("#medio-detalle", "alias deco.norte.demo")
                pagina.click("text=Guardar medio de pago")
                pagina.wait_for_load_state()
                pagina.select_option("#medio-tipo", "Billetera virtual")
                pagina.fill("#medio-detalle", "Mercado Pago")
                pagina.click("text=Guardar medio de pago")
                pagina.wait_for_load_state()
            foto("07-onboarding-3-medios")
            pagina.click("button[value=continuar]")
            pagina.wait_for_load_state()
            pagina.fill("#ci-0-0", "13:00")
            pagina.click("button[value=agregar_0]")
            pagina.wait_for_load_state()
            pagina.fill("#ap-0-1", "16:00")
            pagina.fill("#ci-0-1", "20:00")
            pagina.click("button[value=copiar_0]")
            pagina.wait_for_load_state()
            pagina.check("input[name=atiende_5]")
            pagina.fill("#ap-5-0", "10:00")
            pagina.fill("#ci-5-0", "13:00")
            foto("08-onboarding-4-horarios")
            pagina.click("button[value=guardar]")
            pagina.wait_for_load_state()
            foto("09-onboarding-resumen")
            pagina.click("text=Confirmar e ir a la activación")
            pagina.wait_for_load_state()

        # Activación con chat de prueba (CU07)
        pagina.goto(base + "/activacion")
        pagina.click("[data-chat-reiniciar]")
        for texto in ["Hola", "¿Hacen envíos a Salta?", "4400", "¿Qué medios de pago aceptan?"]:
            pagina.fill("#chat-prueba-texto", texto)
            pagina.click("#chat-prueba button[type=submit]")
            pagina.wait_for_timeout(900)
        foto("10-activacion-chat-de-prueba")
        if pagina.locator("text=Activar bot").count():
            pagina.click("text=Activar bot")
            pagina.wait_for_load_state()
        foto("11-activacion-enlace-y-qr")
        pagina.goto(base + "/activacion/cartel")
        foto("12-cartel-imprimible")
        contexto.clear_cookies()

        # Panel del comercio con historial (CU13, CU14 y secciones de CU04 a CU06)
        pagina.goto(base + "/ingresar")
        pagina.fill("#campo-email", DEMO[0])
        pagina.fill("#campo-contrasena", DEMO[1])
        pagina.click("button[type=submit]")
        pagina.wait_for_load_state()
        pagina.goto(base + "/panel")
        foto("13-resumen-y-pendientes")
        pagina.goto(base + "/historial")
        foto("14-historial")
        pagina.goto(base + "/historial?resultado=DERIVADA")
        foto("15-historial-filtrado")
        enlace = pagina.locator("a:has-text('Ver conversación')").first.get_attribute("href")
        pagina.goto(base + enlace)
        foto("16-detalle-de-consulta")
        pagina.goto(base + "/zonas")
        foto("17-zonas-de-envio")
        pagina.goto(base + "/medios-de-pago")
        foto("18-medios-de-pago")
        pagina.goto(base + "/horarios")
        foto("19-horarios")
        pagina.goto(base + "/activacion")
        foto("20-activacion-bot-activo")
        pagina.goto(base + "/mi-comercio")
        foto("21-datos-del-negocio")
        pagina.goto(base + "/cuenta")
        foto("27-cuenta")
        pagina.goto(base + "/ayuda")
        foto("28-ayuda")

        # Respuestas propias (CU15): listado y prueba antes de guardar
        pagina.goto(base + "/respuestas")
        foto("24-respuestas-frecuentes")
        pagina.click("a:has-text('Editar') >> nth=1")
        pagina.wait_for_load_state()
        pagina.fill("[data-probar-mensaje]", "Holis, los precios son con iva?")
        pagina.click("[data-probar-formulario] button")
        pagina.wait_for_selector(".probar__veredicto")
        foto("25-respuesta-probar")
        contexto.clear_cookies()
        pagina.goto(base + "/ingresar")
        pagina.fill("#campo-email", "demo@mundotextil.com.ar")
        pagina.fill("#campo-contrasena", DEMO[1])
        pagina.click("button[type=submit]")
        pagina.wait_for_load_state()
        pagina.goto(base + "/respuestas")
        foto("26-respuestas-sugerencias")

        # Comprador en el simulador (CU08 a CU12)
        simulador = contexto.new_page()
        simulador.goto(base + "/simulador")
        simulador.click("[data-sim-nuevo]")
        simulador.wait_for_timeout(400)
        simulador.fill("#sim-nombre", "Lucía")
        simulador.dispatch_event("#sim-nombre", "change")
        simulador.click("li:has-text('Casa & Detalles') button[data-sim-enlace]")
        simulador.click("#chat-simulador button[type=submit]")
        simulador.wait_for_timeout(900)
        for texto in ["¿Hacen envíos a Río Cuarto?", "5800", "¿y cómo se paga?", "¿Tienen el mantel en otro color?"]:
            simulador.fill("#chat-simulador-texto", texto)
            simulador.click("#chat-simulador button[type=submit]")
            simulador.wait_for_timeout(900)
        simulador.screenshot(path=str(salida / "22-simulador-comprador.png"), full_page=True)
        print("   22-simulador-comprador")

        # Vista en celular
        movil = navegador.new_context(viewport={"width": 390, "height": 844}, locale="es-AR", device_scale_factor=3)
        pm = movil.new_page()
        pm.goto(base + "/ingresar")
        pm.fill("#campo-email", DEMO[0])
        pm.fill("#campo-contrasena", DEMO[1])
        pm.click("button[type=submit]")
        pm.wait_for_load_state()
        pm.screenshot(path=str(salida / "23-movil-resumen.png"))
        print("   23-movil-resumen")
        navegador.close()
    comprimir(salida)
    print(f"Capturas guardadas en {salida}")


def comprimir(carpeta: Path) -> None:
    """Reduce el peso de las imágenes con una paleta de 256 colores, si Pillow está instalado."""
    try:
        from PIL import Image
    except ImportError:
        return
    for archivo in carpeta.glob("*.png"):
        imagen = Image.open(archivo).convert("RGB")
        imagen.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(
            archivo, optimize=True
        )


if __name__ == "__main__":
    main()
