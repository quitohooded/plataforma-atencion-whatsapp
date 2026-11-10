"""Servicio de Intercambio y Provisión de Meta Embedded Signup (WhatsApp Cloud API).

Permite conectar un número propio de WhatsApp en 1 solo clic para el comerciante,
sin que tenga que lidiar con tokens técnicos, identificadores complejos ni la Graph API.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from flask import current_app

from ..extensiones import db
from ..modelos import Comercio

log = logging.getLogger(__name__)

URL_GRAPH = "https://graph.facebook.com"


class ErrorMetaSignup(Exception):
    """Excepción para errores controlados de Meta Embedded Signup."""


def intercambiar_codigo_embedded(
    comercio: Comercio,
    codigo_auth: str,
    waba_id: str | None = None,
    phone_number_id: str | None = None,
) -> dict[str, Any]:
    """Intercambia el auth code del popup de Meta y aprovisiona la línea de WhatsApp del comercio.

    Modo Real (cuando META_APP_ID y WHATSAPP_APP_SECRET están configurados):
    - Intercambia `codigo_auth` por el `access_token` en Graph API (/oauth/access_token).
    - Inspecciona el token para asociar el WABA si no viene en el payload (/debug_token).
    - Obtiene los números telefónicos del WABA (/phone_numbers).
    - Suscribe automáticamente los webhooks de nuestra plataforma (/subscribed_apps).
    - Guarda las credenciales y el número en el Comercio.

    Modo Simulación / Local (cuando no hay credenciales de Meta configuradas):
    - Aprovisiona de forma segura datos simulados para permitir demos y pruebas locales.
    """
    codigo_auth = (codigo_auth or "").strip()
    if not codigo_auth:
        raise ValueError("Código de autorización de Meta requerido.")

    cfg = current_app.config
    app_id = (cfg.get("META_APP_ID") or "").strip()
    app_secret = (cfg.get("WHATSAPP_APP_SECRET") or "").strip()
    version = (cfg.get("WHATSAPP_API_VERSION") or "v23.0").strip()
    system_user_token = (cfg.get("META_SYSTEM_USER_TOKEN") or "").strip()

    es_real = bool(app_id and app_secret)

    if es_real:
        return _intercambiar_real(
            comercio=comercio,
            codigo_auth=codigo_auth,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            app_id=app_id,
            app_secret=app_secret,
            version=version,
            system_user_token=system_user_token,
        )

    return _intercambiar_simulado(
        comercio=comercio,
        codigo_auth=codigo_auth,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
    )


def _intercambiar_simulado(
    comercio: Comercio,
    codigo_auth: str,
    waba_id: str | None = None,
    phone_number_id: str | None = None,
) -> dict[str, Any]:
    """Aprovisionamiento simulado para pruebas locales y demostraciones."""
    if codigo_auth.lower() in ("invalido", "error", "expired"):
        raise ValueError("Código de autorización de Meta inválido o expirado.")

    phone_id = phone_number_id or "10987654321"
    w_id = waba_id or "waba_demo_123"
    token = "token_meta_simulado"
    numero_publico = "5493512345678"

    comercio.whatsapp_phone_number_id = phone_id
    comercio.whatsapp_waba_id = w_id
    comercio.whatsapp_token = token
    comercio.whatsapp_numero_publico = numero_publico

    db.session.commit()
    log.info(
        "Línea de WhatsApp aprovisionada en modo simulado para comercio %s (id=%s)",
        comercio.nombre,
        comercio.id_comercio,
    )

    return {
        "ok": True,
        "comercio": comercio.nombre,
        "numero": comercio.whatsapp_numero_publico,
    }


def _intercambiar_real(
    comercio: Comercio,
    codigo_auth: str,
    waba_id: str | None,
    phone_number_id: str | None,
    app_id: str,
    app_secret: str,
    version: str,
    system_user_token: str,
) -> dict[str, Any]:
    """Flujo real con Meta Graph API."""
    token_url = f"{URL_GRAPH}/{version}/oauth/access_token"
    try:
        resp = requests.get(
            token_url,
            params={
                "client_id": app_id,
                "client_secret": app_secret,
                "code": codigo_auth,
            },
            timeout=10,
        )
    except requests.RequestException as err:
        log.error("Error de conexión al canjear código con Meta: %s", err)
        raise ValueError(f"Error de conexión con Meta: {err}") from err

    try:
        datos_token = resp.json()
    except Exception:
        datos_token = {}

    if resp.status_code >= 400 or "error" in datos_token:
        error_msg = datos_token.get("error", {}).get("message") or resp.text
        log.warning("Meta OAuth rechazó el código: %s", error_msg)
        raise ValueError(f"Error de Meta OAuth: {error_msg}")

    access_token = datos_token.get("access_token")
    if not access_token:
        raise ValueError("Meta no devolvió un access_token válido.")

    # Si waba_id no vino en el payload, inspeccionar el token con /debug_token
    if not waba_id:
        token_debug = system_user_token or access_token
        try:
            resp_debug = requests.get(
                f"{URL_GRAPH}/{version}/debug_token",
                params={"input_token": access_token, "access_token": token_debug},
                timeout=10,
            )
            if resp_debug.status_code == 200:
                dbg_data = resp_debug.json().get("data", {})
                granular = dbg_data.get("granular_scopes", [])
                for g_scope in granular:
                    if g_scope.get("scope") in ("whatsapp_business_management", "whatsapp_business_messaging"):
                        targets = g_scope.get("target_ids", [])
                        if targets:
                            waba_id = targets[0]
                            break
                if not waba_id:
                    waba_id = dbg_data.get("waba_id") or dbg_data.get("target_id")
        except requests.RequestException as err:
            log.warning("Error al inspeccionar debug_token en Meta: %s", err)

    if not waba_id:
        raise ValueError("No se pudo determinar el WABA ID asociado a la cuenta de WhatsApp.")

    # Si phone_number_id no vino en el payload, consultar los números de este WABA
    display_phone_number = None
    if not phone_number_id:
        try:
            resp_phones = requests.get(
                f"{URL_GRAPH}/{version}/{waba_id}/phone_numbers",
                params={"access_token": access_token},
                timeout=10,
            )
            if resp_phones.status_code == 200:
                phones_data = resp_phones.json().get("data", [])
                if phones_data:
                    phone_number_id = str(phones_data[0].get("id"))
                    display_phone_number = phones_data[0].get("display_phone_number")
        except requests.RequestException as err:
            log.warning("Error al listar números del WABA %s: %s", waba_id, err)

    if not phone_number_id:
        raise ValueError(f"No se encontró ningún número de WhatsApp registrado en el WABA {waba_id}.")

    # Si tenemos phone_number_id pero no display_phone_number, consultar el número
    if not display_phone_number:
        try:
            resp_num = requests.get(
                f"{URL_GRAPH}/{version}/{phone_number_id}",
                params={"fields": "display_phone_number,verified_name", "access_token": access_token},
                timeout=10,
            )
            if resp_num.status_code == 200:
                display_phone_number = resp_num.json().get("display_phone_number")
        except Exception as err:
            log.warning("Error al obtener datos del número %s: %s", phone_number_id, err)

    if not display_phone_number:
        display_phone_number = "".join(ch for ch in str(phone_number_id) if ch.isdigit())

    # Suscribir automáticamente nuestra URL de webhook al WABA del comercio
    token_sub = system_user_token or access_token
    try:
        resp_sub = requests.post(
            f"{URL_GRAPH}/{version}/{waba_id}/subscribed_apps",
            params={"access_token": token_sub},
            timeout=10,
        )
        if resp_sub.status_code >= 400:
            log.warning("Meta subscribed_apps retornó error %s: %s", resp_sub.status_code, resp_sub.text)
    except requests.RequestException as err:
        log.warning("Error de red al suscribir webhook del WABA %s: %s", waba_id, err)

    comercio.whatsapp_phone_number_id = str(phone_number_id)
    comercio.whatsapp_waba_id = str(waba_id)
    comercio.whatsapp_token = access_token
    comercio.whatsapp_numero_publico = display_phone_number
    db.session.commit()

    log.info(
        "WhatsApp oficial conectado exitosamente para comercio %s: phone_id=%s, waba_id=%s, numero=%s",
        comercio.nombre,
        phone_number_id,
        waba_id,
        display_phone_number,
    )

    return {
        "ok": True,
        "comercio": comercio.nombre,
        "numero": comercio.whatsapp_numero_publico,
    }


def desconectar_whatsapp_comercio(comercio: Comercio) -> dict[str, Any]:
    """Desconecta la línea propia de WhatsApp del comercio y limpia sus credenciales."""
    cfg = current_app.config
    app_id = (cfg.get("META_APP_ID") or "").strip()
    app_secret = (cfg.get("WHATSAPP_APP_SECRET") or "").strip()
    version = (cfg.get("WHATSAPP_API_VERSION") or "v23.0").strip()
    system_user_token = (cfg.get("META_SYSTEM_USER_TOKEN") or "").strip()

    if app_id and app_secret and comercio.whatsapp_waba_id:
        token_desuscribir = system_user_token or comercio.whatsapp_token
        if token_desuscribir:
            try:
                requests.delete(
                    f"{URL_GRAPH}/{version}/{comercio.whatsapp_waba_id}/subscribed_apps",
                    params={"access_token": token_desuscribir},
                    timeout=10,
                )
            except Exception as err:
                log.warning("No se pudo desuscribir webhook de Meta para WABA %s: %s", comercio.whatsapp_waba_id, err)

    comercio.whatsapp_phone_number_id = None
    comercio.whatsapp_waba_id = None
    comercio.whatsapp_token = None
    comercio.whatsapp_numero_publico = None
    db.session.commit()

    log.info("Línea de WhatsApp desconectada para comercio %s (id=%s)", comercio.nombre, comercio.id_comercio)
    return {"ok": True}
