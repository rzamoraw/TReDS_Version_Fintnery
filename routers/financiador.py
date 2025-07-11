from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from database import SessionLocal
from models import Financiador
from models import FacturaDB, OfertaFinanciamiento

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
def inicio_financiador(request: Request, db: Session = Depends(get_db)):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)
    
    financiador = db.query(Financiador).filter(Financiador.id == financiador_id).first()
    financiador_nombre = financiador.nombre if financiador else "Desconocido"

    return templates.TemplateResponse("inicio_financiador.html", {
        "request": request,
        "financiador_id": financiador_id,
        "financiador_nombre": financiador_nombre
    })

# -------------------------------
#  Marketplace del financiador
# -------------------------------
@router.get("/marketplace")
def ver_marketplace(
    request: Request,
    db: Session = Depends(get_db)
):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)
    
    financiador = db.query(Financiador).filter(Financiador.id == financiador_id).first()
    financiador_nombre = financiador.nombre if financiador else "Desconocido"


    # 1️⃣  Solo facturas en "Confirming solicitado"
    facturas = (
        db.query(FacturaDB)
        .filter(
            FacturaDB.estado_dte == "Confirming solicitado",
            FacturaDB.financiador_adjudicado.is_(None)
        )
        .all()
    )

    # 2️⃣  Ofertas propias (para saber si ya ofertó)
    ofertas_propias = {
        o.factura_id: o
        for o in db.query(OfertaFinanciamiento)
                   .filter_by(financiador_id=financiador_id)
                   .all()
    }

    return templates.TemplateResponse(
        "marketplace_financiador.html",        # ⬅️  NUEVO template
        {
            "request": request,
            "facturas": facturas,
            "ofertas_propias": ofertas_propias,
            "financiador_nombre": financiador_nombre
        }
    )

# -------------------------------
#  Costo de fondos diario
# -------------------------------

@router.get("/costo-fondos")
def form_costo_fondos(request: Request, db: Session = Depends(get_db)):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)

    financiador = db.query(Financiador).filter(Financiador.id == financiador_id).first()
    return templates.TemplateResponse(
        "costo_fondos.html",
        {
            "request": request,
            "costo_fondos": financiador.costo_fondos,
            "financiador_nombre": financiador.nombre
        }
    )

@router.post("/costo-fondos")
def guardar_costo_fondos(
    request: Request,
    nuevo_costo: float = Form(...),
    db: Session = Depends(get_db)
):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)

    financiador = db.query(Financiador).filter(Financiador.id == financiador_id).first()
    financiador.costo_fondos = nuevo_costo
    db.commit()

# -------------------------------
#  Ofertas del FInanciador
# -------------------------------
@router.get("/ofertar/{factura_id}")
def mostrar_formulario_oferta(
    factura_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)

    financiador = db.query(Financiador).filter(Financiador.id == financiador_id).first()
    financiador_nombre = financiador.nombre if financiador else "Desconocido"

    factura = db.query(FacturaDB).filter(FacturaDB.id == factura_id).first()
    if not factura:
        return templates.TemplateResponse("error.html", {"request": request, "mensaje": "Factura no encontrada"})

    return templates.TemplateResponse("ofertar.html", {
        "request": request,
        "factura": factura,
        "financiador_nombre": financiador_nombre
    })
  
# -------------------------------
#  Registrar Ofertas del Financiador
# -------------------------------
@router.post("/registrar-oferta/{factura_id}")
def registrar_oferta(
    factura_id: int,
    request: Request,
    tasa_interes: float = Form(...),
    dias_anticipacion: int = Form(...),
    db: Session = Depends(get_db)
):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)

    nueva = OfertaFinanciamiento(
        factura_id=factura_id,
        financiador_id=financiador_id,
        tasa_interes=tasa_interes,
        dias_anticipacion=dias_anticipacion,
        estado="Oferta realizada"
    )
    db.add(nueva)
    db.commit()

    return RedirectResponse(url="/financiador/costo-fondos?msg=ok", status_code=303)