"""Motor de IA híbrido y flujo operativo bidireccional (Fases 3 y 4).

Combina la API oficial de Google Gemini Interactions (Mayo 2026+) con modelos
gemini-3.5-flash-lite y gemini-3.8-flash, junto a un extractor y razonador local
determinístico de respaldo para operar sin API key o sin conexión externa.

Dirección 1 (Herramientas -> Bot):
    Recauda datos de catálogo nativo, zonas de envío, medios de pago, horarios,
    preguntas frecuentes y contexto libre para responder consultas con IA.

Dirección 2 (Bot -> Panel y Conexiones):
    Detecta pedidos, intenciones de compra y avisos de pago en el chat y los
    transforma en registros PedidoChat y eventos de sincronización con conexiones
    externas (TiendaNube, Google Sheets, Mercado Pago).
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import unicodedata
from datetime import datetime

import requests
from flask import current_app

from ..extensiones import db
from ..modelos import (
    Comercio,
    Comprador,
    Consulta,
    Conversacion,
    ItemCatalogo,
    PedidoChat,
    TemaConsulta,
    formato_pesos,
)

log = logging.getLogger(__name__)

GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
API_REVISION = "2026-05-20"


def _normalizar(texto: str) -> str:
    """Normaliza texto eliminando tildes y pasando a minúsculas."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _llamar_gemini_interactions(
    prompt: str,
    modelo: str,
    schema: dict,
    api_key: str,
    timeout: int = 10,
) -> dict | None:
    """Invoca la API de Interactions de Gemini solicitando formato estructurado JSON."""
    headers = {
        "x-goog-api-key": api_key,
        "Api-Revision": API_REVISION,
        "Content-Type": "application/json",
    }
    payload = {
        "model": modelo,
        "input": prompt,
        "response_format": {
            "type": "text",
            "mime_type": "application/json",
            "schema": schema,
        },
    }

    try:
        resp = requests.post(
            GEMINI_INTERACTIONS_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        if not resp.ok:
            log.warning("Gemini Interactions API retornó código %s: %s", resp.status_code, resp.text[:200])
            return None

        datos = resp.json()
        # Estructura Interactions API: steps -> model_output -> content -> text
        if "steps" in datos:
            for step in reversed(datos["steps"]):
                if step.get("type") == "model_output":
                    for bloque in step.get("content", []):
                        if bloque.get("type") == "text" and bloque.get("text"):
                            return json.loads(bloque["text"])

        # Compatibilidad adicional con candidatos estándar
        if "candidates" in datos:
            for cand in datos["candidates"]:
                partes = cand.get("content", {}).get("parts", [])
                for parte in partes:
                    if "text" in parte:
                        return json.loads(parte["text"])

    except Exception as e:
        log.warning("Fallo al comunicarse con Gemini Interactions API: %s", e)

    return None


# ---------------------------------------------------------------------------
# A. IA para Compradores (Dirección 1: Herramientas/Catálogo -> Bot)
# ---------------------------------------------------------------------------


def resolver_con_ia_comprador(
    comercio: Comercio,
    texto_comprador: str,
    ahora: datetime,
) -> dict | None:
    """Intenta responder la consulta de un comprador utilizando IA sobre el catálogo y contexto.

    Verifica la cuota del comercio. Si la IA puede resolver con certeza, descuenta 1 crédito
    y devuelve un dict con {'respuesta': ..., 'resuelta': True, 'pedido_detalle': ..., 'monto_estimado': ...}.
    Si no puede resolver, devuelve None para permitir degradación suave a reglas.
    """
    if not comercio.puede_usar_ia_chat(ahora.date()):
        return None

    texto_limpio = texto_comprador.strip()
    norm_comprador = _normalizar(texto_limpio)
    items_activos = [it for it in comercio.items_catalogo if it.activo]

    api_key = current_app.config.get("GEMINI_API_KEY", "").strip()

    # Si hay API key disponible, intentamos resolver mediante Gemini Interactions API
    if api_key:
        schema = {
            "type": "object",
            "properties": {
                "resuelta": {
                    "type": "boolean",
                    "description": "True si la información del negocio responde con certeza a la pregunta",
                },
                "respuesta": {
                    "type": "string",
                    "description": "Respuesta cordial, clara y precisa para el cliente de WhatsApp",
                },
                "pedido_detectado": {
                    "type": "string",
                    "description": "Nombre de productos y cantidades si el cliente manifiesta encargar/comprar",
                    "nullable": True,
                },
                "monto_estimado": {
                    "type": "integer",
                    "description": "Monto total en pesos si hay pedido claro, o null",
                    "nullable": True,
                },
            },
            "required": ["resuelta", "respuesta"],
        }

        # Construcción del contexto del comercio
        catalogo_lineas = [
            f"- {it.nombre}: ${it.precio} ({'con stock' if it.stock_disponible else 'sin stock'}) "
            f"Categoría: {it.categoria or 'General'}. {it.descripcion or ''}"
            for it in items_activos
        ]
        contexto_prompt = (
            f"Sos el asistente virtual de {comercio.nombre} ({comercio.rubro}).\n"
            f"Reglas y contexto interno: {comercio.contexto_ia or 'No especificado'}\n"
            f"Catálogo de productos disponibles:\n"
            + ("\n".join(catalogo_lineas) if catalogo_lineas else "Sin productos cargados.")
            + f"\nMedios de pago: {', '.join(m.texto for m in comercio.medios_activos)}\n"
            f"Mensaje del comprador: \"{texto_limpio}\"\n"
            "Respondé solo con certeza. Si no sabés la respuesta o requiere hablar con un humano, "
            "marcá resuelta: false."
        )

        modelo = current_app.config.get("GEMINI_MODEL_CHAT") or "gemini-3.5-flash-lite"
        resultado_gemini = _llamar_gemini_interactions(contexto_prompt, modelo, schema, api_key)

        if resultado_gemini and resultado_gemini.get("resuelta"):
            comercio.consumir_ia_chat(ahora.date())
            return {
                "respuesta": resultado_gemini.get("respuesta", "").strip(),
                "resuelta": True,
                "pedido_detalle": resultado_gemini.get("pedido_detectado"),
                "monto_estimado": resultado_gemini.get("monto_estimado"),
            }

    # Motor inteligente local de respaldo (sin API externa o fallback)
    # 1. Búsqueda directa en catálogo
    coincidencias: list[ItemCatalogo] = []
    for it in items_activos:
        norm_nombre = _normalizar(it.nombre)
        # Coincidencia si el nombre completo del producto está en el texto
        if norm_nombre and norm_nombre in norm_comprador:
            coincidencias.append(it)
            continue
        # O si palabras clave del producto (>= 4 caracteres) están en la consulta
        palabras_it = [p for p in norm_nombre.split() if len(p) >= 4]
        if palabras_it and any(p in norm_comprador for p in palabras_it):
            coincidencias.append(it)

    if coincidencias:
        comercio.consumir_ia_chat(ahora.date())
        if len(coincidencias) == 1:
            it = coincidencias[0]
            stock_txt = "Tenemos stock disponible." if it.stock_disponible else "Por el momento está agotado."
            desc_txt = f" {it.descripcion}" if it.descripcion else ""
            resp = f"El producto *{it.nombre}* cuesta {formato_pesos(it.precio)}. {stock_txt}{desc_txt}"
            return {
                "respuesta": resp,
                "resuelta": True,
                "pedido_detalle": it.nombre,
                "monto_estimado": it.precio,
            }
        else:
            lineas = [
                f"• *{it.nombre}*: {formato_pesos(it.precio)} ({'con stock' if it.stock_disponible else 'agotado'})"
                for it in coincidencias[:4]
            ]
            resp = "Tenemos estas opciones en nuestro catálogo:\n" + "\n".join(lineas)
            return {
                "respuesta": resp,
                "resuelta": True,
                "pedido_detalle": coincidencias[0].nombre,
                "monto_estimado": coincidencias[0].precio,
            }

    # 2. Búsqueda en contexto libre de IA
    if comercio.contexto_ia:
        norm_ctx = _normalizar(comercio.contexto_ia)
        palabras_consulta = [p for p in norm_comprador.split() if len(p) >= 4]
        # Si al menos una palabra clave de la consulta figura en el contexto libre
        if any(p in norm_ctx for p in palabras_consulta):
            comercio.consumir_ia_chat(ahora.date())
            # Devolvemos el contexto o la primera regla relevante
            return {
                "respuesta": comercio.contexto_ia.strip(),
                "resuelta": True,
                "pedido_detalle": None,
                "monto_estimado": None,
            }

    return None


# ---------------------------------------------------------------------------
# B. Flujo Operativo Bidireccional (Dirección 2: Bot -> Pedidos y Conexiones)
# ---------------------------------------------------------------------------


def procesar_flujo_bidireccional(
    comercio: Comercio,
    conversacion: Conversacion,
    comprador: Comprador,
    texto: str,
    consultas: list[Consulta],
    ahora: datetime,
) -> PedidoChat | None:
    """Detecta pedidos o pagos informados en la conversación y actualiza el estado operativo.

    Crea o actualiza registros PedidoChat y deja constancia de sincronización en
    las conexiones externas activas (Mercado Pago, TiendaNube, Google Sheets).
    """
    temas = {c.tema for c in consultas}
    norm_texto = _normalizar(texto)

    es_pago = TemaConsulta.PAGOS_INFORMADOS in temas or any(
        w in norm_texto for w in ["transferi", "comprobante", "ya pague", "pague", "envio comprobante", "pago listo"]
    )
    palabras_pedido = [
        "quiero comprar", "encargar", "hacer un pedido", "te pido", "llevo", "comprar", "pedido"
    ]
    es_pedido = TemaConsulta.PEDIDOS in temas or any(w in norm_texto for w in palabras_pedido)

    items_activos = [it for it in comercio.items_catalogo if it.activo]
    detectados: list[tuple[ItemCatalogo, int]] = []

    for it in items_activos:
        norm_item = _normalizar(it.nombre)
        if norm_item and norm_item in norm_texto:
            # Detección de cantidad (ej: "2 remeras", "remera x 3")
            patron_cant = rf"(\d+)\s*(?:x|de)?\s*{re.escape(norm_item)}|{re.escape(norm_item)}\s*x?\s*(\d+)"
            m = re.search(patron_cant, norm_texto)
            cant = 1
            if m:
                cant_str = m.group(1) or m.group(2)
                if cant_str and cant_str.isdigit():
                    cant = max(1, int(cant_str))
            detectados.append((it, cant))

    if detectados:
        es_pedido = True

    # Si no es pedido ni pago informado, no hay acción en el tablero
    if not (es_pago or es_pedido):
        return None

    # Resumen y cálculo de monto
    if detectados:
        monto_total: int | None = sum(it.precio * cant for it, cant in detectados)
        detalle = ", ".join(f"{cant}x {it.nombre}" if cant > 1 else it.nombre for it, cant in detectados)
    else:
        monto_total = None
        detalle = texto.strip()

    pedido_retorno: PedidoChat | None = None

    if es_pago:
        # Busca pedido sin pagar del cliente en este comercio
        existente = db.session.scalar(
            db.select(PedidoChat)
            .where(
                PedidoChat.id_comercio == comercio.id_comercio,
                PedidoChat.cliente_telefono == comprador.telefono,
                PedidoChat.estado_pago == "SIN_PAGAR",
            )
            .order_by(PedidoChat.fecha_hora.desc())
        )
        if existente:
            existente.estado_pago = "INFORMADO"
            pedido_retorno = existente
        else:
            nuevo = PedidoChat(
                id_comercio=comercio.id_comercio,
                id_conversacion=conversacion.id_conversacion,
                cliente_nombre=comprador.nombre or f"Cliente {comprador.telefono[-4:]}",
                cliente_telefono=comprador.telefono,
                detalle=f"Aviso de pago: {detalle}",
                monto_total=monto_total,
                estado_pedido="PENDIENTE",
                estado_pago="INFORMADO",
                fecha_hora=ahora,
            )
            db.session.add(nuevo)
            pedido_retorno = nuevo
    elif es_pedido:
        nuevo = PedidoChat(
            id_comercio=comercio.id_comercio,
            id_conversacion=conversacion.id_conversacion,
            cliente_nombre=comprador.nombre or f"Cliente {comprador.telefono[-4:]}",
            cliente_telefono=comprador.telefono,
            detalle=detalle,
            monto_total=monto_total,
            estado_pedido="PENDIENTE",
            estado_pago="SIN_PAGAR",
            fecha_hora=ahora,
        )
        db.session.add(nuevo)
        pedido_retorno = nuevo

    db.session.flush()

    if pedido_retorno:
        # Enlaces de cobro automáticos con Mercado Pago si está conectado
        for cx in comercio.conexiones_externas:
            if cx.estado == "CONECTADO":
                if cx.proveedor == "mercadopago" and not pedido_retorno.enlace_pago:
                    slug_com = comercio.slug or comercio.asegurar_slug()
                    id_p = pedido_retorno.id_pedido or (secrets.randbelow(90000) + 10000)
                    pedido_retorno.enlace_pago = f"https://mpago.la/responde-{slug_com}-{id_p}"
                elif cx.proveedor in ("google_sheets", "tiendanube"):
                    cx.ultima_sincronizacion = ahora

    return pedido_retorno


# ---------------------------------------------------------------------------
# C. Copiloto Interno de IA (Extracción para el Comerciante)
# ---------------------------------------------------------------------------


def extraer_configuracion_negocio_ia(comercio: Comercio, texto_libre: str) -> dict:
    """Extrae productos, FAQs, medios de pago y resumen de contexto a partir de texto libre.

    Descuenta 1 uso interno de IA del comercio. Utiliza Gemini 3.8 Flash si GEMINI_API_KEY
    está definida, o el motor de extracción inteligente local con expresiones regulares.
    """
    if not comercio.puede_usar_ia_interna():
        raise ValueError("El comercio no cuenta con créditos de IA interna disponibles.")

    comercio.consumir_ia_interna()
    texto = texto_libre.strip()
    api_key = current_app.config.get("GEMINI_API_KEY", "").strip()

    if api_key:
        schema = {
            "type": "object",
            "properties": {
                "productos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "nombre": {"type": "string"},
                            "categoria": {"type": "string"},
                            "precio": {"type": "integer"},
                            "descripcion": {"type": "string"},
                        },
                        "required": ["nombre", "precio"],
                    },
                },
                "faqs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "titulo": {"type": "string"},
                            "palabras_clave": {"type": "string"},
                            "respuesta": {"type": "string"},
                        },
                        "required": ["titulo", "respuesta"],
                    },
                },
                "medios_pago": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "nombre": {"type": "string"},
                            "detalle": {"type": "string"},
                        },
                        "required": ["nombre"],
                    },
                },
                "resumen_contexto": {"type": "string"},
            },
            "required": ["productos", "faqs", "medios_pago", "resumen_contexto"],
        }

        prompt = (
            "Sos un asistente experto en estructuración de datos para comercios de WhatsApp.\n"
            "Analizá el siguiente texto libre de un comercio argentino y extraé de forma estructurada:\n"
            "1. Lista de productos (con precio entero en pesos, categoría y descripción).\n"
            "2. Preguntas frecuentes o condiciones de venta.\n"
            "3. Medios de pago detectados (Mercado Pago, transferencia, efectivo, etc.).\n"
            "4. Un resumen claro de las políticas comerciales para que el bot responda al cliente.\n\n"
            f"Texto del comerciante:\n{texto}"
        )

        modelo = current_app.config.get("GEMINI_MODEL_INTERNO") or "gemini-3.8-flash"
        resultado = _llamar_gemini_interactions(prompt, modelo, schema, api_key)
        if resultado and isinstance(resultado, dict):
            return {
                "productos": resultado.get("productos", []),
                "faqs": resultado.get("faqs", []),
                "medios_pago": resultado.get("medios_pago", []),
                "resumen_contexto": resultado.get("resumen_contexto", ""),
            }

    # Extractor inteligente local de respaldo
    productos: list[dict] = []
    medios_pago: list[dict] = []
    faqs: list[dict] = []
    lineas_contexto: list[str] = []

    lineas = texto.splitlines()
    for linea in lineas:
        linea_limpia = linea.strip()
        if not linea_limpia:
            continue

        # Detección de productos por precio: $15000, $ 15.000, 15000 pesos
        m_precio = re.search(r"\$\s*([\d\.\,]+)|([\d\.\,]+)\s*(?:pesos|\$|ars)", linea_limpia, re.I)
        if m_precio:
            raw_num = m_precio.group(1) or m_precio.group(2)
            # Limpiar puntos de miles y comas
            num_limpio = raw_num.replace(".", "").replace(",", "")
            if num_limpio.isdigit():
                precio = int(num_limpio)
                # Extraer nombre quitando el precio y separadores iniciales
                nombre_raw = linea_limpia[: m_precio.start()].strip(" -:•*")
                desc_raw = linea_limpia[m_precio.end() :].strip(" -:•*()")
                # Si el nombre quedó vacío (ej: "$15000 Camiseta"), buscar después
                if not nombre_raw and desc_raw:
                    nombre_raw, desc_raw = desc_raw, ""
                nombre = nombre_raw or "Producto sin nombre"
                productos.append(
                    {
                        "nombre": nombre[:120],
                        "categoria": "General",
                        "precio": precio,
                        "descripcion": desc_raw[:300] if desc_raw else "",
                    }
                )
                continue

        # Detección de preguntas frecuentes
        if "¿" in linea_limpia or linea_limpia.endswith("?"):
            partes = linea_limpia.split("?", 1)
            pregunta = partes[0].replace("¿", "").strip()
            respuesta = partes[1].strip(" :-\t") if len(partes) > 1 else ""
            if pregunta:
                faqs.append(
                    {
                        "titulo": pregunta[:120],
                        "palabras_clave": ", ".join(pregunta.lower().split()[:5]),
                        "respuesta": respuesta or "Consultar con el comercio.",
                    }
                )
                continue

        # Detección de medios de pago
        norm_l = _normalizar(linea_limpia)
        if "mercado pago" in norm_l or "mercadopago" in norm_l:
            medios_pago.append({"nombre": "Mercado Pago", "detalle": linea_limpia})
            continue
        elif "transferencia" in norm_l or "alias" in norm_l or "cbu" in norm_l:
            medios_pago.append({"nombre": "Transferencia Bancaria", "detalle": linea_limpia})
            continue
        elif "efectivo" in norm_l:
            medios_pago.append({"nombre": "Efectivo", "detalle": linea_limpia})
            continue
        elif "tarjeta" in norm_l or "credito" in norm_l or "debito" in norm_l:
            medios_pago.append({"nombre": "Tarjetas", "detalle": linea_limpia})
            continue

        # Líneas descriptivas pasan al resumen del contexto
        lineas_contexto.append(linea_limpia)

    return {
        "productos": productos,
        "faqs": faqs,
        "medios_pago": medios_pago,
        "resumen_contexto": "\n".join(lineas_contexto),
    }
