import json
import os
import requests
from glob import glob

# Ruta de los archivos JSON exportados por detalle_dte.py
DATA_FOLDER = "facturas_sii/data"
UPLOAD_URL = "http://127.0.0.1:8000/proveedor/facturas"

# Detectar archivos de facturas descargadas
json_files = glob(os.path.join(DATA_FOLDER, "detalle_*.json"))

if not json_files:
    print("⚠️ No se encontraron archivos JSON para subir.")
    exit()

for path in json_files:
    print(f"📄 Procesando archivo: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Manejar si es lista directa o anidada
    if isinstance(data, list):
        facturas = data
    else:
        facturas = data.get("dataResp", {}).get("detalles", [])

    if not facturas:
        print("❌ No se encontraron facturas válidas en el archivo.")
        continue

    for factura in facturas:
        # Validación mínima
        if not factura.get("folio") or not factura.get("fechaEmisionA") or not factura.get("mntTotal"):
            print(f"❌ Factura inválida: {factura}")
            continue

        # Construcción de XML básico
        folio = factura["folio"]
        fecha = factura["fechaEmisionA"]
        monto = factura["mntTotal"]
        rut_emisor = factura.get("rutEmisor", "76262370")
        rut_receptor = str(factura.get("rutReceptor", "")) + str(factura.get("dvReceptor", ""))
        razon_social_emisor = factura.get("rznSocEmisor", "Proveedor Genérico")
        razon_social_receptor = factura.get("rznSocRecep", "Pagador Genérico")

        xml = f"""<?xml version="1.0" encoding="ISO-8859-1"?>
<Factura>
    <Folio>{folio}</Folio>
    <Emisor>
        <RUTEmisor>{rut_emisor}</RUTEmisor>
        <RazonSocialEmisor>{razon_social_emisor}</RazonSocialEmisor>
    </Emisor>
    <Receptor>
        <RUTReceptor>{rut_receptor}</RUTReceptor>
        <RazonSocialReceptor>{razon_social_receptor}</RazonSocialReceptor>
    </Receptor>
    <FechaEmision>{fecha}</FechaEmision>
    <MontoTotal>{monto}</MontoTotal>
</Factura>"""

        files = {
            "files": ("factura.xml", xml.encode("ISO-8859-1"), "application/xml")
        }

        try:
            print(f"\n📤 Enviando factura {folio} con XML:\n{xml}\n")
            response = requests.post(UPLOAD_URL, files=files)
            if response.status_code == 200:
                print(f"✅ Factura {folio} subida exitosamente.")
            else:
                print(f"❌ Error al subir factura {folio}. Status: {response.status_code}")
        except Exception as e:
            print(f"❌ Excepción al subir factura {folio}: {e}")
