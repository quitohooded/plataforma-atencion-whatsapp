"""RF13 Aislamiento de datos por comercio: un comercio no ve ni modifica datos de otro."""

from app.bot.servicio import MensajeEntrante, procesar_mensaje_entrante
from app.extensiones import db
from app.modelos import MedioPago, ZonaEnvio

from .conftest import ingresar


def test_un_comercio_no_accede_a_registros_de_otro(cliente, comercio, otro_comercio):
    procesar_mensaje_entrante(MensajeEntrante(telefono="5493510000009", texto=comercio.texto_primer_mensaje()))
    derivada = procesar_mensaje_entrante(MensajeEntrante(telefono="5493510000009", texto="tienen almohadones?"))
    zona_ajena = comercio.zonas[0]
    medio_ajeno = comercio.medios_pago[0]

    ingresar(cliente, otro_comercio.usuario.email)
    for metodo, ruta in [
        ("get", f"/zonas/{zona_ajena.id_zona}/editar"),
        ("post", f"/zonas/{zona_ajena.id_zona}/eliminar"),
        ("get", f"/medios-de-pago/{medio_ajeno.id_medio_pago}/editar"),
        ("post", f"/medios-de-pago/{medio_ajeno.id_medio_pago}/estado"),
        ("post", f"/medios-de-pago/{medio_ajeno.id_medio_pago}/eliminar"),
        ("get", f"/historial/{derivada.consulta.id_consulta}"),
    ]:
        assert getattr(cliente, metodo)(ruta).status_code == 404, ruta

    cliente.post(f"/panel/consultas/{derivada.consulta.id_consulta}/atendida")
    assert derivada.consulta.atendida is False
    assert db.session.get(ZonaEnvio, zona_ajena.id_zona) is not None
    assert db.session.get(MedioPago, medio_ajeno.id_medio_pago).activo is True


def test_listados_muestran_solo_lo_propio(cliente, comercio, otro_comercio):
    procesar_mensaje_entrante(MensajeEntrante(telefono="5493510000009", texto=comercio.texto_primer_mensaje()))
    procesar_mensaje_entrante(MensajeEntrante(telefono="5493510000009", texto="tienen almohadones?"))
    otro_comercio.zonas[0].descripcion = "Rosario"
    db.session.commit()

    ingresar(cliente, otro_comercio.usuario.email)
    assert "Todavía no hay consultas registradas" in cliente.get("/historial").get_data(as_text=True)
    assert "No hay consultas pendientes" in cliente.get("/panel").get_data(as_text=True)
    zonas = cliente.get("/zonas").get_data(as_text=True)
    assert "<strong>Rosario</strong>" in zonas
    assert "<strong>Córdoba Capital</strong>" not in zonas
