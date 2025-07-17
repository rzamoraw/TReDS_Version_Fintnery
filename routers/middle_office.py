from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates
import os
from dotenv import load_dotenv

from database import get_db
from models import Fondo, Financiador
from utils import pwd_context

load_dotenv()

router = APIRouter(prefix="/middle", tags=["Middle Office"])
templates = Jinja2Templates(directory="templates")

# Validación con clave maestra
@router.get("/login")
def login_middle(request: Request):
    return templates.TemplateResponse("login_middle.html", {"request": request})

@router.post("/login")
def validar_acceso(request: Request, clave: str = Form(...)):
    clave_maestra = os.getenv("ADMIN_ACCESS_KEY")
    if clave == clave_maestra:
        response = RedirectResponse(url="/middle/fondos", status_code=303)
        response.set_cookie("middle_auth", "ok")
        return response
    return templates.TemplateResponse("login_middle.html", {"request": request, "error": "Clave incorrecta"})

# Listado de fondos existentes
@router.get("/fondos")
def listar_fondos(request: Request, db: Session = Depends(get_db)):
    if request.cookies.get("middle_auth") != "ok":
        return RedirectResponse(url="/middle/login")
    fondos = db.query(Fondo).all()
    success = request.query_params.get("success")
    return templates.TemplateResponse("fondos_middle.html", {"request": request, "fondos": fondos, "success": "Fondo creado exitosamente." if success else None})

# Formulario de creación de fondo + admin
@router.get("/fondos/crear")
def mostrar_formulario_creacion_fondo(request: Request):
    if request.cookies.get("middle_auth") != "ok":
        return RedirectResponse(url="/middle/login")
    return templates.TemplateResponse("crear_fondo.html", {"request": request})

@router.post("/fondos/crear")
def crear_fondo(
    request: Request,
    nombre_fondo: str = Form(...),
    descripcion: str = Form(...),
    nombre_admin: str = Form(...),
    usuario_admin: str = Form(...),
    clave_admin: str = Form(...),
    db: Session = Depends(get_db)
):
    if request.cookies.get("middle_auth") != "ok":
        return RedirectResponse(url="/middle/login")

    fondo = Fondo(nombre=nombre_fondo, descripcion=descripcion, activo=True)
    db.add(fondo)
    db.commit()
    db.refresh(fondo)

    admin = Financiador(
        nombre=nombre_admin,
        usuario=usuario_admin,
        clave_hash=pwd_context.hash(clave_admin),
        fondo_id=fondo.id,
        es_admin=True
    )
    db.add(admin)
    db.commit()

    return RedirectResponse(url="/middle/fondos?success=1", status_code=303)