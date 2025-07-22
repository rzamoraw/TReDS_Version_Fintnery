import requests
import json

# --- Inputs del usuario ---
rut_completo = input("🔐 Ingrese su RUT completo (sin guion, con DV, ej: 762623706): ").strip()
periodo = input("📅 Ingrese el periodo (formato YYYY-MM, Ej: 2025-07): ").strip()

# --- Separar RUT y DV ---
rut = rut_completo[:-1]
dv = rut_completo[-1]

# --- Headers y Cookies capturados del navegador ---
headers = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-419,es;q=0.9",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Origin": "https://www4.sii.cl",
    "Referer": "https://www4.sii.cl/consemitidosinternetui/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "x-dtpc": "11$590866572_487h9vFKRTDSHMNCAEVGFIRUPIENPDGNALBKAA-0e0",
    "x-dtreferer": "https://www4.sii.cl/consemitidosinternetui/"
}

cookies = {
    "CSESSIONID": "S98UITJAZ2BN7",
    "NETSCAPE_LIVEWIRE.clave": "SIUbEGX5VBg6.SIOhN5ka7smvI",
    "NETSCAPE_LIVEWIRE.rut": rut,
    "NETSCAPE_LIVEWIRE.dv": dv,
    "NETSCAPE_LIVEWIRE.mac": "1ad6kqkj0tkna8cr7rod19r9p9",  # puedes omitir este si no es crítico
    "TOKEN": "S98UITJAZ2BN7"
}

# --- Payload del request ---
data = {
    "metaData": {
        "namespace": "cl.sii.sdi.lob.diii.consemitidos.data.api.interfaces.FacadeService/getResumen",
        "conversationId": cookies["CSESSIONID"],
        "transactionId": "ebdd304f-eba1-4b72-8a05-90348e68a518",  # Puede ser aleatorio
        "page": None
    },
    "data": {
        "periodo": periodo,
        "rutContribuyente": rut,
        "dvContribuyente": dv,
        "operacion": 1
    }
}

# --- Request ---
print("📄 Consultando resumen...")
url = "https://www4.sii.cl/consemitidosinternetui/services/data/facadeService/getResumen"
res = requests.post(url, headers=headers, cookies=cookies, data=json.dumps(data))

# --- Validación ---
if res.status_code != 200:
    print(f"❌ Error en getResumen: {res.status_code}")
    print(res.text)
else:
    print("✅ Respuesta obtenida")
    resumen = res.json()
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    