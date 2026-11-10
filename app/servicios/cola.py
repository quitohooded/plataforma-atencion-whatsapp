"""Cola de tareas en segundo plano para operaciones asíncronas y resiliencia (Pilar 5).

Permite responder a Meta en menos de 30 ms ante eventos de WhatsApp Webhook y procesar
tareas pesadas en segundo plano dentro del contexto de la aplicación Flask sin requerir
servicios externos pagos como Redis en una máquina virtual de 1 GB de RAM.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from flask import Flask, current_app, has_app_context

log = logging.getLogger(__name__)


class ColaTareas:
    """Gestor de tareas en segundo plano con ThreadPoolExecutor y modo sincrónico."""

    def __init__(self, app: Flask | None = None, max_workers: int = 2):
        self.app = app
        self.max_workers = max_workers
        self._executor: ThreadPoolExecutor | None = None
        self._sincronica: bool | None = None
        self._total_encoladas = 0
        self._total_exitosas = 0
        self._total_fallidas = 0
        self._lock = threading.Lock()
        if app is not None:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Registra la cola de tareas en la aplicación Flask."""
        self.app = app
        self._sincronica = app.config.get("COLA_SINCRONICA", False)
        self.max_workers = app.config.get("COLA_MAX_WORKERS", self.max_workers)
        app.extensions["cola_tareas"] = self
        if not getattr(self, "_atexit_registrado", False):
            atexit.register(self.shutdown, wait=True)
            self._atexit_registrado = True

    @property
    def sincronica(self) -> bool:
        if has_app_context():
            return bool(current_app.config.get("COLA_SINCRONICA", False))
        if self.app is not None:
            return bool(self.app.config.get("COLA_SINCRONICA", False))
        if self._sincronica is not None:
            return self._sincronica
        return False

    @sincronica.setter
    def sincronica(self, valor: bool) -> None:
        self._sincronica = bool(valor)
        if self.app is not None:
            self.app.config["COLA_SINCRONICA"] = self._sincronica

    @property
    def total_encoladas(self) -> int:
        with self._lock:
            return self._total_encoladas

    @property
    def total_exitosas(self) -> int:
        with self._lock:
            return self._total_exitosas

    @property
    def total_fallidas(self) -> int:
        with self._lock:
            return self._total_fallidas

    def _obtener_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None or getattr(self._executor, "_shutdown", False):
                self._executor = ThreadPoolExecutor(
                    max_workers=self.max_workers,
                    thread_name_prefix="cola-worker",
                )
            return self._executor

    def encolar(self, funcion: Callable, *args: Any, **kwargs: Any) -> Any:
        """Encola una tarea para su ejecución.

        - Modo sincrónico (COLA_SINCRONICA=True): ejecuta de inmediato en el hilo actual.
        - Modo asíncrono (COLA_SINCRONICA=False): envía al pool de hilos y ejecuta con app_context.
        """
        with self._lock:
            self._total_encoladas += 1

        if self.sincronica:
            app = self.app or (current_app._get_current_object() if has_app_context() else None)
            if app and not has_app_context():
                with app.app_context():
                    return self._ejecutar_sincronico(funcion, *args, **kwargs)
            return self._ejecutar_sincronico(funcion, *args, **kwargs)

        executor = self._obtener_executor()
        app = self.app or (current_app._get_current_object() if has_app_context() else None)
        return executor.submit(self._ejecutar_con_contexto, app, funcion, *args, **kwargs)

    def _ejecutar_sincronico(self, funcion: Callable, *args: Any, **kwargs: Any) -> Any:
        try:
            res = funcion(*args, **kwargs)
            with self._lock:
                self._total_exitosas += 1
            return res
        except Exception:
            with self._lock:
                self._total_fallidas += 1
            raise

    def _ejecutar_con_contexto(self, app: Flask | None, funcion: Callable, *args: Any, **kwargs: Any) -> Any:
        """Ejecuta la función dentro del contexto de Flask capturando excepciones de forma resiliente."""
        try:
            if app:
                with app.app_context():
                    try:
                        res = funcion(*args, **kwargs)
                    except Exception:
                        from ..extensiones import db

                        with contextlib.suppress(Exception):
                            db.session.rollback()
                        raise
            else:
                res = funcion(*args, **kwargs)

            with self._lock:
                self._total_exitosas += 1
            return res
        except Exception as error:
            with self._lock:
                self._total_fallidas += 1
            log.exception(
                "Error al ejecutar tarea en segundo plano %s: %s",
                getattr(funcion, "__name__", str(funcion)),
                error,
            )
            return None

    def shutdown(self, wait: bool = True) -> None:
        """Cierra el ThreadPoolExecutor de forma limpia."""
        with self._lock:
            if self._executor is not None:
                self._executor.shutdown(wait=wait)
                self._executor = None

    def estado(self) -> dict[str, Any]:
        """Devuelve el estado y las métricas de la cola de tareas."""
        with self._lock:
            return {
                "sincronica": self.sincronica,
                "max_workers": self.max_workers,
                "total_encoladas": self._total_encoladas,
                "total_exitosas": self._total_exitosas,
                "total_fallidas": self._total_fallidas,
                "executor_activo": self._executor is not None and not getattr(self._executor, "_shutdown", False),
            }


cola_tareas = ColaTareas()


def procesar_webhook_asincrono(app: Flask | dict | None, payload: dict | None = None) -> int:
    """Helper para procesar eventos del webhook de WhatsApp (mensajes y estados) dentro del app_context."""
    if isinstance(app, dict) and payload is None:
        payload = app
        app = current_app._get_current_object() if has_app_context() else None

    from ..web.webhook import procesar_eventos_webhook

    if app is not None and not has_app_context():
        with app.app_context():
            return procesar_eventos_webhook(payload or {})
    return procesar_eventos_webhook(payload or {})
