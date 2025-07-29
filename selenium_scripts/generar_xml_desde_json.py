import os
import json
import zipfile
from xml.etree.ElementTree import Element, SubElement, ElementTree
from datetime import datetime

# Parámetros base
RUT = "76262370"
PERIODO = "2025-07"
json_path = f"facturas_sii/data/detalle_{RUT}_{PERIODO}.json"
output_folder = f"descargadas_sii_{RUT}"
zip_name = f"facturas_sii_{RUT}.zip"

# Crear carpeta si no existe
os.makedirs(output_folder, exist_ok=True)

# Leer JSON
with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

facturas = data.get("dataResp", {}).get("detalles", [])

for factura in facturas:
    folio = str(factura["folio"])
    fecha = factura.get("fechaEmisionA", "2025-07-01")
    monto = str(factura["mntTotal"])
    rut_emisor = factura["rutEmisor"]
    rut_receptor = f'{factura["rutReceptor"]}-{factura["dvReceptor"]}'
    rzn_emisor = factura.get("rznSocEmisor", "Desconocido")
    rzn_receptor = factura.get("rznSocRecep", "Desconocido")

    # Generar XML básico
    dte = Element("DTE")
    documento = SubElement(dte, "Documento")
    SubElement(documento, "TipoDTE").text = "33"
    SubElement(documento, "Folio").text = folio
    SubElement(documento, "FchEmis").text = fecha
    SubElement(documento, "FchVenc").text = fecha
    SubElement(documento, "RUTEmisor").text = rut_emisor
    SubElement(documento, "RUTRecep").text = rut_receptor
    SubElement(documento, "RznSoc").text = rzn_emisor
    SubElement(documento, "RznSocRecep").text = rzn_receptor
    SubElement(documento, "MntTotal").text = monto

    # Guardar XML
    xml_path = os.path.join(output_folder, f"factura_{folio}.xml")
    tree = ElementTree(dte)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)

# Crear ZIP
with zipfile.ZipFile(zip_name, "w") as zipf:
    for filename in os.listdir(output_folder):
        if filename.endswith(".xml"):
            zipf.write(os.path.join(output_folder, filename), arcname=filename)

print(f"✅ Se generaron {len(facturas)} archivos XML en {output_folder}")
print(f"📦 ZIP creado: {zip_name}")