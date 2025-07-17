from fastapi import APIRouter, Request, Form, Depends, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from passlib.context import CryptContext
from database import SessionLocal
from models import Proveedor, FacturaDB, OfertaFinanciamiento
from datetime import datetime
import os, zipfile, xml.etree.ElementTree as ET
from fastapi import HTTPException

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates_middle = Jinja2Templates(directory="templates/middle")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─────────────────────────  Registro / Login  ──────────────────────────
@router.get("/registro")
def mostrar_formulario_registro(request: Request):
    return templates_middle.TemplateResponse("registro_proveedor.html", {"request": request})     

@router.post("/registro")
def registrar_proveedor(
    request: Request,
    nombre: str = Form(...),
    rut: str = Form(...),
    usuario: str = Form(...),
    clave: str = Form(...),
    db: Session = Depends(get_db)
):  
    existente = db.query(Proveedor).filter(Proveedor.usuario == usuario).first()
    if existente:
        return templates_middle.TemplateResponse("registro_proveedor.html", {"request": request, "error": "El usuario ya existe."})    

    clave_hash = pwd_context.hash(clave)
    nuevo = Proveedor(nombre=nombre, rut=rut, usuario=usuario, clave_hash=clave_hash)
    db.add(nuevo)
    db.commit()
    return RedirectResponse(url="/proveedor/login", status_code=303)


@router.get("/login")
def mostrar_formulario_login(request: Request):
    return templates.TemplateResponse("login_proveedor.html", {"request": request})


@router.post("/login")
def login_proveedor(
    request: Request,
    usuario: str = Form(...),
    clave: str = Form(...),
    db: Session = Depends(get_db)
):
    proveedor = db.query(Proveedor).filter(Proveedor.usuario == usuario).first()
    if not proveedor or not pwd_context.verify(clave, proveedor.clave_hash):
        return templates.TemplateResponse(
            "login_proveedor.html",
            {"request": request, "error": "Usuario o clave incorrectos"}
        )
    request.session["proveedor_id"] = proveedor.id
    return RedirectResponse(url="/proveedor/facturas", status_code=303)


@router.get("/logout")
def logout_proveedor(request: Request):
    request.session.clear()
    return RedirectResponse(url="/proveedor/login", status_code=303)


# ─────────────────────────  Inicio  ──────────────────────────
@router.get("/inicio")
def inicio_proveedor(request: Request, db: Session = Depends(get_db)):
    proveedor_id = request.session.get("proveedor_id")
    if not proveedor_id:
        return RedirectResponse(url="/proveedor/login", status_code=303)

    proveedor = db.query(Proveedor).get(proveedor_id)
    
    proveedor_nombre = proveedor.nombre if proveedor else "Desconocido"

    return templates.TemplateResponse(
        "inicio_proveedor.html",
        {
            "request": request,
            "proveedor_id": proveedor_id,
            "proveedor_nombre": proveedor_nombre
        }
    )


# ─────────────────────────  Facturas  ──────────────────────────
@router.get("/facturas")
def ver_facturas_proveedor(request: Request, db: Session = Depends(get_db)):
    prov_id = request.session.get("proveedor_id")
    if not prov_id:
        return RedirectResponse("/proveedor/login", 303)

    proveedor = db.query(Proveedor).get(prov_id)
    if not proveedor:
        return RedirectResponse("/proveedor/login", 303)
    nombre = proveedor.nombre

    # traemos facturas + ofertas en una sola consulta
    facturas = (
    db.query(FacturaDB)
      .options(
          joinedload(FacturaDB.ofertas)
          .joinedload(OfertaFinanciamiento.financiador)
      )
      .filter(
          FacturaDB.proveedor_id == prov_id,
          FacturaDB.rut_emisor   == proveedor.rut
      )      # ← aquí termina filter
      .all() # ← aquí, sobre el Query
)

    # dict {factura_id: [lista de ofertas]}
    ofertas_por_factura = {f.id: f.ofertas for f in facturas}

    return templates.TemplateResponse(
        "facturas.html",
        {
            "request": request,
            "facturas": facturas,
            "ofertas_por_factura": ofertas_por_factura,
            "proveedor_nombre": nombre
        }
    )


@router.post("/facturas")
async def subir_factura_archivo(
    request: Request,
    archivo: UploadFile = Form(...),
    db: Session = Depends(get_db)
):
    proveedor_id = request.session.get("proveedor_id")
    if not proveedor_id:
        return RedirectResponse(url="/proveedor/login", status_code=303)

    proveedor = db.query(Proveedor).get(proveedor_id)
    proveedor_nombre = proveedor.nombre if proveedor else "Desconocido"

    contenido = await archivo.read()
    if archivo.filename.endswith(".zip"):
        with open(f"{UPLOAD_FOLDER}/temp.zip", "wb") as f:
            f.write(contenido)
        with zipfile.ZipFile(f"{UPLOAD_FOLDER}/temp.zip", "r") as zf:
            zf.extractall(UPLOAD_FOLDER)
        archivos_xml = [f for f in os.listdir(UPLOAD_FOLDER) if f.endswith(".xml")]
    elif archivo.filename.endswith(".xml"):
        with open(os.path.join(UPLOAD_FOLDER, archivo.filename), "wb") as f:
            f.write(contenido)
        archivos_xml = [archivo.filename]
    else:
        return templates.TemplateResponse("facturas.html", {
            "request": request,
            "mensaje": "Solo se permiten archivos XML o ZIP.",
            "proveedor_nombre": proveedor_nombre
        })
  
    errores = []
    for nombre in archivos_xml:
        ruta = os.path.join(UPLOAD_FOLDER, nombre)
        try:
            tree = ET.parse(ruta)
            root = tree.getroot()
            folio = int(root.find(".//Folio").text)
            rut_emisor = root.find(".//RUTEmisor").text
            rut_receptor = root.find(".//RUTRecep").text

            # Validación de consistencia con el proveedor logeado
            if rut_emisor != proveedor.rut:
                errores.append(f"Factura folio {folio} descartada: RUT emisor ({rut_emisor}) no coincide con proveedor logeado ({proveedor.rut})")
                continue

            duplicada = db.query(FacturaDB).filter_by(
                rut_emisor=rut_emisor, rut_receptor=rut_receptor, folio=folio
            ).first()
            if duplicada:
                errores.append(f"Factura duplicada folio {folio}")
                continue

            factura = FacturaDB(
                rut_emisor=rut_emisor,
                rut_receptor=rut_receptor,
                tipo_dte=root.find(".//TipoDTE").text,
                folio=folio,
                monto=int(root.find(".//MntTotal").text),
                razon_social_emisor=root.find(".//RznSoc").text,
                razon_social_receptor=root.find(".//RznSocRecep").text,
                fecha_emision=datetime.strptime(root.find(".//FchEmis").text, "%Y-%m-%d").date(),
                fecha_vencimiento=datetime.strptime(root.find(".//FchVenc").text, "%Y-%m-%d").date(),
                fecha_vencimiento_original=datetime.strptime(root.find(".//FchVenc").text, "%Y-%m-%d").date(),
                estado_dte="Cargada",
                confirming_solicitado=False,
                origen_confirmacion="Proveedor",
                proveedor_id=proveedor_id
            )
            db.add(factura)
            db.commit()
        except Exception as e:
            errores.append(f"Error en {nombre}: {e}")

    facturas = db.query(FacturaDB).filter(FacturaDB.proveedor_id == proveedor_id).all()
    return templates.TemplateResponse(
        "facturas.html",
        {
            "request": request,
            "facturas": facturas,
            "errores": errores or None,
            "proveedor_nombre": proveedor_nombre
        }
    )


@router.get("/solicitar_confirmacion/{factura_id}")
def solicitar_confirmacion_factura(
    factura_id: int, request: Request, db: Session = Depends(get_db)
):
    proveedor_id = request.session.get("proveedor_id")
    if not proveedor_id:
        return RedirectResponse(url="/proveedor/login", status_code=303)

    factura = db.query(FacturaDB).filter(
        FacturaDB.id == factura_id,
        FacturaDB.proveedor_id == proveedor_id
    ).first()
    if factura:
        factura.estado_dte = "Confirmación solicitada al pagador"
        factura.confirming_solicitado = True
        factura.origen_confirmacion = "Proveedor"
        db.commit()

    return RedirectResponse(url="/proveedor/facturas", status_code=303)


@router.post("/solicitar_confirming/{factura_id}")
def solicitar_confirming(factura_id: int, db: Session = Depends(get_db)):
    factura = db.query(FacturaDB).get(factura_id)
    if factura and factura.estado_dte == "Confirmada por pagador":
        factura.estado_dte = "Confirming solicitado"
        factura.confirming_solicitado = True
        db.commit()
    return RedirectResponse("/proveedor/facturas", 303)


@router.post("/rechazar_vencimiento/{factura_id}")
def rechazar_vencimiento(factura_id: int, db: Session = Depends(get_db)):
    factura = db.query(FacturaDB).get(factura_id)
    if factura and factura.estado_dte == "Confirmada por pagador":
        factura.estado_dte = "Vencimiento rechazado por proveedor"
        db.commit()
    return RedirectResponse("/proveedor/facturas", 303)


@router.get("/ofertas/{factura_id}")
def ver_ofertas_factura(
    factura_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    prov_id = request.session.get("proveedor_id")
    if not prov_id:
        return RedirectResponse("/proveedor/login", 303)

    factura = db.query(FacturaDB).get(factura_id)
    if not factura or factura.proveedor_id != prov_id:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    if factura.estado_dte != "Confirming solicitado":
        raise HTTPException(status_code=400, detail="La factura ya fue adjudicada o aún no solicitada")

    ofertas = (
        db.query(OfertaFinanciamiento)
          .filter_by(factura_id=factura_id)
          .order_by(OfertaFinanciamiento.tasa_interes.asc())
          .all()
    )

    return templates.TemplateResponse(
        "ofertas_proveedor.html",
        {
            "request": request,
            "factura": factura,
            "ofertas": ofertas
        }
    )


@router.post("/aceptar-oferta/{oferta_id}")
def aceptar_oferta(oferta_id: int, request: Request, db: Session = Depends(get_db)):
    prov_id = request.session.get("proveedor_id")
    if not prov_id:
        return RedirectResponse("/proveedor/login", 303)

    oferta = db.query(OfertaFinanciamiento).get(oferta_id)
    if not oferta:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")

    factura = oferta.factura
    if factura.proveedor_id != prov_id:
        raise HTTPException(status_code=403, detail="No autorizado")

    oferta.estado = "Adjudicada"

    (
        db.query(OfertaFinanciamiento)
          .filter(OfertaFinanciamiento.factura_id == factura.id,
                  OfertaFinanciamiento.id != oferta_id)
          .update({"estado": "No adjudicada"})
    )

    factura.financiador_adjudicado = str(oferta.financiador_id)
    factura.estado_dte = "Confirming adjudicado"
    db.commit()

    return RedirectResponse("/proveedor/facturas?msg=oferta_ok", 303)
