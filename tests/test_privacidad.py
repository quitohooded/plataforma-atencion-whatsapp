"""Privacidad (#14): política de privacidad y términos, consentimiento al registrarse, preguntas y
pedidos de borrado de datos en el bot y supresión desde el panel (Ley 25.326)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import create_app
from app.bot.contexto import ContextoConversacion
from app.bot.motor import MotorConversacional
from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.config import ConfigPruebas
from app.datos.casa_y_detalles import datos_comercio
from app.datos.palabras_clave import items_catalogo
from app.extensiones import db
from app.modelos import Bloqueo, Comercio, Comprador, Consulta, Conversacion, TemaConsulta, Usuario
from app.servicios import metricas

from .conftest import MARTES_NOCHE, ingresar

CASA = datos_comercio()
CATALOGO = items_catalogo()


def procesar(texto, contexto=None, datos=CASA, ahora=MARTES_NOCHE):
    return MotorConversacional().procesar(datos, contexto or ContextoConversacion(), texto, CATALOGO, ahora)


# --- Páginas legales ------------------------------------------------------------------


def test_politica_de_privacidad(cliente):
    r = cliente.get("/privacidad")
    html = " ".join(r.get_data(as_text=True).split())
    assert r.status_code == 200
    assert "Política de privacidad" in html and "Ley N.º 25.326" in html
    # Leyendas de la Disposición 10/2008: derecho de acceso y órgano de control.
    assert "a intervalos no inferiores a seis meses" in html
    assert "Agencia de Acceso a la Información Pública" in html
    # Lo que se guarda y lo que no.
    assert "se ocultan antes de guardar" in html and "No se usan para publicidad" in html
    # Plazo de retención configurado (365 días).
    assert "se borran automáticamente al año" in html
    assert 'href="/terminos"' in html


def test_terminos_de_uso(cliente):
    r = cliente.get("/terminos")
    html = " ".join(r.get_data(as_text=True).split())
    assert r.status_code == 200
    assert "Términos de uso" in html and "políticas de" in html and "business.whatsapp.com/policy" in html
    assert 'href="/privacidad"' in html


class ConfigConContacto(ConfigPruebas):
    CONTACTO_PLATAFORMA = "privacidad@ejemplo.com"
    RETENCION_DIAS = 180


def test_contacto_y_plazo_configurables(reloj):
    aplicacion = create_app(ConfigConContacto)
    with aplicacion.app_context():
        cliente = aplicacion.test_client()
        html = " ".join(cliente.get("/privacidad").get_data(as_text=True).split())
        assert 'href="mailto:privacidad@ejemplo.com"' in html and "a los 180 días" in html
        assert 'href="mailto:privacidad@ejemplo.com"' in cliente.get("/terminos").get_data(as_text=True)
        db.session.remove()
        db.engine.dispose()


@pytest.mark.parametrize("ruta", ["/", "/ingresar", "/registro", "/simulador"])
def test_enlaces_legales_en_las_paginas_publicas(cliente, ruta):
    html = cliente.get(ruta).get_data(as_text=True)
    assert 'href="/privacidad"' in html and 'href="/terminos"' in html


def test_la_ayuda_del_panel_explica_los_datos_personales(sesion):
    html = " ".join(sesion.get("/ayuda").get_data(as_text=True).split())
    assert "Datos personales de sus compradores" in html and 'href="/privacidad"' in html
    assert "después de 365 días" in html


# --- Bot: preguntas sobre los datos ----------------------------------------------------


def test_el_bot_explica_que_se_hace_con_los_datos():
    r = procesar("¿qué hacen con mis datos?")
    assert r.acciones == ["PRIVACIDAD"] and r.consultas == []
    texto = r.textos[0]
    assert "Casa & Detalles" in texto and "sin datos de tarjeta" in texto and "no se usan para publicidad" in texto
    assert "*borrar mis datos*" in texto


def test_la_respuesta_incluye_el_plazo_y_el_enlace_si_estan_configurados():
    datos = replace(CASA, retencion_dias=365, url_privacidad="https://responde.example/privacidad")
    texto = procesar("guardan mis mensajes?", datos=datos).textos[0]
    assert "Se borran solos al año" in texto and "borren antes" in texto
    assert texto.endswith("Más información: https://responde.example/privacidad")


def test_pedido_de_borrar_los_datos_se_deriva():
    r = procesar("quiero que borren mis datos")
    assert r.acciones == ["D:DATOS"]
    assert r.consultas[0].tema == TemaConsulta.DATOS_PERSONALES
    assert "borre tus mensajes y tus datos" in r.textos[0] and "351 012-3456" in r.textos[0]


def test_pedido_de_borrado_con_una_consulta():
    r = procesar("hacen envíos a Rosario? y borren mis datos después")
    assert set(r.acciones) == {"ENVIO", "D:DATOS"}


def test_pedido_de_borrado_durante_una_derivacion_no_se_duplica():
    primero = procesar("tienen el mantel en gris?")
    segundo = procesar("y borren mis datos por favor", contexto=primero.contexto)
    assert segundo.acciones == ["D:DATOS"]
    tercero = procesar("borren mis datos", contexto=segundo.contexto)
    assert "D:DATOS" not in tercero.acciones


def test_pedido_de_borrado_se_atiende_aunque_el_bot_este_en_pausa():
    spam = procesar("Ganá dinero desde tu casa con cripto, escribime")
    assert spam.acciones == ["SPAM"]
    r = procesar("borren mis datos", contexto=spam.contexto, ahora=MARTES_NOCHE + timedelta(minutes=5))
    assert r.acciones == ["D:DATOS"]


@pytest.mark.parametrize(
    "mensaje,esperado",
    [
        ("te paso mis datos para el envío a Córdoba", ["ENVIO"]),
        ("necesito tus datos para transferir", ["PAGO"]),
        ("mis datos personales: Juan Pérez, DNI en el pedido 2045", None),
    ],
)
def test_frases_parecidas_que_no_son_de_privacidad(mensaje, esperado):
    acciones = procesar(mensaje).acciones
    assert "PRIVACIDAD" not in acciones and "D:DATOS" not in acciones
    if esperado is not None:
        assert acciones == esperado


# --- Panel: el pedido queda pendiente y se resuelve desde el detalle ------------------------


def _conversar(comercio, telefono, *textos, momento=MARTES_NOCHE):
    procesar_mensaje_entrante(
        MensajeEntrante(telefono=telefono, texto=comercio.texto_primer_mensaje(), fecha_hora=momento)
    )
    resultado = None
    for texto in textos:
        resultado = procesar_mensaje_entrante(MensajeEntrante(telefono=telefono, texto=texto, fecha_hora=momento))
    return resultado


def test_pedido_de_borrado_queda_pendiente_con_prioridad(app, comercio):
    _conversar(comercio, "5493511110001", "tienen el mantel en gris?")
    resultado = _conversar(comercio, "5493511110002", "borren mis datos por favor")
    consulta = resultado.consulta
    assert consulta.tema == TemaConsulta.DATOS_PERSONALES and consulta.pendiente
    assert consulta.tema.prioritario and consulta.etiqueta_tema == "Datos personales"
    pendientes = metricas.pendientes(comercio)
    assert [p.consulta.tema for p in pendientes] == [TemaConsulta.DATOS_PERSONALES, TemaConsulta.PRODUCTOS]
    assert "por tu pedido de borrar tus datos" in metricas.mensaje_sugerido(consulta)


def test_el_comercio_borra_los_datos_del_comprador(app, comercio, otro_comercio):
    telefono = "5493511110003"
    _conversar(otro_comercio, telefono, "aceptan mercado pago?")
    consulta = _conversar(comercio, telefono, "borren mis datos").consulta
    cliente = app.test_client()
    ingresar(cliente)

    detalle = cliente.get(f"/historial/{consulta.id_consulta}").get_data(as_text=True)
    assert "tiene cinco días hábiles" in detalle and "Borrar los datos de este comprador" in detalle
    confirmacion = cliente.get(f"/historial/{consulta.id_consulta}/borrar-comprador").get_data(as_text=True)
    assert "+54 9 351 111-0003" in confirmacion and "Borrar sus datos" in confirmacion

    r = cliente.post(f"/historial/{consulta.id_consulta}/borrar-comprador")
    assert r.status_code == 302 and r.headers["Location"].endswith("/historial")
    assert "Se borraron los datos" in cliente.get("/historial").get_data(as_text=True)
    # Solo con este comercio: la conversación con el otro comercio sigue.
    conversaciones = db.session.scalars(select(Conversacion)).all()
    assert [c.id_comercio for c in conversaciones] == [otro_comercio.id_comercio]
    assert db.session.scalar(select(func.count()).select_from(Comprador)) == 1


def test_borrar_conserva_el_bloqueo(app, comercio):
    consulta = _conversar(comercio, "5493511110004", "borren mis datos").consulta
    comprador = consulta.conversacion.comprador
    db.session.add(Bloqueo(comercio=comercio, comprador=comprador, motivo="spam", fecha_alta=MARTES_NOCHE))
    db.session.commit()
    cliente = app.test_client()
    ingresar(cliente)
    assert "sigue bloqueado" in cliente.get(f"/historial/{consulta.id_consulta}/borrar-comprador").get_data(
        as_text=True
    )
    cliente.post(f"/historial/{consulta.id_consulta}/borrar-comprador")
    assert db.session.scalar(select(func.count()).select_from(Conversacion)) == 0
    assert db.session.scalar(select(func.count()).select_from(Bloqueo)) == 1


def test_no_se_borran_datos_de_otro_comercio(app, comercio, otro_comercio):
    consulta = _conversar(otro_comercio, "5493511110005", "borren mis datos").consulta
    cliente = app.test_client()
    ingresar(cliente)
    assert cliente.get(f"/historial/{consulta.id_consulta}/borrar-comprador").status_code == 404
    assert cliente.post(f"/historial/{consulta.id_consulta}/borrar-comprador").status_code == 404
    assert db.session.scalar(select(func.count()).select_from(Consulta)) == 1


# --- Baja de un comercio ----------------------------------------------------------------


def test_admin_borrar_comercio(app, comercio, otro_comercio):
    _conversar(comercio, "5493511110006", "aceptan mercado pago?")
    _conversar(otro_comercio, "5493511110007", "aceptan mercado pago?")
    r = app.test_cli_runner().invoke(args=["admin", "borrar-comercio", "demo@casaydetalles.com.ar", "--si"])
    assert r.exit_code == 0 and "dado de baja" in r.output
    assert [c.nombre for c in db.session.scalars(select(Comercio))] == ["Mundo Textil"]
    assert [u.email for u in db.session.scalars(select(Usuario))] == ["demo@mundotextil.com.ar"]
    assert [c.telefono for c in db.session.scalars(select(Comprador))] == ["5493511110007"]


def test_registro_guarda_la_aceptacion(cliente):
    crear = {
        "nombre": "Deco Norte",
        "rubro": "Decoración",
        "telefono": "387 012-3344",
        "email": "hola@deconorte.com.ar",
        "contrasena": "decoNorte2026",
        "acepta": "1",
    }
    assert cliente.post("/registro", data=crear).status_code == 302
    assert db.session.scalar(select(Usuario)).terminos_aceptados == MARTES_NOCHE
