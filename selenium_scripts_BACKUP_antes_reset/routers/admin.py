# routers/admin.py
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from database import SessionLocal
from models import (
    FacturaDB,
    OfertaFinanciamiento,
    CondicionesPorPagador,
    Financiador,
    Pagador,
    Proveedor,
)

router = APIRouter()

# ────────────────────────────── DB dependency ──────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ────────────────────────────── Hard reset endpoint ──────────────────────────────
# ⚠️ Este endpoint borra toda la información. Proteger con un chequeo mínimo.

@router.get("/reset")
def resetear_base_de_datos(request: Request, db: Session = Depends(get_db)):
    import os

    # Validar mediante token secreto desde query param
    token_proporcionado = request.query_params.get("token")
    token_secreto = os.getenv("RESET_TOKEN", "midOfficeClaveUltraSecreta")

    if token_proporcionado != token_secreto:
        raise HTTPException(status_code=403, detail="Acceso denegado: token inválido")

    # ⚠️ El orden importa por claves foráneas → borrar primero tablas dependientes
    db.query(OfertaFinanciamiento).delete()
    db.query(FacturaDB).delete()
    db.query(CondicionesPorPagador).delete()
    db.query(Financiador).delete()
    db.query(Pagador).delete()
    db.query(Proveedor).delete()

    db.commit()

    # Redirigimos al login del proveedor tras limpiar
    return RedirectResponse("/proveedor/login", status_code=303)
