# main.py
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from database import engine, Base
from routers import (
    proveedor,
    pagador,
    financiador,
    auth,
    configuracion,          # <- tu nuevo módulo
    facturas_proveedor,
    admin,
    marketplace,
)

app = FastAPI()

# --- Base de datos ---------------------------------------------------------
Base.metadata.create_all(bind=engine)

# --- Archivos estáticos y plantillas --------------------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Sesiones --------------------------------------------------------------
app.add_middleware(SessionMiddleware, secret_key="super-secret-key")

# --- Routers ---------------------------------------------------------------
app.include_router(auth.router)

# Portales principales
app.include_router(proveedor.router,   prefix="/proveedor",   tags=["Proveedor"])
app.include_router(pagador.router,     prefix="/pagador",     tags=["Pagador"])
app.include_router(financiador.router, prefix="/financiador", tags=["Financiador"])

# Configuraciones del financiador  (SIN prefijo extra)
app.include_router(configuracion.router, prefix="/financiador", tags=["Configuracion"])

# Otros módulos auxiliares
app.include_router(facturas_proveedor.router, prefix="/proveedor", tags=["Facturas"])
app.include_router(admin.router)
app.include_router(marketplace.router)

# --- Landing temporal ------------------------------------------------------
@app.get("/")
def inicio(request: Request):
    return templates.TemplateResponse("inicio.html", {"request": request})

# --- Debug: mostrar rutas montadas ---
from fastapi.routing import APIRoute

@app.on_event("startup")
async def show_routes():
    print("\nRUTAS MONTADAS:")
    for route in app.routes:
        if isinstance(route, APIRoute):
            print(f"{route.methods} {route.path}")
    print()