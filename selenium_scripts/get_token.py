from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import json
import os

# ───────────── CONFIGURACIÓN ─────────────
RCV_URL = "https://www4.sii.cl/consdcvinternetui/#/index"
COOKIES_PATH = "facturas_sii/cookies/cookies.json"
TOKEN_OUTPUT = "facturas_sii/token_recaptcha.txt"

# ───────────── OBTENER TOKEN RECAPTCHA ─────────────
def obtener_token():
    options = Options()
    options.add_argument("--headless=new")  # Quita esta línea para debug
    options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=options)

    driver.get(RCV_URL)
    time.sleep(2)

    # Cargar cookies
    with open(COOKIES_PATH, "r") as f:
        cookies = json.load(f)
    for cookie in cookies:
        for key in ["sameSite", "storeId", "hostOnly", "httpOnly", "secure", "session"]:
            cookie.pop(key, None)
        if "www4.sii.cl" in cookie.get("domain", ""):
            driver.add_cookie(cookie)

    # Volver a cargar la página para aplicar las cookies
    driver.get(RCV_URL)

    try:
        # Espera que cargue algún contenido dinámico
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "main-content"))
        )
    except:
        time.sleep(3)

    # Intentar obtener el token hasta 5 veces
    token = None
    for _ in range(5):
        token = driver.execute_script("return sessionStorage.getItem('TokenRecaptcha');")
        if token:
            break
        time.sleep(1.5)

    driver.quit()
    return token

# ───────────── EJECUCIÓN ─────────────
if __name__ == "__main__":
    print("🔍 Obteniendo TokenRecaptcha desde el SII...")

    try:
        token = obtener_token()
        if token:
            print(f"✅ Token reCAPTCHA obtenido:\n{token}")
            os.makedirs(os.path.dirname(TOKEN_OUTPUT), exist_ok=True)
            with open(TOKEN_OUTPUT, "w") as f:
                f.write(token)
            print(f"💾 Token guardado en {TOKEN_OUTPUT}")
        else:
            print("❌ No se encontró TokenRecaptcha. ¿Sesión válida o expiró?")
    except Exception as e:
        print(f"❌ Error al obtener el token: {e}")