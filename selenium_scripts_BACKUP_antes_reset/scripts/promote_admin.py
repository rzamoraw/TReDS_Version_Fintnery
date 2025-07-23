#!/usr/bin/env python3
import sys
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Financiador

def main():
    if len(sys.argv) != 3:
        print("Uso: promote_admin.py <usuario> <1|0>")
        sys.exit(1)

    usuario = sys.argv[1]
    nuevo_estado = bool(int(sys.argv[2]))

    db: Session = SessionLocal()
    financiador = db.query(Financiador).filter_by(usuario=usuario).first()

    if not financiador:
        print(f"❌ Financiador con usuario '{usuario}' no encontrado.")
        return

    financiador.es_admin = nuevo_estado
    db.commit()
    estado_str = "ADMINISTRADOR" if nuevo_estado else "USUARIO NORMAL"
    print(f"✅ Usuario '{usuario}' ahora tiene rol: {estado_str}")

if __name__ == "__main__":
    main()
    