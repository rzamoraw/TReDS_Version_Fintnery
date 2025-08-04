# routers/configuracion.py
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import SessionLocal
from models import CondicionesPorPagador, Financiador
from rut_utils import normalizar_rut

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# ────────────────────────────── DB Dependency ──────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ─────────────────────── Ver condiciones por financiador ───────────────────────
@router.get("/condiciones")
def ver_condiciones(request: Request, db: Session = Depends(get_db)):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)

    financiador = db.query(Financiador).get(financiador_id)
    condiciones = (
        db.query(CondicionesPorPagador)
        .filter_by(financiador_id=financiador_id)
        .all()
    )

    return templates.TemplateResponse(
        "condiciones.html",
        {
            "request": request,
            "condiciones": condiciones,
            "financiador_nombre": financiador.nombre  # 🔷 habilita el nombre en base.html
        }
    )

# ─────────────────────── Formulario nueva condición ───────────────────────
@router.get("/nueva-condicion")
def nueva_condicion_form(request: Request):
    if not request.session.get("financiador_id"):
        return RedirectResponse(url="/financiador/login", status_code=303)
    
    return templates.TemplateResponse("nueva_condicion.html", {"request": request})

# ─────────────────────────── Guardar nueva condición ───────────────────────────
@router.post("/nueva-condicion")
def guardar_condicion(
    request: Request,
    rut_pagador: str = Form(...),
    nombre_pagador: str = Form(...),
    spread: float = Form(...),
    dias_anticipacion: int = Form(...),
    comisiones: float = Form(...),
    db: Session = Depends(get_db)
):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)

    financiador = db.query(Financiador).get(financiador_id)
    
    nueva = CondicionesPorPagador(
        rut_pagador=normalizar_rut(rut_pagador),
        nombre_pagador=nombre_pagador,
        spread=spread,
        dias_anticipacion=dias_anticipacion,
        comisiones=comisiones,
        financiador_id=financiador_id,
        nombre_financiador=financiador.nombre
    )
    db.add(nueva)
    db.commit()

    return RedirectResponse(url="/financiador/condiciones", status_code=303)