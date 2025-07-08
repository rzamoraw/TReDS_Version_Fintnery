from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import SessionLocal
from models import FacturaDB, OfertaFinanciamiento, CondicionesPorPagador, Financiador, Pagador, Proveedor

router = APIRouter()

# DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/admin/reset")
def resetear_base_de_datos(request: Request, db: Session = Depends(get_db)):
    # ⚠️ Borrar primero relaciones dependientes (ofertas, condiciones...)
    db.query(OfertaFinanciamiento).delete()
    db.query(FacturaDB).delete()
    db.query(CondicionesPorPagador).delete()
    db.query(Financiador).delete()
    db.query(Pagador).delete()
    db.query(Proveedor).delete()
    db.commit()

    # Redirige al login del proveedor después del reset
    return RedirectResponse(url="/proveedor/login", status_code=303)
