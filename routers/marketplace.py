from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import SessionLocal
from models import FacturaDB

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# DB session dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Marketplace general: muestra facturas con confirming solicitado
@router.get("/marketplace-general")
def ver_marketplace_general(request: Request, db: Session = Depends(get_db)):
    facturas = db.query(FacturaDB).filter(FacturaDB.estado_dte == "Confirming solicitado").all()

    return templates.TemplateResponse("marketplace_general.html", {
        "request": request,
        "facturas": facturas
    })
