"""Cliente de WhatsApp Business Platform (Cloud API).

Envía mensajes de texto mediante la Graph API y valida la firma de los eventos
que Meta envía al webhook. Si el token o el identificador del número no están
configurados, el cliente queda en «modo sin envío»: registra las respuestas en el
log y el resto del sistema funciona igual (útil con el simulador).
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

    def enviar_texto(self, telefono: str, texto: str) -> str | None:
        """Envía un mensaje de texto. Devuelve el id del mensaje de WhatsApp o None en modo sin envío."""
        if not self.configurado:
            log.info("[modo sin envío] Respuesta para %s: %s", telefono, texto.replace("\n", " | "))
            return None

        url = f"{URL_GRAPH}/{self.version}/{self.phone_number_id}/messages"
        cuerpo = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.destino(telefono),
            "type": "text",
            "text": {"preview_url": False, "body": texto[:4096]},
        }
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


def firma_valida(cuerpo: bytes, encabezado: str | None, secreto: str) -> bool:
    """Valida X-Hub-Signature-256 (HMAC SHA-256 del cuerpo con la clave secreta de la app)."""
    if not secreto:
        return True
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


_TIPOS = {
    "image": "imagen",
    "audio": "audio",
    "video": "video",
    "document": "documento",
    "sticker": "sticker",
    "location": "ubicación",
    "contacts": "contacto",
}


def extraer_mensajes(payload: dict) -> list[EventoMensaje]:
    """Obtiene los mensajes entrantes del cuerpo del webhook. Ignora estados de entrega."""
    eventos: list[EventoMensaje] = []
    for entrada in payload.get("entry", []) or []:
        for cambio in entrada.get("changes", []) or []:
            valor = cambio.get("value", {}) or {}
            nombres = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in valor.get("contacts", []) or []}
            for mensaje in valor.get("messages", []) or []:
                tipo = mensaje.get("type")
                if tipo == "text":
                    texto = (mensaje.get("text") or {}).get("body", "")
                elif tipo == "button":
                    texto = (mensaje.get("button") or {}).get("text", "")
                elif tipo == "interactive":
                    interactivo = mensaje.get("interactive") or {}
                    respuesta = interactivo.get("button_reply") or interactivo.get("list_reply") or {}
                    texto = respuesta.get("title", "")
                else:
                    texto = f"[Mensaje de tipo {_TIPOS.get(tipo, tipo or 'desconocido')}]"
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
                    )
                )
    return eventos
