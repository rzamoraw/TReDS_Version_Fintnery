# services/pagador_360.py (nuevo archivo utilitario)
from datetime import datetime
from sqlalchemy import func, extract, or_
from models import FacturaDB, EsgCertificacion, PagadorProfile, OfertaFinanciamiento

CONF_SET = {"confirmada", "confirming solicitado", "adjudicada", "adjudicadas"}
RECHAZO  = "rechazada"

def kpis_pagador(db, rut_norm):
    q = db.query(FacturaDB).filter(FacturaDB.rut_receptor == rut_norm)

    # EXISTS: oferta adjudicada (correlacionada con FacturaDB.id)
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

    confirmadas = q.filter(
        or_(
            func.lower(FacturaDB.estado_confirmacion).in_(list(CONF_SET)),
            FacturaDB.confirming_solicitado.is_(True),
            FacturaDB.financiador_adjudicado.isnot(None),
            adj_exists,
        )
    ).count()

    rechazadas = q.filter(func.lower(FacturaDB.estado_confirmacion) == RECHAZO).count()
    pendientes = max(total - confirmadas - rechazadas, 0)

    # TMC (solo con fechas presentes)
    tmc = db.query(
        func.avg(func.julianday(FacturaDB.fecha_confirmacion) - func.julianday(FacturaDB.fecha_emision))
    ).filter(
        FacturaDB.rut_receptor == rut_norm,
        or_(
            func.lower(FacturaDB.estado_confirmacion).in_(list(CONF_SET)),
            FacturaDB.confirming_solicitado.is_(True),
            FacturaDB.financiador_adjudicado.isnot(None),
            adj_exists,
        ),
        FacturaDB.fecha_confirmacion.isnot(None),
        FacturaDB.fecha_emision.isnot(None)
    ).scalar()
    tiempo_medio_confirmacion = round(tmc, 2) if tmc is not None else None

    tmp = db.query(
        func.avg(func.julianday(FacturaDB.fecha_pago_real) - func.julianday(FacturaDB.fecha_emision))
    ).filter(
        FacturaDB.rut_receptor == rut_norm,
        FacturaDB.fecha_pago_real.isnot(None),
        FacturaDB.fecha_emision.isnot(None)
    ).scalar()
    tiempo_medio_pago = round(tmp, 2) if tmp is not None else None

    montos_por_mes = db.query(
        extract('year', FacturaDB.fecha_emision).label('y'),
        extract('month', FacturaDB.fecha_emision).label('m'),
        func.sum(FacturaDB.monto).label('total_monto')
    ).filter(
        FacturaDB.rut_receptor == rut_norm,
        or_(
            func.lower(FacturaDB.estado_confirmacion).in_(list(CONF_SET)),
            FacturaDB.confirming_solicitado.is_(True),
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
            func.lower(FacturaDB.estado_confirmacion).in_(list(CONF_SET)),
            FacturaDB.confirming_solicitado.is_(True),
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
        "esg": { "certificaciones": certs, "perfil": perfil }
    }