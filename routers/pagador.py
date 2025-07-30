# routers/pagador.py
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
templates_middle = Jinja2Templates(directory="templates/middle")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ───────────── DB Dependency ─────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ───────────── Registro / Login ─────────────
@router.get("/registro")
def mostrar_formulario_registro(request: Request):
    return templates_middle.TemplateResponse("registro_pagador.html", {"request": request})


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
        return templates.TemplateResponse(
            "login_pagador.html",
            {"request": request, "error": "Usuario o clave incorrectos"}
        )
    request.session["pagador_id"] = pagador.id
    return RedirectResponse(url="/pagador/facturas", status_code=303)


# ───────────── Inicio ─────────────
@router.get("/inicio")
def inicio_pagador(request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    pagador = db.query(Pagador).get(pagador_id)
    pagador_nombre = pagador.nombre if pagador else ""

    return templates.TemplateResponse(
        "inicio_pagador.html",
        {
            "request": request,
            "pagador_id": pagador_id,
            "pagador_nombre": pagador_nombre
        }
    )


# ───────────── Logout ─────────────
@router.get("/logout")
def logout_pagador(request: Request):
    request.session.clear()
    return RedirectResponse(url="/pagador/login", status_code=303)


# ───────────── Ver Facturas ─────────────
@router.get("/facturas")
def ver_facturas_pagador(request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    pagador = db.query(Pagador).get(pagador_id)
    if not pagador:
        request.session.clear()
        return RedirectResponse(url="/pagador/login", status_code=303)

    facturas_pendientes = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == pagador.rut,
        FacturaDB.estado_dte == "Confirmación solicitada al pagador"
    ).all()

    facturas_gestionadas = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == pagador.rut,
        FacturaDB.estado_dte.in_([
            "Confirmada por pagador",
            "Rechazada por pagador",
            "Enviado a confirming",
            "Confirming adjudicado"
        ])
    ).all()

    return templates.TemplateResponse(
        "facturas_pagador.html",
        {
            "request": request,
            "facturas_pendientes": facturas_pendientes,
            "facturas_gestionadas": facturas_gestionadas,
            "pagador_nombre": pagador.nombre
        }
    )


# ───────────── Editar Vencimiento ─────────────
@router.post("/editar-vencimiento/{folio}")
def editar_vencimiento_pagador(
    folio: int,
    request: Request,
    nueva_fecha_vencimiento: str = Form(...),
    db: Session = Depends(get_db)
):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(FacturaDB.folio == folio).first()
    if factura:
        factura.fecha_vencimiento = datetime.strptime(nueva_fecha_vencimiento, "%Y-%m-%d").date()
        db.commit()

    return RedirectResponse(url="/pagador/facturas?msg=fecha_actualizada", status_code=303)

# ───────────── Confirmar / Rechazar ─────────────
@router.post("/confirmar-factura/{folio}")
def confirmar_factura(folio: int, request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(FacturaDB.folio == folio).first()

    if factura is None:
        print(f"❌ Factura con folio {folio} no encontrada.")
        return RedirectResponse(url="/pagador/facturas?msg=error", status_code=303)

    if factura.estado_dte != "Confirmación solicitada al pagador":
        print(f"❌ Estado no válido para confirmación. Estado actual: {factura.estado_dte}")
        return RedirectResponse(url="/pagador/facturas?msg=error_estado", status_code=303)

    factura.estado_dte = "Confirmada por pagador"
    try:
        db.flush()   # 💥 Forzar escritura inmediata
        db.commit()
        print(f"✅ Factura {folio} confirmada y guardada en DB")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al confirmar factura {folio}: {e}")

    return RedirectResponse(url="/pagador/facturas?msg=confirmada", status_code=303)


@router.post("/rechazar-factura/{folio}")
def rechazar_factura(
    folio: int,
    request: Request,
    db: Session = Depends(get_db)
):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(FacturaDB.folio == folio).first()
    if factura:
        factura.estado_dte = "Rechazada por pagador"
        db.commit()

    return RedirectResponse(url="/pagador/facturas?msg=rechazada", status_code=303)