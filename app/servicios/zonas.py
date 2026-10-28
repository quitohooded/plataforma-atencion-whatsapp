"""Administración de zonas de envío (CU04), incluida la importación desde planilla CSV."""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass

from ..extensiones import db
from ..modelos import Comercio, ZonaEnvio
from . import ErrorValidacion

CP_MIN, CP_MAX = 1000, 9999
PLAZO_MAX = 60
COLUMNAS = ["descripcion", "cp_desde", "cp_hasta", "plazo_min_dias", "plazo_max_dias"]
MAX_FILAS_CSV = 500


@dataclass
class DatosZona:
    descripcion: str
    cp_desde: int
    cp_hasta: int
    plazo_min_dias: int
    plazo_max_dias: int

    def como_dict(self) -> dict:
        return asdict(self)

    def se_superpone(self, otra: DatosZona | ZonaEnvio) -> bool:
        return not (self.cp_hasta < otra.cp_desde or self.cp_desde > otra.cp_hasta)


def _entero(valor) -> int:
    texto = str(valor).strip()
    if texto == "":
        raise ValueError
    return int(texto)


def interpretar(datos: dict) -> DatosZona:
    """Valida los campos de una zona sin considerar las demás zonas del comercio."""
    descripcion = (datos.get("descripcion") or "").strip()
    crudos = [datos.get(c) for c in COLUMNAS[1:]]
    if not descripcion or any(v is None or str(v).strip() == "" for v in crudos):
        raise ErrorValidacion("Complete todos los campos obligatorios.")
    try:
        cp_desde, cp_hasta, plazo_min, plazo_max = (_entero(v) for v in crudos)
    except ValueError as error:
        raise ErrorValidacion("Los códigos postales y los plazos deben ser números enteros.") from error
    if len(descripcion) > 80:
        raise ErrorValidacion("La descripción no puede superar los 80 caracteres.")
    if not (CP_MIN <= cp_desde <= CP_MAX and CP_MIN <= cp_hasta <= CP_MAX):
        raise ErrorValidacion("Los códigos postales tienen 4 dígitos (entre 1000 y 9999).")
    if cp_desde > cp_hasta:
        raise ErrorValidacion("El código postal inicial no puede ser mayor que el final.")
    if not (0 <= plazo_min <= PLAZO_MAX and 0 <= plazo_max <= PLAZO_MAX):
        raise ErrorValidacion(f"Los plazos deben estar entre 0 y {PLAZO_MAX} días.")
    if plazo_min > plazo_max:
        raise ErrorValidacion("El plazo mínimo no puede ser mayor que el máximo.")
    return DatosZona(descripcion, cp_desde, cp_hasta, plazo_min, plazo_max)


def verificar_superposicion(comercio: Comercio, zona: DatosZona, excluir_id: int | None = None) -> None:
    for existente in comercio.zonas:
        if existente.id_zona == excluir_id:
            continue
        if zona.se_superpone(existente):
            raise ErrorValidacion(
                f"El rango se superpone con la zona «{existente.descripcion}» ({existente.rango_texto})."
            )


def crear_zona(comercio: Comercio, datos: dict) -> ZonaEnvio:
    zona = interpretar(datos)
    verificar_superposicion(comercio, zona)
    nueva = ZonaEnvio(comercio=comercio, **zona.como_dict())
    db.session.add(nueva)
    db.session.commit()
    return nueva


def actualizar_zona(comercio: Comercio, zona: ZonaEnvio, datos: dict) -> ZonaEnvio:
    nuevos = interpretar(datos)
    verificar_superposicion(comercio, nuevos, excluir_id=zona.id_zona)
    for campo, valor in nuevos.como_dict().items():
        setattr(zona, campo, valor)
    db.session.commit()
    return zona


def eliminar_zona(zona: ZonaEnvio) -> None:
    db.session.delete(zona)
    db.session.commit()


# ---------------------------------------------------------------------------
# Importación desde planilla (CU04, flujo alternativo)
# ---------------------------------------------------------------------------


@dataclass
class FilaObservada:
    numero: int
    valores: list[str]
    motivo: str


@dataclass
class ResultadoImportacion:
    validas: list[DatosZona]
    observadas: list[FilaObservada]


def decodificar(contenido: bytes) -> str:
    for codificacion in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    raise ErrorValidacion("No fue posible leer el archivo. Guárdelo como CSV (UTF-8).")


def analizar_csv(comercio: Comercio, contenido: bytes) -> ResultadoImportacion:
    """Valida cada fila y separa las válidas de las observadas (CU04, paso alternativo 4)."""
    texto = decodificar(contenido)
    if not texto.strip():
        raise ErrorValidacion("El archivo está vacío.")

    primera_linea = texto.splitlines()[0]
    separador = ";" if primera_linea.count(";") >= primera_linea.count(",") else ","
    lector = csv.reader(io.StringIO(texto), delimiter=separador)
    filas = [f for f in lector if any(c.strip() for c in f)]
    if not filas:
        raise ErrorValidacion("El archivo está vacío.")

    encabezado = [c.strip().lower() for c in filas[0]]
    if encabezado[: len(COLUMNAS)] != COLUMNAS:
        raise ErrorValidacion(
            "La planilla no tiene las columnas esperadas. Descargue la plantilla y respete el orden: "
            + ", ".join(COLUMNAS)
            + "."
        )
    datos_filas = filas[1:]
    if not datos_filas:
        raise ErrorValidacion("La planilla no tiene filas con zonas.")
    if len(datos_filas) > MAX_FILAS_CSV:
        raise ErrorValidacion(f"La planilla supera el máximo de {MAX_FILAS_CSV} filas.")

    validas: list[DatosZona] = []
    observadas: list[FilaObservada] = []
    for numero, fila in enumerate(datos_filas, start=2):
        valores = [c.strip() for c in fila[: len(COLUMNAS)]] + [""] * (len(COLUMNAS) - len(fila))
        try:
            zona = interpretar(dict(zip(COLUMNAS, valores, strict=False)))
            verificar_superposicion(comercio, zona)
            for anterior in validas:
                if zona.se_superpone(anterior):
                    raise ErrorValidacion(f"Se superpone con otra fila de la planilla («{anterior.descripcion}»).")
            validas.append(zona)
        except ErrorValidacion as error:
            observadas.append(FilaObservada(numero, valores, error.mensaje))
    return ResultadoImportacion(validas, observadas)


def importar(comercio: Comercio, filas: list[dict]) -> int:
    """Incorpora las filas confirmadas, validándolas de nuevo contra las zonas actuales."""
    agregadas = 0
    for datos in filas:
        try:
            zona = interpretar(datos)
            verificar_superposicion(comercio, zona)
        except ErrorValidacion:
            continue
        # Al asignar el comercio, la zona se suma a comercio.zonas y entra en la
        # verificación de superposición de las filas siguientes.
        db.session.add(ZonaEnvio(comercio=comercio, **zona.como_dict()))
        agregadas += 1
    db.session.commit()
    return agregadas


def plantilla_csv() -> str:
    filas = [
        COLUMNAS,
        ["Córdoba Capital", "5000", "5099", "1", "2"],
        ["Interior de Córdoba", "5100", "5999", "2", "4"],
        ["CABA", "1000", "1499", "3", "5"],
    ]
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=";", lineterminator="\r\n")
    escritor.writerows(filas)
    return "﻿" + salida.getvalue()
