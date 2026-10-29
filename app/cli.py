"""Comandos de consola: base de datos, datos de demostración, catálogo de palabras clave y
administración de la plataforma.

flask --app app crear-tablas
flask --app app demo [--si] [--solo-si-vacia]
flask --app app palabras listar [--tema ENVIO]
flask --app app palabras agregar "termino" ENVIO [--peso 1.5]
flask --app app palabras quitar "termino"

flask --app app admin comercios
flask --app app admin restablecer-clave CORREO [--generar]
flask --app app admin desbloquear CORREO
flask --app app admin pausar CORREO|ID
flask --app app admin activar CORREO|ID
flask --app app admin borrar-comprador TELEFONO [--comercio CORREO|ID] [--si]
flask --app app admin depurar [--dias 365] [--si]
flask --app app admin respaldar [DESTINO]
flask --app app admin verificar
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
            click.echo(f"{p.tema.value:<17} {p.peso:>4.1f}  {p.termino}")

    @palabras.command("agregar")
    @click.argument("termino")
    @click.argument("tema", type=click.Choice([t.value for t in TemaConsulta if t != TemaConsulta.NO_RECONOCIDO]))
    @click.option(
        "--peso",
        type=click.FloatRange(0.1, 5.0),
        default=1.0,
        show_default=True,
        help="Peso del término: más de 1 para frases inequívocas, menos para palabras que solo orientan.",
    )
    def agregar(termino, tema, peso):
        from .bot import intencion
        from .bot.normalizacion import normalizar

        termino = normalizar(termino)
        if not termino:
            raise click.ClickException("El término está vacío.")
        if db.session.scalar(select(PalabraClave).where(PalabraClave.termino == termino)):
            raise click.ClickException(f"«{termino}» ya está en el catálogo.")
        if termino in intencion.terminos_conversacionales():
            raise click.ClickException(
                f"«{termino}» es parte del vocabulario conversacional del bot (saludos, pedido de una persona, "
                "menú…) y no puede asignarse a un tema."
            )
        db.session.add(PalabraClave(termino=termino, tema=TemaConsulta(tema), peso=peso))
        db.session.commit()
        click.echo(f"Agregado «{termino}» al tema {tema} con peso {peso:g}.")

    @palabras.command("quitar")
    @click.argument("termino")
    def quitar(termino):
        from .bot.normalizacion import normalizar
        from .datos.palabras_clave import items_catalogo

        palabra = db.session.scalar(select(PalabraClave).where(PalabraClave.termino == normalizar(termino)))
        if palabra is None:
            raise click.ClickException("Ese término no está en el catálogo.")
        db.session.delete(palabra)
        db.session.commit()
        click.echo("Término quitado.")
        if palabra.termino in {normalizar(t) for t, _, _ in items_catalogo()}:
            click.echo(
                "Atención: el término viene con la aplicación y vuelve a agregarse cuando una actualización "
                "sincroniza el catálogo. Para quitarlo definitivamente, quítelo de app/datos/palabras_clave.py."
            )

    app.cli.add_command(palabras)
    app.cli.add_command(admin)


# ---------------------------------------------------------------------------
# Administración de la plataforma (O1, O6, O10)
# ---------------------------------------------------------------------------

admin = click.Group("admin", help="Administración de la plataforma: cuentas, comercios, datos y configuración.")


def _comercio(identificador: str) -> Comercio:
    """Comercio por su número o por el correo de su usuario."""
    from .modelos import Usuario, normalizar_email

    comercio = None
    if identificador.isdigit():
        comercio = db.session.get(Comercio, int(identificador))
    else:
        usuario = db.session.scalar(select(Usuario).where(Usuario.email == normalizar_email(identificador)))
        comercio = usuario.comercio if usuario else None
    if comercio is None:
        raise click.ClickException(f"No hay un comercio con el número o el correo «{identificador}».")
    return comercio


@admin.command("comercios")
def comercios():
    """Lista los comercios con su estado, su usuario y sus consultas pendientes."""
    from .modelos import Consulta, Conversacion, ResultadoConsulta

    filas = db.session.scalars(select(Comercio).order_by(Comercio.id_comercio)).all()
    if not filas:
        click.echo("No hay comercios registrados.")
        return
    click.echo(f"{'N.º':>4}  {'Comercio':<28} {'Estado':<18} {'Código':<7} {'Pend.':>5}  Correo")
    for c in filas:
        pendientes = db.session.scalar(
            select(func.count(Consulta.id_consulta))
            .join(Conversacion)
            .where(
                Conversacion.id_comercio == c.id_comercio,
                Consulta.resultado == ResultadoConsulta.DERIVADA,
                Consulta.atendida.is_(False),
            )
        )
        usuario = c.usuario
        correo = usuario.email if usuario else "-"
        if usuario and usuario.bloqueado_hasta:
            correo += f" (ingreso bloqueado hasta {usuario.bloqueado_hasta:%d/%m %H:%M})"
        click.echo(
            f"{c.id_comercio:>4}  {c.nombre[:28]:<28} {c.estado.etiqueta:<18} {c.codigo_acceso or '-':<7} "
            f"{pendientes:>5}  {correo}"
        )


@admin.command("restablecer-clave")
@click.argument("correo")
@click.option("--generar", is_flag=True, help="Generar una contraseña aleatoria y mostrarla una sola vez.")
def restablecer_clave(correo, generar):
    """Asigna una contraseña nueva a un usuario (por ejemplo, si no tiene acceso a su correo).

    También levanta el bloqueo por intentos y cierra sus sesiones abiertas."""
    import secrets

    from .servicios import ErrorValidacion
    from .servicios.cuentas import restablecer_contrasena

    usuario = _comercio(correo).usuario
    if generar:
        nueva = secrets.token_urlsafe(9)
        repetida = nueva
    else:
        nueva = click.prompt("Contraseña nueva", hide_input=True)
        repetida = click.prompt("Repita la contraseña", hide_input=True)
    try:
        restablecer_contrasena(usuario, nueva, repetida)
    except ErrorValidacion as error:
        raise click.ClickException(error.mensaje) from error
    click.echo(f"Contraseña de {usuario.email} actualizada. Sus sesiones abiertas se cerraron.")
    if generar:
        click.echo(f"Contraseña temporal: {nueva}")
        click.echo("Pídale que la cambie en «Cuenta» al ingresar.")


@admin.command("desbloquear")
@click.argument("correo")
def desbloquear(correo):
    """Levanta el bloqueo de ingreso por intentos fallidos (CU02)."""
    usuario = _comercio(correo).usuario
    usuario.intentos_fallidos = 0
    usuario.bloqueado_hasta = None
    db.session.commit()
    click.echo(f"{usuario.email} puede volver a ingresar.")


@admin.command("pausar")
@click.argument("comercio")
def pausar(comercio):
    """Pausa el bot de un comercio (por ejemplo, ante un uso indebido): responde que no está disponible."""
    c = _comercio(comercio)
    c.pausar_bot()
    db.session.commit()
    click.echo(f"Bot de {c.nombre} pausado. El responsable puede reactivarlo desde «Activación del bot».")


@admin.command("activar")
@click.argument("comercio")
def activar(comercio):
    """Activa (o reactiva) el bot de un comercio que completó el onboarding (CU07)."""
    c = _comercio(comercio)
    try:
        c.activar_bot()
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    db.session.commit()
    click.echo(f"Bot de {c.nombre} activo con el código {c.codigo_acceso}.")


@admin.command("borrar-comprador")
@click.argument("telefono")
@click.option("--comercio", "comercio", default=None, help="Solo sus datos con este comercio (número o correo).")
@click.option("--si", is_flag=True, help="No pedir confirmación.")
def borrar_comprador(telefono, comercio, si):
    """Borra las conversaciones de un comprador que lo pidió (Ley 25.326, art. 16)."""
    from .bot.servicio import normalizar_telefono
    from .modelos import Comprador
    from .servicios.retencion import borrar_datos_comprador

    numero = normalizar_telefono(telefono)
    comprador = db.session.scalar(select(Comprador).where(Comprador.telefono == numero))
    if comprador is None:
        raise click.ClickException(f"No hay datos del número {telefono}.")
    c = _comercio(comercio) if comercio else None
    alcance = f"con {c.nombre}" if c else "con todos los comercios"
    if not si:
        click.confirm(
            f"Se borrarán las conversaciones de {comprador.telefono_legible} {alcance}. ¿Continuar?", abort=True
        )
    cantidad = borrar_datos_comprador(comprador, c)
    click.echo(f"Conversaciones borradas: {cantidad}.")


@admin.command("depurar")
@click.option("--dias", type=click.IntRange(1), default=None, help="Antigüedad en días (por defecto, RETENCION_DIAS).")
@click.option("--si", is_flag=True, help="No pedir confirmación.")
def depurar(dias, si):
    """Borra los mensajes y las consultas antiguas, salvo las consultas pendientes (O6)."""
    from flask import current_app

    from .servicios.retencion import depurar as depurar_datos
    from .servicios.retencion import limite_de_retencion

    dias = dias or current_app.config.get("RETENCION_DIAS") or 0
    if dias <= 0:
        raise click.ClickException("RETENCION_DIAS es 0: indique los días con --dias.")
    limite = limite_de_retencion(dias)
    if not si:
        click.confirm(f"Se borrarán los datos anteriores al {limite:%d/%m/%Y %H:%M}. ¿Continuar?", abort=True)
    resultado = depurar_datos(limite)
    click.echo(f"Borrados: {resultado}.")


@admin.command("respaldar")
@click.argument("destino", required=False, type=click.Path(dir_okay=False))
def respaldar(destino):
    """Copia la base SQLite a un archivo (por defecto, instance/respaldos/plataforma-AAAAMMDD-HHMM.db).

    Usa la copia en caliente de SQLite: se puede ejecutar con el servidor andando."""
    import sqlite3
    from pathlib import Path

    from flask import current_app

    from .utilidades import tiempo

    if db.engine.dialect.name != "sqlite":
        raise click.ClickException("El respaldo integrado solo funciona con SQLite.")
    if destino:
        ruta = Path(destino)
    else:
        carpeta = Path(current_app.instance_path) / "respaldos"
        ruta = carpeta / f"plataforma-{tiempo.ahora():%Y%m%d-%H%M}.db"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    origen = db.engine.raw_connection()
    try:
        copia = sqlite3.connect(ruta)
        try:
            origen.driver_connection.backup(copia)
        finally:
            copia.close()
    finally:
        origen.close()
    click.echo(f"Respaldo guardado en {ruta} ({ruta.stat().st_size // 1024} KB).")


@admin.command("verificar")
def verificar():
    """Revisa la configuración y avisa lo inseguro o incompleto (O10). Sale con código 1 si hay errores."""
    from flask import current_app

    from .verificacion import en_produccion, problemas_de_configuracion

    modo = "despliegue real" if en_produccion(current_app.config) else "local o demostración"
    click.echo(f"Configuración ({modo}):")
    problemas = problemas_de_configuracion(current_app)
    if not problemas:
        click.echo("  Sin observaciones.")
        return
    for problema in problemas:
        click.echo(f"  [{problema.nivel}] {problema.texto}")
    if any(p.nivel == "error" for p in problemas):
        raise SystemExit(1)
