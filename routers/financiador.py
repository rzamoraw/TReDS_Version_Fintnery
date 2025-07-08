from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from database import SessionLocal
from models import Financiador
from models import FacturaDB

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
    return templates.TemplateResponse("registro_financiador.html", {"request": request})

@router.post("/registro")
def registrar_financiador(
    request: Request,
    nombre: str = Form(...),
    usuario: str = Form(...),
    clave: str = Form(...),
    db: Session = Depends(get_db)
):
    clave_hash = pwd_context.hash(clave)
    nuevo = Financiador(nombre=nombre, usuario=usuario, clave_hash=clave_hash)
    db.add(nuevo)
    db.commit()
    return RedirectResponse(url="/financiador/login", status_code=303)

@router.get("/login")
def mostrar_formulario_login(request: Request):
    return templates.TemplateResponse("login_financiador.html", {"request": request})

@router.post("/login")
def login_financiador(
    request: Request,
    usuario: str = Form(...),
    clave: str = Form(...),
    db: Session = Depends(get_db)
):
    financiador = db.query(Financiador).filter(Financiador.usuario == usuario).first()
    if not financiador or not pwd_context.verify(clave, financiador.clave_hash):
        return templates.TemplateResponse("login_financiador.html", {
            "request": request,
            "error": "Usuario o clave incorrectos"
        })
    
    request.session["financiador_id"] = financiador.id
    return RedirectResponse(url="/financiador/inicio", status_code=303)

@router.get("/inicio")
def inicio_financiador(request: Request):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)
    
    return templates.TemplateResponse("inicio_financiador.html", {
        "request": request,
        "financiador_id": financiador_id
    })

# Ruta marketplace
@router.get("/marketplace")
def ver_marketplace(request: Request, db: Session = Depends(get_db)):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)

    facturas_confirmadas = db.query(FacturaDB).filter(FacturaDB.estado_dte == "Confirmada por pagador").all()

    return templates.TemplateResponse("marketplace.html", {
        "request": request,
        "facturas": facturas_confirmadas
    })