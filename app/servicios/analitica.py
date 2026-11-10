"""Servicio de analítica avanzada de negocio y métricas SuperAdmin SaaS (Pilar 6).

Provee:
1. Métricas de valor percibido para el comercio (ventas $ARS en chat, tiempo ahorrado,
   tasa de resolución automática 24/7 y radar de demanda no satisfecha).
2. Métricas globales de plataforma para el SuperAdmin SaaS (MRR, distribución por plan,
   facturación por packs prepagos, llamadas IA Gemini y margen operativo >95%).
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select

from ..extensiones import db
from ..modelos import (
    Comercio,
    Consulta,
    Conversacion,
    EstadoComercio,
    ItemCatalogo,
    PedidoChat,
    PlanComercio,
    ResultadoConsulta,
    TransaccionPago,
)
from ..utilidades import tiempo

PERIODOS_ANALITICA = {
    "hoy": ("Hoy", 0),
    "7": ("Últimos 7 días", 7),
    "30": ("Últimos 30 días", 30),
    "90": ("Últimos 90 días", 90),
}


class MetricasDict(dict):
    """Diccionario que permite acceso tanto por clave como por atributo."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as err:
            raise AttributeError(f"No existe la métrica {name!r}") from err

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def metricas_comercio_analitica(
    comercio: Comercio, periodo: str = "30", ahora: datetime | None = None
) -> MetricasDict:
    """Calcula las métricas de valor percibido e impacto comercial para el comercio."""
    if ahora is None:
        ahora = tiempo.ahora()

    clave_periodo = str(periodo) if str(periodo) in PERIODOS_ANALITICA else "30"
    etiqueta, dias = PERIODOS_ANALITICA[clave_periodo]

    inicio_hoy = datetime.combine(ahora.date(), time.min)
    desde = inicio_hoy - timedelta(days=max(dias - 1, 0)) if dias else inicio_hoy
    hasta = ahora

    # 1. Pedidos en el chat y ventas en pesos ARS
    pedidos = db.session.scalars(
        select(PedidoChat).where(
            PedidoChat.id_comercio == comercio.id_comercio,
            PedidoChat.fecha_hora >= desde,
            PedidoChat.fecha_hora <= hasta,
        )
    ).all()

    pedidos_totales = len(pedidos)
    ventas_totales_ars = sum(p.monto_total or 0 for p in pedidos)
    ventas_pagadas_ars = sum(
        p.monto_total or 0 for p in pedidos if (p.estado_pago or "").upper() in ("PAGADO", "INFORMADO")
    )
    ventas_sin_pagar_ars = sum(
        p.monto_total or 0 for p in pedidos if (p.estado_pago or "").upper() not in ("PAGADO", "INFORMADO")
    )

    ticket_promedio = round(ventas_totales_ars / pedidos_totales, 2) if pedidos_totales > 0 else 0
    ventas_desglose = MetricasDict({
        "pagado_informado": ventas_pagadas_ars,
        "sin_pagar": ventas_sin_pagar_ars,
        "PAGADO": ventas_pagadas_ars,
        "SIN_PAGAR": ventas_sin_pagar_ars,
    })

    # 2. Consultas, tasa de resolución y horas ahorradas
    consultas = db.session.scalars(
        select(Consulta)
        .join(Conversacion)
        .where(
            Conversacion.id_comercio == comercio.id_comercio,
            Consulta.fecha_hora >= desde,
            Consulta.fecha_hora <= hasta,
        )
    ).all()

    consultas_totales = len(consultas)
    consultas_resueltas = sum(1 for c in consultas if c.resultado == ResultadoConsulta.RESUELTA)
    consultas_derivadas = sum(1 for c in consultas if c.resultado == ResultadoConsulta.DERIVADA)

    # 6 minutos por consulta resuelta por bot = resueltas * 0.1 horas
    horas_ahorradas = round(consultas_resueltas * 0.1, 1)
    tasa_resolucion_auto = (
        round((consultas_resueltas / consultas_totales) * 100, 1) if consultas_totales > 0 else 0.0
    )

    consultas_fuera_horario = sum(
        1
        for c in consultas
        if c.fuera_de_horario is True or (c.fuera_de_horario is None and not comercio.esta_abierto(c.fecha_hora))
    )

    # 3. Radar de Demanda (temas derivados, productos sin stock, palabras reiteradas)
    radar_demanda: list[MetricasDict] = []
    temas_derivadas: dict[Any, int] = {}
    mensajes_derivados: list[str] = []

    for c in consultas:
        if c.resultado == ResultadoConsulta.DERIVADA:
            temas_derivadas[c.tema] = temas_derivadas.get(c.tema, 0) + 1
            if c.mensaje and c.mensaje.texto:
                mensajes_derivados.append(c.mensaje.texto)

    for tema, cant in sorted(temas_derivadas.items(), key=lambda x: -x[1]):
        radar_demanda.append(
            MetricasDict({
                "concepto": tema.etiqueta,
                "termino": tema.etiqueta,
                "tema": tema.value,
                "frecuencia": cant,
                "cantidad": cant,
                "tipo": "consulta_derivada",
                "motivo": "Consultas derivadas a atención humana",
            })
        )

    # Productos agotados en el catálogo
    items_sin_stock = db.session.scalars(
        select(ItemCatalogo).where(
            ItemCatalogo.id_comercio == comercio.id_comercio,
            ItemCatalogo.stock_disponible.is_(False),
            ItemCatalogo.activo.is_(True),
        )
    ).all()

    for item in items_sin_stock:
        radar_demanda.append(
            MetricasDict({
                "concepto": f"Sin stock: {item.nombre}",
                "termino": item.nombre,
                "tema": "PRODUCTOS",
                "frecuencia": 1,
                "cantidad": 1,
                "tipo": "sin_stock",
                "motivo": "Producto agotado en catálogo",
            })
        )

    # Palabras clave repetidas en mensajes de consultas derivadas
    palabras_ignorar = {
        "hola", "buenas", "buenos", "dias", "tardes", "noches", "gracias", "por", "favor",
        "para", "como", "esta", "este", "estos", "estan", "quiero", "necesito", "consulta",
        "ustedes", "donde", "cuando", "cuanto", "tiene", "tienen", "hacer", "puedo", "info",
    }
    conteo_palabras: dict[str, int] = {}
    for txt in mensajes_derivados:
        palabras = re.findall(r"[a-záéíóúñ]{4,}", txt.lower())
        for p in palabras:
            if p not in palabras_ignorar:
                conteo_palabras[p] = conteo_palabras.get(p, 0) + 1

    for p, cant in sorted(conteo_palabras.items(), key=lambda x: -x[1])[:5]:
        if cant > 1:
            radar_demanda.append(
                MetricasDict({
                    "concepto": f"Palabra frecuente: «{p}»",
                    "termino": p,
                    "tema": "PALABRA_FRECUENTE",
                    "frecuencia": cant,
                    "cantidad": cant,
                    "tipo": "palabra_clave",
                    "motivo": f"Mencionada {cant} veces en consultas no resueltas",
                })
            )

    return MetricasDict({
        "periodo": clave_periodo,
        "etiqueta_periodo": etiqueta,
        "desde": desde,
        "hasta": hasta,
        "ventas_totales_ars": ventas_totales_ars,
        "ventas_pagadas_ars": ventas_pagadas_ars,
        "ventas_sin_pagar_ars": ventas_sin_pagar_ars,
        "ventas_desglose": ventas_desglose,
        "pedidos_totales": pedidos_totales,
        "ticket_promedio": ticket_promedio,
        "consultas_totales": consultas_totales,
        "consultas_resueltas": consultas_resueltas,
        "consultas_derivadas": consultas_derivadas,
        "horas_ahorradas": horas_ahorradas,
        "tasa_resolucion_auto": tasa_resolucion_auto,
        "consultas_fuera_horario": consultas_fuera_horario,
        "radar_demanda": radar_demanda,
    })


def metricas_superadmin_saas() -> MetricasDict:
    """Calcula las métricas consolidadas del ecosistema SaaS para el SuperAdmin."""
    total_comercios = db.session.scalar(select(func.count(Comercio.id_comercio))) or 0
    comercios = db.session.scalars(select(Comercio).order_by(Comercio.id_comercio.desc())).all()

    count_free = sum(1 for c in comercios if c.plan == PlanComercio.FREE)
    count_pro = sum(1 for c in comercios if c.plan == PlanComercio.PRO)
    count_enterprise = sum(1 for c in comercios if c.plan == PlanComercio.ENTERPRISE)

    comercios_por_plan = MetricasDict({
        "GRATIS": count_free,
        "PRO": count_pro,
        "A_MEDIDA": count_enterprise,
        "FREE": count_free,
        "ENTERPRISE": count_enterprise,
        PlanComercio.FREE: count_free,
        PlanComercio.PRO: count_pro,
        PlanComercio.ENTERPRISE: count_enterprise,
    })

    # MRR: Comercios Pro * $14.900 ARS
    mrr_estimado_ars = count_pro * 14900

    # Facturación por packs de créditos en el mes en curso
    ahora = tiempo.ahora()
    inicio_mes = datetime(ahora.year, ahora.month, 1)
    transacciones_mes = db.session.scalars(
        select(TransaccionPago).where(
            TransaccionPago.estado.in_(["APROBADO", "approved"]),
            TransaccionPago.fecha_creacion >= inicio_mes,
            TransaccionPago.tipo != "SUSCRIPCION",
        )
    ).all()
    facturacion_packs_mes_ars = sum(t.monto for t in transacciones_mes)

    # Total de llamadas / tokens de IA consumidos
    total_ia_semana = db.session.scalar(select(func.sum(Comercio.ia_usados_semana))) or 0
    total_ia_interna = db.session.scalar(select(func.sum(Comercio.ia_usados_interna))) or 0
    total_ia_usados = total_ia_semana + total_ia_interna

    # Costo Gemini en tier gratuito = $0 ARS -> Margen > 95%
    costo_estimado_ia_ars = 0
    facturacion_total = mrr_estimado_ars + facturacion_packs_mes_ars
    if facturacion_total > 0:
        margen_estimado_porcentaje = round(
            ((facturacion_total - costo_estimado_ia_ars) / facturacion_total) * 100, 1
        )
    else:
        margen_estimado_porcentaje = 100.0

    # Flota de comercios detallada
    flota_comercios: list[MetricasDict] = []
    for c in comercios:
        if (c.whatsapp_phone_number_id and c.whatsapp_token) or c.whatsapp_phone_number_id:
            canal_activo = "WABA"
        elif c.slug:
            canal_activo = "Web"
        else:
            canal_activo = "Simulador"

        email = c.usuario.email if c.usuario else "-"
        flota_comercios.append(
            MetricasDict({
                "id_comercio": c.id_comercio,
                "nombre": c.nombre,
                "rubro": c.rubro,
                "email": email,
                "plan": c.plan.value,
                "plan_etiqueta": c.plan.etiqueta,
                "canal_activo": canal_activo,
                "creditos_ia": c.saldo_creditos,
                "saldo_creditos": c.saldo_creditos,
                "ia_usados_semana": c.ia_usados_semana,
                "fecha_registro": c.fecha_alta,
                "fecha_alta": c.fecha_alta,
                "estado": c.estado.value,
                "estado_etiqueta": c.estado.etiqueta,
                "bot_activo": c.estado == EstadoComercio.ACTIVO,
                "objeto": c,
            })
        )

    return MetricasDict({
        "total_comercios": total_comercios,
        "comercios_por_plan": comercios_por_plan,
        "mrr_estimado_ars": mrr_estimado_ars,
        "facturacion_packs_mes_ars": facturacion_packs_mes_ars,
        "total_ia_usados": total_ia_usados,
        "costo_estimado_ia_ars": costo_estimado_ia_ars,
        "margen_estimado_porcentaje": margen_estimado_porcentaje,
        "flota_comercios": flota_comercios,
    })


def cambiar_plan_comercio(comercio: Comercio, nuevo_plan_str: str) -> None:
    """Actualiza el plan de suscripción de un comercio desde SuperAdmin."""
    plan_normalizado = (nuevo_plan_str or "").strip().upper()
    if plan_normalizado in ("PRO", PlanComercio.PRO.value):
        comercio.plan = PlanComercio.PRO
        comercio.ia_cuota_semanal = 250
        comercio.ia_cuota_interna = 100
        comercio.ia_semana_inicio = tiempo.ahora().date()
        comercio.ia_usados_semana = 0
    elif plan_normalizado in ("A_MEDIDA", "ENTERPRISE", PlanComercio.ENTERPRISE.value):
        comercio.plan = PlanComercio.ENTERPRISE
        comercio.ia_cuota_interna = 200
    elif plan_normalizado in ("GRATIS", "FREE", PlanComercio.FREE.value):
        comercio.plan = PlanComercio.FREE
        comercio.ia_cuota_semanal = 0
        comercio.ia_usados_semana = 0
    else:
        raise ValueError(f"Plan no reconocido: {nuevo_plan_str}")
    db.session.commit()


def otorgar_creditos_comercio(comercio: Comercio, cantidad: int) -> None:
    """Otorga un paquete de créditos de cortesía a la billetera prepaga del comercio."""
    if cantidad <= 0:
        raise ValueError("La cantidad de créditos debe ser positiva.")
    comercio.saldo_creditos += cantidad
    db.session.commit()


def cambiar_estado_bot_comercio(comercio: Comercio, activar: bool) -> None:
    """Activa o pausa el bot de atención del comercio."""
    if activar:
        if not comercio.codigo_acceso:
            from ..modelos import generar_codigo_unico

            comercio.codigo_acceso = generar_codigo_unico()
        comercio.asegurar_slug()
        comercio.estado = EstadoComercio.ACTIVO
    else:
        comercio.estado = EstadoComercio.PAUSADO
    db.session.commit()
