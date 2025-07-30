import json
import os
import time
import requests
from datetime import datetime
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === INPUTS ===
rut_completo = input("🔐 Ingrese su RUT completo (sin guion, con DV, ej: 76262370K): ").upper()
rut = rut_completo[:-1]
dv = rut_completo[-1]
periodo = input("📅 Ingrese el periodo (formato YYYY-MM, Ej: 2025-07): ")
periodo_sii = periodo.replace("-", "")  # Ej: "202507"

# === CARGAR COOKIES ===
cookies_path = Path("facturas_sii/cookies/cookies.json")
if not cookies_path.exists():
    print("❌ No se encontró cookies.json. Ejecuta primero login_sii.py")
    exit()

with open(cookies_path, "r") as f:
    raw_cookies = json.load(f)

cookies = {cookie['name']: cookie['value'] for cookie in raw_cookies}
conversation_id = cookies.get("CSESSIONID")
if not conversation_id:
    print("❌ No se encontró la cookie 'CSESSIONID'. Requiere nuevo login.")
    exit()

# === OBTENER TOKEN RECAPTCHA CON SELENIUM ===
print("🌐 Abriendo navegador para obtener tokenRecaptcha...")

options = Options()
# options.add_argument("--headless")  # Descomentar si no se requiere ver el navegador
driver = webdriver.Chrome(options=options)

driver.get("https://www4.sii.cl")
print("🧩 Insertando cookies...")

for cookie in raw_cookies:
    if ".sii.cl" in cookie.get("domain", "") and not cookie['name'].startswith("AMCV"):
        try:
            driver.add_cookie({
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie["domain"],
                "path": cookie.get("path", "/"),
                "secure": cookie.get("secure", False)
            })
        except Exception as e:
            print(f"⚠️ Error con cookie {cookie['name']}: {e}")

driver.get("https://www4.sii.cl/consdcvinternetui/#/index")
print("📄 Página cargada.")

# === SELECCIONAR MES Y AÑO ===
try:
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//select[@ng-model='periodoAnho']")))
    driver.execute_script(
        "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'))",
        driver.find_element(By.XPATH, "//select[@ng-model='periodoAnho']"), periodo.split("-")[0]
    )
    time.sleep(1)

    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//select[@ng-model='periodoMes']")))
    driver.execute_script(
        "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'))",
        driver.find_element(By.XPATH, "//select[@ng-model='periodoMes']"), periodo.split("-")[1]
    )
    time.sleep(1)

except Exception as e:
    print(f"❌ Error seleccionando mes/año: {e}")
    driver.quit()
    exit()

# === OBTENER TOKEN DESDE LOCALSTORAGE ===
try:
    WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Consultar')]")))
    driver.find_element(By.XPATH, "//button[contains(., 'Consultar')]").click()
    print("🔄 Botón 'Consultar' presionado...")

    token = None
    for _ in range(10):
        time.sleep(1)
        token_json = driver.execute_script("return window.localStorage.getItem('siilastsesion');")
        if token_json and '"token":"' in token_json:
            token = json.loads(token_json).get("token")
            break

    driver.quit()

    if not token:
        raise Exception("❌ Token no encontrado en localStorage.")

    print("✅ tokenRecaptcha obtenido correctamente.")

except Exception as e:
    print(f"❌ Error al obtener tokenRecaptcha: {e}")
    driver.quit()
    exit()

# === HEADERS Y PAYLOAD ===
headers = {
    "Content-Type": "application/json;charset=UTF-8",
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://www4.sii.cl",
    "Referer": "https://www4.sii.cl/consdcvinternetui/"
}

payload = {
    "metaData": {
        "namespace": "cl.sii.sdi.lob.diii.consdcv.data.api.interfaces.FacadeService/getDetalleCompra",
        "conversationId": conversation_id,
        "transactionId": str(int(time.time() * 1000))
    },
    "data": {
        "rutEmisor": rut,
        "dvEmisor": dv,
        "ptributario": periodo_sii,
        "codTipoDoc": "33",
        "operacion": "COMPRA",
        "estadoContab": "REGISTRO",
        "accionRecaptcha": "RCV_DETC",
        "tokenRecaptcha": token
    }
}

# === REQUEST A getDetalleCompra ===
print("📡 Enviando request a getDetalleCompra...")
response = requests.post(
    "https://www4.sii.cl/consdcvinternetui/services/data/facadeService/getDetalleCompra",
    headers=headers, cookies=cookies, json=payload
)

print(f"📥 Código HTTP recibido: {response.status_code}")

if response.status_code != 200:
    print(response.text)
    raise Exception("❌ Error HTTP en la consulta al SII.")

try:
    data = response.json()
except Exception as e:
    print("❌ Error parseando JSON:", e)
    print(response.text)
    exit()

# === GUARDAR FACTURAS ===
if "data" in data and isinstance(data["data"], list):
    output_dir = "facturas_sii/data"
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"detalle_compras_{rut}_{periodo}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data["data"], f, indent=2, ensure_ascii=False)
    print(f"✅ Detalle de compras guardado en {filename} ({len(data['data'])} registros)")

else:
    print("⚠️ No se encontraron facturas de compras o formato inesperado.")
    print(json.dumps(data, indent=2, ensure_ascii=False))