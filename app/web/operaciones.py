"""Hub de operaciones, catálogo interactivo, tablero de pedidos y conexiones 1-clic."""

from __future__ import annotations

import contextlib
import json
import logging
import secrets

from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select

from ..bot.ia import extraer_configuracion_negocio_ia
from ..extensiones import db
from ..modelos import (
    ConexionExterna,
    ItemCatalogo,
    MedioPago,
    PedidoChat,
    RespuestaFrecuente,
)
from ..servicios import google_sheets, mp_connect, tiendanube
from ..utilidades import tiempo
from . import del_comercio, requiere_onboarding

log = logging.getLogger(__name__)

bp = Blueprint("operaciones", __name__)

PROVEEDORES_VALIDOS = {"tiendanube", "mercadopago", "google_sheets"}
ESTADOS_PEDIDO_VALIDOS = {"PENDIENTE", "EN_PREPARACION", "ENVIADO", "ENTREGADO"}
ESTADOS_PAGO_VALIDOS = {"SIN_PAGAR", "INFORMADO", "PAGADO"}


@bp.get("/operaciones")
@requiere_onboarding
def inicio():
    """Pantalla unificada: Asistente IA, Tablero de Pedidos, Catálogo y Conexiones 1-Clic."""
    comercio = g.comercio

    # Pedidos ordenados por fecha descendente
    pedidos = db.session.scalars(
        select(PedidoChat)
        .where(PedidoChat.id_comercio == comercio.id_comercio)
        .order_by(PedidoChat.fecha_hora.desc())
    ).all()

    # Catálogo nativo y sincronizado
    items = db.session.scalars(
        select(ItemCatalogo)
        .where(ItemCatalogo.id_comercio == comercio.id_comercio, ItemCatalogo.activo.is_(True))
        .order_by(ItemCatalogo.categoria, ItemCatalogo.nombre)
    ).all()

    # Conexiones externas organizadas por proveedor
    conexiones_lista = db.session.scalars(
        select(ConexionExterna).where(ConexionExterna.id_comercio == comercio.id_comercio)
    ).all()
    conexiones = {c.proveedor: c for c in conexiones_lista}

    return render_template(
        "panel/operaciones.html",
        seccion="operaciones",
        comercio=comercio,
        pedidos=pedidos,
        items=items,
        conexiones=conexiones,
    )


# ---------------------------------------------------------------------------
# Bloque 1: Asistente Interno con IA y Contexto del Negocio
# ---------------------------------------------------------------------------


@bp.post("/operaciones/asistente-ia")
@requiere_onboarding
def asistente_ia():
    """Procesa texto libre del comerciante y extrae catálogo, medios y contexto con IA."""
    comercio = g.comercio
    texto_libre = (request.form.get("texto_libre") or "").strip()

    if not texto_libre:
        flash("Escribí o pegá la información de tu comercio para que la IA la procese.", "alerta")
        return redirect(url_for("operaciones.inicio"))

    try:
        resultado = extraer_configuracion_negocio_ia(comercio, texto_libre)
    except ValueError as e:
        flash(str(e), "peligro")
        return redirect(url_for("operaciones.inicio"))

    cant_prod = 0
    for p in resultado.get("productos", []):
        nombre = p.get("nombre", "").strip()
        precio = int(p.get("precio", 0))
        if nombre and precio > 0:
            item = ItemCatalogo(
                id_comercio=comercio.id_comercio,
                nombre=nombre[:120],
                categoria=(p.get("categoria") or "General")[:80],
                precio=precio,
                descripcion=(p.get("descripcion") or "")[:300],
                origen="asistente_ia",
                stock_disponible=True,
                activo=True,
            )
            db.session.add(item)
            cant_prod += 1

    cant_medios = 0
    for m in resultado.get("medios_pago", []):
        nombre = m.get("nombre", "").strip()
        if nombre:
            existente = db.session.scalar(
                select(MedioPago).where(
                    MedioPago.id_comercio == comercio.id_comercio,
                    MedioPago.nombre == nombre,
                )
            )
            if not existente:
                db.session.add(
                    MedioPago(
                        id_comercio=comercio.id_comercio,
                        nombre=nombre[:80],
                        detalle=(m.get("detalle") or "")[:150],
                        activo=True,
                    )
                )
                cant_medios += 1

    cant_faqs = 0
    for f in resultado.get("faqs", []):
        titulo = f.get("titulo", "").strip()
        respuesta = f.get("respuesta", "").strip()
        if titulo and respuesta:
            existente = db.session.scalar(
                select(RespuestaFrecuente).where(
                    RespuestaFrecuente.id_comercio == comercio.id_comercio,
                    RespuestaFrecuente.titulo == titulo,
                )
            )
            if not existente:
                db.session.add(
                    RespuestaFrecuente(
                        id_comercio=comercio.id_comercio,
                        plantilla=None,
                        titulo=titulo[:120],
                        palabras_clave=(f.get("palabras_clave") or titulo)[:200],
                        respuesta=respuesta,
                        activa=True,
                        fecha_alta=tiempo.ahora(),
                    )
                )
                cant_faqs += 1

    resumen_ctx = resultado.get("resumen_contexto", "").strip()
    if resumen_ctx:
        if comercio.contexto_ia:
            comercio.contexto_ia += "\n" + resumen_ctx
        else:
            comercio.contexto_ia = resumen_ctx

    db.session.commit()
    flash(
        f"Copiloto IA: Se cargaron {cant_prod} productos, {cant_medios} medios de pago, "
        f"{cant_faqs} respuestas frecuentes y se actualizaron las reglas del negocio.",
        "exito",
    )
    return redirect(url_for("operaciones.inicio"))


@bp.post("/operaciones/contexto-ia")
@requiere_onboarding
def contexto_ia():
    """Actualiza manualmente las reglas y contexto general para la IA del bot."""
    comercio = g.comercio
    nuevo_contexto = (request.form.get("contexto_ia") or "").strip()
    comercio.contexto_ia = nuevo_contexto or None
    db.session.commit()
    flash("Reglas y contexto de IA actualizados correctamente.", "exito")
    return redirect(url_for("operaciones.inicio"))


# ---------------------------------------------------------------------------
# Bloque 2: Tablero de Pedidos y Cobros del Chat (Vista Nativa)
# ---------------------------------------------------------------------------


@bp.post("/operaciones/pedidos/nuevo")
@requiere_onboarding
def pedidos_nuevo():
    """Crea manualmente un pedido en el tablero nativo del comercio."""
    comercio = g.comercio
    cliente_nombre = (request.form.get("cliente_nombre") or "").strip() or "Cliente Mostrador"
    cliente_telefono = (request.form.get("cliente_telefono") or "").strip() or None
    detalle = (request.form.get("detalle") or "").strip()
    monto_raw = (request.form.get("monto_total") or "").strip()

    if not detalle:
        flash("El detalle del pedido es obligatorio.", "alerta")
        return redirect(url_for("operaciones.inicio"))

    monto_total = None
    if monto_raw:
        with contextlib.suppress(ValueError):
            monto_total = int(monto_raw.replace(".", "").replace("$", ""))

    estado_pedido = request.form.get("estado_pedido", "PENDIENTE")
    if estado_pedido not in ESTADOS_PEDIDO_VALIDOS:
        estado_pedido = "PENDIENTE"

    estado_pago = request.form.get("estado_pago", "SIN_PAGAR")
    if estado_pago not in ESTADOS_PAGO_VALIDOS:
        estado_pago = "SIN_PAGAR"

    pedido = PedidoChat(
        id_comercio=comercio.id_comercio,
        cliente_nombre=cliente_nombre,
        cliente_telefono=cliente_telefono,
        detalle=detalle,
        monto_total=monto_total,
        estado_pedido=estado_pedido,
        estado_pago=estado_pago,
        fecha_hora=tiempo.ahora(),
    )
    db.session.add(pedido)
    db.session.flush()

    # Sincronización con conexiones externas activas
    mp_conectado = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == "mercadopago",
            ConexionExterna.estado == "CONECTADO",
        )
    )
    if mp_conectado:
        try:
            mp_connect.crear_preferencia_vendedor(comercio, pedido)
        except Exception:
            slug = comercio.slug or comercio.asegurar_slug()
            pedido.enlace_pago = f"https://mpago.la/responde-{slug}-{pedido.id_pedido}"

    tn_conectado = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == "tiendanube",
            ConexionExterna.estado == "CONECTADO",
        )
    )
    if tn_conectado:
        with contextlib.suppress(Exception):
            tiendanube.exportar_pedido_tiendanube(comercio, pedido)

    gs_conectado = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == "google_sheets",
            ConexionExterna.estado == "CONECTADO",
        )
    )
    if gs_conectado:
        with contextlib.suppress(Exception):
            google_sheets.sincronizar_pedido_a_sheets(comercio, pedido)

    db.session.commit()
    flash("Pedido registrado correctamente en el tablero nativo.", "exito")
    return redirect(url_for("operaciones.inicio"))


@bp.post("/operaciones/pedidos/<int:id_pedido>/estado")
@requiere_onboarding
def pedidos_estado(id_pedido: int):
    """Actualiza el estado de preparación o pago de un pedido."""
    pedido = del_comercio(PedidoChat, id_pedido)

    nuevo_estado_pedido = request.form.get("estado_pedido")
    if nuevo_estado_pedido in ESTADOS_PEDIDO_VALIDOS:
        pedido.estado_pedido = nuevo_estado_pedido

    nuevo_estado_pago = request.form.get("estado_pago")
    if nuevo_estado_pago in ESTADOS_PAGO_VALIDOS:
        pedido.estado_pago = nuevo_estado_pago

    db.session.commit()
    flash(f"Pedido #{pedido.id_pedido} actualizado ({pedido.estado_pedido} / {pedido.estado_pago}).", "exito")
    return redirect(url_for("operaciones.inicio"))


# ---------------------------------------------------------------------------
# Bloque 3: Catálogo Interactivo para el Bot (Vista Nativa)
# ---------------------------------------------------------------------------


@bp.post("/operaciones/catalogo/nuevo")
@requiere_onboarding
def catalogo_nuevo():
    """Agrega un nuevo producto al catálogo nativo para que el bot con IA lo informe."""
    comercio = g.comercio
    nombre = (request.form.get("nombre") or "").strip()
    categoria = (request.form.get("categoria") or "").strip() or "General"
    precio_raw = (request.form.get("precio") or "").strip()
    descripcion = (request.form.get("descripcion") or "").strip()
    stock_disponible = request.form.get("stock_disponible") in ("1", "true", "on", "yes", "si")

    if not nombre or not precio_raw:
        flash("El nombre y el precio del producto son obligatorios.", "alerta")
        return redirect(url_for("operaciones.inicio"))

    try:
        precio = int(precio_raw.replace(".", "").replace("$", ""))
    except ValueError:
        flash("El precio ingresado no es válido.", "peligro")
        return redirect(url_for("operaciones.inicio"))

    item = ItemCatalogo(
        id_comercio=comercio.id_comercio,
        nombre=nombre[:120],
        categoria=categoria[:80],
        precio=precio,
        descripcion=descripcion[:300] or None,
        stock_disponible=stock_disponible,
        origen="nativo",
        activo=True,
    )
    db.session.add(item)
    db.session.commit()
    flash(f"Producto «{item.nombre}» agregado al catálogo del bot.", "exito")
    return redirect(url_for("operaciones.inicio"))


@bp.post("/operaciones/catalogo/<int:id_item>/toggle")
@requiere_onboarding
def catalogo_toggle(id_item: int):
    """Alterna el stock disponible/agotado de un producto del catálogo."""
    item = del_comercio(ItemCatalogo, id_item)
    item.stock_disponible = not item.stock_disponible
    db.session.commit()
    estado = "disponible con stock" if item.stock_disponible else "agotado"
    flash(f"«{item.nombre}» ahora figura como {estado}.", "info")
    return redirect(url_for("operaciones.inicio"))


@bp.post("/operaciones/catalogo/<int:id_item>/eliminar")
@requiere_onboarding
def catalogo_eliminar(id_item: int):
    """Elimina un producto del catálogo del bot."""
    item = del_comercio(ItemCatalogo, id_item)
    db.session.delete(item)
    db.session.commit()
    flash(f"Producto «{item.nombre}» eliminado del catálogo.", "info")
    return redirect(url_for("operaciones.inicio"))


# ---------------------------------------------------------------------------
# Bloque 4: Conexiones 1-Clic con Sistemas Externos (OAuth & Sincronización)
# ---------------------------------------------------------------------------


@bp.post("/operaciones/conexiones/tiendanube/iniciar")
@requiere_onboarding
def conexiones_tiendanube_iniciar():
    """Inicia el flujo de autorización OAuth 2.0 con TiendaNube."""
    comercio = g.comercio
    redirect_uri = url_for("operaciones.conexiones_tiendanube_callback", _external=True)
    url_auth = tiendanube.generar_url_autorizacion(comercio.id_comercio, redirect_uri)
    return redirect(url_auth)


@bp.route("/operaciones/conexiones/tiendanube/callback", methods=["GET", "POST"])
@requiere_onboarding
def conexiones_tiendanube_callback():
    """Callback de retorno del OAuth de TiendaNube: intercambia código y sincroniza catálogo."""
    comercio = g.comercio
    codigo = request.args.get("code") or request.form.get("code")
    if not codigo:
        flash("No se recibió el código de autorización de TiendaNube.", "peligro")
        return redirect(url_for("operaciones.inicio"))

    redirect_uri = url_for("operaciones.conexiones_tiendanube_callback", _external=True)
    datos = tiendanube.intercambiar_codigo(codigo, redirect_uri)

    conexion = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == "tiendanube",
        )
    )
    if not conexion:
        conexion = ConexionExterna(
            id_comercio=comercio.id_comercio,
            proveedor="tiendanube",
        )
        db.session.add(conexion)

    conexion.estado = "CONECTADO"
    store_id = str(datos.get("user_id") or "123456")
    conexion.cuenta_externa = f"Tienda #{store_id}"
    conexion.token_acceso = datos.get("access_token")
    conexion.configuracion = json.dumps(datos)
    conexion.ultima_sincronizacion = tiempo.ahora()
    db.session.commit()

    cant = tiendanube.sincronizar_catalogo_tiendanube(comercio, conexion)
    flash(f"¡TiendaNube conectada exitosamente! Se sincronizaron {cant} productos al catálogo del bot.", "exito")
    return redirect(url_for("operaciones.inicio"))


@bp.post("/operaciones/conexiones/mercadopago/iniciar")
@requiere_onboarding
def conexiones_mercadopago_iniciar():
    """Inicia el flujo de autorización OAuth 2.0 con Mercado Pago Connect."""
    comercio = g.comercio
    redirect_uri = url_for("operaciones.conexiones_mercadopago_callback", _external=True)
    url_auth = mp_connect.generar_url_autorizacion_mp_connect(comercio.id_comercio, redirect_uri)
    return redirect(url_auth)


@bp.route("/operaciones/conexiones/mercadopago/callback", methods=["GET", "POST"])
@requiere_onboarding
def conexiones_mercadopago_callback():
    """Callback de retorno de Mercado Pago Connect: guarda credenciales delegadas del vendedor."""
    comercio = g.comercio
    codigo = request.args.get("code") or request.form.get("code")
    if not codigo:
        flash("No se recibió el código de autorización de Mercado Pago.", "peligro")
        return redirect(url_for("operaciones.inicio"))

    redirect_uri = url_for("operaciones.conexiones_mercadopago_callback", _external=True)
    datos = mp_connect.intercambiar_codigo_mp_connect(codigo, redirect_uri)

    conexion = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == "mercadopago",
        )
    )
    if not conexion:
        conexion = ConexionExterna(
            id_comercio=comercio.id_comercio,
            proveedor="mercadopago",
        )
        db.session.add(conexion)

    conexion.estado = "CONECTADO"
    seller_id = str(datos.get("user_id") or "Connect")
    conexion.cuenta_externa = f"Vendedor MP #{seller_id}"
    conexion.token_acceso = datos.get("access_token")
    conexion.configuracion = json.dumps(datos)
    conexion.ultima_sincronizacion = tiempo.ahora()
    db.session.commit()

    # Genera enlaces de cobro con la cuenta del vendedor para pedidos pendientes
    pedidos_sin_link = db.session.scalars(
        select(PedidoChat).where(
            PedidoChat.id_comercio == comercio.id_comercio,
            PedidoChat.enlace_pago.is_(None),
        )
    ).all()
    for p in pedidos_sin_link:
        mp_connect.crear_preferencia_vendedor(comercio, p)

    flash("¡Mercado Pago Connect activado con éxito para tu cuenta de vendedor!", "exito")
    return redirect(url_for("operaciones.inicio"))


@bp.post("/operaciones/conexiones/google_sheets/configurar")
@requiere_onboarding
def conexiones_google_sheets_configurar():
    """Configura o activa la conexión con Google Sheets para exportar pedidos y consultas."""
    comercio = g.comercio
    sheet_id = (request.form.get("spreadsheet_id") or "").strip() or "Planilla de Ventas y Pedidos"

    conexion = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == "google_sheets",
        )
    )
    if not conexion:
        conexion = ConexionExterna(
            id_comercio=comercio.id_comercio,
            proveedor="google_sheets",
        )
        db.session.add(conexion)

    conexion.estado = "CONECTADO"
    conexion.cuenta_externa = sheet_id
    cfg_existente: dict = {}
    if conexion.configuracion:
        with contextlib.suppress(Exception):
            cfg_existente = json.loads(conexion.configuracion)
    cfg_existente["spreadsheet_id"] = sheet_id
    cfg_existente.setdefault("filas_pedidos", [])
    cfg_existente.setdefault("filas_consultas", [])
    conexion.configuracion = json.dumps(cfg_existente)
    conexion.ultima_sincronizacion = tiempo.ahora()
    db.session.commit()

    # Sincroniza pedidos existentes a sheets
    pedidos = db.session.scalars(
        select(PedidoChat).where(PedidoChat.id_comercio == comercio.id_comercio)
    ).all()
    for p in pedidos:
        google_sheets.sincronizar_pedido_a_sheets(comercio, p)

    flash("¡Google Sheets conectado y sincronizado correctamente!", "exito")
    return redirect(url_for("operaciones.inicio"))


@bp.post("/operaciones/conexiones/<proveedor>/conectar")
@requiere_onboarding
def conexiones_conectar(proveedor: str):
    """Conecta una aplicación externa con un solo clic (compatibilidad hacia atrás)."""
    if proveedor not in PROVEEDORES_VALIDOS:
        flash("Proveedor de conexión no soportado.", "peligro")
        return redirect(url_for("operaciones.inicio"))

    comercio = g.comercio
    ahora = tiempo.ahora()

    conexion = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == proveedor,
        )
    )
    if not conexion:
        conexion = ConexionExterna(
            id_comercio=comercio.id_comercio,
            proveedor=proveedor,
        )
        db.session.add(conexion)

    conexion.estado = "CONECTADO"
    slug_ref = comercio.slug or comercio.asegurar_slug()
    conexion.cuenta_externa = f"cuenta-{proveedor}-{slug_ref}@ejemplo.com"
    conexion.token_acceso = f"tok_oauth_{proveedor}_{comercio.id_comercio}_{secrets.token_hex(4)}"
    conexion.ultima_sincronizacion = ahora
    db.session.commit()

    # Sincronizaciones inmediatas según proveedor
    if proveedor == "tiendanube":
        tiendanube.sincronizar_catalogo_tiendanube(comercio, conexion)
    elif proveedor == "google_sheets":
        pedidos = db.session.scalars(
            select(PedidoChat).where(PedidoChat.id_comercio == comercio.id_comercio)
        ).all()
        for p in pedidos:
            google_sheets.sincronizar_pedido_a_sheets(comercio, p)
    elif proveedor == "mercadopago":
        pedidos_sin_link = db.session.scalars(
            select(PedidoChat).where(
                PedidoChat.id_comercio == comercio.id_comercio,
                PedidoChat.enlace_pago.is_(None),
            )
        ).all()
        for p in pedidos_sin_link:
            mp_connect.crear_preferencia_vendedor(comercio, p)

    nombres_proveedor = {
        "tiendanube": "TiendaNube",
        "mercadopago": "Mercado Pago",
        "google_sheets": "Google Sheets",
    }
    flash(f"¡Conexión 1-Clic con {nombres_proveedor[proveedor]} activada con éxito!", "exito")
    return redirect(url_for("operaciones.inicio"))


@bp.post("/operaciones/conexiones/<proveedor>/sincronizar")
@requiere_onboarding
def conexiones_sincronizar(proveedor: str):
    """Fuerza la sincronización bidireccional con una aplicación externa."""
    if proveedor not in PROVEEDORES_VALIDOS:
        flash("Proveedor no válido.", "peligro")
        return redirect(url_for("operaciones.inicio"))

    comercio = g.comercio
    conexion = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == proveedor,
        )
    )
    if conexion and conexion.estado == "CONECTADO":
        conexion.ultima_sincronizacion = tiempo.ahora()
        if proveedor == "tiendanube":
            cant = tiendanube.sincronizar_catalogo_tiendanube(comercio, conexion)
            flash(f"Datos sincronizados correctamente con TiendaNube. Se actualizaron {cant} productos.", "exito")
        elif proveedor == "mercadopago":
            pedidos_sin_link = db.session.scalars(
                select(PedidoChat).where(
                    PedidoChat.id_comercio == comercio.id_comercio,
                    PedidoChat.enlace_pago.is_(None),
                )
            ).all()
            for p in pedidos_sin_link:
                mp_connect.crear_preferencia_vendedor(comercio, p)
            flash("Datos sincronizados correctamente con Mercado Pago.", "exito")
        elif proveedor == "google_sheets":
            pedidos = db.session.scalars(
                select(PedidoChat).where(PedidoChat.id_comercio == comercio.id_comercio)
            ).all()
            for p in pedidos:
                google_sheets.sincronizar_pedido_a_sheets(comercio, p)
            flash("Datos sincronizados correctamente con Google Sheets.", "exito")
        else:
            flash(f"Datos sincronizados correctamente con {proveedor.title()}.", "exito")
        db.session.commit()
    else:
        flash("La aplicación debe estar conectada para poder sincronizar.", "alerta")

    return redirect(url_for("operaciones.inicio"))


@bp.post("/operaciones/conexiones/<proveedor>/desconectar")
@requiere_onboarding
def conexiones_desconectar(proveedor: str):
    """Pausa o desconecta una aplicación externa sin borrar los datos del bot."""
    if proveedor not in PROVEEDORES_VALIDOS:
        flash("Proveedor no válido.", "peligro")
        return redirect(url_for("operaciones.inicio"))

    comercio = g.comercio
    conexion = db.session.scalar(
        select(ConexionExterna).where(
            ConexionExterna.id_comercio == comercio.id_comercio,
            ConexionExterna.proveedor == proveedor,
        )
    )
    if conexion:
        conexion.estado = "DESCONECTADO"
        db.session.commit()
        flash(f"Conexión con {proveedor.title()} desconectada.", "info")

    return redirect(url_for("operaciones.inicio"))
