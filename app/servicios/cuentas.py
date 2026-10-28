"""Registro del comercio (CU01) e inicio de sesión con bloqueo por intentos (CU02)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

from flask import current_app
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensiones import db
from ..modelos import Comercio, EstadoComercio, Usuario, normalizar_email
from ..utilidades import tiempo
from . import ErrorValidacion

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LARGO_MINIMO_CONTRASENA = 8

# Hash de relleno para que verificar un correo inexistente tarde lo mismo que uno existente.
_HASH_RELLENO = generate_password_hash("relleno-para-igualar-tiempos")


class CorreoYaRegistrado(ErrorValidacion):
    pass


def validar_telefono(telefono: str) -> str:
    digitos = "".join(ch for ch in telefono or "" if ch.isdigit())
    if not 8 <= len(digitos) <= 15:
        raise ErrorValidacion("Ingrese un teléfono de contacto válido, con código de área.", ["telefono"])
    return telefono.strip()


_DOMINIO = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$", re.IGNORECASE)
_USUARIO_INSTAGRAM = re.compile(r"^@([a-z0-9._]{1,30})$", re.IGNORECASE)


def validar_enlace_catalogo(valor: str | None) -> str | None:
    """Enlace al catálogo: una dirección web o el usuario de Instagram («@casaydetalles»).

    Vacío devuelve None. Se agrega «https://» si falta. Solo se aceptan direcciones http(s).
    """
    texto = (valor or "").strip()
    if not texto:
        return None
    usuario = _USUARIO_INSTAGRAM.match(texto)
    if usuario:
        return f"https://www.instagram.com/{usuario.group(1)}"
    if not re.match(r"^https?://", texto, re.IGNORECASE):
        if "://" in texto:
            raise ErrorValidacion("El enlace del catálogo debe ser una dirección web (https://...).", ["catalogo"])
        texto = "https://" + texto
    partes = urlparse(texto)
    if (
        len(texto) > 300
        or any(c.isspace() for c in texto)
        or partes.scheme.lower() not in {"http", "https"}
        or not _DOMINIO.match(partes.hostname or "")
    ):
        raise ErrorValidacion(
            "Ingrese un enlace válido para el catálogo, por ejemplo https://www.instagram.com/sucomercio.",
            ["catalogo"],
        )
    return texto


def validar_datos_negocio(nombre: str, rubro: str, telefono: str) -> tuple[str, str, str]:
    nombre, rubro, telefono = (nombre or "").strip(), (rubro or "").strip(), (telefono or "").strip()
    faltantes = [c for c, v in (("nombre", nombre), ("rubro", rubro), ("telefono", telefono)) if not v]
    if faltantes:
        raise ErrorValidacion("Complete todos los campos obligatorios.", faltantes)
    if len(nombre) > 80:
        raise ErrorValidacion("El nombre del comercio no puede superar los 80 caracteres.", ["nombre"])
    return nombre, rubro, validar_telefono(telefono)


def registrar_comercio(nombre: str, rubro: str, telefono: str, email: str, contrasena: str) -> Usuario:
    email = normalizar_email(email)
    campos = {"nombre": nombre, "rubro": rubro, "telefono": telefono, "email": email, "contrasena": contrasena}
    faltantes = [c for c, v in campos.items() if not (v or "").strip()]
    if faltantes:
        raise ErrorValidacion("Complete todos los campos obligatorios.", faltantes)

    nombre, rubro, telefono = validar_datos_negocio(nombre, rubro, telefono)
    if not _EMAIL.match(email):
        raise ErrorValidacion("Ingrese un correo electrónico válido.", ["email"])
    if len(contrasena) < LARGO_MINIMO_CONTRASENA:
        raise ErrorValidacion("Ingrese una contraseña de al menos ocho caracteres.", ["contrasena"])
    if db.session.scalar(select(Usuario.id_usuario).where(Usuario.email == email)):
        raise CorreoYaRegistrado("Ya existe una cuenta con ese correo electrónico.", ["email"])

    comercio = Comercio(
        nombre=nombre,
        rubro=rubro,
        telefono_contacto=telefono,
        estado=EstadoComercio.EN_ONBOARDING,
        fecha_alta=tiempo.ahora().date(),
        paso_onboarding=1,
    )
    usuario = Usuario(comercio=comercio, email=email, intentos_fallidos=0)
    usuario.establecer_contrasena(contrasena)
    usuario.ultimo_ingreso = tiempo.ahora()
    db.session.add_all([comercio, usuario])
    db.session.commit()
    return usuario


@dataclass
class ResultadoIngreso:
    usuario: Usuario | None = None
    error: str | None = None
    bloqueado: bool = False


def iniciar_sesion(email: str, contrasena: str) -> ResultadoIngreso:
    email = normalizar_email(email)
    ahora = tiempo.ahora()
    max_intentos = current_app.config["LOGIN_MAX_INTENTOS"]
    minutos = current_app.config["LOGIN_BLOQUEO_MINUTOS"]

    if not email or not contrasena:
        return ResultadoIngreso(error="Complete todos los campos obligatorios.")

    usuario = db.session.scalar(select(Usuario).where(Usuario.email == email))
    if usuario is None:
        check_password_hash(_HASH_RELLENO, contrasena)
        return ResultadoIngreso(error="Correo o contraseña incorrectos.")

    if usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora:
        restantes = max(1, int((usuario.bloqueado_hasta - ahora).total_seconds() // 60) + 1)
        return ResultadoIngreso(
            error=f"El ingreso está bloqueado por intentos fallidos. Intente nuevamente en {restantes} minutos.",
            bloqueado=True,
        )

    if not usuario.autenticar(email, contrasena):
        usuario.intentos_fallidos = (usuario.intentos_fallidos or 0) + 1
        if usuario.intentos_fallidos >= max_intentos:
            usuario.bloqueado_hasta = ahora + timedelta(minutes=minutos)
            usuario.intentos_fallidos = 0
            db.session.commit()
            return ResultadoIngreso(
                error=(
                    "Correo o contraseña incorrectos. Por seguridad, el ingreso queda bloqueado "
                    f"durante {minutos} minutos."
                ),
                bloqueado=True,
            )
        db.session.commit()
        return ResultadoIngreso(error="Correo o contraseña incorrectos.")

    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    usuario.ultimo_ingreso = ahora
    db.session.commit()
    return ResultadoIngreso(usuario=usuario)
