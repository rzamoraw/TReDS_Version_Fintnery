# routers/pagador.py
from fastapi import APIRouter, Request, Form, Depends, File, UploadFile, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, extract, case
from passlib.context import CryptContext

from database import SessionLocal, get_db
from models import Pagador, FacturaDB, Financiador, Fondo, PagadorProfile, EsgCertificacion, OfertaFinanciamiento
from datetime import datetime, timedelta, date
from rut_utils import normalizar_rut
from services.pagador_360 import kpis_pagador
from services.connectors.mercado_publico import (fetch_proveedor_por_rut, fetch_ordenes_de_compra_por_rut, fetch_adjudicaciones_por_rut, resumen_mercado_publico,)
from services.connectors.esg_certificaciones import fetch_esg_certificaciones_por_rut

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
    rut = normalizar_rut(rut)
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
    
    request.session["rut"] = normalizar_rut(pagador.rut)
    request.session["nombre"] = pagador.nombre
    return RedirectResponse(url="/pagador/facturas", status_code=303)


# ───────────── Inicio ─────────────
@router.get("/inicio")
def inicio_pagador(request: Request, db: Session = Depends(get_db)):
    rut = request.session.get("rut")
    if not rut:
        return RedirectResponse(url="/pagador/login", status_code=303)

    pagador = db.query(Pagador).filter(Pagador.rut == rut).first()
    pagador_nombre = pagador.nombre if pagador else ""

    return templates.TemplateResponse(
        "inicio_pagador.html",
        {
            "request": request,
            "rut": rut,
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
    session = request.session
    rut_pagador = normalizar_rut(session.get("rut"))
    if not rut_pagador:
        return RedirectResponse(url="/pagador/login", status_code=303)

    # 🧾 Facturas pendientes de acción
    facturas_pendientes = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == rut_pagador,
        FacturaDB.estado_dte.in_([
            "Emitida",
            "Ingresada por pagador",
            "Confirmación solicitada al pagador"
        ]),
        FacturaDB.origen_confirmacion != "Proveedor"  # Se asume que las del proveedor van en otra sección
    ).all()

    # 📩 Facturas solicitadas por proveedores
    facturas_solicitadas = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == rut_pagador,
        FacturaDB.estado_dte == "Confirmación solicitada al pagador",
        FacturaDB.origen_confirmacion == "Proveedor"
    ).all()

    # 📁 Historial de facturas gestionadas
    facturas_gestionadas = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == rut_pagador,
        FacturaDB.estado_dte.in_([
            "Confirmada por pagador",
            "Rechazada por pagador",
            "Enviado a confirming",
            "Confirming adjudicado"
        ])
    ).all()

    # --- Utilidades para el template (no rompe el hito) ---
    dias_por_folio = {}
    adjudicacion_por_folio = {}

    for factura in facturas_gestionadas:
        # Días al vencimiento (desde emisión)
        try:
            if factura.fecha_emision and factura.fecha_vencimiento:
                dias_por_folio[factura.folio] = (factura.fecha_vencimiento - factura.fecha_emision).days
            else:
                dias_por_folio[factura.folio] = "—"
        except Exception:
            dias_por_folio[factura.folio] = "—"

        # Adjudicación (solo si adjudicada)
        if factura.estado_dte == "Confirming adjudicado" and factura.financiador_adjudicado:
            fin = db.query(Financiador).options(joinedload(Financiador.fondo)).get(int(factura.financiador_adjudicado))
            if fin:
                fondo_nombre = fin.fondo.nombre if fin.fondo else "—"
                adjudicacion_por_folio[factura.folio] = f"{fin.nombre} ({fondo_nombre})"
            else:
                adjudicacion_por_folio[factura.folio] = "—"
        else:
            adjudicacion_por_folio[factura.folio] = "—"

    return templates.TemplateResponse("facturas_pagador.html", {
        "request": request,
        "facturas_pendientes": facturas_pendientes,
        "facturas_solicitadas": facturas_solicitadas,
        "facturas_gestionadas": facturas_gestionadas,
        "pagador_nombre": session.get("nombre"),
        "facturas_descartadas": [],
        "dias_por_folio":dias_por_folio,
        "adjudicacion_por_folio": adjudicacion_por_folio
    })

# ───────────── Editar Vencimiento ─────────────
@router.post("/editar-vencimiento/{folio}")
def editar_vencimiento_pagador(
    folio: int,
    request: Request,
    nueva_fecha_vencimiento: str = Form(...),
    db: Session = Depends(get_db)
):
    session = request.session
    rut_pagador = normalizar_rut(session.get("rut"))
    if not rut_pagador:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(
        FacturaDB.folio == folio,
        FacturaDB.rut_receptor == rut_pagador
    ).first()

    if factura is None:
        print(f"❌ Factura no encontrada o no pertenece al pagador")
        return RedirectResponse(url="/pagador/facturas?msg=error_folio", status_code=303)

    if factura.estado_dte in ["Confirmada por pagador", "Rechazada por pagador"]:
        print(f"⚠️ Factura ya fue gestionada, no se puede cambiar vencimiento")
        return RedirectResponse(url="/pagador/facturas?msg=error_estado", status_code=303)

    try:
        nueva_fecha = datetime.strptime(nueva_fecha_vencimiento, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse("/pagador/facturas?msg=fecha_invalida", status_code=303)
    
    hoy = date.today()

    # ⛔ no permitir vencimiento en el pasado
    if nueva_fecha < hoy:
        return RedirectResponse("/pagador/facturas?msg=vencimiento_pasado", status_code=303)
    
    # ⛔ no permitir vencimiento antes de la emisión
    if factura.fecha_emision and nueva_fecha < factura.fecha_emision:
        return RedirectResponse("/pagador/facturas?msg=vencimiento_antes_emision", status_code=303)
    
    try:
        # ✅ si pasa validaciones, persistimos
        factura.fecha_vencimiento = nueva_fecha
        factura.origen_confirmacion = "Fecha modificada por pagador"
        db.commit()
        print(f"✅ Fecha de vencimiento actualizada para folio {folio}")

        # 🔹 Calcular días de plazo tal como en financiador
        dias_plazo = (nueva_fecha - hoy).days
        print(f"📅 Plazo calculado desde hoy: {dias_plazo} días")

        db.commit()
        print(f"✅ Fecha de vencimiento actualizada para folio {folio}")
    
    except Exception as e:
        db.rollback()
        print(f"❌ Error al actualizar vencimiento: {e}")

    return RedirectResponse(url="/pagador/facturas?msg=fecha_actualizada", status_code=303)

# ───────────── Confirmar / Rechazar ─────────────
@router.post("/confirmar-factura/{folio}")
def confirmar_factura(folio: int, request: Request, db: Session = Depends(get_db)):
    rut_pagador = normalizar_rut(request.session.get("rut"))
    if not rut_pagador:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(
        FacturaDB.folio == folio,
        FacturaDB.rut_receptor == rut_pagador,
        FacturaDB.estado_dte.in_([
            "Confirmación solicitada al pagador",
            "Ingresada por pagador"
        ])
    ).first()

    if factura is None:
        print(f"❌ Factura con folio {folio} no encontrada o no en estado confirmable.")
        return RedirectResponse(url="/pagador/facturas?msg=error", status_code=303)
    
    # ⛔ no permitir confirmar con vencimiento en el pasado
    hoy = date.today()
    if not factura.fecha_vencimiento or factura.fecha_vencimiento < hoy:
        return RedirectResponse(url="/pagador/facturas?msg=vencimiento_pasado", status_code=303)

    factura.estado_dte = "Confirmada por pagador"
    factura.origen_confirmacion = "Confirmada manualmente por pagador"

    if not factura.fecha_vencimiento_original:
        factura.fecha_vencimiento_original = factura.fecha_vencimiento
        factura.fecha_confirmacion = date.today()

    try:
        db.commit()
        print(f"✅ Factura {folio} confirmada por pagador")
    except Exception as e:
        db.rollback()
        print(f"❌ Error al confirmar factura {folio}: {e}")

    return RedirectResponse(url="/pagador/facturas?msg=confirmada", status_code=303)


@router.post("/rechazar-factura/{folio}")
def rechazar_factura(folio: int, request: Request, db: Session = Depends(get_db)):
    rut_pagador = normalizar_rut(request.session.get("rut"))
    if not rut_pagador:
        return RedirectResponse(url="/pagador/login", status_code=303)

    factura = db.query(FacturaDB).filter(
        FacturaDB.folio == folio,
        FacturaDB.rut_receptor == rut_pagador,
        FacturaDB.estado_dte.in_([
            "Confirmación solicitada al pagador",
            "Ingresada por pagador"
        ])
    ).first()

    if factura is None:
        print(f"❌ Factura con folio {folio} no encontrada o no en estado rechazable.")
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
    rut_pagador = normalizar_rut(session.get("rut"))   # ✅ usar RUT, no pagador_id
    if not rut_pagador:
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
            rut_emisor = normalizar_rut(str(factura.get("detRutDoc")) + factura.get("detDvDoc", ""))
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
                rut_receptor=rut_pagador,
                tipo_dte="33"
            ).first()

            if factura_existente:
                facturas_descartadas.append(f"Factura folio {folio} ya registrada.")
                continue

            # Estado fijo: todas se ingresan como "Ingresada por pagador"
            estado_dte = "Ingresada por pagador"

            nueva_factura = FacturaDB(
                rut_emisor=rut_emisor,
                rut_receptor=rut_pagador,
                razon_social_emisor=razon_social_emisor,
                razon_social_receptor=session.get("nombre"),
                tipo_dte="33",
                folio=folio,
                monto=factura.get("detMntTotal", 0),
                estado_dte=estado_dte,
                fecha_emision=fecha_emision,
                fecha_vencimiento=fecha_vencimiento,
                fecha_vencimiento_original=fecha_vencimiento,
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
        FacturaDB.rut_receptor == rut_pagador,
        FacturaDB.estado_dte.in_([
            "Ingresada por pagador",
            "Confirmación solicitada al pagador"
        ])
    ).all()

    facturas_gestionadas = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == rut_pagador,
        FacturaDB.estado_dte.in_([
            "Confirmada por pagador",
            "Rechazada por pagador",
            "Enviado a confirming",
            "Confirming adjudicado"
        ])
    ).all()

    facturas_solicitadas = db.query(FacturaDB).filter(
        FacturaDB.rut_receptor == rut_pagador,
        FacturaDB.estado_dte == "Confirmación solicitada al pagador",
        FacturaDB.origen_confirmacion == "Proveedor"
    ).all()


    return templates.TemplateResponse("facturas_pagador.html", {
        "request": request,
        "facturas_pendientes": facturas_pendientes,
        "facturas_solicitadas": facturas_solicitadas,
        "facturas_gestionadas": facturas_gestionadas,
        "facturas_descartadas": facturas_descartadas,
        "pagador_nombre": session.get ("nombre")
    })

@router.get("/importar_facturas")
def redireccion_despues_de_refresh():
    return RedirectResponse(url="/pagador/facturas", status_code=303)

@router.get("/360/{rut}")
async def vista_360_pagador(request: Request, rut: str, db: Session = Depends(get_db)):
    rut_norm = normalizar_rut(rut)
    datos = kpis_pagador(db, rut_norm)

    # Series para Chart.js
    tmc_labels   = [p["periodo"] for p in datos["series"]["tmc_por_mes"]]
    tmc_data     = [p["tmc"]     for p in datos["series"]["tmc_por_mes"]]
    monto_labels = [p["periodo"] for p in datos["series"]["montos_por_mes"]]
    monto_data   = [p["monto"]   for p in datos["series"]["montos_por_mes"]]

    # Facturas recientes
    recientes = (db.query(FacturaDB)
                   .filter(FacturaDB.rut_receptor == rut_norm)
                   .order_by(FacturaDB.fecha_emision.desc())
                   .limit(10).all())

    ids = [f.id for f in recientes]
    if ids:
        adj_ids = {
            r[0] for r in db.query(OfertaFinanciamiento.factura_id)
                            .filter(
                                OfertaFinanciamiento.factura_id.in_(ids),
                                func.lower(OfertaFinanciamiento.estado).like("adjudic%")
                            ).all()
        }
    else:
        adj_ids = set()

    for f in recientes:
        if f.financiador_adjudicado is not None or f.id in adj_ids:
            f.estado_vista = "Adjudicada"
        elif f.confirming_solicitado:
            f.estado_vista = "Confirming solicitado"
        elif (f.estado_confirmacion or "").lower() == "rechazada":
            f.estado_vista = "Rechazada"
        elif (f.estado_confirmacion or "").lower() in {"confirmada"}:
            f.estado_vista = "Confirmada"
        else:
            f.estado_vista = "Pendiente"

    # 🔌 Mercado Público
    mp = await fetch_proveedor_por_rut(rut_norm)
    mp_oc   = await fetch_ordenes_de_compra_por_rut(rut_norm, limit=10)
    mp_adj  = await fetch_adjudicaciones_por_rut(rut_norm, limit=10)

    # ----- ESG desde API + fusión con BD -----
    # 1) Certificaciones que ya obtienes de BD (si las tienes en `certs` o `datos["esg"]["certificaciones"]`)
    certs_db = datos["esg"]["certificaciones"]  # ORM objects

    # 2) Llamada a la API ESG
    esg_api = await fetch_esg_certificaciones_por_rut(rut_norm, force=False) or {}
    api_certs = esg_api.get("certificaciones", [])  # lista de dicts

    # 3) Normaliza ORM -> dict para mezclar con API sin romper el template
    certs_db_norm = [
        {
            "tipo": c.tipo,
            "emisor": c.emisor,
            "valido_hasta": getattr(c, "valido_hasta", None),
            "enlace": c.enlace,
            "fuente": "BD"
        }
        for c in certs_db
    ]

    # 4) Marca fuente API
    api_certs_norm = [
        {
            "tipo": c.get("tipo"),
            "emisor": c.get("emisor"),
            "valido_hasta": c.get("valido_hasta"),
            "enlace": c.get("enlace"),
            "fuente": "API"
        }
        for c in api_certs
    ]

    # 5) Fusiona y (opcional) deduplica por (tipo, emisor)
    seen = set()
    certs_merged = []
    for item in certs_db_norm + api_certs_norm:
        key = (item.get("tipo"), item.get("emisor"))
        if key in seen:
            continue
    seen.add(key)
    certs_merged.append(item)

    context = {
        "request": request,
        "rut": rut_norm,
        "perfil": datos["esg"]["perfil"] or PagadorProfile(rut=rut_norm, razon_social="(Sin registro)"),
        "kpis": datos,
        "certs": certs_merged,
        "esg_api": esg_api,
        "recientes": recientes,
        "tmc_labels_json":   json.dumps(tmc_labels, ensure_ascii=False),
        "tmc_data_json":     json.dumps(tmc_data, ensure_ascii=False),
        "monto_labels_json": json.dumps(monto_labels, ensure_ascii=False),
        "monto_data_json":   json.dumps(monto_data, ensure_ascii=False),
        "mp": mp,
        "mp_oc": mp_oc,
        "mp_adj": mp_adj,
    }
    return templates.TemplateResponse("pagador_360.html", context)

@router.get("/ext/mp/ordenes/{rut}")
async def mp_preview(rut: str):
    return await resumen_mercado_publico

@router.get("/ext/mp/adjudicaciones/{rut}")
async def mp_adj_preview(
    rut: str,
    desde: str | None = Query(None),
    hasta: str | None = Query(None),
    limit: int = Query(20),
    force: int = Query(0),
):
    return await fetch_adjudicaciones_por_rut(rut, desde=desde, hasta=hasta, limit=limit, force=bool(force))