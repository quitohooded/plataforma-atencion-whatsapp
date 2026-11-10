"""Canal de atención web propio por comercio (/t/<slug> y subdominios).

Permite que los compradores conversen con el bot directamente desde el navegador
o mediante un widget embebido en el sitio del comercio, sin depender de WhatsApp.
Las consultas y mensajes quedan registrados en el panel del comercio exactamente igual.
"""

from __future__ import annotations

import secrets

from flask import Blueprint, abort, jsonify, render_template, request, session
from sqlalchemy import func, or_, select

from ..bot.motor import BOTONES
from ..bot.prueba import serializar_respuesta
from ..bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from ..extensiones import db
from ..modelos import Comercio
from ..seguridad_web import limitar

bp = Blueprint("canal_web", __name__)

PREFIJO_WEB = "5493518"


def generar_telefono_web() -> str:
    """Genera un identificador virtual con formato de teléfono para el visitante web."""
    return PREFIJO_WEB + "".join(secrets.choice("0123456789") for _ in range(10))


def es_telefono_web(telefono: str | None) -> bool:
    return bool(
        isinstance(telefono, str)
        and telefono.startswith(PREFIJO_WEB)
        and 13 <= len(telefono) <= 20
        and telefono.isdigit()
    )


def buscar_comercio(slug_o_codigo: str) -> Comercio | None:
    if not slug_o_codigo:
        return None
    val = slug_o_codigo.strip()
    return db.session.scalar(
        select(Comercio).where(
            or_(
                func.lower(Comercio.slug) == val.lower(),
                func.upper(Comercio.codigo_acceso) == val.upper(),
            )
        )
    )


@bp.before_app_request
def detectar_subdominio():
    """Detecta si el host contiene un subdominio que coincide con el slug de un comercio."""
    if request.path != "/":
        return None
    host = request.host.split(":")[0].lower()
    partes = host.split(".")
    # Evitar direcciones IP tipo 127.0.0.1
    if len(partes) == 4 and all(p.isdigit() for p in partes):
        return None
    if len(partes) >= 2:
        candidato = partes[0]
        if candidato in ("www", "api", "app", "mail", "admin", "static"):
            return None
        comercio = db.session.scalar(select(Comercio).where(func.lower(Comercio.slug) == candidato))
        if comercio:
            return chat(comercio.slug)
    return None


@bp.get("/t/<slug>")
def chat(slug: str):
    comercio = buscar_comercio(slug)
    if not comercio:
        abort(404)

    if not comercio.slug:
        comercio.asegurar_slug()
        db.session.commit()

    clave_sesion = f"comprador_web_{comercio.id_comercio}"
    telefono = session.get(clave_sesion)
    if not es_telefono_web(telefono):
        telefono = generar_telefono_web()
        session[clave_sesion] = telefono

    embed = request.args.get("embed") == "1"
    return render_template(
        "canal_web/chat.html",
        comercio=comercio,
        embed=embed,
    )


@bp.post("/t/<slug>/mensajes")
@limitar("simulador")
def enviar(slug: str):
    comercio = buscar_comercio(slug)
    if not comercio:
        abort(404)

    datos = request.get_json(silent=True) or {}
    texto = str(datos.get("texto", "")).strip()[:1000]
    boton = str(datos.get("boton", "")).strip() or None
    if boton not in BOTONES:
        boton = None

    if not texto:
        return jsonify(error="Escriba un mensaje."), 400

    clave_sesion = f"comprador_web_{comercio.id_comercio}"
    telefono = session.get(clave_sesion)
    if not es_telefono_web(telefono):
        telefono = generar_telefono_web()
        session[clave_sesion] = telefono

    nombre = str(datos.get("nombre", "")).strip()[:60] or "Cliente Web"

    resultado = procesar_mensaje_entrante(
        MensajeEntrante(
            telefono=telefono,
            texto=texto,
            nombre=nombre,
            tipo="interactive" if (boton and boton in BOTONES) else "text",
            boton=boton if (boton and boton in BOTONES) else None,
            id_comercio_directo=comercio.id_comercio,
        )
    )

    conversacion = resultado.conversacion
    return jsonify(
        respuestas=[serializar_respuesta(r) for r in resultado.respuestas],
        estado=conversacion.estado.etiqueta if (conversacion and conversacion.estado) else None,
    )


@bp.post("/t/<slug>/reiniciar")
def reiniciar(slug: str):
    comercio = buscar_comercio(slug)
    if not comercio:
        abort(404)

    clave_sesion = f"comprador_web_{comercio.id_comercio}"
    session[clave_sesion] = generar_telefono_web()
    return jsonify(ok=True)
