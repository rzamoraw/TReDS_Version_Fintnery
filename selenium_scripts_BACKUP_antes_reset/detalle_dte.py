import json
import requests
import os


# ------------------ Ruta robusta al JSON ------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cookies_path = os.path.join(BASE_DIR, "selenium_scripts", "facturas_sii", "cookies", "cookies.json")

with open(cookies_path, "r") as f:
    cookies_list = json.load(f)

# ------------------ Leer cookies ------------------
with open("facturas_sii/cookies/cookies.json", "r") as f:
    cookies_list = json.load(f)

cookies = {cookie["name"]: cookie["value"] for cookie in cookies_list}

# ------------------ Inputs ------------------
rut_completo = input("🔐 Ingrese su RUT completo (sin guion, con DV, ej: 76262370K): ").strip().upper()
periodo = input("📅 Ingrese el periodo (formato YYYY-MM, Ej: 2025-07): ").strip()

# ------------------ Normalizar RUT ------------------
def normalizar_rut(rut_input):
    rut_input = rut_input.replace(".", "").replace("-", "").upper().strip()
    if not rut_input[:-1].isdigit() or rut_input[-1] not in "0123456789K":
        raise ValueError("❌ RUT ingresado no es válido. Debe tener dígito verificador.")
    return rut_input[:-1], rut_input[-1]

rut, dv = normalizar_rut(rut_completo)

# ------------------ Headers y Payload ------------------
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
        "transactionId": "detalle-tx",
        "page": {}
    },
    "data": {
        "periodo": periodo,
        "rut": rut,
        "dv": dv,
        "tipoDoc": 33,
        "operacion": 1
    }
}

# ------------------ Request ------------------
print("📥 Consultando detalle completo de facturas tipo 33...")
res = requests.post(
    "https://www4.sii.cl/consemitidosinternetui/services/data/facadeService/getDetalle",
    headers=headers,
    cookies=cookies,
    json=payload
)

try:
    data = res.json()
    detalles = data.get("data", {}).get("detalles", [])

    if not detalles:
        print("⚠️ No se encontraron detalles de facturas.")
    else:
        print(f"✅ Se recibieron {len(detalles)} documentos en el detalle.")
        print("🧾 Ejemplo primer documento:")
        print(json.dumps(detalles[0], indent=2, ensure_ascii=False))

        # Guardar resultado
        os.makedirs("facturas_sii/data", exist_ok=True)
        ruta_json = f"facturas_sii/data/detalle_{rut}_{periodo}.json"
        with open(ruta_json, "w") as f:
            json.dump(detalles, f, indent=2, ensure_ascii=False)
        print(f"💾 Detalle completo guardado en: {ruta_json}")

except Exception as e:
    print("❌ Error al procesar el detalle:", e)
    print("📄 Contenido bruto:", res.text[:1000])
