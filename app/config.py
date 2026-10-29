"""Configuración de la aplicación a partir de variables de entorno (.env)."""

import os


def _bool(nombre: str, por_defecto: bool) -> bool:
    valor = os.environ.get(nombre)
    if valor is None or valor.strip() == "":
        return por_defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def _int(nombre: str, por_defecto: int) -> int:
    try:
        return int(os.environ.get(nombre, por_defecto))
    except (TypeError, ValueError):
        return por_defecto


class Config:
    # Si no se define, create_app genera una clave aleatoria y la guarda en instance/clave_secreta.txt.
    SECRET_KEY = os.environ.get("SECRET_KEY") or None
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or None  # se completa en create_app
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # planillas CSV de hasta 2 MB
    WTF_CSRF_TIME_LIMIT = None

    PLATAFORMA_NOMBRE = os.environ.get("PLATAFORMA_NOMBRE") or "Respondé"
    ZONA_HORARIA = os.environ.get("ZONA_HORARIA") or "America/Argentina/Cordoba"
    CONVERSACION_HORAS_INACTIVIDAD = _int("CONVERSACION_HORAS_INACTIVIDAD", 24)
    SIMULADOR_HABILITADO = _bool("SIMULADOR_HABILITADO", True)
    CONFIAR_EN_PROXY = _bool("CONFIAR_EN_PROXY", False)

    # CU02: bloqueo luego de cinco intentos fallidos durante quince minutos.
    LOGIN_MAX_INTENTOS = _int("LOGIN_MAX_INTENTOS", 5)
    LOGIN_BLOQUEO_MINUTOS = _int("LOGIN_BLOQUEO_MINUTOS", 15)

    # CU09: cantidad de códigos postales inválidos antes de derivar.
    BOT_MAX_INTENTOS_CP = _int("BOT_MAX_INTENTOS_CP", 2)

    WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "")
    WHATSAPP_API_VERSION = os.environ.get("WHATSAPP_API_VERSION") or "v23.0"
    WHATSAPP_NUMERO_PUBLICO = "".join(ch for ch in os.environ.get("WHATSAPP_NUMERO_PUBLICO", "") if ch.isdigit())
    WHATSAPP_AR_QUITAR_9 = _bool("WHATSAPP_AR_QUITAR_9", True)

    # Dirección pública del panel, para los enlaces de los correos (por ejemplo, https://respondé.ar).
    URL_PUBLICA = (os.environ.get("URL_PUBLICA") or "").rstrip("/")

    # Seguridad web (#12). Las cookies viajan solo por HTTPS cuando la dirección pública es https
    # (o si se fuerza con COOKIES_SEGURAS=true). Límites de intentos por IP en ingreso, registro,
    # recuperación de contraseña y simulador.
    COOKIES_SEGURAS = _bool("COOKIES_SEGURAS", URL_PUBLICA.startswith("https://"))
    SESSION_COOKIE_SECURE = COOKIES_SEGURAS
    LIMITES_POR_IP = _bool("LIMITES_POR_IP", True)

    # Correo (avisos de pendientes y recuperación de contraseña). Sin costo por defecto: en modo
    # «archivo» los correos se guardan en instance/correos. Para enviarlos se usa cualquier
    # servidor SMTP, por ejemplo una cuenta de Gmail con contraseña de aplicación.
    MAIL_MODO = (os.environ.get("MAIL_MODO") or "archivo").strip().lower()  # archivo, smtp o desactivado
    MAIL_SERVIDOR = os.environ.get("MAIL_SERVIDOR", "")
    MAIL_PUERTO = _int("MAIL_PUERTO", 587)
    MAIL_USUARIO = os.environ.get("MAIL_USUARIO", "")
    MAIL_CONTRASENA = os.environ.get("MAIL_CONTRASENA", "")
    MAIL_REMITENTE = os.environ.get("MAIL_REMITENTE", "")
    MAIL_TLS = _bool("MAIL_TLS", True)
    # Como máximo un aviso de pendientes por correo cada tantos minutos.
    AVISOS_CORREO_MINUTOS = _int("AVISOS_CORREO_MINUTOS", 30)
    # Vigencia del enlace de recuperación de contraseña.
    RECUPERACION_MINUTOS = _int("RECUPERACION_MINUTOS", 60)


class ConfigPruebas(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "pruebas"
    SIMULADOR_HABILITADO = True
    WHATSAPP_TOKEN = ""
    WHATSAPP_PHONE_NUMBER_ID = ""
    WHATSAPP_VERIFY_TOKEN = "token-de-prueba"
    WHATSAPP_APP_SECRET = "secreto-de-prueba"
    WHATSAPP_NUMERO_PUBLICO = "15550000000"
    MAIL_MODO = "memoria"
    URL_PUBLICA = "http://localhost"
    COOKIES_SEGURAS = False
    SESSION_COOKIE_SECURE = False
    # Las pruebas de límites los activan en su propia configuración.
    LIMITES_POR_IP = False
