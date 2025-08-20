# services/connectors/retc.py
import httpx
from typing import List, Dict, Any

# Recurso CKAN oficial del dataset "Establecimientos" (RETC/MMA)
RETC_ESTABLECIMIENTOS_RESOURCE_ID = "d1682353-3e5f-4100-9a53-f4b9650e2984"
CKAN_DATASTORE_SEARCH = "https://datosretc.mma.gob.cl/api/3/action/datastore_search"

EVIDENCIA_URL = (
    "https://datosretc.mma.gob.cl/dataset/establecimientos"
    "/resource/d1682353-3e5f-4100-9a53-f4b9650e2984"
)

async def fetch_establecimientos_por_razon_social(
    razon_social_exacta: str,
    limit: int = 100,
) -> Dict[str, Any]:
    """
    Consulta RETC (CKAN) por establecimientos usando match exacto del campo 'Razón social'.
    No inventa nada: si no hay filas, devuelve {"ok": True, "matches": []}.
    """
    razon = (razon_social_exacta or "").strip()
    if not razon:
        return {"ok": True, "matches": [], "evidencia_url": EVIDENCIA_URL}

    params = {
        "resource_id": RETC_ESTABLECIMIENTOS_RESOURCE_ID,
        # match exacto por campo (funciona mejor que q= en este recurso)
        "filters": '{"Razón social":"' + razon.replace('"', '\\"') + '"}',
        "limit": str(limit),
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(CKAN_DATASTORE_SEARCH, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "matches": [],
            "evidencia_url": EVIDENCIA_URL,
        }

    result = data.get("result", {})
    records: List[Dict[str, Any]] = result.get("records", []) or []

    # Normalización liviana (sin datos personales, solo info pública del recurso)
    matches = [
        {
            "rut": razon,
            "razon_social": rec.get("Razón social"),
            "establecimiento": rec.get("Nombre de Establecimiento"),
            "region": rec.get("Región"),
            "provincia": rec.get("Provincia"),
            "comuna": rec.get("Comuna"),
            "rubro": rec.get("Rubro RETC"),
            "direccion": rec.get("Calle"),
        }
        for rec in records
    ]

    return {
        "ok": True,
        "total": len(matches),
        "matches": matches,
        "evidencia_url": EVIDENCIA_URL,  # enlace oficial al recurso
    }