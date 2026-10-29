"""Migraciones del esquema de la base SQLite.

El prototipo no usa Alembic: el esquema es chico y cambia poco. Cada versión es una
función que se aplica una sola vez, en orden, y la versión vigente se guarda en
``PRAGMA user_version`` de SQLite. Una base nueva se crea con el esquema completo y queda
directamente en la última versión.

Cada paso es idempotente (verifica antes de alterar), así que aplicarlo dos veces no
rompe nada. Si se agrega una columna a un modelo, se agrega acá un paso nuevo. Las tablas
nuevas no necesitan un paso: ``db.create_all()`` crea las que faltan antes de migrar.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, select

log = logging.getLogger(__name__)


def _columnas(conexion, tabla: str) -> set[str]:
    return {c["name"] for c in inspect(conexion).get_columns(tabla)}


def _agregar_columna(conexion, tabla: str, definicion: str) -> None:
    nombre = definicion.split()[0]
    if nombre not in _columnas(conexion, tabla):
        conexion.exec_driver_sql(f"ALTER TABLE {tabla} ADD COLUMN {definicion}")
        log.info("Migración: columna %s.%s agregada.", tabla, nombre)


def _version_1(conexion) -> None:
    """1.0: costo del envío, catálogo, contexto de la conversación, botones y pesos."""
    _agregar_columna(conexion, "comercio", "envio_gratis_desde INTEGER")
    _agregar_columna(conexion, "comercio", "enlace_catalogo TEXT")
    _agregar_columna(conexion, "zona_envio", "costo INTEGER")
    _agregar_columna(conexion, "conversacion", "intentos_sin_entender INTEGER NOT NULL DEFAULT 0")
    _agregar_columna(conexion, "conversacion", "ultimo_tema VARCHAR(20)")
    _agregar_columna(conexion, "conversacion", "ultimo_cp INTEGER")
    _agregar_columna(conexion, "mensaje", "botones TEXT")
    _agregar_columna(conexion, "palabra_clave", "peso FLOAT NOT NULL DEFAULT 1.0")


def _version_2(conexion) -> None:
    """1.0: respuestas propias del comercio (la tabla respuesta_frecuente la crea create_all)."""
    _agregar_columna(
        conexion,
        "consulta",
        "id_respuesta INTEGER REFERENCES respuesta_frecuente(id_respuesta) ON DELETE SET NULL",
    )


def _version_3(conexion) -> None:
    """1.0: alertas de seguridad, horario al momento de la consulta y pausas por abuso (la tabla
    bloqueo la crea create_all)."""
    _agregar_columna(conexion, "consulta", "alerta VARCHAR(20)")
    _agregar_columna(conexion, "consulta", "fuera_de_horario BOOLEAN")
    _agregar_columna(conexion, "conversacion", "silenciada_hasta DATETIME")
    _agregar_columna(conexion, "conversacion", "advertencias INTEGER NOT NULL DEFAULT 0")


def _version_4(conexion) -> None:
    """1.0: aviso por correo de pendientes y recuperación de contraseña."""
    _agregar_columna(conexion, "comercio", "avisos_correo BOOLEAN NOT NULL DEFAULT 0")
    _agregar_columna(conexion, "comercio", "ultimo_aviso_correo DATETIME")
    _agregar_columna(conexion, "usuario", "recuperacion_enviada DATETIME")


def _version_5(conexion) -> None:
    """1.0: estado de entrega de las respuestas del bot que informa WhatsApp."""
    _agregar_columna(conexion, "mensaje", "estado_envio VARCHAR(12)")


# (versión, paso del esquema, ¿actualiza el catálogo de palabras clave?)
PASOS = [
    (1, _version_1, True),
    (2, _version_2, True),
    (3, _version_3, True),
    (4, _version_4, False),
    (5, _version_5, False),
]
VERSION_ACTUAL = PASOS[-1][0]


def version_de(conexion) -> int:
    if conexion.dialect.name != "sqlite":
        return VERSION_ACTUAL
    return int(conexion.exec_driver_sql("PRAGMA user_version").scalar() or 0)


def _fijar_version(conexion, version: int) -> None:
    if conexion.dialect.name == "sqlite":
        conexion.exec_driver_sql(f"PRAGMA user_version = {int(version)}")


def sincronizar_palabras(session) -> int:
    """Incorpora los términos del catálogo que falten y actualiza el tema y el peso de los
    que vienen con la aplicación. Los términos que agregó el operador no se tocan."""
    from .bot.normalizacion import normalizar
    from .datos.palabras_clave import items_catalogo
    from .modelos import PalabraClave

    existentes = {p.termino: p for p in session.scalars(select(PalabraClave))}
    cambios = 0
    for termino, tema, peso in items_catalogo():
        termino = normalizar(termino)
        actual = existentes.get(termino)
        if actual is None:
            nueva = PalabraClave(termino=termino, tema=tema, peso=peso)
            session.add(nueva)
            existentes[termino] = nueva
            cambios += 1
        elif actual.tema != tema or abs((actual.peso or 0) - peso) > 1e-9:
            actual.tema, actual.peso = tema, peso
            cambios += 1
    session.commit()
    return cambios


def aplicar(db, base_nueva: bool) -> None:
    """Lleva el esquema a la última versión. Se llama al iniciar la aplicación."""
    with db.engine.begin() as conexion:
        version = VERSION_ACTUAL if base_nueva else version_de(conexion)
        pendientes = [p for p in PASOS if p[0] > version]
        for numero, paso, _ in pendientes:
            log.info("Aplicando la migración %s del esquema.", numero)
            paso(conexion)
        _fijar_version(conexion, VERSION_ACTUAL)
    if base_nueva or any(sincroniza for _, _, sincroniza in pendientes):
        cambios = sincronizar_palabras(db.session)
        if cambios and not base_nueva:
            log.info("Catálogo de palabras clave actualizado: %s términos.", cambios)
