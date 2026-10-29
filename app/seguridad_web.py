"""Seguridad de la aplicación web (#12): encabezados, política de contenido y límites por IP.

- Encabezados en todas las respuestas: política de contenido (CSP) sin scripts en línea,
  sin marcos de otros sitios, sin adivinar tipos de archivo y con permisos del navegador
  desactivados. HSTS solo cuando la página se sirve por HTTPS.
- Las páginas del panel no se guardan en la caché del navegador: después de cerrar la sesión,
  el botón «Atrás» no muestra datos de los compradores.
- Límite de pedidos por dirección IP en ingreso, registro, recuperación de contraseña y
  simulador. Se cuenta en memoria del proceso: alcanza para el servidor del prototipo
  (waitress, un proceso con varios hilos). Con varios procesos, cada uno cuenta por separado.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import wraps

from flask import Flask, current_app, jsonify, render_template, request, session

POLITICA_CONTENIDO = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        # Anchos de las barras del resumen y ajustes puntuales en atributos style (no en etiquetas).
        "style-src-attr 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "base-uri 'none'",
        "object-src 'none'",
    ]
)

ENCABEZADOS = {
    "Content-Security-Policy": POLITICA_CONTENIDO,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

HSTS = "max-age=31536000; includeSubDomains"


@dataclass(frozen=True)
class Limite:
    """Cantidad de pedidos permitidos por IP en una ventana de tiempo."""

    pedidos: int
    segundos: int


# Valores pensados para una persona: varios intentos seguidos pasan, un guion automático no.
LIMITES = {
    "ingreso": Limite(20, 10 * 60),
    "registro": Limite(5, 60 * 60),
    "recuperacion": Limite(5, 15 * 60),
    "simulador": Limite(40, 60),
    "simulador_historial": Limite(60, 60),
}


class ContadorPorIP:
    """Ventana deslizante por clave y dirección IP, segura entre hilos."""

    def __init__(self) -> None:
        self._marcas: dict[tuple[str, str], deque[float]] = {}
        self._candado = threading.Lock()
        self._ultima_limpieza = time.monotonic()

    def registrar(self, clave: str, ip: str, limite: Limite, ahora: float | None = None) -> int:
        """Registra un pedido. Devuelve 0 si está permitido o los segundos que faltan para reintentar."""
        ahora = time.monotonic() if ahora is None else ahora
        with self._candado:
            self._limpiar(ahora)
            marcas = self._marcas.setdefault((clave, ip), deque())
            while marcas and ahora - marcas[0] >= limite.segundos:
                marcas.popleft()
            if len(marcas) >= limite.pedidos:
                return max(1, math.ceil(limite.segundos - (ahora - marcas[0])))
            marcas.append(ahora)
            return 0

    def _limpiar(self, ahora: float) -> None:
        """Descarta las direcciones sin pedidos recientes para que la memoria no crezca."""
        if ahora - self._ultima_limpieza < 300:
            return
        ventana = max(limite.segundos for limite in LIMITES.values())
        for clave in [c for c, m in self._marcas.items() if not m or ahora - m[-1] >= ventana]:
            del self._marcas[clave]
        self._ultima_limpieza = ahora


def limitar(clave: str, solo_post: bool = True):
    """Decorador: aplica el límite ``LIMITES[clave]`` a la vista (por defecto, solo a los envíos)."""

    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if current_app.config.get("LIMITES_POR_IP") and (request.method == "POST" or not solo_post):
                contador: ContadorPorIP = current_app.extensions["limites_ip"]
                espera = contador.registrar(clave, request.remote_addr or "-", LIMITES[clave])
                if espera:
                    return demasiados_pedidos(espera)
            return vista(*args, **kwargs)

        return envoltura

    return decorador


def demasiados_pedidos(espera: int):
    minutos = max(1, math.ceil(espera / 60))
    mensaje = f"Demasiados intentos seguidos desde esta conexión. Vuelva a intentar en {minutos} minuto" + (
        "s." if minutos > 1 else "."
    )
    encabezados = {"Retry-After": str(espera)}
    if request.is_json or request.path.startswith("/simulador/api"):
        return jsonify(error=mensaje), 429, encabezados
    return render_template("errores/429.html", mensaje=mensaje), 429, encabezados


def registrar(app: Flask) -> None:
    app.extensions["limites_ip"] = ContadorPorIP()

    @app.after_request
    def encabezados_de_seguridad(respuesta):
        for nombre, valor in ENCABEZADOS.items():
            respuesta.headers.setdefault(nombre, valor)
        if request.is_secure:
            respuesta.headers.setdefault("Strict-Transport-Security", HSTS)
        # Panel con sesión iniciada: sin caché, para que «Atrás» no muestre datos después de salir.
        if session.get("id_usuario") and not request.path.startswith("/static/"):
            respuesta.headers["Cache-Control"] = "no-store"
        return respuesta
