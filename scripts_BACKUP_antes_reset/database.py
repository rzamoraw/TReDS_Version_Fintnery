from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# ✅ Conexión actual a SQLite (puedes migrar a PostgreSQL fácilmente después)
SQLALCHEMY_DATABASE_URL = "sqlite:///./treds.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}  # Requerido solo para SQLite
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base declarativa para los modelos
Base = declarative_base()

# ✅ Función para inyectar la sesión en las rutas con Depends(get_db)
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
