"""Comandos de consola: base de datos, datos de demostración y catálogo de palabras clave.

flask --app app crear-tablas
flask --app app demo [--si] [--solo-si-vacia]
flask --app app palabras listar [--tema ENVIO]
flask --app app palabras agregar "termino" ENVIO
flask --app app palabras quitar "termino"
"""

from __future__ import annotations

import click
from flask import Flask
from sqlalchemy import func, select

from .extensiones import db
from .modelos import Comercio, PalabraClave, TemaConsulta


def registrar_comandos(app: Flask) -> None:
    @app.cli.command("crear-tablas")
    def crear_tablas():
        """Crea las tablas de la base SQLite y carga las palabras clave iniciales."""
        from . import inicializar_base

        inicializar_base()
        click.echo("Base de datos lista.")

    @app.cli.command("demo")
    @click.option("--si", is_flag=True, help="No pedir confirmación antes de borrar los datos.")
    @click.option("--solo-si-vacia", is_flag=True, help="Cargar la demo solo si no hay comercios registrados.")
    def demo(si: bool, solo_si_vacia: bool):
        """Borra la base y carga los comercios de ejemplo con su historial."""
        from .datos.demo import cargar_demo

        if solo_si_vacia and db.session.scalar(select(func.count()).select_from(Comercio)):
            click.echo("Ya hay comercios registrados: no se cargó la demo.")
            return
        if not si and not solo_si_vacia:
            click.confirm("Se borrarán todos los datos de la base. ¿Continuar?", abort=True)
        resumen = cargar_demo()
        click.echo("Datos de demostración cargados:")
        for linea in resumen:
            click.echo(f"  {linea}")

    palabras = click.Group("palabras", help="Catálogo de palabras clave del bot.")

    @palabras.command("listar")
    @click.option("--tema", type=click.Choice([t.value for t in TemaConsulta]), default=None)
    def listar(tema):
        consulta = select(PalabraClave).order_by(PalabraClave.tema, PalabraClave.termino)
        if tema:
            consulta = consulta.where(PalabraClave.tema == TemaConsulta(tema))
        for p in db.session.scalars(consulta):
            click.echo(f"{p.tema.value:<12} {p.termino}")

    @palabras.command("agregar")
    @click.argument("termino")
    @click.argument("tema", type=click.Choice([t.value for t in TemaConsulta if t != TemaConsulta.NO_RECONOCIDO]))
    def agregar(termino, tema):
        from .bot.normalizacion import normalizar

        termino = normalizar(termino)
        if not termino:
            raise click.ClickException("El término está vacío.")
        if db.session.scalar(select(PalabraClave).where(PalabraClave.termino == termino)):
            raise click.ClickException(f"«{termino}» ya está en el catálogo.")
        db.session.add(PalabraClave(termino=termino, tema=TemaConsulta(tema)))
        db.session.commit()
        click.echo(f"Agregado «{termino}» al tema {tema}.")

    @palabras.command("quitar")
    @click.argument("termino")
    def quitar(termino):
        from .bot.normalizacion import normalizar

        palabra = db.session.scalar(select(PalabraClave).where(PalabraClave.termino == normalizar(termino)))
        if palabra is None:
            raise click.ClickException("Ese término no está en el catálogo.")
        db.session.delete(palabra)
        db.session.commit()
        click.echo("Término quitado.")

    app.cli.add_command(palabras)
