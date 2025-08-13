# routers/pagador_esgcert.py

from fastapi import APIRouter, HTTPException
from services.connectors import esg_certificaciones

router = APIRouter(
    prefix="/pagador/esg",
    tags=["Pagador ESG & Certificaciones"]
)


@router.get("/{rut}")
async def obtener_esg_y_certificaciones(rut: str, force: bool = False):
    """
    Retorna las certificaciones y datos ESG de un pagador
    a partir de su RUT.
    """
    try:
        data = await esg_certificaciones.fetch_esg_certificaciones_por_rut(rut, force=force)
        if not data:
            raise HTTPException(status_code=404, detail="No se encontraron certificaciones ESG para este RUT.")
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    