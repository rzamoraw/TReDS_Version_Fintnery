from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi import APIRouter, Request, Form, Depends
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from database import SessionLocal
from models import Financiador
from models import FacturaDB, OfertaFinanciamiento
from datetime import date
from fastapi import HTTPException  # ⬅️ nuevo import

# ---------- Pequeño helper ----------
def _solo_admin(fin: Financiador):
    """Lanza 403 si el usuario NO es admin."""
    if not fin.es_admin:
        raise HTTPException(status_code=403, detail="Solo administradores")

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
    request.session["es_admin"] = financiador.es_admin    # ⬅️ NUEVO
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
    
    # ✔︎ Si no tiene CF cargado HOY → forzamos a cargarlo antes de mostrar el marketplace
    if not financiador.costo_fondos_mensual or financiador.fecha_costo_fondos != date.today():
        return RedirectResponse(url="/financiador/costo-fondos", status_code=303)
    
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

# ----------  ADMINISTRAR USUARIOS (solo admin) ----------
@router.get("/usuarios")
def listar_usuarios(request: Request, db: Session = Depends(get_db)):
    fid = request.session.get("financiador_id")
    if not fid:
        return RedirectResponse("/financiador/login", 303)

    admin = db.query(Financiador).get(fid)
    _solo_admin(admin)

    usuarios = db.query(Financiador).order_by(Financiador.id).all()
    return templates.TemplateResponse(
        "usuarios_financiador.html",
        {
            "request": request,
            "usuarios": usuarios,
            "financiador_nombre": admin.nombre
        }
    )

@router.post("/usuarios/toggle-admin/{user_id}")
def toggle_admin(user_id: int, request: Request, db: Session = Depends(get_db)):
    fid = request.session.get("financiador_id")
    if not fid:
        return RedirectResponse("/financiador/login", 303)

    admin = db.query(Financiador).get(fid)
    _solo_admin(admin)

    usuario = db.query(Financiador).get(user_id)
    if usuario and usuario.id != admin.id:          # evita cambiarte a ti mismo
        usuario.es_admin = not usuario.es_admin
        db.commit()

    return RedirectResponse("/financiador/usuarios", 303)

# -------------------------------
#  Costo de fondos diario
# -------------------------------

@router.get("/costo-fondos")
def form_costo_fondos(request: Request, db: Session = Depends(get_db)):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)

    financiador = db.query(Financiador).filter(Financiador.id == financiador_id).first()
    # ✔︎ Solo el admin puede entrar
    _solo_admin(financiador)        # ⬅️ usa el helper

    return templates.TemplateResponse(
        "costo_fondos.html",
        {
            "request": request,
            "costo_fondos": financiador.costo_fondos_mensual,
            "fecha_costo_fondos": financiador.fecha_costo_fondos,
            "financiador_nombre": financiador.nombre
        }
    )

@router.post("/costo-fondos")
def guardar_costo_fondos(
    request: Request,
    nuevo_costo_mensual: float = Form(...),
    db: Session = Depends(get_db)
):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)
    
    financiador = db.query(Financiador).filter(Financiador.id == financiador_id).first()
    
    # ✔︎ Solo el admin puede guardar
    _solo_admin(financiador)        # ⬅️ usa el helper

    financiador.costo_fondos_mensual = nuevo_costo_mensual
    financiador.fecha_costo_fondos = date.today()
    db.commit()

    # 🔻 redirigimos a donde quieras volver
    return RedirectResponse(url="/financiador/marketplace", status_code=303)

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