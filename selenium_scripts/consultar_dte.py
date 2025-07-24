import json
import requests
from datetime import datetime

# ---------- Leer cookies desde archivo ----------
with open("facturas_sii/cookies/cookies.json", "r") as f:
    cookies_list = json.load(f)
cookies = {cookie["name"]: cookie["value"] for cookie in cookies_list}

# ---------- Inputs del usuario ----------
rut_completo = input("🔐 Ingrese su RUT completo (sin guion, con DV, ej: 76262370K): ").strip().upper()
periodo = input("📅 Ingrese el periodo (formato YYYY-MM, Ej: 2025-07): ").strip()

# ---------- Validar y dividir RUT ----------
def normalizar_rut(rut_input):
    rut_input = rut_input.replace(".", "").replace("-", "").upper().strip()
    if not rut_input[:-1].isdigit() or rut_input[-1] not in "0123456789K":
        raise ValueError("❌ RUT inválido. Debe tener dígito verificador.")
    return rut_input[:-1], rut_input[-1]

rut, dv = normalizar_rut(rut_completo)

# ---------- Preparar headers y payload ----------
headers = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://www4.sii.cl",
    "Referer": "https://www4.sii.cl/consemitidosinternetui/",
    "User-Agent": "Mozilla/5.0",
}

payload = {
    "metaData": {
        "namespace": "cl.sii.sdi.lob.diii.consemitidos.data.api.interfaces.FacadeService/getResumen",
        "conversationId": cookies.get("CSESSIONID", ""),
        "transactionId": "resumen-test-001"
        # ❌ NO poner "page"
    },
    "data": {
        "periodo": periodo,
        "rutContribuyente": rut,
        "dvContribuyente": dv,
        "operacion": 1
    }
}

# ---------- Hacer request al SII ----------
print("📥 Consultando resumen de ventas...")
res = requests.post(
    "https://www4.sii.cl/consemitidosinternetui/services/data/facadeService/getResumen",
    headers=headers,
    cookies=cookies,
    json=payload
)

# ---------- Procesar respuesta ----------
try:
    resumen = res.json()
    resumen_dtes = resumen["data"]["resumenDte"]
    print(f"✅ Resumen recibido. Documentos disponibles: {len(resumen_dtes)}")

    # Guardar resultado en archivo JSON
    resumen_path = f"facturas_sii/data/resumen_{rut}_{periodo}.json"
    with open(resumen_path, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)

    print(f"📄 Archivo guardado como {resumen_path}")

except Exception as e:
    print("❌ Error al procesar el resumen:", e)
    print("📄 Contenido crudo recibido:", res.text[:1000])


