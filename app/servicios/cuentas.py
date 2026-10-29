"""Registro del comercio (CU01) e inicio de sesión con bloqueo por intentos (CU02)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlparse

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
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


# ---------------------------------------------------------------------------
# Cuenta: cambio y recuperación de contraseña (#9)
# ---------------------------------------------------------------------------


def validar_contrasena_nueva(nueva: str, repetida: str) -> str:
    if len(nueva or "") < LARGO_MINIMO_CONTRASENA:
        raise ErrorValidacion("La contraseña nueva debe tener al menos ocho caracteres.", ["nueva"])
    if nueva != repetida:
        raise ErrorValidacion("Las dos contraseñas nuevas no coinciden.", ["repetida"])
    return nueva


def cambiar_contrasena(usuario: Usuario, actual: str, nueva: str, repetida: str) -> None:
    if not check_password_hash(usuario.hash_contrasena, actual or ""):
        raise ErrorValidacion("La contraseña actual no es correcta.", ["actual"])
    validar_contrasena_nueva(nueva, repetida)
    if check_password_hash(usuario.hash_contrasena, nueva):
        raise ErrorValidacion("La contraseña nueva tiene que ser distinta de la actual.", ["nueva"])
    usuario.establecer_contrasena(nueva)
    db.session.commit()


_SAL_RECUPERACION = "recuperar-contrasena"
# Un correo de recuperación por cuenta cada tantos minutos.
MINUTOS_ENTRE_RECUPERACIONES = 5


def _serializador() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_SAL_RECUPERACION)


def token_recuperacion(usuario: Usuario) -> str:
    """Enlace firmado y con vencimiento. Incluye un fragmento del hash de la contraseña: al
    cambiarla, el enlace deja de servir (se usa una sola vez)."""
    return _serializador().dumps({"u": usuario.id_usuario, "h": usuario.hash_contrasena[-16:]})


def usuario_de_token(token: str) -> Usuario | None:
    minutos = current_app.config.get("RECUPERACION_MINUTOS", 60)
    try:
        datos = _serializador().loads(token, max_age=minutos * 60)
    except (SignatureExpired, BadSignature):
        return None
    usuario = db.session.get(Usuario, datos.get("u")) if isinstance(datos, dict) else None
    if usuario is None or usuario.hash_contrasena[-16:] != datos.get("h"):
        return None
    return usuario


def solicitar_recuperacion(email: str) -> Usuario | None:
    """Devuelve el usuario al que hay que mandarle el enlace, o None si el correo no existe o
    ya se mandó uno hace poco. La pantalla responde lo mismo en todos los casos."""
    usuario = db.session.scalar(select(Usuario).where(Usuario.email == normalizar_email(email)))
    if usuario is None:
        return None
    ahora = tiempo.ahora()
    if usuario.recuperacion_enviada and ahora - usuario.recuperacion_enviada < timedelta(
        minutes=MINUTOS_ENTRE_RECUPERACIONES
    ):
        return None
    usuario.recuperacion_enviada = ahora
    db.session.commit()
    return usuario


def restablecer_contrasena(usuario: Usuario, nueva: str, repetida: str) -> None:
    validar_contrasena_nueva(nueva, repetida)
    usuario.establecer_contrasena(nueva)
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    db.session.commit()
