"""CU15 Administrar respuestas propias a preguntas frecuentes: motor, reglas y panel."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.bot.contexto import ContextoConversacion, DatosComercio
from app.bot.motor import MotorConversacional
from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.datos.casa_y_detalles import datos_comercio
from app.datos.palabras_clave import items_catalogo
from app.extensiones import db
from app.modelos import (
    Consulta,
    EstadoConversacion,
    RespuestaFrecuente,
    ResultadoConsulta,
    TemaConsulta,
)
from app.servicios import ErrorValidacion
from app.servicios import respuestas as srv

from .conftest import MARTES_NOCHE, crear_comercio, ingresar

CATALOGO = items_catalogo()
CASA = datos_comercio()
SIN_RESPUESTAS = replace(CASA, respuestas=())


def procesar(texto, datos=CASA, contexto=None, primer_contacto=False):
    return MotorConversacional().procesar(
        datos, contexto or ContextoConversacion(), texto, CATALOGO, MARTES_NOCHE, primer_contacto=primer_contacto
    )


# --- Motor -------------------------------------------------------------------


def test_responde_el_texto_del_comercio_y_registra_la_respuesta():
    r = procesar("hacen factura A?")
    assert r.acciones == ["FAQ:factura"]
    assert r.textos[0].startswith("🧾 Sí, hacemos *factura A o B*")
    assert r.textos[0].endswith("¿Te puedo ayudar con algo más?")
    consulta = r.consulta
    assert consulta.tema == TemaConsulta.RESPUESTA_PROPIA and consulta.resultado == ResultadoConsulta.RESUELTA
    assert consulta.id_respuesta == CASA.respuesta("factura").id_respuesta
    assert r.estado == EstadoConversacion.ACTIVA


@pytest.mark.parametrize(
    "mensaje,esperado",
    [
        ("precio mayorista?", ["FAQ:mayorista"]),  # no es una consulta de precios de productos
        ("venden x mayor?", ["FAQ:mayorista"]),  # abreviatura
        ("hacen fatura?", ["FAQ:factura"]),  # error de tipeo
        ("puedo pasar a buscar el pedido?", ["FAQ:retiro"]),  # «el pedido» es genérico
        ("se puede retirar en sucursal de andreani?", ["ENVIO?"]),  # retiro en el correo: es un envío
        ("cambié de dirección, puedo modificar el envío de mi compra?", ["D:PEDIDOS"]),
        ("puedo cambiar el medio de pago?", ["PAGO"]),
    ],
)
def test_prioridad_de_las_respuestas_propias(mensaje, esperado):
    assert procesar(mensaje).acciones == esperado


def test_un_pedido_concreto_se_deriva_aunque_haya_respuesta():
    r = procesar("me olvidé de pedir factura en mi compra")
    assert r.acciones == ["FAQ:factura", "D:PEDIDOS"]
    assert [c.tema for c in r.consultas] == [TemaConsulta.RESPUESTA_PROPIA, TemaConsulta.PEDIDOS]
    assert r.estado == EstadoConversacion.DERIVADA


def test_un_reclamo_no_se_responde_con_la_politica_de_cambios():
    assert procesar("quiero devolverlo porque vino fallado").acciones == ["D:RECLAMOS"]


def test_varias_preguntas_con_respuesta_propia():
    assert procesar("abren el sábado? y hacen factura?").acciones == ["HORARIO", "FAQ:factura"]


def test_con_la_consulta_derivada_sigue_respondiendo_las_respuestas_propias():
    derivada = procesar("tienen el mantel de lino en gris?")
    assert derivada.estado == EstadoConversacion.DERIVADA
    r = procesar("y hacen factura?", contexto=derivada.contexto)
    assert r.acciones == ["FAQ:factura"] and r.estado == EstadoConversacion.DERIVADA


def test_pedir_una_persona_sobre_el_tema_deriva_sin_respuesta_automatica():
    r = procesar("quiero hablar con una persona por la factura")
    assert r.acciones == ["D:OTRA"]
    assert r.consulta.tema == TemaConsulta.NO_RECONOCIDO


def test_sin_respuesta_propia_la_pregunta_se_deriva():
    assert procesar("¿hacen factura?", datos=SIN_RESPUESTAS).acciones == ["D:OTRA"]
    # El saludo no tapa la pregunta.
    assert procesar("Hola, ¿hacen factura A?", datos=SIN_RESPUESTAS, primer_contacto=True).acciones == ["D:OTRA"]
    assert procesar("Hola, ¿cómo va?", datos=SIN_RESPUESTAS).acciones == ["BIENVENIDA"]


def test_la_bienvenida_y_la_identidad_mencionan_las_respuestas_propias():
    assert "otras preguntas frecuentes, como cambios y devoluciones" in procesar("hola", primer_contacto=True).textos[0]
    assert "otras preguntas frecuentes" in procesar("sos un bot?").textos[0]
    assert "preguntas frecuentes" not in procesar("hola", datos=SIN_RESPUESTAS).textos[0]


# --- Reglas del servicio --------------------------------------------------------


@pytest.fixture
def casa(app):
    return crear_comercio()


def _crear(comercio, titulo="Factura", palabras="factura, factura a, iva", respuesta="Sí, hacemos factura A.", **kw):
    return srv.crear(comercio, titulo, palabras, respuesta, **kw)


@pytest.mark.parametrize(
    "titulo,palabras,respuesta,mensaje",
    [
        ("", "factura", "Sí.", "Indique un título"),
        ("Factura", "", "Sí.", "al menos una palabra clave"),
        ("Factura", "envío", "Sí.", "ya la usa el bot para responder sobre envíos"),
        ("Factura", "transferencia", "Sí.", "medios de pago"),
        ("Factura", "gracias", "Sí.", "para conversar"),
        ("Factura", "cuánto sale", "Sí.", "preguntas de precio"),
        ("Factura", "Rosario", "Sí.", "nombre de una localidad"),
        ("Factura", "para que", "Sí.", "demasiado general"),
        ("Factura", "ab", "Sí.", "muy corta"),
        ("Factura", "123", "Sí.", "tiene que tener letras"),
        ("Factura", "llegó roto", "Sí.", "reclamos"),
        ("Factura", ", ".join(f"palabra{i}" for i in range(21)), "Sí.", "hasta 20"),
        ("Factura", "factura", "", "Escriba la respuesta"),
        ("Factura", "factura", "x" * 801, "hasta 800"),
        ("Factura", "factura", "Mirá https://otrositio.example/factura", "no puede incluir enlaces"),
    ],
)
def test_validaciones(casa, titulo, palabras, respuesta, mensaje):
    with pytest.raises(ErrorValidacion) as error:
        srv.crear(casa, titulo, palabras, respuesta)
    assert mensaje in error.value.mensaje
    assert db.session.scalar(select(func.count(RespuestaFrecuente.id_respuesta))) == 0


def test_palabras_como_las_escribio_y_comparadas_como_las_lee_el_bot(casa):
    r = _crear(casa, palabras="Factura A, FACTURA, ¿x mayor?, factura a,  razón   social")
    assert r.lista_palabras == ["Factura A", "FACTURA", "x mayor", "razón social"]
    datos = DatosComercio.desde_comercio(casa)
    assert datos.respuestas[0].terminos == ("factura a", "factura", "por mayor", "razon social")
    with pytest.raises(ErrorValidacion, match="ya está en la respuesta"):
        _crear(casa, titulo="Mayoristas", palabras="POR MAYOR")


def test_titulo_y_palabras_no_se_repiten_entre_respuestas(casa):
    _crear(casa)
    with pytest.raises(ErrorValidacion, match="Ya tiene una respuesta con ese título"):
        _crear(casa, titulo="factura")
    with pytest.raises(ErrorValidacion, match="ya está en la respuesta «Factura»"):
        _crear(casa, titulo="Impuestos", palabras="IVA")


def test_enlaces_solo_al_catalogo_del_comercio(casa):
    casa.enlace_catalogo = "https://www.instagram.com/casaydetalles"
    db.session.commit()
    ok = _crear(casa, respuesta="Mirá las condiciones en https://instagram.com/casaydetalles/ 🙂")
    assert ok.id_respuesta
    with pytest.raises(ErrorValidacion, match="solo puede incluir enlaces a su catálogo"):
        _crear(casa, titulo="Otra", palabras="garantia", respuesta="Ver instagram.com/otra.cuenta")
    # Un correo electrónico no es un enlace.
    assert _crear(casa, titulo="Mail", palabras="razon social", respuesta="Escribinos a ventas@casa.example")


def test_una_plantilla_se_usa_una_vez(casa):
    primera = _crear(casa, plantilla="factura")
    segunda = _crear(casa, titulo="Factura C", palabras="factura c", plantilla="factura")
    assert primera.plantilla == "factura" and primera.clave == "factura"
    assert segunda.plantilla is None and segunda.clave == f"r{segunda.id_respuesta}"
    assert "factura" not in [p.clave for p in srv.plantillas_disponibles(casa)]


def test_limite_de_respuestas_por_comercio(casa, monkeypatch):
    monkeypatch.setattr(srv, "MAX_RESPUESTAS", 1)
    _crear(casa)
    with pytest.raises(ErrorValidacion, match="hasta 1 respuestas"):
        _crear(casa, titulo="Otra", palabras="garantia")


def _mensaje(comercio, telefono, texto, momento):
    return procesar_mensaje_entrante(
        MensajeEntrante(telefono=telefono, texto=texto, fecha_hora=momento, nombre="Lucía")
    )


def test_el_bot_usa_la_respuesta_guardada_y_mide_su_uso(casa, reloj):
    respuesta = _crear(casa)
    _mensaje(casa, "5493510000001", casa.texto_primer_mensaje(), MARTES_NOCHE)
    resultado = _mensaje(casa, "5493510000001", "me hacen factura?", MARTES_NOCHE + timedelta(minutes=1))
    assert resultado.acciones == [f"FAQ:{respuesta.clave}"] == ["FAQ:r1"]
    consulta = resultado.consulta
    assert consulta.id_respuesta == respuesta.id_respuesta and consulta.respuesta is respuesta
    assert consulta.etiqueta_tema == "Respuestas del comercio: Factura"
    assert srv.usos(casa) == {respuesta.id_respuesta: 1}

    # Desactivada, el bot no la usa (la pregunta se deriva).
    srv.cambiar_activa(respuesta, False)
    otra = _mensaje(casa, "5493510000002", casa.texto_primer_mensaje() + " hacen factura?", MARTES_NOCHE)
    assert otra.acciones == ["D:OTRA"]

    # Al eliminarla, la consulta queda en el historial sin el vínculo.
    srv.eliminar(respuesta)
    consulta = db.session.get(Consulta, consulta.id_consulta)
    assert consulta.id_respuesta is None and consulta.tema == TemaConsulta.RESPUESTA_PROPIA
    assert consulta.etiqueta_tema == "Respuestas del comercio"


def test_sugerencias_a_partir_de_las_consultas_derivadas(casa):
    for numero, texto in enumerate(["venden por mayor?", "tienen precio mayorista?", "llegó roto, quiero devolverlo"]):
        telefono = f"549351000010{numero}"
        _mensaje(casa, telefono, casa.texto_primer_mensaje(), MARTES_NOCHE - timedelta(days=2))
        _mensaje(casa, telefono, texto, MARTES_NOCHE - timedelta(days=2) + timedelta(minutes=1))
    sugerencias = {s.plantilla.clave: s for s in srv.sugerencias(casa)}
    assert sugerencias["mayorista"].cantidad == 2
    # El reclamo no cuenta para la plantilla de cambios: lo tiene que ver una persona.
    assert "cambios" not in sugerencias
    _crear(casa, titulo="Por mayor", palabras="por mayor, mayorista", plantilla="mayorista")
    assert "mayorista" not in {s.plantilla.clave for s in srv.sugerencias(casa)}


def test_desde_comercio_solo_toma_las_activas(casa):
    activa = _crear(casa)
    inactiva = _crear(casa, titulo="Garantía", palabras="garantia")
    srv.cambiar_activa(inactiva, False)
    datos = DatosComercio.desde_comercio(casa)
    assert [r.id_respuesta for r in datos.respuestas] == [activa.id_respuesta]


# --- Panel -----------------------------------------------------------------------


@pytest.fixture
def panel(cliente, casa):
    assert ingresar(cliente).status_code == 302
    return cliente


def test_requiere_sesion(cliente, casa):
    assert cliente.get("/respuestas").status_code == 302


def test_listado_con_plantillas(panel):
    html = panel.get("/respuestas").get_data(as_text=True)
    assert "Todavía no tiene respuestas propias" in html
    assert "Cambios y devoluciones" in html and "Usar plantilla" in html


def test_alta_desde_plantilla_edicion_y_baja(panel, casa):
    formulario = panel.get("/respuestas/nueva?plantilla=factura").get_data(as_text=True)
    assert "factura a" in formulario and "cámbielo por sus condiciones reales" in formulario

    r = panel.post(
        "/respuestas/nueva",
        data={
            "titulo": "Factura",
            "palabras": "factura, factura a, iva",
            "respuesta": "🧾 Hacemos *factura A*.",
            "plantilla": "factura",
        },
    )
    assert r.status_code == 302
    respuesta = db.session.scalar(select(RespuestaFrecuente))
    assert respuesta.plantilla == "factura" and respuesta.activa
    listado = panel.get("/respuestas").get_data(as_text=True)
    assert "Factura" in listado and "iva" in listado

    error = panel.post(
        f"/respuestas/{respuesta.id_respuesta}/editar",
        data={"titulo": "Factura", "palabras": "envío", "respuesta": "x"},
    )
    assert error.status_code == 400 and "ya la usa el bot" in error.get_data(as_text=True)
    panel.post(
        f"/respuestas/{respuesta.id_respuesta}/editar",
        data={"titulo": "Factura A y B", "palabras": "factura", "respuesta": "Hacemos factura A y B."},
    )
    assert db.session.get(RespuestaFrecuente, respuesta.id_respuesta).titulo == "Factura A y B"

    panel.post(f"/respuestas/{respuesta.id_respuesta}/estado", data={"activa": "0"})
    assert db.session.get(RespuestaFrecuente, respuesta.id_respuesta).activa is False

    assert "Eliminar respuesta" in panel.get(f"/respuestas/{respuesta.id_respuesta}/eliminar").get_data(as_text=True)
    panel.post(f"/respuestas/{respuesta.id_respuesta}/eliminar")
    assert db.session.get(RespuestaFrecuente, respuesta.id_respuesta) is None


def test_no_se_accede_a_respuestas_de_otro_comercio(panel):
    otro = crear_comercio(nombre="Mundo Textil", email="demo@mundotextil.com.ar", codigo="TEXT42")
    ajena = _crear(otro)
    for url in (f"/respuestas/{ajena.id_respuesta}/editar", f"/respuestas/{ajena.id_respuesta}/eliminar"):
        assert panel.get(url).status_code == 404
    assert panel.post(f"/respuestas/{ajena.id_respuesta}/estado", data={"activa": "0"}).status_code == 404
    prueba = panel.post("/respuestas/probar", json={"mensaje": "hola", "id_respuesta": ajena.id_respuesta})
    assert prueba.status_code == 404
    assert db.session.get(RespuestaFrecuente, ajena.id_respuesta).activa is True


def test_probar_una_respuesta_sin_guardarla(panel):
    borrador = {"titulo": "Factura", "palabras": "factura, iva", "respuesta": "Sí, hacemos *factura A*."}
    si = panel.post("/respuestas/probar", json={**borrador, "mensaje": "los precios son con iva?"}).get_json()
    assert si["usa"] is True and si["respuestas"][0]["texto"].startswith("Sí, hacemos *factura A*.")
    no = panel.post("/respuestas/probar", json={**borrador, "mensaje": "hacen envíos al 5000?"}).get_json()
    assert no["usa"] is False and "plazo de envío" in no["explicacion"]
    error = panel.post("/respuestas/probar", json={**borrador, "palabras": "envío", "mensaje": "hola"})
    assert error.status_code == 400 and "ya la usa el bot" in error.get_json()["error"]
    assert panel.post("/respuestas/probar", json={**borrador, "mensaje": " "}).status_code == 400
    assert db.session.scalar(select(func.count(RespuestaFrecuente.id_respuesta))) == 0


def test_el_historial_muestra_la_respuesta_usada(panel, casa):
    _crear(casa)
    _mensaje(casa, "5493510000001", casa.texto_primer_mensaje(), MARTES_NOCHE)
    _mensaje(casa, "5493510000001", "hacen factura?", MARTES_NOCHE + timedelta(minutes=1))
    html = panel.get("/historial").get_data(as_text=True)
    assert "Respuestas del comercio: Factura" in html
