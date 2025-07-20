from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER
import os
from dotenv import load_dotenv

from database import get_db
from models import Fondo, Financiador
from utils import pwd_context

load_dotenv()

router = APIRouter(prefix="/middle", tags=["Middle Office"])

# Templates
templates = Jinja2Templates(directory="templates")                 # Para login, fondos, etc.
templates_middle = Jinja2Templates(directory="templates/middle")  # Para formularios de registro internos


# ─────────────────────── LOGIN ───────────────────────

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


# ─────────────────────── LISTAR FONDOS ───────────────────────

@router.get("/fondos")
def listar_fondos(request: Request, db: Session = Depends(get_db)):
    if request.cookies.get("middle_auth") != "ok":
        return RedirectResponse(url="/middle/login")
    fondos = db.query(Fondo).all()
    success = request.query_params.get("success")
    return templates.TemplateResponse("fondos_middle.html", {
        "request": request,
        "fondos": fondos,
        "success": "Fondo creado exitosamente." if success else None
    })


# ─────────────────────── CREAR FONDO + ADMIN ───────────────────────

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

    existente = db.query(Financiador).filter_by(usuario=usuario_admin).first()
    if existente:
        return templates.TemplateResponse("crear_fondo.html", {
            "request": request,
            "error": "Ese nombre de usuario ya existe. Usa uno diferente."
        })

    try:
        fondo = Fondo(nombre=nombre_fondo, descripcion=descripcion, activo=True)
        db.add(fondo)
        db.flush()

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
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse("crear_fondo.html", {
            "request": request,
            "error": f"Ocurrió un error al crear el fondo: {str(e)}"
        })


# ─────────────────────── REGISTRAR NUEVO FINANCIADOR ───────────────────────

@router.get("/registrar-financiador")
def mostrar_formulario_registro_financiador(request: Request, db: Session = Depends(get_db)):
    if request.cookies.get("middle_auth") != "ok":
        return RedirectResponse(url="/middle/login", status_code=HTTP_303_SEE_OTHER)

    fondos = db.query(Fondo).filter(Fondo.activo == True).all()
    return templates_middle.TemplateResponse("registro_financiador_middle.html", {
        "request": request,
        "fondos": fondos
    })

@router.post("/registrar-financiador")
def registrar_financiador_desde_middle(
    request: Request,
    nombre: str = Form(...),
    usuario: str = Form(...),
    clave: str = Form(...),
    fondo_id: int = Form(...),
    es_admin: bool = Form(False),
    db: Session = Depends(get_db)
):
    if request.cookies.get("middle_auth") != "ok":
        return RedirectResponse(url="/middle/login", status_code=HTTP_303_SEE_OTHER)

    existente = db.query(Financiador).filter_by(usuario=usuario).first()
    if existente:
        fondos = db.query(Fondo).filter(Fondo.activo == True).all()
        return templates_middle.TemplateResponse("registro_financiador_middle.html", {
            "request": request,
            "fondos": fondos,
            "error": "Este usuario ya existe. Usa otro nombre de usuario."
        })

    hash_clave = pwd_context.hash(clave)
    nuevo = Financiador(
        nombre=nombre,
        usuario=usuario,
        clave_hash=hash_clave,
        fondo_id=fondo_id,
        es_admin=es_admin
    )
    db.add(nuevo)
    db.commit()

    fondos = db.query(Fondo).filter(Fondo.activo == True).all()
    return templates_middle.TemplateResponse("registro_financiador_middle.html", {
        "request": request,
        "fondos": fondos,
        "success": f"Financiador '{nombre}' registrado exitosamente."
    })


# ─────────────────────── ELIMINAR FONDO ───────────────────────

@router.post("/fondos/eliminar")
def eliminar_fondo(request: Request, fondo_id: int = Form(...), db: Session = Depends(get_db)):
    if request.cookies.get("middle_auth") != "ok":
        return RedirectResponse(url="/middle/login", status_code=HTTP_303_SEE_OTHER)

    fondo = db.query(Fondo).filter(Fondo.id == fondo_id).first()
    if fondo:
        db.delete(fondo)
        db.commit()
        return RedirectResponse(url="/middle/fondos?success=Fondo eliminado correctamente", status_code=303)
    else:
        return RedirectResponse(url="/middle/fondos?error=Fondo no encontrado", status_code=303)