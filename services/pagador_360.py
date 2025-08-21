# services/pagador_360.py
from datetime import datetime
from sqlalchemy import func, extract, or_
from models import FacturaDB, EsgCertificacion, PagadorProfile, OfertaFinanciamiento
from models import ESGAssessment, ESGAnswer, ESGCriterion
from services.connectors.esg_certificaciones import get_esg_payload


# ——— Helper NUEVO: mapea tu modelo EsgCertificacion al formato del panel ESG ———
def _map_certs_for_esg(certs):
    out = []
    for c in certs or []:
        out.append({
            "certificacion": getattr(c, "certificacion", getattr(c, "nombre", "")),
            "categoria": getattr(c, "categoria", None),
            "emisor": getattr(c, "emisor", None),
            "vigencia_inicio": getattr(c, "vigencia_inicio", None),
            "vigencia_fin": getattr(c, "vigencia_fin", None),
            "evidencia_url": getattr(c, "evidencia_url", None),
            "estado": getattr(c, "estado", None),
        })
    return out

def _build_esg_questionnaire_snapshot(db, pagador_rut: str):
    """
    Toma la última evaluación ESG del pagador y arma un dict con:
    - periodo (año/mes)
    - estado
    - puntaje_total (suma de respuestas)
    - respuestas detalladas con criterio
    Si no hay evaluación, retorna None.
    """
    # última evaluación por periodo (y, m, id)
    ultima = (
        db.query(ESGAssessment)
        .filter(ESGAssessment.pagador_rut == pagador_rut)
        .order_by(ESGAssessment.periodo_anio.desc(),
                  ESGAssessment.periodo_mes.desc(),
                  ESGAssessment.id.desc())
        .first()
    )
    if not ultima:
        return None

    rows = (
        db.query(ESGAnswer, ESGCriterion)
        .join(ESGCriterion, ESGAnswer.criterio_id == ESGCriterion.id)
        .filter(ESGAnswer.assessment_id == ultima.id)
        .all()
    )

    respuestas = []
    puntaje_total = 0.0
    for ans, crit in rows:
        respuestas.append({
            "criterio_code": crit.code,
            "criterio_nombre": crit.nombre,
            "categoria": crit.categoria,
            "peso": crit.peso,
            "answer_type": crit.answer_type,
            "valor_bool": ans.valor_bool,
            "valor_number": ans.valor_number,
            "valor_text": ans.valor_text,
            "puntaje": ans.puntaje or 0.0,
        })
        puntaje_total += (ans.puntaje or 0.0)

    return {
        "assessment_id": ultima.id,
        "periodo_anio": ultima.periodo_anio,
        "periodo_mes": ultima.periodo_mes,
        "estado": ultima.estado,
        "puntaje_total": round(puntaje_total, 2),
        "respuestas": respuestas,
    }

# ✅ Estados que SÍ cuentan como confirmadas/adjudicadas
CONF_STRICT = {
    "confirmada por pagador",
    "confirmada",                # por compatibilidad con datos antiguos
    "confirming adjudicado",
}

# ✅ Estados que cuentan como rechazadas
RECH_SET = {"rechazada", "rechazada por pagador"}

def kpis_pagador(db, rut_norm):
    q = db.query(FacturaDB).filter(FacturaDB.rut_receptor == rut_norm)

    # EXISTS: oferta adjudicada (por si el campo financiador_adjudicado no está poblado)
    adj_exists = (
        db.query(OfertaFinanciamiento.id)
          .filter(
              OfertaFinanciamiento.factura_id == FacturaDB.id,
              func.lower(OfertaFinanciamiento.estado).like("adjudic%")
          )
          .correlate(FacturaDB)
          .exists()
    )

    total = q.count()

    # ✅ Confirmadas/adjudicadas (NO incluye "confirming solicitado" ni bandera confirming_solicitado)
    confirmadas = q.filter(
        or_(
            func.lower(func.coalesce(FacturaDB.estado_confirmacion, "")).in_(list(CONF_STRICT)),
            func.lower(func.coalesce(FacturaDB.estado_dte, ""))            .in_(list(CONF_STRICT)),
            FacturaDB.financiador_adjudicado.isnot(None),
            adj_exists,
        )
    ).count()

    # ✅ Rechazadas
    rechazadas = q.filter(
        or_(
            func.lower(func.coalesce(FacturaDB.estado_confirmacion, "")).in_(list(RECH_SET)),
            func.lower(func.coalesce(FacturaDB.estado_dte, ""))            .in_(list(RECH_SET)),
        )
    ).count()

    pendientes = max(total - confirmadas - rechazadas, 0)

    # ✅ TMC: solo sobre confirmadas/adjudicadas reales
    tmc = db.query(
        func.avg(func.julianday(FacturaDB.fecha_confirmacion) - func.julianday(FacturaDB.fecha_emision))
    ).filter(
        FacturaDB.rut_receptor == rut_norm,
        or_(
            func.lower(func.coalesce(FacturaDB.estado_confirmacion, "")).in_(list(CONF_STRICT)),
            func.lower(func.coalesce(FacturaDB.estado_dte, ""))            .in_(list(CONF_STRICT)),
            FacturaDB.financiador_adjudicado.isnot(None),
            adj_exists,
        ),
        FacturaDB.fecha_confirmacion.isnot(None),
        FacturaDB.fecha_emision.isnot(None)
    ).scalar()
    tiempo_medio_confirmacion = round(tmc, 2) if tmc is not None else None

    # Tiempo medio de pago (si lo usas)
    tmp = db.query(
        func.avg(func.julianday(FacturaDB.fecha_pago_real) - func.julianday(FacturaDB.fecha_emision))
    ).filter(
        FacturaDB.rut_receptor == rut_norm,
        FacturaDB.fecha_pago_real.isnot(None),
        FacturaDB.fecha_emision.isnot(None)
    ).scalar()
    tiempo_medio_pago = round(tmp, 2) if tmp is not None else None

    # ✅ Series: solo confirmadas/adjudicadas
    montos_por_mes = db.query(
        extract('year', FacturaDB.fecha_emision).label('y'),
        extract('month', FacturaDB.fecha_emision).label('m'),
        func.sum(FacturaDB.monto).label('total_monto')
    ).filter(
        FacturaDB.rut_receptor == rut_norm,
        or_(
            func.lower(func.coalesce(FacturaDB.estado_confirmacion, "")).in_(list(CONF_STRICT)),
            func.lower(func.coalesce(FacturaDB.estado_dte, ""))            .in_(list(CONF_STRICT)),
            FacturaDB.financiador_adjudicado.isnot(None),
            adj_exists,
        ),
        FacturaDB.fecha_emision.isnot(None)
    ).group_by('y', 'm').order_by('y', 'm').all()

    serie_montos = [
        {"periodo": f"{int(y)}-{int(m):02d}", "monto": int(total_monto or 0)}
        for (y, m, total_monto) in montos_por_mes
    ]

    tmc_mes = db.query(
        extract('year', FacturaDB.fecha_confirmacion).label('y'),
        extract('month', FacturaDB.fecha_confirmacion).label('m'),
        func.avg(
            func.julianday(FacturaDB.fecha_confirmacion) - func.julianday(FacturaDB.fecha_emision)
        ).label('tmc')
    ).filter(
        FacturaDB.rut_receptor == rut_norm,
        or_(
            func.lower(func.coalesce(FacturaDB.estado_confirmacion, "")).in_(list(CONF_STRICT)),
            func.lower(func.coalesce(FacturaDB.estado_dte, ""))            .in_(list(CONF_STRICT)),
            FacturaDB.financiador_adjudicado.isnot(None),
            adj_exists,
        ),
        FacturaDB.fecha_confirmacion.isnot(None),
        FacturaDB.fecha_emision.isnot(None)
    ).group_by('y', 'm').order_by('y', 'm').all()

    serie_tmc = [
        {"periodo": f"{int(y)}-{int(m):02d}", "tmc": round(t, 2) if t is not None else None}
        for (y, m, t) in tmc_mes
    ]

    certs  = db.query(EsgCertificacion).filter(EsgCertificacion.rut == rut_norm).all()
    perfil = db.query(PagadorProfile).filter(PagadorProfile.rut == rut_norm).first()

    # ——— NUEVO: obtener payload ESG unificado desde el conector (con fallback seguro) ———
    try:
        esg_payload = get_esg_payload(rut_norm)
    except Exception as e:
        # Fallback: si el conector falla o aún no está completo, construimos un payload mínimo con tus certificaciones
        mapped = _map_certs_for_esg(certs)
        esg_payload = {
            "sector": {"clasificacion": "NO MINERIA", "confianza": 0, "evidencias": []},
            "score": {
                "total": 0,
                "nivel": "E",
                "detalle": {
                    "certificaciones_validas": len([x for x in mapped if (x.get("estado") or "").lower() == "vigente"])
                },
                "ultima_actualizacion": datetime.now().strftime("%Y-%m-%d %H:%M")
            },
            "indicadores": [],
            "iniciativas": [],
            "certificaciones": mapped,
            "fuentes_externas": {}
        }

    # ——— NUEVO: sumar cuestionario ESG interno (tablas ESG* locales) ———
    cuestionario = _build_esg_questionnaire_snapshot(db, rut_norm)

    return {
        "totales": {
            "total": total,
            "confirmadas": confirmadas,
            "rechazadas": rechazadas,
            "pendientes": pendientes,
            "confirmacion_rate": round((confirmadas / total) * 100, 1) if total else 0.0
        },
        "tiempos": {
            "tiempo_medio_confirmacion": tiempo_medio_confirmacion,
            "tiempo_medio_pago": tiempo_medio_pago
        },
        "series": {
            "montos_por_mes": serie_montos,
            "tmc_por_mes": serie_tmc
        },
        "esg": {
            "certificaciones": certs,   # legacy: se mantiene igual
            "perfil": perfil,           # legacy: se mantiene igual
            "payload": esg_payload,      # NUEVO: JSON unificado para mostrar el panel ESG
            "cuestionario": cuestionario  # ← NUEVO: snapshot ESG interno (puede ser None)
        }
    }

# ──────────────────────────────────────────────────────────────────────────────
# Mercado Público → lecturas para Vista 360 (ventas 12m)
# No persiste. Solo consulta al conector y normaliza.
# ──────────────────────────────────────────────────────────────────────────────

# al final de services/pagador_360.py
async def mp_vision_360_por_rut(rut_proveedor: str, *, force: bool = False, pdf_path: str = None) -> dict:
    """
    Obtiene la 'visión 360' de Mercado Público:
      - Si se pasa pdf_path -> lee la ficha PDF (modo offline)
      - Si no -> consulta API REST (con cache 24h)
    SIEMPRE retorna un dict (nunca None) para no romper el template/router.
    """
    from services.connectors import mercado_publico as mp
    try:
        if pdf_path:
            out = await mp.fetch_mp_vision_desde_pdf(pdf_path)
        else:
            # usa el nombre unificado "fetch_mp_vision"
            out = await mp.fetch_mp_vision(rut_proveedor, force=force)
    except Exception as e:
        out = {"ok": False, "error": f"{type(e).__name__}: {e}", "rut_consultado": rut_proveedor}

    # defensa extra: nunca None
    return out or {"ok": False, "error": "sin datos", "rut_consultado": rut_proveedor}

    