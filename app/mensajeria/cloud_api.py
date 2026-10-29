"""Cliente de WhatsApp Business Platform (Cloud API).

Envía mensajes de texto y mensajes interactivos con botones mediante la Graph API y
valida la firma de los eventos que Meta envía al webhook. Si el token o el
identificador del número no están configurados, el cliente queda en «modo sin envío»:
registra las respuestas en el log y el resto del sistema funciona igual (útil con el
simulador).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

import requests
from flask import current_app

log = logging.getLogger(__name__)

URL_GRAPH = "https://graph.facebook.com"
LARGO_MAXIMO_TEXTO = 4096
LARGO_MAXIMO_INTERACTIVO = 1024


class ErrorEnvio(Exception):
    def __init__(self, mensaje: str, codigo: int | None = None):
        super().__init__(mensaje)
        self.codigo = codigo


@dataclass
class ClienteWhatsApp:
    token: str
    phone_number_id: str
    version: str = "v23.0"
    quitar_9_argentina: bool = True
    timeout: float = 10.0

    @classmethod
    def desde_config(cls) -> ClienteWhatsApp:
        cfg = current_app.config
        return cls(
            token=cfg.get("WHATSAPP_TOKEN", ""),
            phone_number_id=cfg.get("WHATSAPP_PHONE_NUMBER_ID", ""),
            version=cfg.get("WHATSAPP_API_VERSION", "v23.0"),
            quitar_9_argentina=cfg.get("WHATSAPP_AR_QUITAR_9", True),
        )

    @property
    def configurado(self) -> bool:
        return bool(self.token and self.phone_number_id)

    def destino(self, telefono: str) -> str:
        """Los números móviles argentinos llegan como 549 + área + número. En modo de prueba
        la API solo los acepta sin el 9 (54 + área + número)."""
        digitos = "".join(ch for ch in telefono if ch.isdigit())
        if self.quitar_9_argentina and digitos.startswith("549") and len(digitos) == 13:
            return "54" + digitos[3:]
        return digitos

    def enviar(self, telefono: str, respuesta) -> str | None:
        """Envía una respuesta del bot: con botones si los tiene y caben, o como texto.

        Si WhatsApp rechaza el mensaje interactivo, se reintenta como texto con la
        instrucción para escribir la opción (``Respuesta.texto_plano``).
        """
        botones = getattr(respuesta, "botones", ())
        if botones and len(respuesta.texto) <= LARGO_MAXIMO_INTERACTIVO and all(len(b.titulo) <= 20 for b in botones):
            try:
                return self.enviar_botones(telefono, respuesta.texto, botones)
            except ErrorEnvio as error:
                if error.codigo == 131030:
                    raise
                log.warning("No se pudo enviar el mensaje con botones (%s); se envía como texto.", error)
        return self.enviar_texto(telefono, respuesta.texto_plano() if botones else respuesta.texto)

    def enviar_botones(self, telefono: str, texto: str, botones) -> str | None:
        """Mensaje interactivo con hasta tres botones de respuesta."""
        if not self.configurado:
            titulos = " / ".join(b.titulo for b in botones)
            log.info("[modo sin envío] Respuesta para %s: %s [%s]", telefono, texto.replace("\n", " | "), titulos)
            return None
        return self._publicar(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": self.destino(telefono),
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": texto[:LARGO_MAXIMO_INTERACTIVO]},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": b.id[:256], "title": b.titulo[:20]}} for b in botones[:3]
                        ]
                    },
                },
            }
        )

    def enviar_texto(self, telefono: str, texto: str) -> str | None:
        """Envía un mensaje de texto. Devuelve el id del mensaje de WhatsApp o None en modo sin envío."""
        if not self.configurado:
            log.info("[modo sin envío] Respuesta para %s: %s", telefono, texto.replace("\n", " | "))
            return None
        return self._publicar(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": self.destino(telefono),
                "type": "text",
                # Vista previa del enlace cuando el texto lo trae (por ejemplo, el catálogo).
                "text": {"preview_url": "http" in texto, "body": texto[:LARGO_MAXIMO_TEXTO]},
            }
        )

    def marcar_leido(self, id_mensaje: str) -> None:
        """Marca como leído un mensaje del comprador (doble tilde azul en su WhatsApp)."""
        if not self.configurado or not id_mensaje:
            return
        self._publicar({"messaging_product": "whatsapp", "status": "read", "message_id": id_mensaje})

    def _publicar(self, cuerpo: dict) -> str | None:
        url = f"{URL_GRAPH}/{self.version}/{self.phone_number_id}/messages"
        try:
            respuesta = requests.post(
                url,
                json=cuerpo,
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.token}"},
            )
        except requests.RequestException as error:
            raise ErrorEnvio(f"No fue posible conectar con WhatsApp: {error}") from error

        if respuesta.status_code >= 400:
            try:
                detalle = respuesta.json().get("error", {})
            except ValueError:
                detalle = {}
            codigo = detalle.get("code")
            mensaje = detalle.get("message") or respuesta.text[:300]
            if codigo == 131030:
                mensaje += (
                    " (el número no está en la lista de destinatarios permitidos del número de prueba: "
                    "agréguelo en la configuración de la API de WhatsApp en Meta)"
                )
            raise ErrorEnvio(f"WhatsApp rechazó el envío: {mensaje}", codigo)

        try:
            return respuesta.json()["messages"][0]["id"]
        except (ValueError, KeyError, IndexError):
            return None


def firma_valida(cuerpo: bytes, encabezado: str | None, secreto: str, permitir_sin_clave: bool = False) -> bool:
    """Valida X-Hub-Signature-256 (HMAC SHA-256 del cuerpo con la clave secreta de la app).

    Sin clave configurada se rechaza todo (cualquiera podría inventar mensajes), salvo que se
    permita explícitamente para pruebas locales (WHATSAPP_PERMITIR_SIN_FIRMA)."""
    if not secreto:
        return permitir_sin_clave
    if not encabezado or not encabezado.startswith("sha256="):
        return False
    esperado = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, encabezado.split("=", 1)[1])


@dataclass
class EventoMensaje:
    id_externo: str
    telefono: str
    nombre: str | None
    texto: str
    timestamp: int | None
    tipo: str = "text"
    boton: str | None = None


def _contenido(mensaje: dict) -> tuple[str, str, str | None]:
    """Tipo, texto e identificador de botón de un mensaje entrante."""
    tipo = mensaje.get("type") or "unsupported"
    if tipo == "text":
        return tipo, (mensaje.get("text") or {}).get("body", ""), None
    if tipo == "button":
        boton = mensaje.get("button") or {}
        return tipo, boton.get("text", ""), boton.get("payload") or None
    if tipo == "interactive":
        interactivo = mensaje.get("interactive") or {}
        respuesta = interactivo.get("button_reply") or interactivo.get("list_reply") or {}
        return tipo, respuesta.get("title", ""), respuesta.get("id") or None
    if tipo in {"image", "video", "document"}:
        # Las imágenes y los documentos pueden traer un texto (caption).
        return tipo, (mensaje.get(tipo) or {}).get("caption", "") or "", None
    if tipo == "reaction":
        return tipo, (mensaje.get("reaction") or {}).get("emoji", "") or "", None
    return tipo, "", None


# Estados de entrega de WhatsApp y su nombre en el modelo (Mensaje.estado_envio).
ESTADOS_WHATSAPP = {"sent": "enviado", "delivered": "entregado", "read": "leido", "failed": "fallido"}


@dataclass
class EstadoEntrega:
    id_externo: str
    estado: str  # enviado, entregado, leido o fallido
    destinatario: str
    error: str | None = None


def extraer_estados(payload: dict) -> list[EstadoEntrega]:
    """Estados de entrega de los mensajes enviados (``statuses`` del webhook)."""
    estados: list[EstadoEntrega] = []
    for entrada in payload.get("entry", []) or []:
        for cambio in entrada.get("changes", []) or []:
            for item in (cambio.get("value", {}) or {}).get("statuses", []) or []:
                estado = ESTADOS_WHATSAPP.get(item.get("status", ""))
                if not estado or not item.get("id"):
                    continue
                error = None
                errores = item.get("errors") or []
                if errores:
                    primero = errores[0] or {}
                    detalle = (primero.get("error_data") or {}).get("details") or primero.get("message") or ""
                    error = f"{primero.get('code', '?')} {primero.get('title', '')}: {detalle}".strip(": ")
                estados.append(EstadoEntrega(item["id"], estado, item.get("recipient_id", ""), error))
    return estados


def extraer_mensajes(payload: dict) -> list[EventoMensaje]:
    """Obtiene los mensajes entrantes del cuerpo del webhook. Ignora estados de entrega."""
    eventos: list[EventoMensaje] = []
    for entrada in payload.get("entry", []) or []:
        for cambio in entrada.get("changes", []) or []:
            valor = cambio.get("value", {}) or {}
            nombres = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in valor.get("contacts", []) or []}
            for mensaje in valor.get("messages", []) or []:
                tipo, texto, boton = _contenido(mensaje)
                telefono = mensaje.get("from", "")
                try:
                    timestamp = int(mensaje.get("timestamp")) if mensaje.get("timestamp") else None
                except ValueError:
                    timestamp = None
                eventos.append(
                    EventoMensaje(
                        id_externo=mensaje.get("id", ""),
                        telefono=telefono,
                        nombre=nombres.get(telefono),
                        texto=texto,
                        timestamp=timestamp,
                        tipo=tipo,
                        boton=boton,
                    )
                )
    return eventos
