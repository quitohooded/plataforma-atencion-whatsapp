"""Reglas de negocio del panel de administración, independientes de la interfaz web."""


class ErrorValidacion(Exception):
    """Error de validación con un mensaje apto para mostrar al responsable del comercio."""

    def __init__(self, mensaje: str, campos: list[str] | None = None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.campos = campos or []
