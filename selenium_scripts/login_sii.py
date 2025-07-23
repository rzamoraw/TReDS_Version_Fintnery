from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json, os, time

# ---------- Limpiar RUT ----------
def limpiar_rut(rut_input):
    # Elimina puntos y guiones, mantiene el dígito verificador
    rut_input = rut_input.replace(".", "").replace("-", "").upper().strip()
    if not rut_input[:-1].isdigit() or rut_input[-1] not in "0123456789K":
        raise ValueError("❌ Formato inválido. Ingrese RUT con dígito verificador (ej: 76262370K)")
    return rut_input

# ---------- Inputs ----------
rut = limpiar_rut(input("🔐 Ingrese RUT completo (ej: 76262370K): ").strip())
clave = input("🔑 Ingrese clave SII: ").strip()

# ---------- Selenium ----------
chrome_options = Options()
chrome_options.add_argument("--start-maximized")
driver = webdriver.Chrome(options=chrome_options)
wait = WebDriverWait(driver, 15)

print("🌐 Cargando formulario de autenticación SII...")
driver.get("https://zeusr.sii.cl/AUT2000/InicioAutenticacion/IngresoRutClave.html")

try:
    wait.until(EC.presence_of_element_located((By.ID, "rutcntr"))).send_keys(rut)
    driver.find_element(By.ID, "clave").send_keys(clave)
    driver.find_element(By.ID, "bt_ingresar").click()
    print("🔓 Login enviado correctamente.")
except Exception as e:
    print("❌ Error al ingresar RUT/clave:", e)
    driver.quit()
    exit()

# ---------- Esperar cookies ----------
time.sleep(5)
cookies = driver.get_cookies()

# ---------- Guardar cookies ----------
os.makedirs("facturas_sii/cookies", exist_ok=True)
with open("facturas_sii/cookies/cookies.json", "w") as f:
    json.dump(cookies, f, indent=2)

print("✅ Login correcto. Cookies guardadas.")
driver.quit()
