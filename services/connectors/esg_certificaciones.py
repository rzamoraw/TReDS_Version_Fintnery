# services/connectors/esg_certificaciones.py
from datetime import datetime, date
from typing import List, Optional
from sqlalchemy.orm import Session
from models import EsgCertificacion

def _parse_fecha(fecha_str: Optional[str]) -> Optional[date]:
    if not fecha_str:
        return None
    # admite "YYYY-MM-DD" (input type="date")
    try:
        return datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except Exception:
        return None

def listar_certificaciones(db: Session, rut: str) -> List[EsgCertificacion]:
    return db.query(EsgCertificacion).filter(EsgCertificacion.rut == rut).all()

def agregar_certificacion(
    db: Session,
    rut: str,
    tipo: str,
    emisor: Optional[str] = None,
    valido_hasta: Optional[str] = None,
    enlace: Optional[str] = None,
) -> EsgCertificacion:
    cert = EsgCertificacion(
        rut=rut,
        tipo=tipo.strip(),
        emisor=(emisor or None),
        valido_hasta=_parse_fecha(valido_hasta),
        enlace=(enlace or None),
    )
    db.add(cert)
    db.commit()
    db.refresh(cert)
    return cert

def eliminar_certificacion(db: Session, cert_id: int) -> bool:
    cert = db.query(EsgCertificacion).get(cert_id)
    if not cert:
        return False
    db.delete(cert)
    db.commit()
    return True

# services/connectors/esg_certificaciones.py

async def fetch_esg_certificaciones_por_rut(rut: str, force: bool = False) -> dict:
    """
    Obtiene datos ESG y certificaciones asociadas al RUT indicado.
    TODO: Implementar la lógica de extracción desde la fuente de datos real.
    """
    # Ejemplo estático (luego se reemplaza por llamada a API o BD)
    fake_data = {
        "rut": rut,
        "certificaciones": [
            {
                "tipo": "ISO 9001",
                "emisor": "Bureau Veritas",
                "valido_hasta": "2025-12-31",
                "enlace": "https://ejemplo.com/certificado/iso9001"
            },
            {
                "tipo": "Certificación ESG Oro",
                "emisor": "Sustainalytics",
                "valido_hasta": "2026-06-30",
                "enlace": "https://ejemplo.com/certificado/esgoro"
            }
        ]
    }
    return fake_data