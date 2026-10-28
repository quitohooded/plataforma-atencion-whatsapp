"""Generación de códigos QR en SVG (no requiere librerías de imágenes)."""

import io
import re

import qrcode
import qrcode.image.svg


def qr_svg(datos: str, color: str = "#1C2A24", titulo: str = "Código QR") -> str:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2, box_size=10)
    qr.add_data(datos)
    qr.make(fit=True)
    imagen = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)
    salida = io.BytesIO()
    imagen.save(salida)
    svg = salida.getvalue().decode("utf-8")
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    # Tamaño adaptable al contenedor, color propio y fondo blanco para que se pueda escanear impreso.
    svg = re.sub(r'\swidth="[^"]*"\s+height="[^"]*"', "", svg, count=1)
    svg = svg.replace("<svg ", f'<svg role="img" aria-label="{titulo}" ', 1)
    svg = re.sub(r"(<svg[^>]*>)", r'\1<rect width="100%" height="100%" fill="#ffffff"/>', svg, count=1)
    svg = svg.replace("<path ", f'<path fill="{color}" ')
    return svg
