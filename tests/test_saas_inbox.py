"""Pruebas del Sprint 3: Live Inbox & Atención Humana en Vivo (Panel Multi-Agente)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import select

from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.extensiones import db
from app.modelos import (
    Comercio,
    Comprador,
    Consulta,
    Conversacion,
    DireccionMensaje,
    EstadoConversacion,
    Mensaje,
    Operador,
    TemaConsulta,
)
from app.utilidades import tiempo
from tests.conftest import crear_comercio, ingresar


def test_inbox_vacio_y_con_conversaciones(cliente, sesion, comercio):
    # Sin conversaciones
    res = cliente.get("/inbox")
    assert res.status_code == 200
    assert "Bandeja en vivo" in res.get_data(as_text=True)

    # Creamos un comprador y una conversación
    ahora = tiempo.ahora()
    comprador = Comprador(telefono="5493512345678", nombre="Juan Pérez", fecha_primer_contacto=ahora)
    conv = Conversacion(
        comercio=comercio,
        comprador=comprador,
        estado=EstadoConversacion.ACTIVA,
        fecha_inicio=ahora,
        ultima_actividad=ahora,
    )
    db.session.add_all([comprador, conv])
    db.session.flush()
    msg = Mensaje(
        conversacion=conv,
        texto="Hola, tienen stock?",
        direccion=DireccionMensaje.ENTRANTE,
        fecha_hora=ahora,
        emisor_tipo="COMPRADOR",
    )
    db.session.add(msg)
    db.session.commit()

    # Carga con la conversación
    res = cliente.get(f"/inbox?conversacion={conv.id_conversacion}")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Juan Pérez" in html
    assert "Hola, tienen stock?" in html

    # Endpoint JSON de mensajes
    res_json = cliente.get(f"/inbox/{conv.id_conversacion}/mensajes")
    assert res_json.status_code == 200
    datos = res_json.get_json()
    assert datos["ok"] is True
    assert datos["pausa_humana"] is False
    assert len(datos["mensajes"]) == 1
    assert datos["mensajes"][0]["texto"] == "Hola, tienen stock?"
    assert datos["mensajes"][0]["emisor_tipo"] == "COMPRADOR"


def test_toma_de_control_humana_pausa_bot(cliente, sesion, comercio):
    ahora = tiempo.ahora()
    comprador = Comprador(telefono="5493512345678", nombre="Ana Gómez", fecha_primer_contacto=ahora)
    conv = Conversacion(
        comercio=comercio,
        comprador=comprador,
        estado=EstadoConversacion.ACTIVA,
        fecha_inicio=ahora,
        ultima_actividad=ahora,
    )
    db.session.add_all([comprador, conv])
    db.session.commit()

    # Pausar bot desde el inbox
    res = cliente.post(f"/inbox/{conv.id_conversacion}/pausar-bot")
    assert res.status_code == 302
    db.session.refresh(conv)
    assert conv.en_pausa_humana(ahora) is True
    assert conv.pausa_humana_hasta > ahora

    # Mensaje posterior del comprador: no debe ser respondido por el bot
    entrante = MensajeEntrante(
        telefono="5493512345678",
        texto="¿Cuánto sale el envío?",
        fecha_hora=ahora + timedelta(minutes=5),
        id_externo="WA-12345",
    )
    res_atencion = procesar_mensaje_entrante(entrante, ahora=ahora + timedelta(minutes=5))
    assert res_atencion.respuestas == []
    assert "PAUSA_HUMANA" in res_atencion.acciones

    # Verificar que el mensaje se guardó con emisor_tipo=COMPRADOR
    mensajes = db.session.scalars(
        select(Mensaje).where(Mensaje.id_conversacion == conv.id_conversacion).order_by(Mensaje.id_mensaje)
    ).all()
    assert len(mensajes) == 1
    assert mensajes[0].texto == "¿Cuánto sale el envío?"
    assert mensajes[0].emisor_tipo == "COMPRADOR"

    # Reactivar bot
    res_reactivar = cliente.post(f"/inbox/{conv.id_conversacion}/reactivar-bot")
    assert res_reactivar.status_code == 302
    db.session.refresh(conv)
    assert conv.en_pausa_humana(ahora) is False
    assert conv.pausa_humana_hasta is None


def test_responder_como_operador_y_envio_whatsapp(cliente, sesion, comercio):
    ahora = tiempo.ahora()
    comprador = Comprador(telefono="5493519876543", nombre="Carlos López", fecha_primer_contacto=ahora)
    conv = Conversacion(
        comercio=comercio,
        comprador=comprador,
        estado=EstadoConversacion.DERIVADA,
        fecha_inicio=ahora,
        ultima_actividad=ahora,
    )
    db.session.add_all([comprador, conv])
    db.session.flush()
    # Consulta derivada pendiente
    consulta = Consulta(
        conversacion=conv,
        tema=TemaConsulta.RECLAMOS,
        resultado=TemaConsulta.RECLAMOS,
        fecha_hora=ahora,
        atendida=False,
    )
    from app.modelos import ResultadoConsulta
    consulta.resultado = ResultadoConsulta.DERIVADA
    db.session.add(consulta)
    db.session.commit()

    with patch("app.web.inbox.ClienteWhatsApp.para_comercio") as mock_cliente_wa:
        instancia_wa = MagicMock()
        instancia_wa.enviar_texto.return_value = "wamid.HBgLM..."
        mock_cliente_wa.return_value = instancia_wa

        res = cliente.post(
            f"/inbox/{conv.id_conversacion}/responder",
            data={"texto": "Hola Carlos, te habla el soporte humano. ¿Cómo podemos ayudarte?"},
        )
        assert res.status_code == 302
        instancia_wa.enviar_texto.assert_called_once_with(
            "5493519876543", "Hola Carlos, te habla el soporte humano. ¿Cómo podemos ayudarte?"
        )

    db.session.refresh(conv)
    assert conv.atendida_por_humano is True
    assert conv.en_pausa_humana(ahora) is True
    assert consulta.atendida is True

    # Mensaje guardado
    msg = db.session.scalar(
        select(Mensaje).where(Mensaje.id_conversacion == conv.id_conversacion, Mensaje.emisor_tipo == "OPERADOR")
    )
    assert msg is not None
    assert msg.texto == "Hola Carlos, te habla el soporte humano. ¿Cómo podemos ayudarte?"
    assert msg.estado_envio == "enviado"
    assert msg.id_externo == "wamid.HBgLM..."


def test_canal_web_en_inbox_no_envia_whatsapp(cliente, sesion, comercio):
    ahora = tiempo.ahora()
    # Prefijo web 5493518...
    comprador = Comprador(telefono="5493518000001", nombre="Visitante Web", fecha_primer_contacto=ahora)
    conv = Conversacion(
        comercio=comercio,
        comprador=comprador,
        estado=EstadoConversacion.ACTIVA,
        fecha_inicio=ahora,
        ultima_actividad=ahora,
    )
    db.session.add_all([comprador, conv])
    db.session.commit()

    with patch("app.web.inbox.ClienteWhatsApp.para_comercio") as mock_cliente_wa:
        res = cliente.post(
            f"/inbox/{conv.id_conversacion}/responder",
            data={"texto": "Respuesta por canal web"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert res.status_code == 200
        assert res.get_json()["ok"] is True
        mock_cliente_wa.assert_not_called()

    # Cerrar conversación
    res_cerrar = cliente.post(
        f"/inbox/{conv.id_conversacion}/cerrar",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert res_cerrar.status_code == 200
    assert res_cerrar.get_json()["estado"] == "CERRADA"
    db.session.refresh(conv)
    assert conv.estado == EstadoConversacion.CERRADA


def test_gestion_operadores_y_autenticacion(cliente, sesion, comercio):
    # Ver listado de equipo
    res = cliente.get("/cuenta/equipo")
    assert res.status_code == 200
    assert "Equipo y operadores" in res.get_data(as_text=True)

    # Crear nuevo operador
    res_crear = cliente.post(
        "/cuenta/equipo/nuevo",
        data={
            "nombre": "Agustín Operador",
            "email": "agustin@comercio.com",
            "rol": "OPERADOR",
            "contrasena": "claveOp123",
        },
    )
    assert res_crear.status_code == 302
    operador = db.session.scalar(select(Operador).where(Operador.email == "agustin@comercio.com"))
    assert operador is not None
    assert operador.nombre == "Agustín Operador"
    assert operador.rol == "OPERADOR"
    assert operador.verificar_contrasena("claveOp123") is True
    assert operador.comercio.id_comercio == comercio.id_comercio

    # Intentar crear operador con mismo email
    res_dup = cliente.post(
        "/cuenta/equipo/nuevo",
        data={
            "nombre": "Otro",
            "email": "agustin@comercio.com",
            "rol": "OPERADOR",
            "contrasena": "claveOp123",
        },
    )
    assert res_dup.status_code == 302

    # Cerrar sesión
    cliente.post("/salir")

    # Iniciar sesión como Operador
    res_login = cliente.post(
        "/ingresar",
        data={"email": "agustin@comercio.com", "contrasena": "claveOp123"},
    )
    assert res_login.status_code == 302
    assert res_login.headers["Location"].rstrip("/").endswith("/inbox")

    # Navegar por el panel como operador
    res_inbox = cliente.get("/inbox")
    assert res_inbox.status_code == 200

    # Responder una conversación siendo el operador logueado
    ahora = tiempo.ahora()
    comprador = Comprador(telefono="5493511112222", nombre="Cliente Prueba", fecha_primer_contacto=ahora)
    conv = Conversacion(
        comercio=comercio,
        comprador=comprador,
        estado=EstadoConversacion.ACTIVA,
        fecha_inicio=ahora,
        ultima_actividad=ahora,
    )
    db.session.add_all([comprador, conv])
    db.session.commit()

    with patch("app.web.inbox.ClienteWhatsApp.para_comercio") as mock_wa:
        mock_wa.return_value.enviar_texto.return_value = "wamid.op123"
        res_resp = cliente.post(
            f"/inbox/{conv.id_conversacion}/responder",
            data={"texto": "Hola, soy Agustín"},
        )
        assert res_resp.status_code == 302

    msg = db.session.scalar(
        select(Mensaje).where(Mensaje.id_conversacion == conv.id_conversacion, Mensaje.emisor_tipo == "OPERADOR")
    )
    assert msg is not None
    assert msg.nombre_emisor == "Agustín Operador"

    db.session.refresh(conv)
    assert conv.id_operador_asignado == operador.id_operador
    assert conv.nombre_operador == "Agustín Operador"

    # Eliminar operador
    res_elim = cliente.post(f"/cuenta/equipo/{operador.id_operador}/eliminar")
    assert res_elim.status_code == 302
    assert db.session.get(Operador, operador.id_operador) is None


def test_inbox_filtros_y_busqueda(cliente, sesion, comercio):
    ahora = tiempo.ahora()
    # Conversación 1: Activa con bot
    c1 = Comprador(telefono="5493510000010", nombre="Comprador Bot", fecha_primer_contacto=ahora)
    conv1 = Conversacion(
        comercio=comercio,
        comprador=c1,
        estado=EstadoConversacion.ACTIVA,
        fecha_inicio=ahora,
        ultima_actividad=ahora,
    )
    # Conversación 2: En pausa humana
    c2 = Comprador(telefono="5493510000020", nombre="Comprador Humano", fecha_primer_contacto=ahora)
    conv2 = Conversacion(
        comercio=comercio,
        comprador=c2,
        estado=EstadoConversacion.ACTIVA,
        pausa_humana_hasta=ahora + timedelta(hours=1),
        fecha_inicio=ahora,
        ultima_actividad=ahora,
    )
    # Conversación 3: Cerrada
    c3 = Comprador(telefono="5493510000030", nombre="Comprador Cerrado", fecha_primer_contacto=ahora)
    conv3 = Conversacion(
        comercio=comercio,
        comprador=c3,
        estado=EstadoConversacion.CERRADA,
        fecha_inicio=ahora,
        ultima_actividad=ahora,
    )
    db.session.add_all([c1, c2, c3, conv1, conv2, conv3])
    db.session.commit()

    # Filtro humanas
    res_h = cliente.get("/inbox?filtro=humanas")
    assert res_h.status_code == 200
    html_h = res_h.get_data(as_text=True)
    assert "Comprador Humano" in html_h
    assert "Comprador Cerrado" not in html_h

    # Filtro bot
    res_b = cliente.get("/inbox?filtro=bot")
    assert res_b.status_code == 200
    html_b = res_b.get_data(as_text=True)
    assert "Comprador Bot" in html_b
    assert "Comprador Cerrado" not in html_b

    # Filtro cerradas
    res_c = cliente.get("/inbox?filtro=cerradas")
    assert res_c.status_code == 200
    html_c = res_c.get_data(as_text=True)
    assert "Comprador Cerrado" in html_c
    assert "Comprador Bot" not in html_c

    # Búsqueda por nombre o teléfono
    res_q = cliente.get("/inbox?q=0000020")
    assert res_q.status_code == 200
    html_q = res_q.get_data(as_text=True)
    assert "Comprador Humano" in html_q
    assert "Comprador Bot" not in html_q


def test_seguridad_operadores_otro_comercio(cliente, sesion, comercio, otro_comercio):
    # Crear operador en otro comercio
    ahora = tiempo.ahora()
    op_otro = Operador(
        id_comercio=otro_comercio.id_comercio,
        nombre="Operador Espía",
        email="espia@otro.com",
        hash_contrasena="hash",
        rol="OPERADOR",
        activo=True,
        fecha_alta=ahora,
    )
    db.session.add(op_otro)
    db.session.commit()

    # Intentar eliminar operador de otro comercio -> 404
    res = cliente.post(f"/cuenta/equipo/{op_otro.id_operador}/eliminar")
    assert res.status_code == 404
    assert db.session.get(Operador, op_otro.id_operador) is not None

