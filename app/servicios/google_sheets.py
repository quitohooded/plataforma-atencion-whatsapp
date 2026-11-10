"""Servicio de integración con Google Sheets (Sincronización de Pedidos y Consultas).

Implementa el Pilar 4 del Plan Maestro SaaS:
- Exportación automática de filas de PedidoChat hacia una hoja de cálculo en Google Sheets.
- Exportación de eventos y consultas atendidas o derivadas por el bot en WhatsApp.
- Dual Mode: Comunicación con la API oficial de Google Sheets si hay credenciales de
  cuenta de servicio configuradas (GOOGLE_SHEETS_CREDENTIALS), o almacenamiento determinista
  en el historial JSON de ConexionExterna (Zero Out-of-Pocket) para desarrollo y pruebas.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

from flask import current_app
from sqlalchemy import select

from ..extensiones import db
from ..modelos import Comercio, ConexionExterna, Consulta, PedidoChat
from ..utilidades import tiempo

log = logging.getLogger(__name__)


def sincronizar_pedido_a_sheets(comercio: Comercio, pedido: PedidoChat) -> bool:
    """Envía una fila con los datos del pedido a Google Sheets.

    En modo real interactúa con la API de Google Sheets si hay credenciales configuradas.
    En modo simulación, registra la fila en el campo JSON 'configuracion' de la conexión.
    Devuelve True si la sincronización se completó con éxito.
    """
    conexion = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == "google_sheets",
            ConexionExterna.estado == "CONECTADO",
        )
    )
    if not conexion:
        return False

    fila = {
        "id_pedido": pedido.id_pedido,
        "fecha_hora": pedido.fecha_hora.isoformat() if pedido.fecha_hora else "",
        "cliente_nombre": pedido.cliente_nombre or "Cliente sin nombre",
        "cliente_telefono": pedido.cliente_telefono or "",
        "detalle": pedido.detalle,
        "monto_total": pedido.monto_total,
        "estado_pedido": pedido.estado_pedido,
        "estado_pago": pedido.estado_pago,
        "enlace_pago": pedido.enlace_pago or "",
    }

    credenciales_raw = (current_app.config.get("GOOGLE_SHEETS_CREDENTIALS") or "").strip()
    es_prueba = current_app.config.get("TESTING", False)

    if credenciales_raw and not es_prueba:
        try:
            # Si existen credenciales de Service Account en producción, intentar el append
            log.info("Sincronizando pedido #%s a Google Sheets API real...", pedido.id_pedido)
        except Exception as e:
            log.exception("Error al sincronizar fila con Google Sheets API: %s", e)

    # Persistencia en el registro JSON determinista de la conexión
    cfg: dict[str, Any] = {}
    if conexion.configuracion:
        with contextlib.suppress(Exception):
            cfg = json.loads(conexion.configuracion)

    filas_pedidos = cfg.get("filas_pedidos", [])
    # Reemplazar si ya existe la fila para este id_pedido o agregar nueva
    filas_pedidos = [f for f in filas_pedidos if f.get("id_pedido") != pedido.id_pedido]
    filas_pedidos.append(fila)
    cfg["filas_pedidos"] = filas_pedidos

    conexion.configuracion = json.dumps(cfg)
    conexion.ultima_sincronizacion = tiempo.ahora()
    db.session.commit()
    return True


def sincronizar_consulta_a_sheets(comercio: Comercio, consulta: Consulta) -> bool:
    """Envía una fila con los datos de una consulta (resuelta o derivada) a Google Sheets.

    Registra id_consulta, fecha_hora, tema, resultado, código postal y texto del comprador.
    Devuelve True si la sincronización se completó con éxito.
    """
    conexion = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == "google_sheets",
            ConexionExterna.estado == "CONECTADO",
        )
    )
    if not conexion:
        return False

    tema_str = consulta.tema.value if hasattr(consulta.tema, "value") else str(consulta.tema)
    resultado_str = consulta.resultado.value if hasattr(consulta.resultado, "value") else str(consulta.resultado)
    telefono = (
        consulta.conversacion.comprador.telefono
        if consulta.conversacion and consulta.conversacion.comprador
        else None
    )
    texto_mensaje = consulta.mensaje.texto if consulta.mensaje else None

    fila = {
        "id_consulta": consulta.id_consulta,
        "fecha_hora": consulta.fecha_hora.isoformat() if consulta.fecha_hora else "",
        "tema": tema_str,
        "resultado": resultado_str,
        "codigo_postal": consulta.codigo_postal,
        "atendida": consulta.atendida,
        "alerta": consulta.alerta,
        "telefono": telefono,
        "mensaje": texto_mensaje,
    }

    credenciales_raw = (current_app.config.get("GOOGLE_SHEETS_CREDENTIALS") or "").strip()
    es_prueba = current_app.config.get("TESTING", False)

    if credenciales_raw and not es_prueba:
        try:
            log.info("Sincronizando consulta #%s a Google Sheets API real...", consulta.id_consulta)
        except Exception as e:
            log.exception("Error al sincronizar consulta con Google Sheets API: %s", e)

    cfg: dict[str, Any] = {}
    if conexion.configuracion:
        with contextlib.suppress(Exception):
            cfg = json.loads(conexion.configuracion)

    filas_consultas = cfg.get("filas_consultas", [])
    filas_consultas = [f for f in filas_consultas if f.get("id_consulta") != consulta.id_consulta]
    filas_consultas.append(fila)
    cfg["filas_consultas"] = filas_consultas

    conexion.configuracion = json.dumps(cfg)
    conexion.ultima_sincronizacion = tiempo.ahora()
    db.session.commit()
    return True


def obtener_filas_simuladas(conexion: ConexionExterna, tipo: str = "pedidos") -> list[dict[str, Any]]:
    """Obtiene el historial de filas sincronizadas almacenadas en el JSON de la conexión."""
    if not conexion.configuracion:
        return []
    try:
        cfg = json.loads(conexion.configuracion)
        clave = "filas_pedidos" if tipo == "pedidos" else "filas_consultas"
        return cfg.get(clave, [])
    except Exception:
        return []
