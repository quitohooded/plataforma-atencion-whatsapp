"""Gestión de Planes Comerciales, WhatsApp Propio y Billetera Prepaga.

Permite consultar los planes públicos, solicitar planes corporativos a medida,
administrar la suscripción Pro con cuotas semanales de IA, recargar saldo
prepago anti-impagos y conectar una línea propia de WhatsApp por comercio.
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from flask import Blueprint, current_app, flash, g, jsonify, redirect, render_template, request, url_for

from ..extensiones import csrf, db
from ..modelos import PlanComercio, SolicitudVentas, TransaccionPago
from ..servicios.meta_signup import desconectar_whatsapp_comercio, intercambiar_codigo_embedded
from ..servicios.pagos_mp import (
    cancelar_suscripcion_comercio,
    crear_checkout_recarga,
    crear_checkout_suscripcion_pro,
    procesar_webhook_mp,
)
from ..utilidades import tiempo
from . import requiere_onboarding

bp = Blueprint("planes", __name__)


# ---------------------------------------------------------------------------
# Rutas públicas
# ---------------------------------------------------------------------------


@bp.get("/planes")
def publico_planes():
    """Página comparativa pública de los planes comerciales."""
    return render_template("publico/planes.html", PlanComercio=PlanComercio)


@bp.route("/ventas", methods=["GET", "POST"])
def contacto_ventas():
    """Formulario de contacto para el Plan a Medida / Corporativo."""
    error = None
    if request.method == "POST":
        nombre = request.form.get("nombre_contacto", "").strip()
        email = request.form.get("email", "").strip()
        telefono = request.form.get("telefono", "").strip() or None
        volumen = request.form.get("volumen_mensual", "").strip() or None
        sistemas = request.form.get("sistemas_actuales", "").strip() or None
        mensaje = request.form.get("mensaje", "").strip() or None

        if not nombre or not email:
            error = "Por favor complete su nombre y correo electrónico de contacto."
            return render_template("publico/ventas.html", error=error), 400

        solicitud = SolicitudVentas(
            id_comercio=g.comercio.id_comercio if g.get("comercio") else None,
            nombre_contacto=nombre,
            email=email,
            telefono=telefono,
            volumen_mensual=volumen,
            sistemas_actuales=sistemas,
            mensaje=mensaje,
            estado="NUEVA",
            fecha_hora=tiempo.ahora(),
        )
        db.session.add(solicitud)
        db.session.commit()
        flash(
            "¡Gracias por contactarnos! Recibimos su solicitud y un asesor comercial se comunicará a la brevedad.",
            "exito",
        )
        return redirect(url_for("planes.contacto_ventas"))

    return render_template("publico/ventas.html", error=error)


# ---------------------------------------------------------------------------
# Rutas del panel de administración
# ---------------------------------------------------------------------------


@bp.get("/plan")
@requiere_onboarding
def panel_plan():
    """Pantalla del panel para administrar plan, WhatsApp propio y billetera."""
    comercio = g.comercio
    hoy = tiempo.ahora().date()

    inicio_semana = comercio.ia_semana_inicio or hoy
    dias_transcurridos = (hoy - inicio_semana).days
    if dias_transcurridos >= 7:
        dias_para_reinicio = 7
    else:
        dias_para_reinicio = 7 - dias_transcurridos
    proximo_reinicio = hoy + timedelta(days=dias_para_reinicio)

    porcentaje_chat = (
        min(100, round((comercio.ia_usados_semana / max(1, comercio.ia_cuota_semanal)) * 100))
        if comercio.ia_cuota_semanal > 0
        else 0
    )
    porcentaje_interna = (
        min(100, round((comercio.ia_usados_interna / max(1, comercio.ia_cuota_interna)) * 100))
        if comercio.ia_cuota_interna > 0
        else 0
    )

    return render_template(
        "panel/plan.html",
        seccion="plan",
        comercio=comercio,
        proximo_reinicio=proximo_reinicio,
        porcentaje_chat=porcentaje_chat,
        porcentaje_interna=porcentaje_interna,
        PlanComercio=PlanComercio,
    )


@bp.post("/plan/cambiar")
@requiere_onboarding
def cambiar_plan():
    """Cambia el plan de suscripción del comercio."""
    nuevo_plan = request.form.get("plan", "").strip().upper()
    if nuevo_plan not in (PlanComercio.FREE.value, PlanComercio.PRO.value, PlanComercio.ENTERPRISE.value):
        flash("El plan seleccionado no es válido.", "error")
        return redirect(url_for("planes.panel_plan"))

    comercio = g.comercio
    if nuevo_plan == PlanComercio.PRO.value:
        comercio.plan = PlanComercio.PRO
        comercio.ia_cuota_semanal = 250
        comercio.ia_cuota_interna = 100
        comercio.ia_semana_inicio = tiempo.ahora().date()
        comercio.ia_usados_semana = 0
        db.session.commit()
        flash(
            "Plan Pro Mensual activado con éxito. Se asignaron 250 respuestas de IA semanales y 100 créditos internos.",
            "exito",
        )
    elif nuevo_plan == PlanComercio.FREE.value:
        comercio.plan = PlanComercio.FREE
        comercio.ia_cuota_semanal = 0
        comercio.ia_usados_semana = 0
        db.session.commit()
        flash(
            "Se cambió al Plan Gratuito. El bot continuará respondiendo con sus reglas automáticas ilimitadas.",
            "info",
        )
    elif nuevo_plan == PlanComercio.ENTERPRISE.value:
        comercio.plan = PlanComercio.ENTERPRISE
        db.session.commit()
        flash(
            "Plan a Medida activado. La IA utilizará los créditos prepagos disponibles sin límite fijo semanal.",
            "exito",
        )

    return redirect(url_for("planes.panel_plan"))


@bp.post("/plan/recargar")
@requiere_onboarding
def recargar():
    """Acredita créditos prepagos y actualiza la configuración de recarga automática."""
    comercio = g.comercio

    try:
        cantidad = int(request.form.get("cantidad", 0))
    except (TypeError, ValueError):
        cantidad = 0

    if cantidad > 0:
        comercio.saldo_creditos += cantidad
        flash(f"Se acreditaron {cantidad} créditos a su billetera prepaga.", "exito")

    if "recarga_automatica" in request.form:
        comercio.recarga_automatica = request.form.get("recarga_automatica") in ("1", "true", "on")

    if "umbral_alerta_creditos" in request.form:
        try:
            umbral = int(request.form.get("umbral_alerta_creditos", 50))
            if umbral >= 0:
                comercio.umbral_alerta_creditos = umbral
        except (TypeError, ValueError):
            pass

    db.session.commit()
    if cantidad <= 0:
        flash("Configuración de billetera prepaga actualizada con éxito.", "exito")

    return redirect(url_for("planes.panel_plan"))


@bp.post("/plan/whatsapp")
@requiere_onboarding
def whatsapp():
    """Guarda o limpia las credenciales de la línea propia de WhatsApp."""
    comercio = g.comercio
    accion = request.form.get("accion")

    if accion == "desconectar":
        desconectar_whatsapp_comercio(comercio)
        flash(
            "Línea de WhatsApp desconectada. Su bot responderá a través de la línea compartida de la plataforma.",
            "info",
        )
        return redirect(url_for("planes.panel_plan"))

    numero = request.form.get("whatsapp_numero_publico", "").strip() or None
    phone_id = request.form.get("whatsapp_phone_number_id", "").strip() or None
    waba_id = request.form.get("whatsapp_waba_id", "").strip() or None
    token = request.form.get("whatsapp_token", "").strip() or None

    comercio.whatsapp_numero_publico = numero
    comercio.whatsapp_phone_number_id = phone_id
    comercio.whatsapp_waba_id = waba_id
    comercio.whatsapp_token = token
    db.session.commit()

    flash("Credenciales de su línea propia de WhatsApp guardadas con éxito.", "exito")
    return redirect(url_for("planes.panel_plan"))


@bp.post("/plan/whatsapp/embedded-callback")
@requiere_onboarding
def embedded_callback():
    """Recibe el auth code devuelto por Meta Embedded Signup y aprovisiona el WhatsApp."""
    comercio = g.comercio
    datos = request.get_json(silent=True) or request.form.to_dict() or {}
    codigo = (datos.get("code") or datos.get("codigo_auth") or "").strip()
    if not codigo:
        return jsonify(ok=False, error="Código de autorización no proporcionado."), 400

    waba_id = datos.get("waba_id")
    phone_number_id = datos.get("phone_number_id")

    try:
        intercambiar_codigo_embedded(
            comercio=comercio,
            codigo_auth=codigo,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
        )
        return jsonify(ok=True, numero=comercio.whatsapp_numero_publico, comercio=comercio.nombre)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 400


@bp.get("/plan/whatsapp/meta-config")
@requiere_onboarding
def meta_config():
    """Devuelve la configuración necesaria para inicializar el SDK de Meta en el frontend."""
    app_id = current_app.config.get("META_APP_ID", "")
    config_id = current_app.config.get("META_CONFIG_ID", "")
    return jsonify({
        "app_id": app_id,
        "config_id": config_id,
        "simulado": not bool(app_id),
    })


# ---------------------------------------------------------------------------
# Monetización Real con Mercado Pago (Suscripciones y Billetera Prepaga)
# ---------------------------------------------------------------------------


@bp.post("/plan/suscribir-pro", endpoint="iniciar_suscripcion_pro")
@requiere_onboarding
def iniciar_suscripcion_pro():
    """Inicia el checkout de suscripción mensual recurrente al Plan Pro."""
    comercio = g.comercio
    email = g.usuario.email if getattr(g, "usuario", None) and g.usuario.email else "cliente@ejemplo.com"
    url_retorno = url_for("planes.pago_confirmado", _external=True)
    resultado = crear_checkout_suscripcion_pro(comercio, email, url_retorno)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"url": resultado["url_checkout"], "id_transaccion": resultado["id_transaccion"]})
    return redirect(resultado["url_checkout"])


# Alias para que url_for('planes.suscribir_pro') también funcione correctamente
bp.add_url_rule(
    "/plan/suscribir-pro",
    endpoint="suscribir_pro",
    view_func=iniciar_suscripcion_pro,
    methods=["POST"],
)


@bp.post("/plan/comprar-creditos")
@requiere_onboarding
def comprar_creditos():
    """Inicia el checkout puntual de recarga de créditos prepagos en Mercado Pago."""
    comercio = g.comercio
    try:
        cantidad = int(request.form.get("cantidad") or 200)
    except (TypeError, ValueError):
        cantidad = 200

    if cantidad <= 0:
        cantidad = 200

    url_retorno = url_for("planes.pago_confirmado", _external=True)
    resultado = crear_checkout_recarga(comercio, cantidad, url_retorno)

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"url": resultado["url_checkout"], "id_transaccion": resultado["id_transaccion"]})
    return redirect(resultado["url_checkout"])


@bp.post("/plan/cancelar-suscripcion")
@requiere_onboarding
def cancelar_suscripcion():
    """Cancela la suscripción activa al Plan Pro y pasa al Plan Gratuito."""
    comercio = g.comercio
    cancelar_suscripcion_comercio(comercio, tiempo.ahora())
    flash(
        "Suscripción al Plan Pro cancelada con éxito. Su comercio continuará operando bajo el Plan Gratuito.",
        "info",
    )
    return redirect(url_for("planes.panel_plan"))


@bp.route("/api/pagos/mercadopago/webhook", methods=["GET", "POST"])
@csrf.exempt
def webhook_mercadopago():
    """Recibe y procesa las notificaciones de webhooks e IPN de Mercado Pago."""
    if request.method == "GET":
        return jsonify({"status": "ok"}), 200

    datos = request.get_json(silent=True) or request.form.to_dict() or request.args.to_dict() or {}
    encabezados = dict(request.headers)
    procesado = procesar_webhook_mp(datos, encabezados, tiempo.ahora())
    return jsonify({"status": "ok", "procesado": procesado}), 200


@bp.route("/plan/simulador-pago", methods=["GET", "POST"])
@requiere_onboarding
def simulador_pago():
    """Simulador de pagos local para entornos de prueba y desarrollo sin tokens reales."""
    comercio = g.comercio
    if request.method == "GET":
        id_transaccion = request.args.get("id_transaccion", type=int)
        accion = request.args.get("accion")
    else:
        id_transaccion = request.form.get("id_transaccion", type=int)
        accion = request.form.get("accion")

    if not id_transaccion:
        flash("Identificador de transacción no especificado.", "error")
        return redirect(url_for("planes.panel_plan"))

    transaccion = db.session.get(TransaccionPago, id_transaccion)
    if not transaccion or transaccion.id_comercio != comercio.id_comercio:
        flash("Transacción de pago no encontrada.", "error")
        return redirect(url_for("planes.panel_plan"))

    if accion:
        if accion == "aprobar":
            id_simulado = f"SIM-{secrets.token_hex(6)}"
            procesar_webhook_mp(
                {
                    "id_transaccion": transaccion.id_transaccion,
                    "estado": "approved",
                    "id_externo": id_simulado,
                },
                {},
                tiempo.ahora(),
            )
            flash(
                "¡Pago de prueba aprobado con éxito! Su plan o recarga de créditos ya fueron acreditados.",
                "exito",
            )
        elif accion == "rechazar":
            id_simulado = f"SIM-{secrets.token_hex(6)}"
            procesar_webhook_mp(
                {
                    "id_transaccion": transaccion.id_transaccion,
                    "estado": "rejected",
                    "id_externo": id_simulado,
                },
                {},
                tiempo.ahora(),
            )
            flash("El pago de prueba fue rechazado.", "alerta")
        return redirect(url_for("planes.panel_plan"))

    return render_template("panel/simulador_pago.html", transaccion=transaccion, comercio=comercio)


@bp.get("/plan/pago-confirmado")
@requiere_onboarding
def pago_confirmado():
    """Página de retorno exitoso desde la pasarela de Mercado Pago."""
    flash("¡Pago confirmado! Su suscripción o recarga se ha procesado exitosamente.", "exito")
    return redirect(url_for("planes.panel_plan"))


@bp.get("/plan/pago-pendiente")
@requiere_onboarding
def pago_pendiente():
    """Página de retorno con pago pendiente desde Mercado Pago."""
    flash("Su pago se encuentra en proceso o pendiente de acreditación.", "info")
    return redirect(url_for("planes.panel_plan"))

