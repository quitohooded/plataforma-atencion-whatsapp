"""Comandos de consola del operador: catálogo de palabras clave y datos de demostración."""

from sqlalchemy import func, select

from app.extensiones import db
from app.modelos import Comercio, PalabraClave, TemaConsulta


def test_palabras_agregar_listar_y_quitar(app):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["palabras", "agregar", "Pufs", "PRODUCTOS", "--peso", "1.5"])
    assert r.exit_code == 0, r.output
    palabra = db.session.scalar(select(PalabraClave).where(PalabraClave.termino == "pufs"))
    assert (palabra.tema, palabra.peso) == (TemaConsulta.PRODUCTOS, 1.5)

    listado = runner.invoke(args=["palabras", "listar", "--tema", "PRODUCTOS"])
    assert "pufs" in listado.output and "1.5" in listado.output

    duplicado = runner.invoke(args=["palabras", "agregar", "pufs", "PRODUCTOS"])
    assert duplicado.exit_code != 0 and "ya está en el catálogo" in duplicado.output

    quitar = runner.invoke(args=["palabras", "quitar", "pufs"])
    assert quitar.exit_code == 0 and "Atención" not in quitar.output


def test_palabras_no_admite_vocabulario_conversacional(app):
    r = app.test_cli_runner().invoke(args=["palabras", "agregar", "persona", "PRODUCTOS"])
    assert r.exit_code != 0 and "vocabulario conversacional" in r.output


def test_quitar_un_termino_de_la_aplicacion_avisa_que_vuelve(app):
    r = app.test_cli_runner().invoke(args=["palabras", "quitar", "envio"])
    assert r.exit_code == 0 and "vuelve a agregarse" in r.output


def test_demo_solo_si_vacia_no_borra_datos(app, comercio):
    r = app.test_cli_runner().invoke(args=["demo", "--solo-si-vacia"])
    assert "Ya hay comercios registrados" in r.output
    assert db.session.scalar(select(func.count()).select_from(Comercio)) == 1
