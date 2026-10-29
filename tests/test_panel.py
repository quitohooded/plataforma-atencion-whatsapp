"""Panel de administración: CU03 a CU07, CU13 y CU14 (RF09 a RF12, RF15 a RF17)."""

import io
import json
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.extensiones import db
from app.modelos import (
    Comercio,
    Consulta,
    EstadoComercio,
    EstadoConversacion,
    MedioPago,
    ZonaEnvio,
)

from .conftest import crear_comercio, ingresar


def nuevo_en_onboarding(cliente):
    cliente.post(
        "/registro",
        data={
            "nombre": "Deco Norte",
            "rubro": "Decoración",
            "telefono": "387 012-3344",
            "email": "hola@deconorte.com.ar",
            "contrasena": "decoNorte2026",
        },
    )
    return db.session.scalar(select(Comercio).where(Comercio.nombre == "Deco Norte"))


ZONA = {
    "descripcion": "Salta Capital",
    "cp_desde": "4400",
    "cp_hasta": "4409",
    "plazo_min_dias": "1",
    "plazo_max_dias": "2",
}


# --- CU03 -------------------------------------------------------------------


def test_cu03_recorrido_completo_del_onboarding(cliente):
    comercio = nuevo_en_onboarding(cliente)
    assert (
        cliente.post(
            "/onboarding/paso/1", data={"nombre": "Deco Norte", "rubro": "Deco", "telefono": "387 012-3344"}
        ).status_code
        == 302
    )
    assert cliente.post("/onboarding/paso/2", data={"accion": "agregar", **ZONA}).status_code == 302
    assert cliente.post("/onboarding/paso/2", data={"accion": "continuar"}).headers["Location"].endswith("/paso/3")
    cliente.post("/onboarding/paso/3", data={"accion": "agregar", "tipo": "Efectivo", "detalle": ""})
    assert cliente.post("/onboarding/paso/3", data={"accion": "continuar"}).headers["Location"].endswith("/paso/4")
    r = cliente.post(
        "/onboarding/paso/4",
        data={"accion": "guardar", "atiende_0": "1", "apertura_0_0": "09:00", "cierre_0_0": "18:00"},
    )
    assert r.headers["Location"].endswith("/onboarding/resumen")
    resumen = cliente.get("/onboarding/resumen").get_data(as_text=True)
    assert "Salta Capital" in resumen and "Efectivo" in resumen and "Lunes: 9:00 a 18:00" in resumen
    assert cliente.post("/onboarding/confirmar").headers["Location"].endswith("/activacion")
    assert comercio.onboarding_completo
    assert comercio.estado == EstadoComercio.EN_ONBOARDING  # se activa recién en CU07


def test_cu03_excepcion_paso_incompleto_no_avanza(cliente):
    nuevo_en_onboarding(cliente)
    cliente.post("/onboarding/paso/1", data={"nombre": "Deco Norte", "rubro": "Deco", "telefono": "387 012-3344"})
    r = cliente.post("/onboarding/paso/2", data={"accion": "continuar"})
    assert r.status_code == 400
    assert "al menos una zona" in r.get_data(as_text=True)


def test_cu03_no_se_pueden_saltear_pasos(cliente):
    nuevo_en_onboarding(cliente)
    r = cliente.get("/onboarding/paso/4")
    assert r.headers["Location"].endswith("/onboarding/paso/1")


def test_cu03_alternativo_interrupcion_retoma_en_el_paso_pendiente(cliente):
    nuevo_en_onboarding(cliente)
    cliente.post("/onboarding/paso/1", data={"nombre": "Deco Norte", "rubro": "Deco", "telefono": "387 012-3344"})
    cliente.post("/onboarding/paso/2", data={"accion": "agregar", **ZONA})
    cliente.post("/onboarding/paso/2", data={"accion": "continuar"})
    cliente.post("/salir")
    r = ingresar(cliente, "hola@deconorte.com.ar", "decoNorte2026")
    assert r.headers["Location"].endswith("/onboarding/paso/3")


def test_cu03_alternativo_volver_a_un_paso_anterior_muestra_lo_cargado(cliente):
    nuevo_en_onboarding(cliente)
    cliente.post("/onboarding/paso/1", data={"nombre": "Deco Norte", "rubro": "Deco", "telefono": "387 012-3344"})
    cliente.post("/onboarding/paso/2", data={"accion": "agregar", **ZONA})
    cliente.post("/onboarding/paso/2", data={"accion": "continuar"})
    html = cliente.get("/onboarding/paso/2").get_data(as_text=True)
    assert "Salta Capital" in html


def test_secciones_del_panel_esperan_el_onboarding(cliente):
    nuevo_en_onboarding(cliente)
    assert cliente.get("/zonas").headers["Location"].endswith("/onboarding")


# --- CU04 -------------------------------------------------------------------


def test_cu04_alta_edicion_y_eliminacion_de_zona(sesion, comercio):
    assert sesion.post("/zonas", data={"accion": "agregar", **ZONA}).status_code == 302
    zona = db.session.scalar(select(ZonaEnvio).where(ZonaEnvio.descripcion == "Salta Capital"))
    r = sesion.post(f"/zonas/{zona.id_zona}/editar", data={**ZONA, "plazo_max_dias": "3"})
    assert r.status_code == 302 and zona.plazo_max_dias == 3
    assert "¿Eliminar la zona" in sesion.get(f"/zonas/{zona.id_zona}/eliminar").get_data(as_text=True)
    sesion.post(f"/zonas/{zona.id_zona}/eliminar")
    assert db.session.get(ZonaEnvio, zona.id_zona) is None


def test_cu04_excepciones_rango_invalido_y_superpuesto(sesion, comercio):
    r = sesion.post("/zonas", data={**ZONA, "cp_desde": "4500", "cp_hasta": "4400"})
    assert "inicial no puede ser mayor" in r.get_data(as_text=True)
    r = sesion.post("/zonas", data={**ZONA, "plazo_min_dias": "5", "plazo_max_dias": "2"})
    assert "mínimo no puede ser mayor" in r.get_data(as_text=True)
    r = sesion.post("/zonas", data={**ZONA, "cp_desde": "5050", "cp_hasta": "5150"})
    assert r.status_code == 400
    assert "se superpone con la zona «Córdoba Capital»" in r.get_data(as_text=True)


def test_cu04_alternativo_importacion_de_planilla(sesion, comercio):
    contenido = (
        "descripcion;cp_desde;cp_hasta;plazo_min_dias;plazo_max_dias\n"
        "Salta Capital;4400;4409;1;2\n"
        "Mal cargada;4700;4600;1;2\n"
        "Pisa Córdoba;5050;5060;1;1\n"
        "Pisa otra fila;4405;4406;1;1\n"
    ).encode("cp1252")
    r = sesion.post(
        "/zonas/importar", data={"planilla": (io.BytesIO(contenido), "zonas.csv")}, content_type="multipart/form-data"
    )
    html = r.get_data(as_text=True)
    assert "1 fila válida y 3 observadas" in html
    assert "inicial no puede ser mayor" in html and "Córdoba Capital" in html and "otra fila" in html
    filas = json.dumps(
        [{"descripcion": "Salta Capital", "cp_desde": 4400, "cp_hasta": 4409, "plazo_min_dias": 1, "plazo_max_dias": 2}]
    )
    sesion.post("/zonas/importar/confirmar", data={"filas": filas})
    assert db.session.scalar(select(func.count()).select_from(ZonaEnvio)) == 3


def test_cu04_plantilla_csv(sesion):
    r = sesion.get("/zonas/plantilla.csv")
    assert r.mimetype == "text/csv"
    assert "descripcion;cp_desde;cp_hasta;plazo_min_dias;plazo_max_dias;costo" in r.get_data(as_text=True)


def test_cu04_costo_del_envio_por_zona(sesion, comercio):
    sesion.post("/zonas", data={"accion": "agregar", **ZONA, "costo": "$ 9.900"})
    zona = db.session.scalar(select(ZonaEnvio).where(ZonaEnvio.descripcion == "Salta Capital"))
    assert zona.costo == 9900
    html = sesion.get("/zonas").get_data(as_text=True)
    assert "$9.900" in html and "Sin informar" in html  # las zonas del comercio de prueba no tienen costo
    sesion.post(f"/zonas/{zona.id_zona}/editar", data={**ZONA, "costo": "0"})
    assert zona.costo == 0
    sesion.post(f"/zonas/{zona.id_zona}/editar", data={**ZONA, "costo": ""})
    assert zona.costo is None
    r = sesion.post(f"/zonas/{zona.id_zona}/editar", data={**ZONA, "costo": "doce mil"})
    assert r.status_code == 400 and "monto en pesos" in r.get_data(as_text=True)


def test_cu04_envio_gratis_desde_un_monto(sesion, comercio):
    sesion.post("/zonas/envio-gratis", data={"envio_gratis_desde": "120.000"})
    assert comercio.envio_gratis_desde == 120000
    assert 'value="$120.000"' in sesion.get("/zonas").get_data(as_text=True)
    sesion.post("/zonas/envio-gratis", data={"envio_gratis_desde": "$120.000"})
    assert comercio.envio_gratis_desde == 120000
    r = sesion.post("/zonas/envio-gratis", data={"envio_gratis_desde": "0"}, follow_redirects=True)
    assert "cargue el costo $0 en cada zona" in r.get_data(as_text=True)
    sesion.post("/zonas/envio-gratis", data={"envio_gratis_desde": ""})
    assert comercio.envio_gratis_desde is None


def test_cu04_planilla_con_costo(sesion, comercio):
    contenido = (
        b"descripcion;cp_desde;cp_hasta;plazo_min_dias;plazo_max_dias;costo\n"
        b"Salta Capital;4400;4409;1;2;9.900\n"
        b"Jujuy;4600;4699;2;3;\n"
        b"Costo raro;4700;4799;2;3;mucho\n"
    )
    r = sesion.post(
        "/zonas/importar", data={"planilla": (io.BytesIO(contenido), "zonas.csv")}, content_type="multipart/form-data"
    )
    html = r.get_data(as_text=True)
    assert "2 filas válidas y 1 observada" in html and "$9.900" in html and "monto en pesos" in html


# --- CU05 -------------------------------------------------------------------


def test_cu05_alta_duplicado_desactivacion_y_eliminacion(sesion, comercio):
    r = sesion.post("/medios-de-pago", data={"tipo": "Tarjeta de crédito", "detalle": "3 cuotas sin interés"})
    assert r.status_code == 302
    r = sesion.post("/medios-de-pago", data={"tipo": "Tarjeta de crédito", "detalle": "3 cuotas sin interés"})
    assert "ya está cargado" in r.get_data(as_text=True)
    medio = db.session.scalar(select(MedioPago).where(MedioPago.nombre == "Tarjeta de crédito"))
    sesion.post(f"/medios-de-pago/{medio.id_medio_pago}/estado", data={"activo": "0"})
    assert medio.activo is False
    sesion.post(f"/medios-de-pago/{medio.id_medio_pago}/eliminar")
    assert db.session.get(MedioPago, medio.id_medio_pago) is None


def test_cu05_opcion_otro_requiere_nombre(sesion):
    r = sesion.post("/medios-de-pago", data={"tipo": "Otro", "nombre_otro": "", "detalle": ""})
    assert "Indique el nombre" in r.get_data(as_text=True)
    sesion.post("/medios-de-pago", data={"tipo": "Otro", "nombre_otro": "Cuenta DNI", "detalle": ""})
    assert db.session.scalar(select(MedioPago).where(MedioPago.nombre == "Cuenta DNI"))


# --- CU06 -------------------------------------------------------------------


def test_cu06_guarda_jornada_partida(sesion, comercio):
    r = sesion.post(
        "/horarios",
        data={
            "accion": "guardar",
            "atiende_0": "1",
            "apertura_0_0": "09:00",
            "cierre_0_0": "13:00",
            "apertura_0_1": "16:00",
            "cierre_0_1": "20:00",
        },
    )
    assert r.status_code == 302
    franjas = [(h.dia_semana, h.hora_apertura, h.hora_cierre) for h in comercio.horarios]
    assert franjas == [(0, "09:00", "13:00"), (0, "16:00", "20:00")]


def test_cu06_excepcion_horario_invalido_no_guarda(sesion, comercio):
    antes = len(comercio.horarios)
    r = sesion.post(
        "/horarios", data={"accion": "guardar", "atiende_0": "1", "apertura_0_0": "18:00", "cierre_0_0": "09:00"}
    )
    assert r.status_code == 400
    assert "posterior a la de apertura" in r.get_data(as_text=True)
    r = sesion.post(
        "/horarios",
        data={
            "accion": "guardar",
            "atiende_0": "1",
            "apertura_0_0": "09:00",
            "cierre_0_0": "14:00",
            "apertura_0_1": "13:00",
            "cierre_0_1": "18:00",
        },
    )
    assert "se superponen" in r.get_data(as_text=True)
    db.session.refresh(comercio)
    assert len(comercio.horarios) == antes


def test_cu06_alternativo_copiar_a_dias_habiles(sesion):
    r = sesion.post(
        "/horarios", data={"accion": "copiar_0", "atiende_0": "1", "apertura_0_0": "08:30", "cierre_0_0": "17:30"}
    )
    html = r.get_data(as_text=True)
    assert html.count('value="08:30"') == 5


# --- CU07 -------------------------------------------------------------------


def test_cu07_activar_genera_codigo_y_pausar(cliente, app):
    comercio = crear_comercio(codigo=None, estado=EstadoComercio.EN_ONBOARDING)
    ingresar(cliente)
    assert cliente.get("/panel").headers["Location"].endswith("/activacion")  # precondición de CU13
    cliente.post("/activacion/activar")
    assert comercio.estado == EstadoComercio.ACTIVO
    assert comercio.codigo_acceso and len(comercio.codigo_acceso) == 6
    html = cliente.get("/activacion").get_data(as_text=True)
    assert comercio.codigo_acceso in html and "https://wa.me/15550000000?text=" in html
    assert cliente.get("/activacion/qr.svg").mimetype == "image/svg+xml"
    cliente.post("/activacion/pausar")
    assert comercio.estado == EstadoComercio.PAUSADO
    codigo = comercio.codigo_acceso
    cliente.post("/activacion/activar")
    assert comercio.codigo_acceso == codigo  # reactivar conserva el código


def test_cu07_chat_de_prueba_responde_sin_registrar(sesion):
    r1 = sesion.post("/activacion/chat-prueba", json={"texto": "hacen envíos?"}).get_json()
    assert r1["respuestas"][0]["texto"].startswith("¡Hola! 👋 Soy el asistente automático")
    assert "código postal" in r1["respuestas"][0]["texto"]
    r2 = sesion.post("/activacion/chat-prueba", json={"texto": "5800"}).get_json()
    assert "2 a 4 días hábiles" in r2["respuestas"][0]["texto"]
    r3 = sesion.post("/activacion/chat-prueba", json={"texto": "tienen almohadones?"}).get_json()
    assert r3["nota"] and "pendiente" in r3["nota"] and r3["tema"] == "Productos y precios"
    # En la prueba se puede seguir probando después de una derivación.
    r4 = sesion.post("/activacion/chat-prueba", json={"texto": "Medios de pago", "boton": "op_pago"}).get_json()
    assert "Transferencia bancaria" in r4["respuestas"][0]["texto"]
    assert db.session.scalar(select(func.count()).select_from(Consulta)) == 0


def test_cu07_requiere_onboarding_completo(cliente):
    nuevo_en_onboarding(cliente)
    assert cliente.post("/activacion/activar").headers["Location"].endswith("/onboarding")


# --- CU13 -------------------------------------------------------------------


def _consulta(comercio_texto, texto, fecha, telefono):
    procesar_mensaje_entrante(MensajeEntrante(telefono=telefono, texto=comercio_texto, fecha_hora=fecha))
    return procesar_mensaje_entrante(MensajeEntrante(telefono=telefono, texto=texto, fecha_hora=fecha))


def test_cu13_indicadores_del_periodo(sesion, comercio, reloj):
    lunes_11 = datetime(2026, 10, 26, 11, 0)
    _consulta(comercio.texto_primer_mensaje(), "formas de pago?", lunes_11, "5493510000001")
    _consulta(comercio.texto_primer_mensaje(), "horarios?", reloj.actual - timedelta(minutes=5), "5493510000002")
    _consulta(
        comercio.texto_primer_mensaje(), "tienen almohadones?", reloj.actual - timedelta(minutes=3), "5493510000003"
    )
    _consulta(comercio.texto_primer_mensaje(), "envíos al 5000", reloj.actual - timedelta(days=20), "5493510000004")

    html = sesion.get("/panel").get_data(as_text=True)
    assert 'el bot recibió <span class="cifra">3</span>' in html
    assert 'resolvió <span class="cifra">2</span> sin intervención (67&nbsp;%)' in html
    assert '<span class="cifra">2</span> llegaron con el comercio cerrado' in html
    assert "Consultas pendientes (1)" in html and "tienen almohadones?" in html
    assert "https://wa.me/5493510000003" in html

    html30 = sesion.get("/panel?periodo=30").get_data(as_text=True)
    assert 'el bot recibió <span class="cifra">4</span>' in html30


def test_cu13_marcar_atendida_devuelve_la_conversacion_al_bot(sesion, comercio, reloj):
    r = _consulta(comercio.texto_primer_mensaje(), "tienen almohadones?", reloj.actual, "5493510000003")
    sesion.post(f"/panel/consultas/{r.consulta.id_consulta}/atendida")
    consulta = db.session.get(Consulta, r.consulta.id_consulta)
    assert consulta.atendida and consulta.fecha_atencion == reloj.actual
    assert consulta.conversacion.estado == EstadoConversacion.ACTIVA
    assert "No hay consultas pendientes" in sesion.get("/panel").get_data(as_text=True)


def test_cu13_sin_consultas(sesion):
    assert "todavía no hubo consultas" in sesion.get("/panel").get_data(as_text=True)


# --- CU14 -------------------------------------------------------------------


def test_cu14_historial_filtros_y_detalle(sesion, comercio, reloj):
    _consulta(comercio.texto_primer_mensaje(), "formas de pago?", reloj.actual - timedelta(days=2), "5493510000001")
    r = _consulta(comercio.texto_primer_mensaje(), "tienen almohadones?", reloj.actual, "5493510000002")

    html = sesion.get("/historial").get_data(as_text=True)
    tabla = html[html.index("<tbody>") :]
    assert tabla.index("Productos y precios") < tabla.index("Medios de pago")  # más reciente primero
    assert "Pendiente" in html and "No requiere" in html

    solo_derivadas = sesion.get("/historial?resultado=DERIVADA").get_data(as_text=True)
    assert "Productos y precios" in solo_derivadas and "Medios de pago</td>" not in solo_derivadas
    por_tema = sesion.get("/historial?tema=MEDIOS_PAGO").get_data(as_text=True)
    assert "1 consulta." in por_tema
    hoy = reloj.actual.date().isoformat()
    assert "1 consulta." in sesion.get(f"/historial?desde={hoy}&hasta={hoy}").get_data(as_text=True)

    detalle = sesion.get(f"/historial/{r.consulta.id_consulta}").get_data(as_text=True)
    assert "tienen almohadones?" in detalle and "las responde una persona del equipo" in detalle
    # Formato de WhatsApp en el historial: negrita y opciones ofrecidas.
    assert "<strong>Casa &amp; Detalles</strong>" in detalle
    assert '<span class="opciones-enviadas"' in detalle


def test_cu14_sin_registros(sesion):
    assert "Todavía no hay consultas registradas" in sesion.get("/historial").get_data(as_text=True)


def test_datos_del_negocio_con_enlace_al_catalogo(sesion, comercio):
    datos = {"nombre": "Casa & Detalles", "rubro": "Hogar", "telefono": "351 012-3456"}
    sesion.post("/mi-comercio", data={**datos, "catalogo": "@casaydetalles"})
    assert comercio.enlace_catalogo == "https://www.instagram.com/casaydetalles"
    r = sesion.post("/mi-comercio", data={**datos, "catalogo": "javascript:alert(1)"})
    assert r.status_code == 400 and "enlace válido" in r.get_data(as_text=True)
    assert comercio.enlace_catalogo == "https://www.instagram.com/casaydetalles"
    sesion.post("/mi-comercio", data={**datos, "catalogo": ""})
    assert comercio.enlace_catalogo is None


def test_portada_muestra_una_conversacion_del_bot_real(cliente):
    html = cliente.get("/").get_data(as_text=True)
    # El ejemplo se genera con el motor: si cambian las respuestas del bot, cambia la portada.
    assert "Para <strong>Río Cuarto</strong> (CP 5800" in html
    assert "las responde una persona del equipo" in html
    assert cliente.get("/salud").get_json() == {"estado": "ok", "base": "ok"}


def test_portada_redirige_al_panel_con_sesion(sesion):
    assert sesion.get("/").status_code == 302
