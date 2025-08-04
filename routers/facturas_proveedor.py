from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import date

from database import SessionLocal
from models import FacturaDB, Proveedor
from rut_utils import normalizar_rut

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Ver formulario + facturas ya cargadas
@router.get("/facturas")
def ver_facturas_proveedor(request: Request, db: Session = Depends(get_db)):
    proveedor_id = request.session.get("proveedor_id")
    if not proveedor_id:
        return RedirectResponse(url="/proveedor/login", status_code=303)
    
    facturas = db.query(FacturaDB).filter(FacturaDB.proveedor_id == proveedor_id).all()
    return templates.TemplateResponse("facturas.html", {
        "request": request,
        "facturas": facturas
    })

# Subir nueva factura
@router.post("/facturas")
def cargar_factura(
    request: Request,
    rut_receptor: str = Form(...),
    razon_social_receptor: str = Form(...),
    tipo_dte: str = Form(...),
    folio: int = Form(...),
    monto: int = Form(...),
    fecha_emision: date = Form(...),
    fecha_vencimiento: date = Form(...),
    db: Session = Depends(get_db)
):
    proveedor_id = request.session.get("proveedor_id")
    if not proveedor_id:
        return RedirectResponse(url="/proveedor/login", status_code=303)

    proveedor = db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
    if not proveedor:
        return RedirectResponse(url="/proveedor/login", status_code=303)
    
    # 💡 Normalizar ambos RUTs
    rut_emisor = normalizar_rut(proveedor.rut)
    rut_receptor = normalizar_rut(rut_receptor)

    # 🚩 Validar si ya existe una factura con ese folio y rut_emisor
    existe = db.query(FacturaDB).filter_by(
        rut_emisor=proveedor.rut,
        rut_receptor=rut_receptor,
        folio=folio
    ).first()

    if existe:
        return templates.TemplateResponse("facturas.html", {
            "request": request,
            "facturas": db.query(FacturaDB).filter(FacturaDB.proveedor_id == proveedor_id).all(),
            "mensaje": f"⚠️ Ya existe una factura con folio {folio} para ese receptor."
        })

    nueva_factura = FacturaDB(
        rut_emisor=proveedor.rut,
        razon_social_emisor=proveedor.nombre,
        rut_receptor=rut_receptor,
        razon_social_receptor=razon_social_receptor,
        tipo_dte=tipo_dte,
        folio=folio,
        monto=monto,
        fecha_emision=fecha_emision,
        fecha_vencimiento=fecha_vencimiento,
        estado_dte="Cargada",
        proveedor_id=proveedor_id
    )
    db.add(nueva_factura)
    db.commit()
    return RedirectResponse(url="/proveedor/facturas", status_code=303)

