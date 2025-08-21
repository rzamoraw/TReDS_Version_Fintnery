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
from services.connectors.mercado_publico import fetch_mp_minimo
from services.connectors.retc import fetch_emisiones_totales_por_razon_social
from services.resolvers.nombres import resolve_display_name
from services.connectors import snifa

import json
import asyncio

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates_middle = Jinja2Templates(directory="templates/middle")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# SNIFA: importar si existe; si no, dejar stub que retorna {}
try:
    from services.connectors.snifa import fetch_snifa_resumen_por_rut_razon
except Exception:
    async def fetch_snifa_resumen_por_rut_razon(rut: str, razon: str | None = None):
        return {"ok": False, "counters": {}, "muestras": [], "evidencias": []}

def _rango_12m_hasta_hoy():
    """
    Devuelve (agno1, nroMes1, agno2, nroMes2) cubriendo 12 meses hasta el mes actual.
    """
    hoy = date.today()
    agno2, nroMes2 = hoy.year, hoy.month
    m_total = (agno2 * 12 + nroMes2) - 11
    agno1 = (m_total - 1) // 12
    nroMes1 = (m_total - 1) % 12 + 1
    return agno1, nroMes1, agno2, nroMes2


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
    recientes = (
        db.query(FacturaDB)
          .filter(FacturaDB.rut_receptor == rut_norm)
          .order_by(FacturaDB.fecha_emision.desc())
          .limit(10)
          .all()
    )

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

    def _lower(s: str | None) -> str:
        return (s or "").strip().lower()

    for f in recientes:
        dte  = _lower(f.estado_dte)
        conf = _lower(f.estado_confirmacion)

        if (f.financiador_adjudicado is not None) or (f.id in adj_ids) or (dte == "confirming adjudicado"):
            f.estado_vista = "Adjudicada"
        elif dte in {"rechazada por pagador", "rechazada"} or conf in {"rechazada", "rechazada por pagador"}:
            f.estado_vista = "Rechazada"
        elif dte.startswith("confirmada") or conf.startswith("confirmada") or (f.fecha_confirmacion is not None):
            f.estado_vista = "Confirmada"
        elif bool(getattr(f, "confirming_solicitado", False)) or dte in {"confirming solicitado", "enviado a confirming"}:
            f.estado_vista = "Confirming solicitado"
        else:
            f.estado_vista = "Pendiente"

    # ---------- Mercado Público (core) ----------
    from services.connectors.mercado_publico import fetch_mp_minimo, build_mp_context

    try:
        mp = await fetch_mp_minimo(rut_norm)
    except Exception as e:
        print(f"[MP360] fetch_mp_minimo error: {e}")
        mp = {
            "ok": False, "sellos": [], "ventas_12m": 0, "rango": None,
            "registrado": False, "habilitado": None,
            "score": None, "score_promedio": None,
            "razon_social": None, "nombre_fantasia": None,
            "oc_24m": 0, "entCode": None
        }

    ctx_mp    = build_mp_context(mp)
    mp_oc     = ctx_mp["mp_oc"]
    mp_adj    = ctx_mp["mp_adj"]
    mp_ventas = ctx_mp["mp_ventas"]

    # ---------------------------
    # Nombre a mostrar (razón social para RETC)
    # ---------------------------
    display_name = None

    # 1) Perfil en BD (si existe en tu modelo un perfil del pagador)
    perfil_bd = datos.get("esg", {}).get("perfil") if "esg" in datos else None
    if perfil_bd:
        display_name = (
            getattr(perfil_bd, "razon_social", None)
            or getattr(perfil_bd, "nombre_fantasia", None)
        )

    # 2) Razón social de facturas locales (más estable que MP)
    if not display_name:
        for f in recientes:
            if getattr(f, "razon_social_receptor", None):
                display_name = f.razon_social_receptor
                break

    # 3) MP mínimo (si viene algo)
    if not display_name and mp:
        display_name = mp.get("razon_social") or mp.get("nombre_fantasia")

    if not display_name:
        display_name = "(Sin registro)"

    perfil_display = perfil_bd or PagadorProfile(rut=rut_norm, razon_social=display_name)

    # ---------- SNIFA (SMA) ----------
    snifa = {}
    try:
        snifa = await fetch_snifa_resumen_por_rut_razon(
            rut=rut_norm,
            razon_social=display_name if display_name != "(Sin registro)" else None,
            limit_por_tabla=1200,
            muestras=5,
            force=False
        )
    except Exception as e:
        print(f"[SNIFA] error: {e}")
        snifa = {"ok": False, "counters": {}, "muestras": {}, "evidencias": {}}

    # ---------- RETC (RECURSO OFICIAL: Establecimientos) ----------
    # Consultar RETC por razón social exacta y normalizar para el template
    esg_retc = {}
    if display_name and display_name != "(Sin registro)":
        try:
            raw = await fetch_emisiones_totales_por_razon_social(display_name, limit=50, force=False)
            sums = (raw.get("sums") or raw.get("totales") or {})
            esg_retc = {
                "ok": bool(raw.get("ok")),
                "matches": raw.get("matches") or [],
                "sum": {
                    "co2":          round(float(sums.get("co2", 0) or 0), 2),
                    "nox":          round(float(sums.get("nox", 0) or 0), 2),
                    "so2":          round(float(sums.get("so2", 0) or 0), 2),
                    "mp":           round(float(sums.get("mp", 0)  or 0), 2),
                    "res_pelig":    round(float(sums.get("res_pelig", 0) or 0), 2),
                    "res_no_pelig": round(float(sums.get("res_no_pelig", 0) or 0), 2),
                },
                "count": len(raw.get("matches") or []),
                "total": len(raw.get("matches") or []),   # back-compat si el template mira .total
                "year_label": "RETC 2019",                # dataset actual disponible que usamos
                "evidencia_url": raw.get("evidencia_url"),
                "rut": rut_norm,
            }
        except Exception as e:
            print(f"[RETC] error: {e}")
            esg_retc = {
                "ok": False,
                "matches": [],
                "sum": {"co2":0,"nox":0,"so2":0,"mp":0,"res_pelig":0,"res_no_pelig":0},
                "count": 0,
                "total": 0,
                "year_label": "RETC 2019",
                "evidencia_url": None,
                "rut": rut_norm,
                "error": str(e),
            }
    else:
        esg_retc = {
            "ok": False,
            "matches": [],
            "sum": {"co2":0,"nox":0,"so2":0,"mp":0,"res_pelig":0,"res_no_pelig":0},
            "count": 0,
            "total": 0,
            "year_label": "RETC 2019",
            "evidencia_url": None,
            "rut": rut_norm,
        }

    # ---------- Certificaciones (solo BD) ----------
    certs_db = datos.get("esg", {}).get("certificaciones") if "esg" in datos else []
    certs_merged = [
        {
            "tipo": c.tipo,
            "emisor": c.emisor,
            "valido_hasta": getattr(c, "valido_hasta", None),
            "enlace": c.enlace,
            "fuente": "BD",
        }
        for c in (certs_db or [])
    ]

    print(f"[RETC] rut={rut_norm} razon_social='{display_name}' matches={ (esg_retc.get('total') if esg_retc else 0) }")

    context = {
        "request": request,
        "rut": rut_norm,
        "perfil": perfil_display,
        "kpis": datos,
        "certs": certs_merged,
        "esg_api": {},             # mantenemos vacía para compatibilidad con el template
        "esg_retc": esg_retc,      # usado por la card RETC en el template
        "recientes": recientes,
        "tmc_labels_json":   json.dumps(tmc_labels, ensure_ascii=False),
        "tmc_data_json":     json.dumps(tmc_data, ensure_ascii=False),
        "monto_labels_json": json.dumps(monto_labels, ensure_ascii=False),
        "monto_data_json":   json.dumps(monto_data, ensure_ascii=False),
        "mp": mp,
        "mp_oc": mp_oc,
        "mp_adj": mp_adj,
        "mp_ventas": mp_ventas,
        "snifa": snifa,
    }
    return templates.TemplateResponse("pagador_360.html", context)