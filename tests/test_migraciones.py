"""Migraciones del esquema: una base de la versión 0.1 se actualiza sin perder datos."""

import sqlite3
from contextlib import closing

from sqlalchemy import inspect, select

from app import create_app, migraciones
from app.config import ConfigPruebas
from app.extensiones import db
from app.modelos import Comercio, Consulta, PalabraClave, TemaConsulta

# Esquema de las tablas que cambiaron, tal como lo creaba la versión 0.1.
ESQUEMA_0_1 = """
CREATE TABLE comercio (id_comercio INTEGER PRIMARY KEY, nombre TEXT NOT NULL, rubro TEXT NOT NULL,
  telefono_contacto TEXT NOT NULL, codigo_acceso TEXT UNIQUE, estado VARCHAR(20) NOT NULL,
  fecha_alta DATE NOT NULL, paso_onboarding INTEGER NOT NULL);
CREATE TABLE zona_envio (id_zona INTEGER PRIMARY KEY, id_comercio INTEGER NOT NULL REFERENCES comercio(id_comercio),
  cp_desde INTEGER NOT NULL, cp_hasta INTEGER NOT NULL, descripcion TEXT NOT NULL,
  plazo_min_dias INTEGER NOT NULL, plazo_max_dias INTEGER NOT NULL);
CREATE TABLE comprador (id_comprador INTEGER PRIMARY KEY, telefono TEXT UNIQUE NOT NULL, nombre TEXT,
  fecha_primer_contacto DATETIME NOT NULL);
CREATE TABLE conversacion (id_conversacion INTEGER PRIMARY KEY,
  id_comercio INTEGER NOT NULL REFERENCES comercio(id_comercio),
  id_comprador INTEGER NOT NULL REFERENCES comprador(id_comprador), estado VARCHAR(20) NOT NULL,
  fecha_inicio DATETIME NOT NULL, ultima_actividad DATETIME NOT NULL, intentos_cp INTEGER NOT NULL);
CREATE TABLE mensaje (id_mensaje INTEGER PRIMARY KEY,
  id_conversacion INTEGER NOT NULL REFERENCES conversacion(id_conversacion), texto TEXT NOT NULL,
  direccion VARCHAR(20) NOT NULL, fecha_hora DATETIME NOT NULL, id_externo TEXT UNIQUE);
CREATE TABLE consulta (id_consulta INTEGER PRIMARY KEY,
  id_conversacion INTEGER NOT NULL REFERENCES conversacion(id_conversacion), tema VARCHAR(20) NOT NULL,
  resultado VARCHAR(20) NOT NULL, codigo_postal INTEGER, fecha_hora DATETIME NOT NULL, atendida BOOLEAN NOT NULL,
  fecha_atencion DATETIME);
CREATE TABLE palabra_clave (id_palabra INTEGER PRIMARY KEY, termino TEXT UNIQUE NOT NULL, tema VARCHAR(20) NOT NULL);
INSERT INTO comprador VALUES (1, '5493510000001', 'Lucía', '2026-10-20 21:00:00');
INSERT INTO conversacion VALUES (1, 1, 1, 'ACTIVA', '2026-10-20 21:00:00', '2026-10-20 21:05:00', 0);
INSERT INTO consulta VALUES (1, 1, 'ENVIO', 'RESUELTA', 5000, '2026-10-20 21:01:00', 0, NULL);
INSERT INTO comercio VALUES (1, 'Casa & Detalles', 'Hogar', '351 012-3456', 'CASA26', 'ACTIVO', '2026-10-01', 6);
INSERT INTO zona_envio VALUES (1, 1, 5000, 5099, 'Córdoba Capital', 1, 2);
INSERT INTO palabra_clave VALUES (1, 'pague', 'MEDIOS_PAGO');
INSERT INTO palabra_clave VALUES (2, 'puf', 'PRODUCTOS');
"""


class ConfigBaseArchivo(ConfigPruebas):
    SQLALCHEMY_DATABASE_URI = None  # se define en cada prueba


def _app_con_base(ruta):
    class Config(ConfigBaseArchivo):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{ruta}"

    return create_app(Config)


def test_base_nueva_queda_en_la_ultima_version(tmp_path):
    app = _app_con_base(tmp_path / "nueva.db")
    with app.app_context():
        with db.engine.connect() as conexion:
            assert migraciones.version_de(conexion) == migraciones.VERSION_ACTUAL
        assert db.session.scalar(select(PalabraClave).where(PalabraClave.termino == "codigo postal")).peso == 2.0
        db.session.remove()
        db.engine.dispose()


def test_base_de_la_version_0_1_se_actualiza(tmp_path):
    ruta = tmp_path / "vieja.db"
    with closing(sqlite3.connect(ruta)) as conexion:
        conexion.executescript(ESQUEMA_0_1)

    app = _app_con_base(ruta)
    with app.app_context():
        columnas = {c["name"] for c in inspect(db.engine).get_columns("zona_envio")}
        assert "costo" in columnas
        assert {"intentos_sin_entender", "ultimo_tema", "ultimo_cp"} <= {
            c["name"] for c in inspect(db.engine).get_columns("conversacion")
        }
        assert {"id_respuesta", "alerta", "fuera_de_horario"} <= {
            c["name"] for c in inspect(db.engine).get_columns("consulta")
        }
        assert {"silenciada_hasta", "advertencias"} <= {
            c["name"] for c in inspect(db.engine).get_columns("conversacion")
        }
        assert inspect(db.engine).has_table("respuesta_frecuente") and inspect(db.engine).has_table("bloqueo")
        # Los datos existentes se conservan.
        comercio = db.session.get(Comercio, 1)
        consulta = db.session.get(Consulta, 1)
        assert consulta.codigo_postal == 5000 and consulta.id_respuesta is None and comercio.respuestas_frecuentes == []
        # Sin el dato guardado, el resumen calcula «fuera de horario» con el horario actual.
        assert consulta.fuera_de_horario is None and consulta.alerta is None
        assert consulta.conversacion.advertencias == 0
        assert comercio.zonas[0].descripcion == "Córdoba Capital" and comercio.zonas[0].costo is None
        assert comercio.envio_gratis_desde is None
        # El catálogo se sincroniza: el término de la aplicación cambia de tema y el del operador se conserva.
        assert db.session.scalar(select(PalabraClave).where(PalabraClave.termino == "pague")).tema == (
            TemaConsulta.PAGOS_INFORMADOS
        )
        assert db.session.scalar(select(PalabraClave).where(PalabraClave.termino == "puf")) is not None
        assert db.session.scalar(select(PalabraClave).where(PalabraClave.termino == "codigo postal")) is not None
        db.session.remove()
        db.engine.dispose()

    # Iniciar de nuevo no vuelve a migrar ni duplica términos.
    app = _app_con_base(ruta)
    with app.app_context():
        terminos = db.session.scalars(select(PalabraClave.termino)).all()
        assert len(terminos) == len(set(terminos))
        db.session.remove()
        db.engine.dispose()


def test_los_pasos_son_idempotentes(tmp_path):
    app = _app_con_base(tmp_path / "doble.db")
    with app.app_context():
        with db.engine.begin() as conexion:
            for _, paso, _ in migraciones.PASOS:
                paso(conexion)
        db.session.remove()
        db.engine.dispose()
