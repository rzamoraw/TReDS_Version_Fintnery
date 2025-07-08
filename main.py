from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from database import engine, Base
from routers import proveedor, pagador, financiador, auth, configuracion, facturas_proveedor, admin

app = FastAPI()

# Crear las tablas si no existen
Base.metadata.create_all(bind=engine)

# Configuración de plantillas y archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Middleware de sesión (se usará para login por rol)
app.add_middleware(SessionMiddleware, secret_key="super-secret-key")

# Incluir los routers
app.include_router(auth.router)
app.include_router(proveedor.router, prefix="/proveedor", tags=["Proveedor"])
app.include_router(pagador.router, prefix="/pagador", tags=["Pagador"])
app.include_router(financiador.router, prefix="/financiador", tags=["Financiador"])
app.include_router(configuracion.router, prefix="/configuracion", tags=["Configuracion"])
app.include_router(facturas_proveedor.router, prefix="/proveedor", tags=["Facturas"])
app.include_router(auth.router)
app.include_router(admin.router)


# Ruta principal de prueba (landing temporal)
@app.get("/")
def inicio(request: Request):
    return templates.TemplateResponse("inicio.html", {"request": request})