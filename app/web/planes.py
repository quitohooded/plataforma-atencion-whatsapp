"""Gestión de Planes Comerciales, WhatsApp Propio y Billetera Prepaga.

Permite consultar los planes públicos, solicitar planes corporativos a medida,
administrar la suscripción Pro con cuotas semanales de IA, recargar saldo
prepago anti-impagos y conectar una línea propia de WhatsApp por comercio.
"""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..extensiones import db
from ..modelos import PlanComercio, SolicitudVentas
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
        comercio.whatsapp_numero_publico = None
        comercio.whatsapp_phone_number_id = None
        comercio.whatsapp_waba_id = None
        comercio.whatsapp_token = None
        db.session.commit()
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
