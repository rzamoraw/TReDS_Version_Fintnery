import sqlite3
from pathlib import Path

DB = "treds.db"

if not Path(DB).exists():
    raise SystemExit(f"❌  No se encontró {DB} en este directorio.")

conn = sqlite3.connect(DB)
cur = conn.cursor()

try:
    # Intentamos agregar la columna
    cur.execute("ALTER TABLE ofertas_financiamiento ADD COLUMN precio_cesion FLOAT")
    print("✅  Columna 'precio_cesion' agregada con éxito.")
except sqlite3.OperationalError as e:
    # Ya existía o la tabla no está, imprimimos el motivo
    print(f"⚠️  No se pudo agregar la columna: {e}")

conn.commit()
conn.close()