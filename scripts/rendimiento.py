"""Mide el tiempo de respuesta del bot (RNF04: «el bot debe responder las consultas frecuentes en
cuestión de segundos, independientemente del horario en que se reciban»).

Tres mediciones, de adentro hacia afuera:

1. Motor: interpretar y armar la respuesta de cada mensaje de los corpus (sin base de datos).
2. Servicio: el recorrido completo de un mensaje entrante con SQLite en disco (buscar el comercio,
   guardar los mensajes y las consultas, confirmar la transacción), como lo hace el webhook.
3. HTTP con carga: varios compradores simultáneos escribiendo al simulador, servido por waitress
   (el mismo servidor de producción del prototipo).

No incluye la red de WhatsApp (de Meta al servidor y del servidor a Meta), que no depende del
sistema. Uso:

    python scripts/rendimiento.py                    imprime la tabla en Markdown
    python scripts/rendimiento.py --compradores 20 --mensajes 30
"""

from __future__ import annotations

import argparse
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# Mensajes de los tres corpus (desarrollo, validación y a ciegas), con sus diálogos.
from tests.corpus import ciego, mensajes, validacion  # noqa: E402

_CORPUS = (mensajes, validacion, ciego)
MENSAJES = [m for c in _CORPUS for m, _, _ in c.CASOS if not m.startswith("[Mensaje de tipo")]
MENSAJES += [m for c in _CORPUS for _, pasos in c.DIALOGOS for m, _ in pasos if not m.startswith("[")]


def percentiles(tiempos: list[float]) -> dict[str, float]:
    ordenados = sorted(tiempos)

    def p(q: float) -> float:
        return ordenados[min(len(ordenados) - 1, int(round(q * (len(ordenados) - 1))))]

    return {
        "n": len(ordenados),
        "p50": p(0.50),
        "p95": p(0.95),
        "p99": p(0.99),
        "max": ordenados[-1],
        "media": statistics.fmean(ordenados),
    }


def medir_motor(repeticiones: int = 3) -> dict[str, float]:
    from app.bot.motor import MotorConversacional
    from tests.corpus.evaluacion import procesar

    motor = MotorConversacional()
    for mensaje in MENSAJES[:20]:  # precalienta el léxico y las expresiones regulares
        procesar(motor, mensaje)
    tiempos = []
    for _ in range(repeticiones):
        for mensaje in MENSAJES:
            inicio = time.perf_counter()
            procesar(motor, mensaje)
            tiempos.append(time.perf_counter() - inicio)
    return percentiles(tiempos)


def _app_con_demo(carpeta: Path, **config):
    from app import create_app
    from app.config import ConfigPruebas

    class Config(ConfigPruebas):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{carpeta / 'rendimiento.db'}"
        WTF_CSRF_ENABLED = False
        LIMITES_POR_IP = False

    for clave, valor in config.items():
        setattr(Config, clave, valor)
    aplicacion = create_app(Config)
    with aplicacion.app_context():
        from app.datos.demo import cargar_demo

        cargar_demo()
    return aplicacion


def medir_servicio(carpeta: Path) -> dict[str, float]:
    from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
    from app.extensiones import db
    from app.modelos import Comercio

    aplicacion = _app_con_demo(carpeta)
    tiempos = []
    with aplicacion.app_context():
        comercio = db.session.query(Comercio).filter_by(codigo_acceso="CASA26").one()
        primer_mensaje = comercio.texto_primer_mensaje()
        for i, mensaje in enumerate(MENSAJES):
            telefono = f"5493510{i:06d}"
            procesar_mensaje_entrante(MensajeEntrante(telefono=telefono, texto=primer_mensaje))
            inicio = time.perf_counter()
            procesar_mensaje_entrante(MensajeEntrante(telefono=telefono, texto=mensaje))
            tiempos.append(time.perf_counter() - inicio)
        db.session.remove()
        db.engine.dispose()
    return percentiles(tiempos)


def medir_http(carpeta: Path, compradores: int, mensajes: int) -> dict[str, float]:
    import requests
    from waitress.server import create_server

    aplicacion = _app_con_demo(carpeta)
    servidor = create_server(aplicacion, host="127.0.0.1", port=0, threads=8)
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    url = f"http://127.0.0.1:{servidor.effective_port}/simulador/api/mensajes"

    def comprador(numero: int) -> list[float]:
        sesion = requests.Session()
        telefono = f"5493510{900000 + numero:06d}"
        sesion.post(url, json={"telefono": telefono, "texto": "Hola, quiero hacer una consulta. Código: CASA26"})
        tiempos = []
        for i in range(mensajes):
            texto = MENSAJES[(numero * mensajes + i) % len(MENSAJES)]
            inicio = time.perf_counter()
            respuesta = sesion.post(url, json={"telefono": telefono, "texto": texto}, timeout=30)
            tiempos.append(time.perf_counter() - inicio)
            respuesta.raise_for_status()
        return tiempos

    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=compradores) as grupo:
        resultados = list(grupo.map(comprador, range(compradores)))
    duracion = time.perf_counter() - inicio
    servidor.close()
    tiempos = [t for lista in resultados for t in lista]
    medida = percentiles(tiempos)
    medida["por_segundo"] = len(tiempos) / duracion
    return medida


def _ms(segundos: float) -> str:
    return f"{segundos * 1000:.1f} ms".replace(".", ",")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compradores", type=int, default=10, help="Compradores simultáneos en la prueba HTTP")
    parser.add_argument("--mensajes", type=int, default=20, help="Mensajes por comprador en la prueba HTTP")
    args = parser.parse_args()

    os.environ.setdefault("LOG_LEVEL", "WARNING")
    import logging

    logging.disable(logging.WARNING)
    with tempfile.TemporaryDirectory() as temporal:
        carpeta = Path(temporal)
        motor = medir_motor()
        (carpeta / "servicio").mkdir()
        servicio = medir_servicio(carpeta / "servicio")
        (carpeta / "http").mkdir()
        http = medir_http(carpeta / "http", args.compradores, args.mensajes)

    print("### Tiempo de respuesta del bot (RNF04)\n")
    print(
        f"Equipo: {platform.system()} {platform.machine()}, {os.cpu_count()} núcleos, Python "
        f"{platform.python_version()}. {len(MENSAJES)} mensajes de los corpus.\n"
    )
    print("| Medición | Mensajes | Mediana | p95 | p99 | Máximo |")
    print("|---|---|---|---|---|---|")
    filas = [
        ("Motor (sin base de datos)", motor),
        ("Servicio completo con SQLite en disco", servicio),
        (f"HTTP con {args.compradores} compradores simultáneos (waitress, 8 hilos)", http),
    ]
    for nombre, m in filas:
        print(f"| {nombre} | {m['n']} | {_ms(m['p50'])} | {_ms(m['p95'])} | {_ms(m['p99'])} | {_ms(m['max'])} |")
    print(f"\nCon carga se atendieron {http['por_segundo']:.0f} mensajes por segundo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
