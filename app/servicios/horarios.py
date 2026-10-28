"""Administración de horarios de atención (CU06), con jornada partida y copia a días hábiles."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time

from ..extensiones import db
from ..modelos import Comercio, HorarioAtencion
from ..utilidades.tiempo import DIAS_SEMANA

_CAMPO = re.compile(r"^(apertura|cierre)_(\d)_(\d+)$")
DIAS_HABILES = range(0, 5)


@dataclass
class DiaHorario:
    dia: int
    atiende: bool = False
    franjas: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None

    @property
    def nombre(self) -> str:
        return DIAS_SEMANA[self.dia]


def desde_comercio(comercio: Comercio) -> list[DiaHorario]:
    dias = [DiaHorario(d) for d in range(7)]
    for h in sorted(comercio.horarios, key=lambda h: (h.dia_semana, h.hora_apertura)):
        dias[h.dia_semana].atiende = True
        dias[h.dia_semana].franjas.append((h.hora_apertura, h.hora_cierre))
    return dias


def leer_formulario(formulario) -> list[DiaHorario]:
    """Convierte los campos atiende_D, apertura_D_I y cierre_D_I en la grilla semanal."""
    crudo: dict[int, dict[int, dict[str, str]]] = {d: {} for d in range(7)}
    for clave in formulario.keys():
        coincidencia = _CAMPO.match(clave)
        if not coincidencia:
            continue
        tipo, dia, indice = coincidencia.group(1), int(coincidencia.group(2)), int(coincidencia.group(3))
        if dia > 6:
            continue
        crudo[dia].setdefault(indice, {})[tipo] = (formulario.get(clave) or "").strip()

    dias = []
    for d in range(7):
        franjas = []
        for indice in sorted(crudo[d]):
            apertura = crudo[d][indice].get("apertura", "")
            cierre = crudo[d][indice].get("cierre", "")
            if apertura or cierre:
                franjas.append((apertura, cierre))
        dias.append(DiaHorario(d, atiende=bool(formulario.get(f"atiende_{d}")), franjas=franjas))
    return dias


def _hora(texto: str) -> time | None:
    try:
        return time.fromisoformat(texto[:5])
    except (ValueError, TypeError):
        return None


def validar(dias: list[DiaHorario]) -> bool:
    """Marca el error de cada día. Devuelve True si toda la semana es válida (CU06, excepción)."""
    valido = True
    for dia in dias:
        dia.error = None
        if not dia.atiende:
            continue
        if not dia.franjas:
            dia.error = "Indique al menos una franja horaria o desmarque el día."
        intervalos = []
        for apertura, cierre in dia.franjas:
            a, c = _hora(apertura), _hora(cierre)
            if not apertura or not cierre or a is None or c is None:
                dia.error = "Complete la hora de apertura y de cierre de cada franja."
                break
            if c <= a:
                dia.error = "La hora de cierre debe ser posterior a la de apertura."
                break
            intervalos.append((a, c))
        if not dia.error:
            intervalos.sort()
            for (a1, c1), (a2, _c2) in zip(intervalos, intervalos[1:]):
                if a2 < c1:
                    dia.error = "Las franjas horarias del día se superponen."
                    break
        if dia.error:
            valido = False
    return valido


def copiar_a_habiles(dias: list[DiaHorario], origen: int) -> list[DiaHorario]:
    """Copia el horario de un día al resto de los días hábiles (CU06, flujo alternativo)."""
    fuente = dias[origen]
    for d in DIAS_HABILES:
        if d != origen:
            dias[d].atiende = fuente.atiende
            dias[d].franjas = list(fuente.franjas)
            dias[d].error = None
    return dias


def guardar(comercio: Comercio, dias: list[DiaHorario]) -> None:
    for horario in list(comercio.horarios):
        db.session.delete(horario)
    comercio.horarios.clear()
    db.session.flush()
    for dia in dias:
        if not dia.atiende:
            continue
        for apertura, cierre in sorted(dia.franjas):
            db.session.add(HorarioAtencion(
                comercio=comercio, dia_semana=dia.dia,
                hora_apertura=apertura[:5], hora_cierre=cierre[:5],
            ))
    db.session.commit()


def tiene_horarios(dias: list[DiaHorario]) -> bool:
    return any(d.atiende and d.franjas for d in dias)
