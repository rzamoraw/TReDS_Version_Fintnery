import os
import json
import requests
from glob import glob

# Configuraciones
DATA_FOLDER = "facturas_sii/data"
UPLOAD_URL = "http://127.0.0.1:8000/proveedor/facturas/detalle"  # Endpoint que espera una LISTA directamente

# Buscar archivos JSON
json_files = glob(os.path.join(DATA_FOLDER, "detalle_*.json"))

if not json_files:
    print("⚠️ No se encontraron archivos JSON para subir.")
    exit()

# Iterar por cada archivo encontrado
for path in json_files:
    print(f"\n📄 Procesando archivo: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Detectar si es lista directa o anidada
    if isinstance(data, list):
        facturas = data
    else:
        facturas = data.get("dataResp", {}).get("detalles", [])

    if not facturas:
        print("❌ No se encontraron facturas válidas en el archivo.")
        continue

    # Enviar lista de facturas directamente como JSON
    try:
        headers = {"Content-Type": "application/json"}
        response = requests.post(UPLOAD_URL, json=facturas, headers=headers)

        if response.status_code == 200:
            print(f"✅ {len(facturas)} facturas subidas exitosamente.")
        else:
            print(f"❌ Error al subir facturas. Status: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"❌ Excepción al subir facturas desde {path}: {e}")
