# routers/pagador.py
from fastapi import APIRouter, Request, Form, Depends, File, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from database import SessionLocal
from models import Pagador, FacturaDB
from datetime import datetime, timedelta
import json

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates_middle = Jinja2Templates(directory="templates/middle")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")



# ───────────── DB Dependency ─────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ───────────── Registro / Login ─────────────
@router.get("/registro")
def mostrar_formulario_registro(request: Request):
    return templates_middle.TemplateResponse("registro_pagador.html", {"request": request})


@router.post("/registro")
def registrar_pagador(
    request: Request,
    nombre: str = Form(...),
    rut: str = Form(...),
    usuario: str = Form(...),
    clave: str = Form(...),
    db: Session = Depends(get_db)
):
    clave_hash = pwd_context.hash(clave)
    nuevo = Pagador(nombre=nombre, rut=rut, usuario=usuario, clave_hash=clave_hash)
    db.add(nuevo)
    db.commit()
    return RedirectResponse(url="/pagador/login", status_code=303)


@router.get("/login")
def mostrar_formulario_login(request: Request):
    return templates.TemplateResponse("login_pagador.html", {"request": request})


@router.post("/login")
def login_pagador(
    request: Request,
    usuario: str = Form(...),
    clave: str = Form(...),
    db: Session = Depends(get_db)
):
    pagador = db.query(Pagador).filter(Pagador.usuario == usuario).first()
    if not pagador or not pwd_context.verify(clave, pagador.clave_hash):
        return templates.TemplateResponse(
            "login_pagador.html",
            {"request": request, "error": "Usuario o clave incorrectos"}
        )
    request.session["pagador_id"] = pagador.id
    return RedirectResponse(url="/pagador/facturas", status_code=303)


# ───────────── Inicio ─────────────
@router.get("/inicio")
def inicio_pagador(request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    pagador = db.query(Pagador).get(pagador_id)
    pagador_nombre = pagador.nombre if pagador else ""

    return templates.TemplateResponse(
        "inicio_pagador.html",
        {
            "request": request,
            "pagador_id": pagador_id,
            "pagador_nombre": pagador_nombre
        }
    )


# ───────────── Logout ─────────────
@router.get("/logout")
def logout_pagador(request: Request):
    request.session.clear()
    return RedirectResponse(url="/pagador/login", status_code=303)


# ───────────── Ver Facturas ─────────────
@router.get("/facturas")
def ver_facturas_pagador(request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    pagador = db.query(Pagador).get(pagador_id)
    if not pagador:
        request.session.clear()
        return RedirectResponse(url="/pagador/login", status_code=303)

    # 🔹 Facturas solicitadas por el proveedor
    facturas_solicitadas = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == pagador.rut,
        FacturaDB.estado_dte == "Confirmación solicitada al pagador"
    ).all()

    # 🔹 Facturas cargadas por el pagador (pendientes de acción)
    facturas_pendientes = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == pagador.rut,
        FacturaDB.estado_dte == "Emitida"
    ).all()

    # 🔹 Facturas ya gestionadas (historial)
    facturas_gestionadas = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == pagador.rut,
        FacturaDB.estado_dte.in_([
            "Confirmada por pagador",
            "Rechazada por pagador",
            "Enviado a confirming",
            "Confirming adjudicado"
        ])
    ).all()

    return templates.TemplateResponse(
        "facturas_pagador.html",
        {
            "request": request,
            "facturas_pendientes": facturas_pendientes,
            "facturas_solicitadas": facturas_solicitadas,
            "facturas_gestionadas": facturas_gestionadas,
            "pagador_nombre": pagador.nombre
        }
    )

# ───────────── Editar Vencimiento ─────────────
@router.post("/editar-vencimiento/{folio}")
def editar_vencimiento_pagador(
    folio: int,
    request: Request,
    nueva_fecha_vencimiento: str = Form(...),
    db: Session = Depends(get_db)
):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(
        FacturaDB.folio == folio,
        FacturaDB.pagador_id == pagador_id
    ).first()

    if factura is None:
        print(f"❌ Factura no encontrada o no pertenece al pagador")
        return RedirectResponse(url="/pagador/facturas?msg=error_folio", status_code=303)

    if factura.estado_dte in ["Confirmada por pagador", "Rechazada por pagador"]:
        print(f"⚠️ Factura ya fue gestionada, no se puede cambiar vencimiento")
        return RedirectResponse(url="/pagador/facturas?msg=error_estado", status_code=303)

    try:
        nueva_fecha = datetime.strptime(nueva_fecha_vencimiento, "%Y-%m-%d").date()
        factura.fecha_vencimiento = nueva_fecha
        factura.origen_confirmacion = "Fecha modificada por pagador"
        db.commit()
        print(f"✅ Fecha de vencimiento actualizada para folio {folio}")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al actualizar vencimiento: {e}")

    return RedirectResponse(url="/pagador/facturas?msg=fecha_actualizada", status_code=303)

# ───────────── Confirmar / Rechazar ─────────────
@router.post("/confirmar-factura/{folio}")
def confirmar_factura(folio: int, request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(
        FacturaDB.folio == folio,
        FacturaDB.pagador_id == pagador_id,
        FacturaDB.estado_dte.in_(["Confirmación solicitada al pagador", "Ingresada por pagador"])
    ).first()

    if factura is None:
        print(f"❌ Factura con folio {folio} no encontrada o no en estado confirmable.")
        return RedirectResponse(url="/pagador/facturas?msg=error", status_code=303)

    factura.estado_dte = "Confirmada por pagador"
    factura.origen_confirmacion = "Confirmada manualmente por pagador"

    if not factura.fecha_vencimiento_original:
        factura.fecha_vencimiento_original = factura.fecha_vencimiento

    try:
        db.commit()
        print(f"✅ Factura {folio} confirmada por pagador")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al confirmar factura {folio}: {e}")

    return RedirectResponse(url="/pagador/facturas?msg=confirmada", status_code=303)

@router.post("/rechazar-factura/{folio}")
def rechazar_factura(folio: int, request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(
        FacturaDB.folio == folio,
        FacturaDB.pagador_id == pagador_id,
        FacturaDB.estado_dte.in_(["Confirmación solicitada al pagador", "Ingresada por pagador"])
    ).first()

    if factura is None:
        print(f"❌ Factura no encontrada o en estado inválido para rechazo.")
        return RedirectResponse(url="/pagador/facturas?msg=error", status_code=303)

    factura.estado_dte = "Rechazada por pagador"
    factura.origen_confirmacion = "Rechazada manualmente por pagador"

    try:
        db.commit()
        print(f"✅ Factura {folio} rechazada por pagador")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al rechazar factura {folio}: {e}")

    return RedirectResponse(url="/pagador/facturas?msg=rechazada", status_code=303)

# Cargar facturas como confirmador pagador

@router.post("/importar_facturas")
async def importar_facturas_pagador(
    request: Request,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    session = request.session
    pagador_id = session.get("pagador_id")
    if not pagador_id:
        return RedirectResponse(url="/pagador/login", status_code=303)

    contenido = await archivo.read()

    if not contenido:
        facturas_descartadas = ["El archivo está vacío o no contiene datos válidos."]
        return templates.TemplateResponse("facturas_pagador.html", {
            "request": request,
            "facturas_pendientes": [],
            "facturas_solicitadas": [],
            "facturas_gestionadas": [],
            "facturas_descartadas": facturas_descartadas,
            "pagador_nombre": session.get("nombre")
        })

    data = json.loads(contenido)

    facturas_descartadas = []

    for factura in data:
        try:
            folio = factura.get("detNroDoc")
            rut_emisor = str(factura.get("detRutDoc")) + "-" + factura.get("detDvDoc", "")
            razon_social_emisor = factura.get("detRznSoc", "Sin razón social")
            fecha_emision = datetime.strptime(factura.get("detFchDoc"), "%d/%m/%Y").date()

            # 🧠 Descartar facturas de contado
            if factura.get("detEventoReceptor") == "P":
                facturas_descartadas.append(f"Factura {folio} es de pago contado y no puede ser anticipada.")
                continue

            dias_desde_emision = (datetime.now().date() - fecha_emision).days

            fch_venc = factura.get("detFchVenc")
            if fch_venc:
                fecha_vencimiento = datetime.strptime(fch_venc, "%d/%m/%Y").date()
            else:
                fecha_vencimiento = fecha_emision + timedelta(days=30)

            factura_existente = db.query(FacturaDB).filter_by(
                folio=folio,
                rut_emisor=rut_emisor,
                rut_receptor=session.get("rut"),
                tipo_dte="33"
            ).first()

            if factura_existente:
                facturas_descartadas.append(f"Factura folio {folio} ya registrada.")
                continue

            # Estado fijo: todas se ingresan como "Ingresada por pagador"
            estado_dte = "Ingresada por pagador"

            nueva_factura = FacturaDB(
                rut_emisor=rut_emisor,
                rut_receptor=session.get("rut"),
                razon_social_emisor=razon_social_emisor,
                razon_social_receptor=session.get("nombre"),
                tipo_dte="33",
                folio=folio,
                monto=factura.get("detMntTotal", 0),
                estado_dte=estado_dte,
                fecha_emision=fecha_emision,
                fecha_vencimiento=fecha_vencimiento,
                fecha_vencimiento_original=fecha_vencimiento,
                pagador_id=pagador_id,
                origen_confirmacion="Importación pagador",
                detEventoReceptor=factura.get("detEventoReceptor"),
                detEventoReceptorLeyenda=factura.get("detEventoReceptorLeyenda"),
                dias_desde_emision=dias_desde_emision
            )

            db.add(nueva_factura)

        except Exception as e:
            facturas_descartadas.append(f"Folio {factura.get('detNroDoc')}: Error {str(e)}")

    db.commit()

    # 🧾 Pendientes: cargadas por el propio pagador

    facturas_pendientes = db.query(FacturaDB).filter(
        FacturaDB.pagador_id == pagador_id,
        FacturaDB.estado_dte.in_([
        "Ingresada por pagador",
        "Confirmación solicitada al pagador"
    ])
).all()

    facturas_gestionadas = db.query(FacturaDB).filter(
    FacturaDB.pagador_id == pagador_id,
    FacturaDB.estado_dte.in_([
        "Confirmada por pagador",
        "Rechazada por pagador",
        "Enviado a confirming",
        "Confirming adjudicado"
    ])
).all()

    return templates.TemplateResponse("facturas_pagador.html", {
        "request": request,
        "facturas_pendientes": facturas_pendientes,
        "facturas_gestionadas": facturas_gestionadas,
        "facturas_descartadas": facturas_descartadas
    })

