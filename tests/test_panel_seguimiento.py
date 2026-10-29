"""Seguimiento de pendientes (#8), cuenta y ayuda (#9) e historial (#10)."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.extensiones import db
from app.modelos import Comercio, TemaConsulta, Usuario
from app.servicios import metricas

from .conftest import CONTRASENA, MARTES_NOCHE, crear_comercio, ingresar


def _hablar(comercio, telefono, *textos, inicio=MARTES_NOCHE, nombre=None):
    momento = inicio
    procesar_mensaje_entrante(
        MensajeEntrante(telefono=telefono, texto=comercio.texto_primer_mensaje(), fecha_hora=momento, nombre=nombre)
    )
    resultado = None
    for texto in textos:
        momento += timedelta(minutes=1)
        resultado = procesar_mensaje_entrante(
            MensajeEntrante(telefono=telefono, texto=texto, fecha_hora=momento, nombre=nombre)
        )
    return resultado


def _correos(app):
    return app.extensions.setdefault("correos", [])


# --- #8 Pendientes ----------------------------------------------------------------


def test_pendientes_por_prioridad_y_antiguedad(comercio):
    _hablar(comercio, "5493510000001", "tienen manteles?", inicio=MARTES_NOCHE - timedelta(hours=5))
    _hablar(
        comercio, "5493510000002", "ya transferí, te mando el comprobante", inicio=MARTES_NOCHE - timedelta(hours=4)
    )
    _hablar(comercio, "5493510000003", "me llegó roto el plato", inicio=MARTES_NOCHE - timedelta(hours=3))
    _hablar(comercio, "5493510000004", "me llegó rota la taza", inicio=MARTES_NOCHE - timedelta(hours=1))
    _hablar(comercio, "5493510000005", "mi tarjeta es 4509 9535 6623 3704", inicio=MARTES_NOCHE)
    temas = [(p.consulta.tema, p.comprador.telefono[-1]) for p in metricas.pendientes(comercio)]
    assert temas == [
        (TemaConsulta.SEGURIDAD, "5"),
        (TemaConsulta.RECLAMOS, "3"),  # el reclamo que espera hace más tiempo, primero
        (TemaConsulta.RECLAMOS, "4"),
        (TemaConsulta.PAGOS_INFORMADOS, "2"),
        (TemaConsulta.PRODUCTOS, "1"),
    ]


def test_responder_por_whatsapp_con_mensaje_sugerido(comercio):
    _hablar(comercio, "5493510000001", "me llegó roto el plato", nombre="Lucía Pérez")
    pendiente = metricas.pendientes(comercio)[0]
    enlace = urlparse(pendiente.enlace_respuesta)
    assert enlace.netloc == "wa.me" and enlace.path == "/5493510000001"
    texto = parse_qs(enlace.query)["text"][0]
    assert texto == (
        "Hola Lucía, te escribo de Casa & Detalles por lo que nos contaste. Lamentamos el inconveniente. "
        "Nos escribiste: «me llegó roto el plato»"
    )
    _hablar(comercio, "5493510000002", "mi tarjeta es 4509 9535 6623 3704")
    tarjeta = next(p for p in metricas.pendientes(comercio) if p.consulta.alerta == "TARJETA")
    assert "link de pago seguro" in parse_qs(urlparse(tarjeta.enlace_respuesta).query)["text"][0]


def test_estado_de_pendientes_para_el_aviso_en_vivo(sesion, comercio):
    assert sesion.get("/panel/pendientes/estado").get_json() == {"pendientes": 0, "ultima": 0, "detalle": ""}
    _hablar(comercio, "5493510000001", "tienen manteles?", nombre="Lucía")
    estado = sesion.get("/panel/pendientes/estado").get_json()
    assert estado["pendientes"] == 1 and estado["ultima"] > 0
    assert estado["detalle"] == "Productos y precios: Lucía"
    html = sesion.get("/panel").get_data(as_text=True)
    assert "data-estado-pendientes" in html and "data-activar-avisos" in html


def test_aviso_por_correo_con_maximo_por_intervalo(app, sesion, comercio):
    respuesta = sesion.post("/cuenta", data={"accion": "avisos", "avisos_correo": "1"})
    assert respuesta.status_code == 302 and db.session.get(Comercio, comercio.id_comercio).avisos_correo
    _hablar(comercio, "5493510000001", "tienen manteles?", nombre="Lucía")
    assert len(_correos(app)) == 1
    correo = _correos(app)[0]
    assert correo["To"] == "demo@casaydetalles.com.ar"
    assert "1 consulta pendiente en Casa & Detalles" in correo["Subject"]
    cuerpo = correo.get_content()
    assert "«tienen manteles?»" in cuerpo and "http://localhost/panel" in cuerpo
    # Otra derivación a los pocos minutos no manda otro correo.
    _hablar(comercio, "5493510000002", "me llegó roto el plato", inicio=MARTES_NOCHE + timedelta(minutes=10))
    assert len(_correos(app)) == 1
    # Pasado el intervalo, sí.
    _hablar(comercio, "5493510000003", "hay stock del juego de sábanas?", inicio=MARTES_NOCHE + timedelta(minutes=45))
    assert len(_correos(app)) == 2 and "3 consultas pendientes" in _correos(app)[1]["Subject"]


def test_sin_avisos_activados_no_se_manda_correo(app, comercio):
    _hablar(comercio, "5493510000001", "tienen manteles?")
    assert _correos(app) == []


def test_una_falla_del_correo_no_afecta_al_bot(app, comercio, monkeypatch):
    comercio.avisos_correo = True
    db.session.commit()

    def falla(*_args, **_kwargs):
        raise OSError("sin conexión")

    monkeypatch.setattr("app.correo.enviar", falla)
    resultado = _hablar(comercio, "5493510000001", "tienen manteles?")
    assert resultado.acciones == ["D:PRODUCTOS"] and resultado.consulta.pendiente


# --- #9 Cuenta, recuperación y ayuda ---------------------------------------------------


@pytest.mark.parametrize(
    "datos,mensaje",
    [
        (
            {"actual": "otra", "nueva": "nueva-clave-1", "repetida": "nueva-clave-1"},
            "La contraseña actual no es correcta",
        ),
        ({"actual": CONTRASENA, "nueva": "corta", "repetida": "corta"}, "al menos ocho caracteres"),
        ({"actual": CONTRASENA, "nueva": "nueva-clave-1", "repetida": "otra-clave-1"}, "no coinciden"),
        ({"actual": CONTRASENA, "nueva": CONTRASENA, "repetida": CONTRASENA}, "distinta de la actual"),
    ],
)
def test_cambio_de_contrasena_con_errores(sesion, datos, mensaje):
    respuesta = sesion.post("/cuenta", data={"accion": "contrasena", **datos})
    assert respuesta.status_code == 400 and mensaje in respuesta.get_data(as_text=True)


def test_cambio_de_contrasena(sesion, cliente):
    datos = {"accion": "contrasena", "actual": CONTRASENA, "nueva": "nueva-clave-1", "repetida": "nueva-clave-1"}
    assert sesion.post("/cuenta", data=datos).status_code == 302
    sesion.post("/salir")
    assert ingresar(cliente, contrasena=CONTRASENA).status_code == 401
    assert ingresar(cliente, contrasena="nueva-clave-1").status_code == 302


def _enlace_del_correo(correo) -> str:
    return next(linea for linea in correo.get_content().splitlines() if "/recuperar/" in linea).strip()


def test_recuperacion_de_contrasena_por_correo(app, cliente, comercio):
    usuario = comercio.usuario
    usuario.intentos_fallidos, usuario.bloqueado_hasta = 3, MARTES_NOCHE + timedelta(minutes=10)
    db.session.commit()
    respuesta = cliente.post("/recuperar", data={"email": "DEMO@casaydetalles.com.ar"})
    assert "Si el correo corresponde a una cuenta" in respuesta.get_data(as_text=True)
    assert len(_correos(app)) == 1 and "vence en 60 minutos" in _correos(app)[0].get_content()
    enlace = urlparse(_enlace_del_correo(_correos(app)[0])).path
    assert "Elegir una contraseña nueva" in cliente.get(enlace).get_data(as_text=True)
    assert cliente.post(enlace, data={"nueva": "clave-nueva-1", "repetida": "otra"}).status_code == 400
    assert cliente.post(enlace, data={"nueva": "clave-nueva-1", "repetida": "clave-nueva-1"}).status_code == 302
    # El enlace sirve una sola vez y el bloqueo por intentos se levanta.
    assert cliente.get(enlace).status_code == 400
    assert ingresar(cliente, contrasena="clave-nueva-1").status_code == 302


def test_recuperacion_no_revela_cuentas_y_limita_reenvios(app, cliente, comercio, reloj):
    desconocido = cliente.post("/recuperar", data={"email": "nadie@ejemplo.com"}).get_data(as_text=True)
    assert "Si el correo corresponde a una cuenta" in desconocido and _correos(app) == []
    cliente.post("/recuperar", data={"email": "demo@casaydetalles.com.ar"})
    cliente.post("/recuperar", data={"email": "demo@casaydetalles.com.ar"})
    assert len(_correos(app)) == 1
    reloj.actual += timedelta(minutes=6)
    cliente.post("/recuperar", data={"email": "demo@casaydetalles.com.ar"})
    assert len(_correos(app)) == 2


def test_enlace_de_recuperacion_alterado(cliente, comercio):
    assert cliente.get("/recuperar/no-es-un-token").status_code == 400


def test_recuperacion_sin_correo_configurado(app, cliente, comercio):
    app.config["MAIL_MODO"] = "desactivado"
    html = cliente.post("/recuperar", data={"email": "demo@casaydetalles.com.ar"}).get_data(as_text=True)
    assert "no está disponible" in html and _correos(app) == []
    usuario = db.session.scalar(select(Usuario))
    assert usuario.recuperacion_enviada is None


def test_ayuda_y_enlace_de_recuperacion(sesion, cliente):
    assert "Cómo atender una consulta pendiente" in sesion.get("/ayuda").get_data(as_text=True)
    sesion.post("/salir")
    assert "¿Olvidó su contraseña?" in cliente.get("/ingresar").get_data(as_text=True)


def test_vista_previa_del_bot_en_el_onboarding(cliente, app):
    crear_comercio(email="nuevo@comercio.com", codigo=None, paso=Comercio.PASO_RESUMEN)
    ingresar(cliente, email="nuevo@comercio.com")
    html = cliente.get("/onboarding/resumen").get_data(as_text=True)
    assert "Así va a responder el bot" in html
    assert "¿Hacen envíos al 5000?" in html and "1 a 2 días hábiles" in html
    assert "Transferencia bancaria" in html


# --- #10 Historial ----------------------------------------------------------------------


@pytest.fixture
def historial(comercio):
    _hablar(comercio, "5493510000001", "tienen el mantel de lino?", nombre="Lucía")
    _hablar(comercio, "5493515556677", "hacen envíos al 5000?", nombre="Martín")
    _hablar(comercio, "5493510000003", '=HYPERLINK("http://x") cómo se paga?', nombre="@raro")
    return comercio


@pytest.mark.parametrize(
    "busqueda,compradores",
    [("lucía", ["Lucía"]), ("5556677", ["Martín"]), ("mantel de lino", ["Lucía"]), ("nada que ver", [])],
)
def test_busqueda_en_el_historial(sesion, historial, busqueda, compradores):
    filtros = metricas.FiltrosHistorial(busqueda=busqueda)
    pagina = metricas.historial(historial, filtros)
    assert sorted({c.conversacion.comprador.nombre for c in pagina.items}) == compradores
    html = sesion.get("/historial", query_string={"q": busqueda}).get_data(as_text=True)
    assert all(nombre in html for nombre in compradores)


def test_exportacion_csv_con_filtros(sesion, historial):
    respuesta = sesion.get("/historial/exportar.csv", query_string={"tema": "ENVIO"})
    assert respuesta.mimetype == "text/csv" and "attachment" in respuesta.headers["Content-Disposition"]
    texto = respuesta.get_data(as_text=True)
    assert texto.startswith("﻿Fecha;Hora;Comprador;Teléfono;Tema")
    lineas = texto.strip().splitlines()
    assert len(lineas) == 2 and "Martín" in lineas[1] and "Envíos" in lineas[1] and "5000" in lineas[1]


def test_exportacion_no_permite_formulas(sesion, historial):
    texto = sesion.get("/historial/exportar.csv", query_string={"tema": "MEDIOS_PAGO"}).get_data(as_text=True)
    assert ";'@raro;" in texto and "'=HYPERLINK" in texto
