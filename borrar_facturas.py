from sqlalchemy.orm import Session
from database import SessionLocal
from models import FacturaDB

def borrar_facturas():
    db: Session = SessionLocal()
    try:
        cantidad = db.query(FacturaDB).delete()
        db.commit()
        print(f"✅ Se eliminaron {cantidad} facturas correctamente.")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al eliminar facturas: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    borrar_facturas()
