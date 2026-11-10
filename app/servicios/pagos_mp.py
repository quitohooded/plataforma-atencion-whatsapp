"""Servicio de integración con Mercado Pago y Monetización Real (Pilar 1).

Gestiona la suscripción mensual recurrente al Plan Pro, la compra y acreditación
de saldo en la billetera prepaga anti-impagos, la recepción segura de webhooks
y un modo de simulación local para entornos de desarrollo y pruebas automatizadas.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime

import requests
from flask import current_app, url_for
from sqlalchemy import select

from ..extensiones import db
from ..modelos import Comercio, PlanComercio, TransaccionPago
from ..utilidades import tiempo

log = logging.getLogger(__name__)

PRECIOS_PACKS_FIJOS = {
    200: 4500,
    500: 9900,
    2000: 32000,
}
PRECIO_POR_CREDITO_DEFAULT = 20


def obtener_precio_pack(cantidad_creditos: int) -> int:
    """Calcula el precio en pesos ARS para un pack de créditos prepagos."""
    if cantidad_creditos <= 0:
        return 0
    if cantidad_creditos in PRECIOS_PACKS_FIJOS:
        return PRECIOS_PACKS_FIJOS[cantidad_creditos]
    return cantidad_creditos * PRECIO_POR_CREDITO_DEFAULT


def crear_checkout_recarga(comercio: Comercio, cantidad_creditos: int, url_retorno: str) -> dict:
    """Crea una transacción y la preferencia de pago para recargar créditos.

    Si MERCADOPAGO_ACCESS_TOKEN está configurado, interactúa con la API de preferencias
    de Mercado Pago. En caso contrario, genera un enlace al simulador local.
    """
    monto = obtener_precio_pack(cantidad_creditos)
    ahora = tiempo.ahora()

    transaccion = TransaccionPago(
        id_comercio=comercio.id_comercio,
        proveedor="mercadopago",
        tipo="RECARGA_CREDITOS",
        monto=monto,
        estado="PENDIENTE",
        detalle=f"Pack +{cantidad_creditos} créditos IA",
        fecha_creacion=ahora,
        fecha_actualizacion=ahora,
    )
    db.session.add(transaccion)
    db.session.commit()

    token = current_app.config.get("MERCADOPAGO_ACCESS_TOKEN", "").strip()

    if token:
        try:
            url_api = "https://api.mercadopago.com/checkout/preferences"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            body = {
                "items": [
                    {
                        "title": f"Pack +{cantidad_creditos} créditos IA - {comercio.nombre}",
                        "description": f"Recarga de {cantidad_creditos} créditos para respuestas con IA",
                        "quantity": 1,
                        "unit_price": float(monto),
                        "currency_id": "ARS",
                    }
                ],
                "external_reference": str(transaccion.id_transaccion),
                "back_urls": {
                    "success": url_retorno,
                    "pending": url_retorno,
                    "failure": url_retorno,
                },
                "auto_return": "approved",
                "metadata": {
                    "id_comercio": comercio.id_comercio,
                    "id_transaccion": transaccion.id_transaccion,
                    "cantidad_creditos": cantidad_creditos,
                    "tipo": "RECARGA_CREDITOS",
                },
            }
            resp = requests.post(url_api, json=body, headers=headers, timeout=15)
            if resp.status_code in (200, 201):
                datos_mp = resp.json()
                transaccion.id_externo = str(datos_mp.get("id"))
                transaccion.datos_json = json.dumps(datos_mp, ensure_ascii=False)
                db.session.commit()
                checkout_url = datos_mp.get("init_point") or datos_mp.get("sandbox_init_point")
                return {
                    "url_checkout": checkout_url,
                    "id_externo": transaccion.id_externo,
                    "id_transaccion": transaccion.id_transaccion,
                    "modo": "real",
                }
            log.error("Error al crear preferencia en Mercado Pago: HTTP %s: %s", resp.status_code, resp.text)
        except Exception as e:
            log.exception("Excepción conectando a Mercado Pago: %s", e)

    # Modo simulación o fallback seguro
    try:
        checkout_url = url_for("planes.simulador_pago", id_transaccion=transaccion.id_transaccion)
    except RuntimeError:
        checkout_url = f"/plan/simulador-pago?id_transaccion={transaccion.id_transaccion}"
    return {
        "url_checkout": checkout_url,
        "id_externo": None,
        "id_transaccion": transaccion.id_transaccion,
        "modo": "simulacion",
    }


def crear_checkout_suscripcion_pro(comercio: Comercio, email_pagador: str, url_retorno: str) -> dict:
    """Crea una transacción y la suscripción recurrente al Plan Pro.

    Si MERCADOPAGO_ACCESS_TOKEN está configurado, interactúa con la API de Preapproval
    de Mercado Pago. En caso contrario, genera un enlace al simulador local.
    """
    precio_mensual = current_app.config.get("PLAN_PRO_PRECIO_MENSUAL", 14900)
    ahora = tiempo.ahora()

    transaccion = TransaccionPago(
        id_comercio=comercio.id_comercio,
        proveedor="mercadopago",
        tipo="SUSCRIPCION",
        monto=precio_mensual,
        estado="PENDIENTE",
        detalle="Plan Pro Mensual - 1.000 respuestas IA/mes",
        fecha_creacion=ahora,
        fecha_actualizacion=ahora,
    )
    db.session.add(transaccion)
    db.session.commit()

    token = current_app.config.get("MERCADOPAGO_ACCESS_TOKEN", "").strip()

    if token:
        try:
            url_api = "https://api.mercadopago.com/preapproval"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            body = {
                "reason": "Plan Pro Mensual - Respondé",
                "auto_recurring": {
                    "frequency": 1,
                    "frequency_type": "months",
                    "transaction_amount": float(precio_mensual),
                    "currency_id": "ARS",
                },
                "back_url": url_retorno,
                "payer_email": email_pagador or "cliente@ejemplo.com",
                "external_reference": str(transaccion.id_transaccion),
            }
            resp = requests.post(url_api, json=body, headers=headers, timeout=15)
            if resp.status_code in (200, 201):
                datos_mp = resp.json()
                transaccion.id_externo = str(datos_mp.get("id"))
                transaccion.datos_json = json.dumps(datos_mp, ensure_ascii=False)
                db.session.commit()
                checkout_url = datos_mp.get("init_point")
                return {
                    "url_checkout": checkout_url,
                    "id_externo": transaccion.id_externo,
                    "id_transaccion": transaccion.id_transaccion,
                    "modo": "real",
                }
            log.error("Error al crear suscripción en Mercado Pago: HTTP %s: %s", resp.status_code, resp.text)
        except Exception as e:
            log.exception("Excepción conectando a Mercado Pago (preapproval): %s", e)

    # Modo simulación o fallback seguro
    try:
        checkout_url = url_for("planes.simulador_pago", id_transaccion=transaccion.id_transaccion)
    except RuntimeError:
        checkout_url = f"/plan/simulador-pago?id_transaccion={transaccion.id_transaccion}"
    return {
        "url_checkout": checkout_url,
        "id_externo": None,
        "id_transaccion": transaccion.id_transaccion,
        "modo": "simulacion",
    }


def acreditar_transaccion_aprobada(
    transaccion: TransaccionPago, ahora: datetime, raw_data: dict | None = None
) -> None:
    """Acredita los efectos de una transacción aprobada de forma idempotente."""
    if transaccion.estado == "APROBADO":
        return

    transaccion.estado = "APROBADO"
    transaccion.fecha_actualizacion = ahora
    if raw_data:
        transaccion.datos_json = json.dumps(raw_data, ensure_ascii=False)

    comercio = transaccion.comercio

    if transaccion.tipo == "RECARGA_CREDITOS":
        cantidad = 0
        if raw_data and isinstance(raw_data, dict):
            metadata = raw_data.get("metadata") or {}
            cantidad = metadata.get("cantidad_creditos") or 0

        if not cantidad:
            m = re.search(r"(\d+)\s+cr[ée]ditos", transaccion.detalle, re.IGNORECASE)
            if m:
                cantidad = int(m.group(1))
            elif transaccion.monto > 0:
                if transaccion.monto == 4500:
                    cantidad = 200
                elif transaccion.monto == 9900:
                    cantidad = 500
                elif transaccion.monto == 32000:
                    cantidad = 2000
                else:
                    cantidad = transaccion.monto // PRECIO_POR_CREDITO_DEFAULT

        comercio.saldo_creditos += max(0, cantidad)
        log.info(
            "Recarga de %s créditos acreditada con éxito al comercio %s (#%s). Nuevo saldo: %s",
            cantidad,
            comercio.nombre,
            comercio.id_comercio,
            comercio.saldo_creditos,
        )

    elif transaccion.tipo == "SUSCRIPCION":
        comercio.plan = PlanComercio.PRO
        comercio.ia_cuota_semanal = 250
        comercio.ia_cuota_interna = 100
        comercio.ia_semana_inicio = ahora.date()
        comercio.ia_usados_semana = 0
        if transaccion.id_externo:
            comercio.id_suscripcion_externa = transaccion.id_externo
        log.info(
            "Plan Pro Mensual activado con éxito para el comercio %s (#%s). Cuota semanal: 250 respuestas IA.",
            comercio.nombre,
            comercio.id_comercio,
        )

    db.session.commit()


def cancelar_suscripcion_comercio(comercio: Comercio, ahora: datetime) -> None:
    """Cancela la suscripción Pro del comercio y lo degrada al Plan Gratuito."""
    token = current_app.config.get("MERCADOPAGO_ACCESS_TOKEN", "").strip()
    if token and comercio.id_suscripcion_externa:
        try:
            url_api = f"https://api.mercadopago.com/preapproval/{comercio.id_suscripcion_externa}"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            requests.put(url_api, json={"status": "cancelled"}, headers=headers, timeout=10)
        except Exception as e:
            log.warning(
                "No se pudo cancelar el preapproval %s en Mercado Pago: %s",
                comercio.id_suscripcion_externa,
                e,
            )

    if comercio.plan == PlanComercio.PRO:
        comercio.plan = PlanComercio.FREE
        comercio.ia_cuota_semanal = 0
        comercio.ia_usados_semana = 0
        comercio.id_suscripcion_externa = None
        db.session.commit()
        log.info(
            "Suscripción cancelada para el comercio %s (#%s). Ahora opera bajo Plan Gratuito.",
            comercio.nombre,
            comercio.id_comercio,
        )


def _verificar_firma_webhook(encabezados: dict, secreto: str, data_id: str) -> bool:
    """Valida el encabezado x-signature de Mercado Pago con el secreto configurado."""
    x_signature = encabezados.get("x-signature") or encabezados.get("X-Signature")
    if not x_signature:
        return False

    partes = dict(item.strip().split("=", 1) for item in x_signature.split(",") if "=" in item)
    ts = partes.get("ts")
    v1 = partes.get("v1")
    if not ts or not v1:
        return False

    x_request_id = encabezados.get("x-request-id") or encabezados.get("X-Request-Id") or ""
    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
    firma_calculada = hmac.new(secreto.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(firma_calculada, v1)


def procesar_webhook_mp(datos: dict, encabezados: dict, ahora: datetime) -> bool:
    """Procesa una notificación entrante de Mercado Pago (o del simulador local)."""
    if not datos:
        return False

    # 1. Identificar si es un evento directo de simulación o prueba local
    id_transaccion_sim = datos.get("id_transaccion")
    if id_transaccion_sim:
        transaccion = db.session.get(TransaccionPago, int(id_transaccion_sim))
        if not transaccion:
            return False
        estado_raw = str(datos.get("estado") or datos.get("status") or "").lower()
        if datos.get("id_externo"):
            transaccion.id_externo = str(datos["id_externo"])
        if estado_raw in ("approved", "aprobado", "authorized", "autorizado"):
            acreditar_transaccion_aprobada(transaccion, ahora, raw_data=datos)
            return True
        elif estado_raw in ("rejected", "rechazado", "cancelled", "cancelado"):
            transaccion.estado = "RECHAZADO" if "rechaz" in estado_raw or "reject" in estado_raw else "CANCELADO"
            transaccion.fecha_actualizacion = ahora
            transaccion.datos_json = json.dumps(datos, ensure_ascii=False)
            db.session.commit()
            return True

    # 2. Identificar datos del evento Mercado Pago (IPN o Webhooks v1/v2)
    evento_tipo = str(datos.get("type") or datos.get("topic") or datos.get("action") or "").lower()
    data_id = str(datos.get("data", {}).get("id") or datos.get("id") or "")
    if not data_id:
        return False

    secreto = current_app.config.get("MERCADOPAGO_WEBHOOK_SECRET", "").strip()
    if secreto and not _verificar_firma_webhook(encabezados, secreto, data_id):
        log.warning("Firma inválida en webhook de Mercado Pago para evento %s", data_id)
        return False

    token = current_app.config.get("MERCADOPAGO_ACCESS_TOKEN", "").strip()

    # Buscar transacción preexistente por id_externo
    transaccion = db.session.scalar(
        select(TransaccionPago).where(TransaccionPago.id_externo == data_id)
    )

    if token:
        headers = {"Authorization": f"Bearer {token}"}
        if "payment" in evento_tipo:
            try:
                resp = requests.get(f"https://api.mercadopago.com/v1/payments/{data_id}", headers=headers, timeout=10)
                if resp.status_code == 200:
                    pdata = resp.json()
                    ext_ref = pdata.get("external_reference")
                    if not transaccion and ext_ref:
                        with contextlib.suppress(TypeError, ValueError):
                            transaccion = db.session.get(TransaccionPago, int(ext_ref))
                    if transaccion:
                        transaccion.id_externo = data_id
                        status = pdata.get("status")
                        if status == "approved":
                            acreditar_transaccion_aprobada(transaccion, ahora, raw_data=pdata)
                        elif status in ("rejected", "cancelled"):
                            transaccion.estado = status.upper()
                            transaccion.fecha_actualizacion = ahora
                            transaccion.datos_json = json.dumps(pdata, ensure_ascii=False)
                            db.session.commit()
                        return True
            except Exception as e:
                log.exception("Error consultando payment %s en Mercado Pago: %s", data_id, e)

        elif "preapproval" in evento_tipo or "subscription" in evento_tipo:
            try:
                resp = requests.get(f"https://api.mercadopago.com/preapproval/{data_id}", headers=headers, timeout=10)
                if resp.status_code == 200:
                    sdata = resp.json()
                    ext_ref = sdata.get("external_reference")
                    if not transaccion and ext_ref:
                        with contextlib.suppress(TypeError, ValueError):
                            transaccion = db.session.get(TransaccionPago, int(ext_ref))
                    if transaccion:
                        transaccion.id_externo = data_id
                        status = sdata.get("status")
                        if status in ("authorized", "approved"):
                            acreditar_transaccion_aprobada(transaccion, ahora, raw_data=sdata)
                        elif status == "cancelled":
                            transaccion.estado = "CANCELADO"
                            transaccion.fecha_actualizacion = ahora
                            transaccion.datos_json = json.dumps(sdata, ensure_ascii=False)
                            db.session.commit()
                            cancelar_suscripcion_comercio(transaccion.comercio, ahora)
                        return True
            except Exception as e:
                log.exception("Error consultando preapproval %s en Mercado Pago: %s", data_id, e)

    else:
        # Modo simulación / pruebas sin llamadas HTTP externas
        if not transaccion:
            ext_ref = datos.get("external_reference") or datos.get("data", {}).get("external_reference")
            if ext_ref:
                with contextlib.suppress(TypeError, ValueError):
                    transaccion = db.session.get(TransaccionPago, int(ext_ref))

        if transaccion:
            transaccion.id_externo = data_id
            status = str(datos.get("status") or datos.get("data", {}).get("status") or "approved").lower()
            if status in ("approved", "authorized"):
                acreditar_transaccion_aprobada(transaccion, ahora, raw_data=datos)
            else:
                transaccion.estado = status.upper()
                transaccion.fecha_actualizacion = ahora
                transaccion.datos_json = json.dumps(datos, ensure_ascii=False)
                db.session.commit()
            return True

    return False
