import json
import requests
from datetime import datetime

# ---------- Leer cookies ----------
with open("facturas_sii/cookies/cookies.json", "r") as f:
    cookies_list = json.load(f)
cookies = {cookie["name"]: cookie["value"] for cookie in cookies_list}

# ---------- Inputs ----------
rut_completo = input("🔐 Ingrese su RUT completo (sin guion, con DV, ej: 76262370K): ").strip().upper()
periodo = input("📅 Ingrese el periodo (formato YYYY-MM, Ej: 2025-07): ").strip()

# ---------- Validación RUT ----------
def normalizar_rut(rut_input):
    rut_input = rut_input.replace(".", "").replace("-", "").upper().strip()
    if not rut_input[:-1].isdigit() or rut_input[-1] not in "0123456789K":
        raise ValueError("❌ RUT inválido. Debe tener dígito verificador.")
    return rut_input[:-1], rut_input[-1]

rut, dv = normalizar_rut(rut_completo)

# ---------- Cargar resumen ----------
resumen_path = f"facturas_sii/data/resumen_{rut}_{periodo}.json"
try:
    with open(resumen_path, "r") as f:
        resumen = json.load(f)
except FileNotFoundError:
    print(f"❌ Archivo resumen no encontrado: {resumen_path}")
    exit()

# ---------- Obtener total facturas tipo 33 ----------
dtes_33 = [d for d in resumen["data"]["resumenDte"] if d["tipoDoc"] == 33]
if not dtes_33:
    print("⚠️  No se encontraron facturas tipo 33 en el periodo indicado.")
    exit()

print(f"📄 Total facturas electrónicas (tipo 33) encontradas: {dtes_33[0]['totalDoc']}")

# ---------- Consultar detalle (página 1 por ahora) ----------
headers = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://www4.sii.cl",
    "Referer": "https://www4.sii.cl/consemitidosinternetui/",
    "User-Agent": "Mozilla/5.0",
}

payload = {
    "metaData": {
        "namespace": "cl.sii.sdi.lob.diii.consemitidos.data.api.interfaces.FacadeService/getDetalle",
        "conversationId": cookies.get("CSESSIONID", ""),
        "transactionId": "detalle-test-001",
        "page": 1
    },
    "data": {
        "periodo": periodo,
        "rutContribuyente": rut,
        "dvContribuyente": dv,
        "tipoDte": 33,
        "operacion": 1,
        "seccion": "S1",
        "refNCD": 0
    }
}

print("📥 Consultando detalle de DTE tipo 33...")
res = requests.post(
    "https://www4.sii.cl/consemitidosinternetui/services/data/facadeService/getDetalle",
    headers=headers,
    cookies=cookies,
    json=payload
)

try:
    detalle = res.json()
    dtes = detalle["data"]["detalles"]
    print(f"✅ Se recibieron {len(dtes)} documentos en el detalle.")
    print("\n🧾 Ejemplo primer documento:")
    print(json.dumps(dtes[0], indent=2, ensure_ascii=False))  # muestra solo el primero
except Exception as e:
    print("❌ Error al procesar detalle:", e)
    print("📄 Contenido bruto:", res.text[:1000])
