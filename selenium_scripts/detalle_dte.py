import json
import os
import requests
import time
from datetime import datetime
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
with open("facturas_sii/cookies/cookies.json", "r") as f:
    raw_cookies = json.load(f)
cookies = {cookie['name']: cookie['value'] for cookie in raw_cookies}

conversation_id = cookies.get("CSESSIONID")
if not conversation_id:
    print("❌ No se encontró la cookie 'CSESSIONID'. Requiere nuevo login.")
    exit()

# === OBTENER TOKEN RECAPTCHA CON SELENIUM ===
print("🌐 Abriendo navegador para obtener tokenRecaptcha...")
options = Options()
# options.add_argument("--headless")
print("🔄 Iniciando Selenium...")
driver = webdriver.Chrome(options=options)

# Cargar solo cookies del dominio sii.cl y válidas
driver.get("https://www4.sii.cl")
print("🌐 Página base cargada. Insertando cookies...")
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
            print(f"⚠️ Error al cargar cookie {cookie['name']}: {e}")

driver.get("https://www4.sii.cl/consdcvinternetui/#/index")
print("📄 Página RCV cargada.")

# === FORZAR SELECCIÓN DE AÑO Y MES con ng-model ===
try:
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//select[@ng-model='periodoAnho']")))
    anho_select = driver.find_element(By.XPATH, "//select[@ng-model='periodoAnho']")
    driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'))", anho_select, periodo.split("-")[0])
    time.sleep(1)

    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//select[@ng-model='periodoMes']")))
    mes_select = driver.find_element(By.XPATH, "//select[@ng-model='periodoMes']")
    driver.execute_script("arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('change'))", mes_select, periodo.split("-")[1])
    time.sleep(1)

except Exception as e:
    driver.quit()
    print(f"❌ No se pudo seleccionar mes/año: {e}")
    exit()

try:
    # Esperar que cargue botón "Consultar"
    WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Consultar')]")))
    print("✅ Botón 'Consultar' visible. Ejecutando...")

    # Click al botón para que se genere el token en localStorage
    consultar_btn = driver.find_element(By.XPATH, "//button[contains(., 'Consultar')]")
    consultar_btn.click()

    # Esperar a que aparezca el token en localStorage
    print("⌛ Esperando tokenRecaptcha en localStorage...")
    token = None
    for _ in range(10):
        time.sleep(1)
        token = driver.execute_script("return window.localStorage.getItem('siilastsesion');")
        if token and '"token":"' in token:
            break

    driver.quit()

    if not token:
        raise Exception("❌ TokenRecaptcha no encontrado.")
    
    token_dict = json.loads(token)
    token_recaptcha = token_dict.get("token", "")
    if not token_recaptcha:
        raise Exception("❌ TokenRecaptcha vacío.")
    
    print(f"🔐 TokenRecaptcha obtenido correctamente.")

except Exception as e:
    driver.quit()
    print(f"❌ No se pudo obtener tokenRecaptcha: {e}")
    exit()

# === PREPARAR HEADERS Y PAYLOAD ===
headers = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www4.sii.cl",
    "Referer": "https://www4.sii.cl/consdcvinternetui/",
}

payload = {
    "metaData": {
        "namespace": "cl.sii.sdi.lob.diii.consdcv.data.api.interfaces.FacadeService/getDetalleVenta",
        "conversationId": conversation_id,
        "transactionId": str(int(time.time()*1000))  # este puede seguir como timestamp
    },

    "data": {
        "rutEmisor": rut,
        "dvEmisor": dv,
        "ptributario": periodo_sii,
        "codTipoDoc": "33",
        "operacion": "",
        "estadoContab": "",
        "accionRecaptcha": "RCV_DETV",
        "tokenRecaptcha": token_recaptcha
    }
}

# === REQUEST ===
url = "https://www4.sii.cl/consdcvinternetui/services/data/facadeService/getDetalleVenta"
print("📡 Consultando detalle DTE...")

response = requests.post(url, headers=headers, cookies=cookies, json=payload)

if response.status_code == 200:
    data = response.json()
    output_folder = "facturas_sii/data"
    os.makedirs(output_folder, exist_ok=True)
    filename = os.path.join(output_folder, f"detalle_{rut}_{periodo}.json")
    # ✅ Verificar que se recibió correctamente la lista de facturas
if "data" in data and isinstance(data["data"], list):
    facturas = data["data"]
    output_folder = "facturas_sii/data"
    os.makedirs(output_folder, exist_ok=True)
    filename = os.path.join(output_folder, f"detalle_{rut}_{periodo}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(facturas, f, indent=2, ensure_ascii=False)
    print(f"✅ Detalle guardado correctamente en {filename} (facturas: {len(facturas)})")
else:
    print("❌ La respuesta no contiene la clave 'data' o no es una lista válida.")

    print(response.text)