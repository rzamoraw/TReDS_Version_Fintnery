# routers/esg.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import SessionLocal
from models import ESGCriterion

router = APIRouter(prefix="/esg", tags=["ESG"])

# ──────────────────────────────── DB dependency ────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ──────────────────────────────── Criterios base ───────────────────────────────
CRITERIOS_BASE = [
    # Gobernanza (G)
    dict(code="G-ANTI_CORR", nombre="Política anticorrupción vigente y publicada", categoria="G", peso=2.0, answer_type="bool"),
    dict(code="G-CUMPL_TRIB", nombre="Cumplimiento tributario al día (SII)", categoria="G", peso=2.0, answer_type="bool"),
    dict(code="G-KYC_AML",   nombre="Política KYC/AML para evaluación de proveedores", categoria="G", peso=1.5, answer_type="bool"),
    # Social (S)
    dict(code="S-COTIZ",     nombre="Pago de cotizaciones al día", categoria="S", peso=2.0, answer_type="bool"),
    dict(code="S-IGUALDAD",  nombre="Política de igualdad e inclusión", categoria="S", peso=1.0, answer_type="bool"),
    dict(code="S-ACC",       nombre="Accidentes laborales últimos 12 meses", categoria="S", peso=1.0, answer_type="number", options_json={"unit":"#"}),
    # Ambiental (E)
    dict(code="E-RESIDUOS",  nombre="Gestión de residuos con gestores autorizados", categoria="E", peso=1.5, answer_type="bool"),
    dict(code="E-ENERGIA",   nombre="Medición del consumo energético anual", categoria="E", peso=1.0, answer_type="number", options_json={"unit":"kWh"}),
    dict(code="E-CUMPL",     nombre="Permisos/Resoluciones ambientales al día", categoria="E", peso=2.0, answer_type="bool"),
]

# ──────────────────────────────── Endpoints ────────────────────────────────────
@router.get("/health")
def health():
    return {"ok": True, "module": "ESG"}

@router.post("/seed")
def seed_criterios(db: Session = Depends(get_db)):
    existentes = {c.code for c in db.query(ESGCriterion).all()}
    nuevos = 0
    for c in CRITERIOS_BASE:
        if c["code"] not in existentes:
            db.add(ESGCriterion(**c))
            nuevos += 1
    if nuevos:
        db.commit()
    total = db.query(ESGCriterion).count()
    return {"ok": True, "nuevos": nuevos, "total": total}

@router.get("/criterios")
def listar_criterios(db: Session = Depends(get_db)):
    criterios = (
        db.query(ESGCriterion)
        .filter(ESGCriterion.activo == True)
        .order_by(ESGCriterion.categoria, ESGCriterion.peso.desc(), ESGCriterion.code)
        .all()
    )
    return [
        {
            "id": c.id,
            "code": c.code,
            "nombre": c.nombre,
            "categoria": c.categoria,
            "peso": c.peso,
            "answer_type": c.answer_type,
            "options": c.options_json,
        }
        for c in criterios
    ]