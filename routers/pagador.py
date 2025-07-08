from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from database import SessionLocal
from models import Pagador, FacturaDB
from datetime import datetime

router = APIRouter()
templates = Jinja2Templates(directory="templates")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/registro")
def mostrar_formulario_registro(request: Request):
    return templates.TemplateResponse("registro_pagador.html", {"request": request})

@router.post("/registro")
def registrar_pagador(
    request: Request,
    nombre: str = Form(...),
    rut: str = Form(...),
    usuario: str = Form(...),
    clave: str = Form(...),
    db: Session = Depends(get_db)
):
    clave_hash = pwd_context.hash(clave)
    nuevo = Pagador(nombre=nombre, rut=rut, usuario=usuario, clave_hash=clave_hash)
    db.add(nuevo)
    db.commit()
    return RedirectResponse(url="/pagador/login", status_code=303)

@router.get("/login")
def mostrar_formulario_login(request: Request):
    return templates.TemplateResponse("login_pagador.html", {"request": request})

@router.post("/login")
def login_pagador(
    request: Request,
    usuario: str = Form(...),
    clave: str = Form(...),
    db: Session = Depends(get_db)
):
    pagador = db.query(Pagador).filter(Pagador.usuario == usuario).first()
    if not pagador or not pwd_context.verify(clave, pagador.clave_hash):
        return templates.TemplateResponse("login_pagador.html", {
            "request": request,
            "error": "Usuario o clave incorrectos"
        })
    
    request.session["pagador_id"] = pagador.id
    return RedirectResponse(url="/pagador/facturas", status_code=303)

@router.get("/inicio")
def inicio_pagador(request: Request):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)
    
    return templates.TemplateResponse("inicio_pagador.html", {
        "request": request,
        "pagador_id": pagador_id
    })

# NUEVO: Logout
@router.get("/logout")
def logout_pagador(request: Request):
    request.session.clear()
    return RedirectResponse(url="/pagador/login", status_code=303)

# NUEVO: Ver facturas emitidas al pagador
@router.get("/facturas")
def ver_facturas_pagador(request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    pagador = db.query(Pagador).filter(Pagador.id == pagador_id).first()
    if not pagador:
        request.session.clear()
        return RedirectResponse(url="/pagador/login", status_code=303)
    facturas = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == pagador.rut,
        FacturaDB.estado_dte == "Confirmación solicitada al pagador"
    ).all()

    return templates.TemplateResponse("facturas_pagador.html", {
        "request": request,
        "facturas": facturas
    })

# NUEVO: Editar fecha de vencimiento
@router.post("/editar-vencimiento/{factura_id}")
def editar_vencimiento_pagador(
    factura_id: int,
    request: Request,
    nueva_fecha_vencimiento: str = Form(...),
    db: Session = Depends(get_db)
):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(FacturaDB.id == factura_id).first()
    if factura and factura.estado_dte == "Confirmación solicitada al pagador":
        factura.fecha_vencimiento = datetime.strptime(nueva_fecha_vencimiento, "%Y-%m-%d").date()
        db.commit()

    return RedirectResponse(url="/pagador/facturas?msg=fecha_actualizada", status_code=303)

# NUEVO: Confirmar factura
@router.post("/confirmar-factura/{factura_id}")
def confirmar_factura(factura_id: int, request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(FacturaDB.id == factura_id).first()
    if factura:
        # Solo confirmar si está pendiente o en solicitud
        if factura.estado_dte not in ["Confirmada por pagador", "Confirming adjudicado"]:
            factura.estado_dte = "Confirmada por pagador"
            db.commit()

    return RedirectResponse(url="/pagador/facturas", status_code=303)

# NUEVO: Rechazar factura
@router.post("/rechazar-factura/{factura_id}")
def rechazar_factura(factura_id: int, request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(FacturaDB.id == factura_id).first()
    if factura:
        factura.estado_dte = "Rechazada por pagador"
        db.commit()

    return RedirectResponse(url="/pagador/facturas", status_code=303)

