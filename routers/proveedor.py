from fastapi import APIRouter, Request, Form, Depends, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from database import SessionLocal
from models import Proveedor, FacturaDB
from datetime import datetime
import os
import zipfile
import xml.etree.ElementTree as ET

router = APIRouter()
templates = Jinja2Templates(directory="templates")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Registro y login

@router.get("/registro")
def mostrar_formulario_registro(request: Request):
    return templates.TemplateResponse("registro_proveedor.html", {"request": request})

@router.post("/registro")
def registrar_proveedor(request: Request, nombre: str = Form(...), rut: str = Form(...), usuario: str = Form(...), clave: str = Form(...), db: Session = Depends(get_db)):
    clave_hash = pwd_context.hash(clave)
    nuevo = Proveedor(nombre=nombre, rut=rut, usuario=usuario, clave_hash=clave_hash)
    db.add(nuevo)
    db.commit()
    return RedirectResponse(url="/proveedor/login", status_code=303)

@router.get("/login")
def mostrar_formulario_login(request: Request):
    return templates.TemplateResponse("login_proveedor.html", {"request": request})

@router.post("/login")
def login_proveedor(request: Request, usuario: str = Form(...), clave: str = Form(...), db: Session = Depends(get_db)):
    proveedor = db.query(Proveedor).filter(Proveedor.usuario == usuario).first()
    if not proveedor or not pwd_context.verify(clave, proveedor.clave_hash):
        return templates.TemplateResponse("login_proveedor.html", {"request": request, "error": "Usuario o clave incorrectos"})
    request.session["proveedor_id"] = proveedor.id
    return RedirectResponse(url="/proveedor/facturas", status_code=303)

@router.get("/logout")
def logout_proveedor(request: Request):
    request.session.clear()
    return RedirectResponse(url="/proveedor/login", status_code=303)

@router.get("/inicio")
def inicio_proveedor(request: Request):
    proveedor_id = request.session.get("proveedor_id")
    if not proveedor_id:
        return RedirectResponse(url="/proveedor/login", status_code=303)
    return templates.TemplateResponse("inicio_proveedor.html", {"request": request, "proveedor_id": proveedor_id})

# Gestión de facturas

@router.get("/facturas")
def ver_facturas_proveedor(request: Request, db: Session = Depends(get_db)):
    proveedor_id = request.session.get("proveedor_id")
    if not proveedor_id:
        return RedirectResponse(url="/proveedor/login", status_code=303)
    facturas = db.query(FacturaDB).filter(FacturaDB.proveedor_id == proveedor_id).all()
    return templates.TemplateResponse("facturas.html", {"request": request, "facturas": facturas})

@router.post("/facturas")
async def subir_factura_archivo(request: Request, archivo: UploadFile = Form(...), db: Session = Depends(get_db)):
    proveedor_id = request.session.get("proveedor_id")
    if not proveedor_id:
        return RedirectResponse(url="/proveedor/login", status_code=303)

    proveedor = db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
    contenido = await archivo.read()

    if archivo.filename.endswith(".zip"):
        with open(f"{UPLOAD_FOLDER}/temp.zip", "wb") as f:
            f.write(contenido)
        with zipfile.ZipFile(f"{UPLOAD_FOLDER}/temp.zip", "r") as zip_ref:
            zip_ref.extractall(UPLOAD_FOLDER)
        archivos_xml = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith(".xml")]
    elif archivo.filename.endswith(".xml"):
        with open(f"{UPLOAD_FOLDER}/{archivo.filename}", "wb") as f:
            f.write(contenido)
        archivos_xml = [archivo.filename]
    else:
        return templates.TemplateResponse("facturas.html", {"request": request, "mensaje": "Solo se permiten archivos XML o ZIP."})

    errores = []

    for nombre in archivos_xml:
        ruta = os.path.join(UPLOAD_FOLDER, nombre)
        try:
            tree = ET.parse(ruta)
            root = tree.getroot()
            folio = int(root.find(".//Folio").text)
            rut_emisor = root.find(".//RUTEmisor").text
            rut_receptor = root.find(".//RUTRecep").text

            # Validar que el proveedor esté subiendo una factura propia
            if rut_emisor != proveedor.rut:
                errores.append(f"Factura con folio {folio} tiene emisor {rut_emisor}, distinto del proveedor autenticado {proveedor.rut}")
                continue

            # ❗ Validar duplicado
            duplicada = db.query(FacturaDB).filter_by(
                rut_emisor=rut_emisor,
                rut_receptor=rut_receptor,
                folio=folio
            ).first()
            if duplicada:
                errores.append(f"Factura duplicada: RUT emisor {rut_emisor}, receptor {rut_receptor}, folio {folio}")
                continue

            razon_social_emisor = root.find(".//RznSoc").text
            razon_social_receptor = root.find(".//RznSocRecep").text
            tipo_dte = root.find(".//TipoDTE").text
            monto = int(root.find(".//MntTotal").text)
            fecha_emision = datetime.strptime(root.find(".//FchEmis").text, "%Y-%m-%d").date()
            fecha_vencimiento = datetime.strptime(root.find(".//FchVenc").text, "%Y-%m-%d").date()

            factura = FacturaDB(
                rut_emisor=rut_emisor,
                rut_receptor=rut_receptor,
                tipo_dte=tipo_dte,
                folio=folio,
                monto=monto,
                razon_social_emisor=razon_social_emisor,
                razon_social_receptor=razon_social_receptor,
                fecha_emision=fecha_emision,
                fecha_vencimiento=fecha_vencimiento,
                fecha_vencimiento_original=fecha_vencimiento,  # ✅ NUEVO
                estado_dte="Cargada",
                confirming_solicitado=False,
                origen_confirmacion="Proveedor",
                proveedor_id=proveedor_id
            )
            db.add(factura)
            db.commit()
        except Exception as e:
            errores.append(f"Error procesando {nombre}: {e}")

    facturas = db.query(FacturaDB).filter(FacturaDB.proveedor_id == proveedor_id).all()
    return templates.TemplateResponse("facturas.html", {
        "request": request,
        "facturas": facturas,
        "errores": errores if errores else None
    })

@router.get("/solicitar_confirmacion/{factura_id}")
def solicitar_confirmacion_factura(factura_id: int, request: Request, db: Session = Depends(get_db)):
    proveedor_id = request.session.get("proveedor_id")
    if not proveedor_id:
        return RedirectResponse(url="/proveedor/login", status_code=303)
    factura = db.query(FacturaDB).filter(FacturaDB.id == factura_id, FacturaDB.proveedor_id == proveedor_id).first()
    if factura:
        factura.estado_dte = "Confirmación solicitada al pagador"
        factura.confirming_solicitado = True
        factura.origen_confirmacion = "Proveedor"
        db.commit()
    return RedirectResponse(url="/proveedor/facturas", status_code=303)

@router.post("/facturas-manual")
def cargar_factura_manual(
    request: Request,
    rut_receptor: str = Form(...),
    razon_social_receptor: str = Form(...),
    tipo_dte: str = Form(...),
    folio: int = Form(...),
    monto: int = Form(...),
    fecha_emision: str = Form(...),
    fecha_vencimiento: str = Form(...),
    db: Session = Depends(get_db)
):
    proveedor_id = request.session.get("proveedor_id")
    if not proveedor_id:
        return RedirectResponse(url="/proveedor/login", status_code=303)

    proveedor = db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()

    nueva_factura = FacturaDB(
        rut_emisor=proveedor.rut,
        razon_social_emisor=proveedor.nombre,
        rut_receptor=rut_receptor,
        razon_social_receptor=razon_social_receptor,
        tipo_dte=tipo_dte,
        folio=folio,
        monto=monto,
        fecha_emision=datetime.strptime(fecha_emision, "%Y-%m-%d").date(),
        fecha_vencimiento=datetime.strptime(fecha_vencimiento, "%Y-%m-%d").date(),
        fecha_vencimiento_original=datetime.strptime(fecha_vencimiento, "%Y-%m-%d").date(),  # ✅ NUEVO
        estado_dte="Cargada",  # ✅ NUEVO: Estado inicial
        confirming_solicitado=False,  # ✅ NUEVO: Aún no solicitado
        origen_confirmacion="Proveedor",
        proveedor_id=proveedor.id
    )

    db.add(nueva_factura)
    db.commit()

    return RedirectResponse(url="/proveedor/facturas", status_code=303)


# Ruta para solicitar confirming
@router.post("/solicitar_confirming/{factura_id}")
def solicitar_confirming(factura_id: int):
    db = SessionLocal()
    factura = db.query(FacturaDB).filter(FacturaDB.id == factura_id).first()
    if factura and factura.estado_dte == "Confirmada por pagador":
        factura.estado_dte = "En confirming"
        factura.confirming_solicitado = True
        db.commit()
    db.close()
    return RedirectResponse(url="/proveedor/facturas", status_code=status.HTTP_303_SEE_OTHER)

# Ruta para rechazar vencimiento
@router.post("/rechazar_vencimiento/{factura_id}")
def rechazar_vencimiento(factura_id: int):
    db = SessionLocal()
    factura = db.query(FacturaDB).filter(FacturaDB.id == factura_id).first()
    if factura and factura.estado_dte == "Confirmada por pagador":
        factura.estado_dte = "Vencimiento rechazado por proveedor"
        db.commit()
    db.close()
    return RedirectResponse(url="/proveedor/facturas", status_code=status.HTTP_303_SEE_OTHER)