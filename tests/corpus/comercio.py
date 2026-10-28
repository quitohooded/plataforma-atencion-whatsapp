"""Comercio de evaluación: Casa & Detalles con la misma información que la demostración.

Los datos vienen de ``app/datos/casa_y_detalles.py``, la misma fuente que usa la
demostración, para que lo que se mide con el corpus sea lo que se ve en el simulador.
"""

from datetime import datetime

from app.datos.casa_y_detalles import datos_comercio

CASA_Y_DETALLES = datos_comercio()

# Martes 27/10/2026 22:30: fuera del horario de atención.
AHORA = datetime(2026, 10, 27, 22, 30)
