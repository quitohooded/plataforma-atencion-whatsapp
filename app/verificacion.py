"""Verificación de la configuración al iniciar (O10).

Detecta combinaciones inseguras o incompletas (simulador abierto en un despliegue real,
webhook sin clave para verificar la firma, correo sin servidor…) y las informa en el
registro al arrancar y con ``flask --app app admin verificar``. No impide arrancar: un
prototipo en una computadora local no tiene por qué cumplir todo.
"""

from __future__ import annotations

from dataclasses import dataclass

from flask import Flask

EJEMPLO_VERIFY_TOKEN = "un-texto-secreto-para-verificar-el-webhook"


@dataclass(frozen=True)
class Problema:
    nivel: str  # «error»: algo no va a funcionar o es inseguro; «aviso»: conviene revisarlo
    texto: str


def en_produccion(config) -> bool:
    """Despliegue real: la línea de WhatsApp está configurada o el panel se publica por HTTPS."""
    return bool(config.get("WHATSAPP_TOKEN")) or str(config.get("URL_PUBLICA", "")).startswith("https://")


def problemas_de_configuracion(app: Flask) -> list[Problema]:
    c = app.config
    problemas: list[Problema] = []
    produccion = en_produccion(c)

    def error(texto: str) -> None:
        problemas.append(Problema("error", texto))

    def aviso(texto: str) -> None:
        problemas.append(Problema("aviso", texto))

    # --- WhatsApp -----------------------------------------------------------
    if c.get("WHATSAPP_TOKEN"):
        if not c.get("WHATSAPP_APP_SECRET"):
            if c.get("WHATSAPP_PERMITIR_SIN_FIRMA"):
                error(
                    "El webhook acepta eventos sin firma (WHATSAPP_PERMITIR_SIN_FIRMA): cualquiera podría inventar "
                    "mensajes. Configure WHATSAPP_APP_SECRET y quite esa opción."
                )
            else:
                error(
                    "Falta WHATSAPP_APP_SECRET: el webhook rechaza todos los eventos porque no puede verificar la "
                    "firma de Meta."
                )
        if not c.get("WHATSAPP_PHONE_NUMBER_ID"):
            error("Falta WHATSAPP_PHONE_NUMBER_ID: el bot no puede enviar respuestas.")
        if not c.get("WHATSAPP_NUMERO_PUBLICO"):
            aviso("Falta WHATSAPP_NUMERO_PUBLICO: los enlaces y los QR de los comercios apuntan al simulador.")
        if not c.get("WHATSAPP_VERIFY_TOKEN") or c.get("WHATSAPP_VERIFY_TOKEN") == EJEMPLO_VERIFY_TOKEN:
            aviso("WHATSAPP_VERIFY_TOKEN está vacío o es el del ejemplo: use un texto propio y difícil de adivinar.")

    # --- Panel y sesiones ---------------------------------------------------
    if produccion and c.get("SIMULADOR_HABILITADO"):
        aviso(
            "El simulador está habilitado en un despliegue real: cualquiera puede escribirles a los comercios "
            "activos desde /simulador. Desactívelo con SIMULADOR_HABILITADO=false si no lo usa para demostraciones."
        )
    if produccion and not c.get("SECRET_KEY_DEFINIDA"):
        aviso(
            "SECRET_KEY no está definida: se usa la clave guardada en instance/clave_secreta.txt. Si el servidor "
            "borra esa carpeta al desplegar, todas las sesiones se cierran. Defina SECRET_KEY."
        )
    elif c.get("SECRET_KEY_DEFINIDA") and len(str(c.get("SECRET_KEY"))) < 32:
        aviso("SECRET_KEY es corta: use al menos 32 caracteres aleatorios.")
    if str(c.get("URL_PUBLICA", "")).startswith("https://") and not c.get("SESSION_COOKIE_SECURE"):
        aviso(
            "La dirección pública es https pero COOKIES_SEGURAS está desactivado: la sesión podría viajar sin cifrar."
        )
    if produccion and not c.get("LIMITES_POR_IP"):
        aviso("Los límites de intentos por IP están desactivados (LIMITES_POR_IP=false).")

    # --- Correo -------------------------------------------------------------
    modo = c.get("MAIL_MODO")
    if modo not in {"archivo", "smtp", "desactivado", "memoria"}:
        error(f"MAIL_MODO «{modo}» no es válido: use archivo, smtp o desactivado.")
    elif modo == "smtp":
        if not c.get("MAIL_SERVIDOR"):
            error("MAIL_MODO es smtp pero falta MAIL_SERVIDOR: no se envía ningún correo.")
        if not c.get("MAIL_REMITENTE") and not c.get("MAIL_USUARIO"):
            aviso("Falta MAIL_REMITENTE: los correos salen sin remitente claro.")
    if modo in {"smtp", "archivo"} and produccion and not c.get("URL_PUBLICA"):
        aviso("Falta URL_PUBLICA: los enlaces de los correos se arman con la dirección de cada pedido.")
    if produccion and modo == "archivo":
        aviso(
            "Los correos se guardan en instance/correos y no se envían (MAIL_MODO=archivo): la recuperación de "
            "contraseña y los avisos no les llegan a los comercios."
        )

    # --- Privacidad ---------------------------------------------------------
    if produccion and not c.get("CONTACTO_PLATAFORMA"):
        aviso(
            "Falta CONTACTO_PLATAFORMA: la política de privacidad no muestra un correo para ejercer los derechos "
            "sobre los datos personales (Ley 25.326)."
        )
    if not c.get("RETENCION_DIAS"):
        aviso("RETENCION_DIAS es 0: los mensajes se guardan sin límite de tiempo.")
    return problemas
