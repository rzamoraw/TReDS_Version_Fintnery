# routers/financiador.py
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi import Query
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import date, datetime          # ← date ya estaba, datetime seguía
import os
from dotenv import load_dotenv

load_dotenv()

from database import SessionLocal
from models import Financiador, FacturaDB, OfertaFinanciamiento, Fondo

router = APIRouter()
templates = Jinja2Templates(directory="templates")
templates_middle = Jinja2Templates(directory="templates/middle")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ──────────────────────────────── DB dependency ────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ──────────────────────────────── Helper ────────────────────────────────
def _solo_admin(fin: Financiador):
    if not fin.es_admin:
        raise HTTPException(status_code=403, detail="Solo administradores")

# ──────────────────────────────── GET: Registro Financiador ────────────────────────────────
@router.get("/registro")
def mostrar_formulario_registro(request: Request, db: Session = Depends(get_db)):
    admin_id = request.session.get("admin_fondo_id")
    if not admin_id:
        return RedirectResponse("/middle/login", status_code=303)
    
    return templates_middle.TemplateResponse("registrar_financiador.html", {
        "request": request,
        "fondo": fondo
    })


# ──────────────────────────────── POST: Registro Financiador ────────────────────────────────
@router.post("/registro")
def registrar_financiador(
    request: Request,
    nombre: str = Form(...),
    usuario: str = Form(...),
    clave: str = Form(...),
    admin_key: str = Form(None),
    db: Session = Depends(get_db)
):  
    request.session.clear()  # ← 🧹 Limpieza de sesión previa (clave)

    modo_admin = admin == "true"

    # Validar existencia previa
    existente = db.query(Financiador).filter_by(usuario=usuario).first()
    if existente:
        admin_id = request.session.get("admin_fondo_id")
        fondo = db.query(Fondo).filter(Fondo.admin_id == admin_id).first()
        return templates_middle.TemplateResponse("registrar_financiador.html", {
            "request": request,
            "fondo": fondo,
            "error": "El usuario ya existe"
        })

    # Validar fondo por sesión del admin
    admin_id = request.session.get("admin_fondo_id")
    if not admin_id:
        return RedirectResponse("/middle/login", 303)

    fondo = db.query(Fondo).filter(Fondo.admin_id == admin_id).first()
    if not fondo:
        return RedirectResponse("/middle/fondos", 303)

    # Verificar si será administrador
    clave_maestra = os.getenv("ADMIN_ACCESS_KEY")
    es_admin = admin_key == clave_maestra if admin_key else False

    # Crear financiador
    clave_hash = pwd_context.hash(clave)
    nuevo = Financiador(
        nombre=nombre,
        usuario=usuario,
        clave_hash=clave_hash,
        fondo_id=fondo.id,
        es_admin=es_admin
    )
    db.add(nuevo)
    db.commit()

    return RedirectResponse(url="/financiador/login", status_code=303)


@router.get("/login")
def mostrar_formulario_login(request: Request):
    return templates.TemplateResponse("login_financiador.html", {"request": request})

@router.post("/login")
def login_financiador(
    request: Request,
    usuario: str = Form(...),
    clave: str = Form(...),
    admin: str = Query(default="false"),  # viene desde ?admin=true
    db: Session = Depends(get_db)
):
    modo_admin = admin == "true"

    financiador = db.query(Financiador).filter(Financiador.usuario == usuario).first()
    if not financiador or not pwd_context.verify(clave, financiador.clave_hash):
        return templates.TemplateResponse("login_financiador.html", {
            "request": request,
            "error": "Usuario o clave incorrectos"
        })

    # ─── Si intenta entrar como admin pero no lo es ───
    if modo_admin and not financiador.es_admin:
        return templates.TemplateResponse("login_financiador.html", {
            "request": request,
            "error": "No tienes permisos de administrador."
        })

    # ─── Guardar sesión ───
    request.session["financiador_id"] = financiador.id
    request.session["es_admin"] = financiador.es_admin
    request.session["fondo_id"] = financiador.fondo_id  # 👈 ¡CLAVE!

    hoy = date.today()

    # ─── ADMIN: forzar carga diaria ───
    if financiador.es_admin:
        if financiador.fecha_costo_fondos != hoy:
            return RedirectResponse("/financiador/costo-fondos", 303)
        return RedirectResponse("/financiador/marketplace", 303)

    # ─── USUARIO COMERCIAL: bloqueo si admin no cargó hoy ───
    if financiador.fecha_costo_fondos != hoy:
        return templates.TemplateResponse("login_financiador.html", {
            "request": request,
            "error": "El administrador aún no carga el costo de fondos hoy."
        })

    # ─── Acceso permitido ───
    return RedirectResponse("/financiador/marketplace", 303)

@router.get("/inicio")
def inicio_financiador(request: Request, db: Session = Depends(get_db)):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)

    financiador = db.query(Financiador).get(financiador_id)
    nombre = financiador.nombre if financiador else "Desconocido"

    return templates.TemplateResponse("inicio_financiador.html", {
        "request": request,
        "financiador_id": financiador_id,
        "financiador_nombre": nombre
    })

# ──────────────────────────────── Marketplace ────────────────────────────────
@router.get("/marketplace")
def ver_marketplace(request: Request, db: Session = Depends(get_db)):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse("/financiador/login", 303)

    financiador = db.query(Financiador).get(financiador_id)
    hoy = date.today()

    # ── Control de costo-de-fondos ───────────────────────────────────────────
    if not financiador.es_admin and financiador.fecha_costo_fondos != hoy:
        raise HTTPException(
            status_code=403,
            detail="Costo de fondos no disponible todavía. Intente más tarde.",
        )
    if financiador.es_admin and financiador.fecha_costo_fondos != hoy:
        return RedirectResponse("/financiador/costo-fondos", 303)

    # ── 1) Todavía disponibles ──────────────────────────────────────────────
    disponibles = (
        db.query(FacturaDB)
        .filter(
            FacturaDB.estado_dte == "Confirming solicitado",
            FacturaDB.financiador_adjudicado.is_(None),
        )
        .all()
    )

    # ── 2) Ya adjudicadas por ESTE financiador ──────────────────────────────
    mias = (
        db.query(FacturaDB)
        .filter(
            FacturaDB.financiador_adjudicado == str(financiador_id),
            FacturaDB.estado_dte == "Confirming adjudicado",
        )
        .all()
    )

    # ── 3) Adjudicadas por OTRO financiador ────────────────────────────────
    otras = (
        db.query(FacturaDB)
        .filter(
            FacturaDB.estado_dte == "Confirming adjudicado",
            FacturaDB.financiador_adjudicado != str(financiador_id),
        )
        .all()
    )

    # Mapear ofertas propias por factura
    ofertas_propias = {
        o.factura_id: o
        for o in db.query(OfertaFinanciamiento)
        .filter_by(financiador_id=financiador_id)
        .all()
    }

    return templates.TemplateResponse(
        "marketplace_financiador.html",
        {
            "request": request,
            "financiador_nombre": financiador.nombre,
            "disponibles": disponibles,
            "mias": mias,
            "otras": otras,
            "ofertas_propias": ofertas_propias,
        },
    )

# ──────────────────────────────── Administración ────────────────────────────────
@router.get("/usuarios")
def listar_usuarios(request: Request, db: Session = Depends(get_db)):
    fid = request.session.get("financiador_id")
    if not fid:
        return RedirectResponse("/financiador/login", 303)

    admin = db.query(Financiador).get(fid)
    _solo_admin(admin)

    usuarios = db.query(Financiador).order_by(Financiador.id).all()
    return templates.TemplateResponse("usuarios_financiador.html", {
        "request": request,
        "usuarios": usuarios,
        "financiador_nombre": admin.nombre
    })

@router.post("/usuarios/toggle-admin/{user_id}")
def toggle_admin(user_id: int, request: Request, db: Session = Depends(get_db)):
    fid = request.session.get("financiador_id")
    if not fid:
        return RedirectResponse("/financiador/login", 303)

    admin = db.query(Financiador).get(fid)
    _solo_admin(admin)

    usuario = db.query(Financiador).get(user_id)
    if usuario and usuario.id != admin.id:
        usuario.es_admin = not usuario.es_admin
        db.commit()

    return RedirectResponse("/financiador/usuarios", 303)

# ──────────────────────────────── Costo de fondos ────────────────────────────────
@router.get("/costo-fondos")
def form_costo_fondos(request: Request, db: Session = Depends(get_db)):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse("/financiador/login", 303)

    financiador = db.query(Financiador).get(financiador_id)
    _solo_admin(financiador)

    return templates.TemplateResponse("costo_fondos.html", {
        "request": request,
        "costo_fondos": financiador.costo_fondos_mensual,
        "fecha_costo_fondos": financiador.fecha_costo_fondos,
        "financiador_nombre": financiador.nombre,
        "es_admin": financiador.es_admin  # 👈 Esta línea es la clave
    })

@router.post("/costo-fondos")
def guardar_costo_fondos(
    request: Request,
    nuevo_costo_mensual: float = Form(...),
    db: Session = Depends(get_db)
):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse(url="/financiador/login", status_code=303)

    financiador = db.query(Financiador).get(financiador_id)
    if not financiador:
        return RedirectResponse(url="/financiador/login", status_code=303)

    # Validación: el costo de fondos no puede ser cero o negativo
    if nuevo_costo_mensual <= 0:
        return templates.TemplateResponse("costo_fondos.html", {
            "request": request,
            "costo_fondos": financiador.costo_fondos_mensual,
            "fecha_costo_fondos": financiador.fecha_costo_fondos,
            "financiador_nombre": financiador.nombre,
            "es_admin": financiador.es_admin,
            "error": "⚠️ El costo de fondos debe ser mayor a cero para operar."
        })

    # Guardar nuevo costo de fondos
    financiador.costo_fondos_mensual = nuevo_costo_mensual
    financiador.fecha_costo_fondos = date.today()
    db.commit()

    # Redirige siempre a costo-fondos con ?msg=ok (para mostrar opciones)
    return RedirectResponse("/financiador/costo-fondos?msg=ok", status_code=303)

# ──────────────────────────────── Ofertas ────────────────────────────────
@router.get("/ofertar/{factura_id}")
def mostrar_formulario_oferta(factura_id: int, request: Request, db: Session = Depends(get_db)):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse("/financiador/login", 303)

    financiador = db.query(Financiador).get(financiador_id)
    factura = db.query(FacturaDB).get(factura_id)
    if not factura:
        return templates.TemplateResponse("error.html", {"request": request, "mensaje": "Factura no encontrada"})

    dias_anticipacion = (factura.fecha_vencimiento - date.today()).days
    return templates.TemplateResponse("ofertar.html", {
        "request": request,
        "factura": factura,
        "financiador_nombre": financiador.nombre,
        "dias_anticipacion": dias_anticipacion
    })

@router.post("/registrar-oferta/{factura_id}")
def registrar_oferta(
    factura_id: int,
    request: Request,
    tasa_interes: float = Form(...),
    comision_flat: float = Form(...),
    dias_anticipacion: int = Form(...),
    db: Session = Depends(get_db)
):
    financiador_id = request.session.get("financiador_id")
    if not financiador_id:
        return RedirectResponse("/financiador/login", 303)

    factura = db.query(FacturaDB).get(factura_id)
    financiador = db.query(Financiador).get(financiador_id)

    monto = factura.monto
    tasa_total = tasa_interes + financiador.costo_fondos_mensual
    descuento = monto * (tasa_total / 100) * (dias_anticipacion / 30)
    precio_cesion = monto - descuento - comision_flat

    nueva = OfertaFinanciamiento(
        factura_id=factura_id,
        financiador_id=financiador_id,
        tasa_interes=tasa_interes,
        comision_flat=comision_flat,
        dias_anticipacion=dias_anticipacion,
        precio_cesion=precio_cesion,
        estado="Oferta realizada"
    )
    db.add(nueva)
    db.commit()

    return RedirectResponse("/financiador/marketplace", 303)

@router.post("/actualizar-oferta/{oferta_id}")
def actualizar_oferta(
    oferta_id: int,
    request: Request,
    tasa_interes: float = Form(...),
    comision_flat: float = Form(0),
    db: Session = Depends(get_db)
):
    oferta = db.query(OfertaFinanciamiento).get(oferta_id)
    if not oferta or oferta.financiador_id != request.session.get("financiador_id"):
        raise HTTPException(status_code=403)

    oferta.tasa_interes = tasa_interes
    oferta.comision_flat = comision_flat
    db.commit()

    return RedirectResponse(f"/financiador/ver-oferta/{oferta_id}", 303)

@router.get("/ver-oferta/{oferta_id}")
def ver_oferta(oferta_id: int, request: Request, db: Session = Depends(get_db)):
    oferta = db.query(OfertaFinanciamiento).get(oferta_id)
    if not oferta or oferta.financiador_id != request.session.get("financiador_id"):
        raise HTTPException(status_code=403)

    return templates.TemplateResponse("ver_oferta.html", {
        "request": request,
        "factura": oferta.factura,
        "oferta": oferta
    })

# ──────────────────────────────── LogOut ────────────────────────────────
@router.get("/logout")
def logout_financiador(request: Request):
    request.session.clear()
    response = RedirectResponse("/financiador/login", status_code=303)
    response.delete_cookie("session")  # 🔐 Fuerza eliminación total de cookie
    return response