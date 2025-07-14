from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
import os

# Routers (importando los objetos `router` de cada archivo)
from routers.auth import router as auth_router
from routers.proveedor import router as proveedor_router
from routers.pagador import router as pagador_router
from routers.financiador import router as financiador_router
from routers.marketplace import router as marketplace_router
from routers.admin import router as admin_router
from routers.configuracion import router as configuracion_router


# 🔐 Cargar variables de entorno
load_dotenv()

# 🚀 Crear aplicación
app = FastAPI()

# 🔐 Middleware de sesión con clave segura desde .env
SECRET_KEY = os.getenv("SECRET_KEY", "!defaultsecret")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# 📦 Inclusión de routers en orden lógico
app.include_router(auth_router, prefix="/auth")
app.include_router(proveedor_router, prefix="/proveedor")
app.include_router(pagador_router, prefix="/pagador")
app.include_router(financiador_router, prefix="/financiador")
app.include_router(marketplace_router, prefix="/marketplace")
app.include_router(configuracion_router, prefix="/configuracion")
app.include_router(admin_router, prefix="/admin")

# ⚠️ Manejo de errores 404 (opcional y no invasivo)
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(status_code=404, content={"detail": "Recurso no encontrado."})

# ⚠️ Manejo de errores 500 (opcional)
@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor."})
