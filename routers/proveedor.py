from fastapi import APIRouter, Request, Form, Depends, UploadFile, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from passlib.context import CryptContext
from database import SessionLocal
from models import Proveedor, FacturaDB, OfertaFinanciamiento, Financiador, Pagador
from datetime import datetime, timedelta, date
import os, zipfile, xml.etree.ElementTree as ET
from fastapi import HTTPException
from rut_utils import normalizar_rut  # Asegúrate de tener esto al inicio
from urllib.parse import urlencode

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
    rut = normalizar_rut(rut)
    nuevo = Proveedor(nombre=nombre, rut=normalizar_rut(rut), usuario=usuario, clave_hash=clave_hash)
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
    request.session["proveedor_rut"] = proveedor.rut
    request.session["nombre"] = proveedor.nombre

    return RedirectResponse(url="/proveedor/facturas", status_code=303)


@router.get("/logout")
def logout_proveedor(request: Request):
    request.session.clear()
    return RedirectResponse(url="/proveedor/login", status_code=303)


# ─────────────────────────  Inicio  ──────────────────────────
@router.get("/inicio")
def inicio_proveedor(request: Request, db: Session = Depends(get_db)):
    rut_proveedor = request.session.get("proveedor_rut")
    if not rut_proveedor:
        return RedirectResponse(url="/proveedor/login", status_code=303)

    rut_proveedor = normalizar_rut(rut_proveedor)

    proveedor = db.query(Proveedor).filter(Proveedor.rut == rut_proveedor).first()
    
    proveedor_nombre = proveedor.nombre if proveedor else "Desconocido"

    return templates.TemplateResponse(
        "inicio_proveedor.html",
        {
            "request": request,
            "proveedor_rut": rut_proveedor,
            "proveedor_nombre": proveedor_nombre
        }
    )

# ─────────────────────────  Facturas del proveedor ──────────────────────────
@router.get("/facturas")
def ver_facturas_proveedor(request: Request, db: Session = Depends(get_db), msg: str = None):
    rut_proveedor = request.session.get("proveedor_rut")
    if not rut_proveedor:
        return RedirectResponse(url="/proveedor/login", status_code=303)
    
    rut_normalizado = normalizar_rut(rut_proveedor)

    # Obtener el proveedor por su RUT
    proveedor = db.query(Proveedor).filter_by(rut = rut_normalizado).first()
    if not proveedor:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    nombre = proveedor.nombre
    print(">> RUT normalizado del proveedor logeado:", rut_normalizado)
    print(">> PROVEEDOR LOGEADO:", nombre, rut_normalizado)

    # Buscar todas las facturas en que el proveedor es emisor (aunque las haya subido el pagador)
    facturas = (
        db.query(FacturaDB)
        .options(
            joinedload(FacturaDB.ofertas)
            .joinedload(OfertaFinanciamiento.financiador)
        )
        .filter(FacturaDB.rut_emisor.in_([rut_normalizado, rut_normalizado.replace("-", "")]))
        .all()
    )
    print(">> Facturas encontradas para el RUT:", rut_normalizado)
    for f in facturas:
        print(f"   - Folio: {f.folio}, Estado: {f.estado_dte or 'None'}")
    
    facturas_cargadas = [f for f in facturas if f.estado_dte == "Cargada"]

    facturas_pendientes = [
        f for f in facturas if f.estado_dte in [
            "Confirmación solicitada al pagador",
            "Rechazada por pagador"
        ]
    ]
    print("▶ FACTURAS CONFIRMADAS:")
    facturas_confirmadas = [
        f for f in facturas if f.estado_dte in [
            "Confirmada por pagador",
        ]
    ]
    for f in facturas_confirmadas:
        print(f"   - Folio: {f.folio}, Estado: {f.estado_dte}")

    facturas_confirming = [
    f for f in facturas 
    if f.estado_dte in ["Confirming solicitado", "Enviado a confirming"]
    ]

    # NUEVO: adjudicadas
    facturas_adjudicadas = [
    f for f in facturas
    if f.estado_dte == "Confirming adjudicado"
]

    ofertas_por_factura = {f.folio: f.ofertas for f in facturas}
    print(f">> Total facturas confirmadas visibles en frontend: {len(facturas_confirmadas)}")

    
    

    return templates.TemplateResponse(
        "facturas.html",
        {
            "request": request,
            "facturas": facturas,
            "facturas_cargadas": facturas_cargadas,
            "facturas_pendientes": facturas_pendientes,
            "facturas_confirmadas": facturas_confirmadas,
            "facturas_confirming": facturas_confirming,
            "facturas_adjudicadas": facturas_adjudicadas,
            "ofertas_por_factura": ofertas_por_factura,
            "proveedor_nombre": nombre,
            "total_cargadas": len(facturas_cargadas),
            "total_pendientes": len(facturas_pendientes),
            "total_confirmadas": len(facturas_confirmadas),
            "total_confirming": len(facturas_confirming),
            "total_adjudicadas": len(facturas_adjudicadas)
        }
    )

@router.post("/facturas")
async def subir_factura_archivo(
    request: Request,
    archivo: UploadFile = Form(...),
    db: Session = Depends(get_db)
):
    rut_proveedor = request.session.get("proveedor_rut")
    if not rut_proveedor:
        return RedirectResponse(url="/proveedor/login", status_code=303)

    rut_normalizado = normalizar_rut(rut_proveedor)
    proveedor = db.query(Proveedor).filter(Proveedor.rut == rut_normalizado).first()
    if not proveedor:
        return RedirectResponse(url="/proveedor/login", status_code=303)
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
            rut_emisor = normalizar_rut(root.find(".//RUTEmisor").text)
            rut_receptor = normalizar_rut(root.find(".//RUTRecep").text)

            # Validación de consistencia con el proveedor logeado
            if rut_emisor != rut_normalizado:
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
                proveedor_id=proveedor.id
            )
            db.add(factura)
            db.commit()
        except Exception as e:
            errores.append(f"Error en {nombre}: {e}")

    facturas = db.query(FacturaDB).filter(FacturaDB.rut_emisor == rut_normalizado).all()
    return templates.TemplateResponse(
        "facturas.html",
        {
            "request": request,
            "facturas": facturas,
            "errores": errores or None,
            "proveedor_nombre": proveedor_nombre
        }
    )


@router.post("/solicitar_confirmacion/folio/{folio}")
def solicitar_confirmacion_factura_folio(folio: int, request: Request, db: Session = Depends(get_db)):
    rut_proveedor = request.session.get("proveedor_rut")
    if not rut_proveedor:
        return RedirectResponse("/proveedor/login", 303)

    rut_normalizado = normalizar_rut(rut_proveedor)

    # Buscar la factura por folio y rut_emisor
    factura = db.query(FacturaDB).filter(
        FacturaDB.folio == folio,
        FacturaDB.rut_emisor == rut_normalizado
    ).first()

    if factura:
        factura.estado_dte = "Confirmación solicitada al pagador"
        factura.confirming_solicitado = True
        factura.origen_confirmacion = "Proveedor"
        db.commit()

    return RedirectResponse(url="/proveedor/facturas", status_code=303)

@router.post("/solicitar_confirmacion/ajax/{folio}")
def solicitar_confirmacion_ajax(folio: int, request: Request, db: Session = Depends(get_db)):
    rut_proveedor = request.session.get("proveedor_rut")
    if not rut_proveedor:
        raise HTTPException(status_code=401, detail="No autenticado")

    rut_normalizado = normalizar_rut(rut_proveedor)

    factura = db.query(FacturaDB).filter(
        FacturaDB.folio == folio,
        FacturaDB.rut_emisor == rut_normalizado
    ).first()

    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    factura.estado_dte = "Confirmación solicitada al pagador"
    factura.confirming_solicitado = True
    factura.origen_confirmacion = "Proveedor"
    db.commit()

    return {
        "success": True,
        "folio": folio,
        "nuevo_estado": factura.estado_dte
    }

@router.post("/solicitar_confirming/folio/{folio}")
def solicitar_confirming_folio(folio: int, request: Request, db: Session = Depends(get_db)):
    rut_proveedor = request.session.get("proveedor_rut")
    print(">> RUT DE SESIÓN OBTENIDO:", rut_proveedor)
    if not rut_proveedor:
        return RedirectResponse("/proveedor/login", 303)

    rut_normalizado = normalizar_rut(rut_proveedor)
    print(">> RUT desde sesión (antes de normalizar):", rut_proveedor)
    print(">> RUT normalizado:", rut_normalizado)

    factura = (
        db.query(FacturaDB)
        .filter(FacturaDB.folio == folio, FacturaDB.rut_emisor.in_([rut_normalizado, rut_normalizado.replace("-", "")]))
        .first()
    )

    if not factura:
        print(">> No se encontraron facturas para este folio y RUT")
        return RedirectResponse("/proveedor/facturas?err=no_factura", 303)
    print(f">> Estado actual folio {folio}: {factura.estado_dte}")

    # ✅ Solo permite solicitar confirming desde “Confirmada por pagador”
    if (factura.estado_dte or"").strip() == "Confirmada por pagador":
        print(">> No se solicitó confirming: estado no es 'Confirmada por pagador'")
        factura.estado_dte = "Confirming solicitado"
        factura.confirming_solicitado = True
        factura.origen_confirmacion = "Proveedor"
        print(f">> Se solicitó confirming para folio {factura.folio}")
            
        db.add(factura)
        db.commit()
        db.refresh(factura)
        
        print(f"[SC] después -> folio={factura.folio} estado={repr(factura.estado_dte)} confirming={factura.confirming_solicitado}")
        return RedirectResponse("/proveedor/facturas?msg=confirming_solicitado", 303)
    else:
        print(f"[SC] estado no permitido: {repr(factura.estado_dte)}")
        return RedirectResponse("/proveedor/facturas?warn=estado_invalido", 303)
        
@router.post("/rechazar_vencimiento/folio/{folio}")
def rechazar_vencimiento_folio(folio: int, request: Request, db: Session = Depends(get_db)):
    rut_proveedor = request.session.get("proveedor_rut")
    if not rut_proveedor:
        return RedirectResponse("/proveedor/facturas?msg=confirming_solicitado", 303)

    
    rut_normalizado = normalizar_rut(rut_proveedor)
    
    factura = (
        db.query(FacturaDB)
        .filter(FacturaDB.folio == folio, FacturaDB.emisor_id == rut_normalizado)
        .first()
    )
    if factura and factura.estado_dte == "Confirmada por pagador":
        factura.estado_dte = "Vencimiento rechazado por proveedor"
        db.commit()

    return RedirectResponse("/proveedor/facturas", 303)


@router.get("/ofertas-folio/{folio}")
def ver_ofertas_por_folio(folio: int, request: Request, db: Session = Depends(get_db)):
    rut_proveedor = request.session.get("proveedor_rut")
    if not rut_proveedor:
        return RedirectResponse("/proveedor/login", 303)

    rut_normalizado = normalizar_rut(rut_proveedor)

    factura = db.query(FacturaDB).filter(FacturaDB.folio == folio, FacturaDB.rut_emisor == rut_normalizado).first()
    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    
    if factura.estado_dte != "Confirming solicitado":
        raise HTTPException(status_code=400, detail="La factura ya fue adjudicada o aún no solicitada")

    # 🔧 Mejora: Trae el financiador y su fondo directamente
    ofertas = (
        db.query(OfertaFinanciamiento)
          .options(
              joinedload(OfertaFinanciamiento.financiador)
              .joinedload(Financiador.fondo)
          )
          .filter_by(OfertaFinanciamiento.factura_id == factura.id)
          .order_by(OfertaFinanciamiento.tasa_interes.asc())
          .all()
    )

    # Flag para deshabilitar botón si ya fue adjudicada
    bloqueado = (factura.estado_dte == "Confirming adjudicado")

    return templates.TemplateResponse(
        "ofertas_proveedor.html",
        {
            "request": request,
            "factura": factura,
            "ofertas": ofertas,
            "bloqueado": bloqueado
        }
    )

@router.post("/aceptar-oferta/{oferta_id}")
def aceptar_oferta(oferta_id: int, request: Request, db: Session = Depends(get_db)):
    rut_prov = request.session.get("proveedor_rut")
    if not rut_prov:
        return RedirectResponse("/proveedor/login", 303)

    rut_normalizado = normalizar_rut(rut_prov)

    # 1) Cargar oferta y su factura
    oferta = db.query(OfertaFinanciamiento).get(oferta_id)
    if not oferta:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")

    factura = oferta.factura
    if not factura:
        raise HTTPException(status_code=404, detail="Factura asociada no encontrada")

    # 2) Seguridad: la factura debe pertenecer al proveedor logeado
    if normalizar_rut(factura.rut_emisor) != rut_normalizado:
        raise HTTPException(status_code=403, detail="No autorizado")

    # 3) Marcar oferta adjudicada
    oferta.estado = "Adjudicada"

    # 4) Marcar el resto de ofertas de ESTA factura como no adjudicadas
    db.query(OfertaFinanciamiento).filter(
        OfertaFinanciamiento.factura_id == factura.id,
        OfertaFinanciamiento.id != oferta_id
    ).update({"estado": "No adjudicada"}, synchronize_session=False)

    # 5) Actualizar la factura
    factura.financiador_adjudicado = oferta.financiador_id  # INTEGER -> INTEGER
    factura.estado_dte = "Confirming adjudicado"

    db.commit()

    # 6) (Opcional) refrescar si quieres loguear
    # db.refresh(factura); db.refresh(oferta)

    return RedirectResponse(f"/proveedor/facturas?tab=adjudicadas&msg=oferta_adjudicada", status_code=303)

@router.get("/importar_sii_facturas")
@router.post("/importar_sii_facturas")
def importar_facturas_sii(request: Request, db: Session = Depends(get_db)):
    rut_prov = request.session.get("proveedor_rut")
    if not rut_prov:
        return RedirectResponse("/proveedor/login", 303)

    rut_normalizado = normalizar_rut(rut_prov)
    
    proveedor = db.query(Proveedor).filter(Proveedor.rut == rut_normalizado).first()
    if not proveedor:
        return templates.TemplateResponse("error.html", {"request": request, "mensaje": "Proveedor no encontrado"})
    
    rut_base = rut_normalizado[:-1]  # Ej: '76262370'
    nombre = proveedor.nombre
    print(f"Proveedor logeado: {nombre} (RUT original: {proveedor.rut})")

    periodo = datetime.now().strftime("%Y-%m")
    json_path = f"selenium_scripts/facturas_sii/data/detalle_{rut_base}_{periodo}.json"

    print(f"🧪 Importando desde JSON: {json_path}")
    print(f"Proveedor logeado: {proveedor.nombre} (RUT original: {proveedor.rut})")

    if not os.path.exists(json_path):
        print("❌ No existe el archivo JSON esperado")
        return templates.TemplateResponse("facturas.html", {
            "request": request,
            "errores": [f"No se encontró el archivo {json_path}"],
            "facturas": [],
            "proveedor_nombre": proveedor.nombre
        })

    import json
    with open(json_path, "r", encoding="utf-8") as f:
        facturas_data = json.load(f)

    print(f"📄 JSON cargado correctamente. Total facturas encontradas: {len(facturas_data)}")

    errores = []
    nuevas_facturas = []
    facturas_descartadas = []

    # Formatos de fecha que usa el JSON del SII
    FMT_DOC = "%d/%m/%Y"
    FMT_RECEP = "%d/%m/%Y %H:%M:%S"

    for d in facturas_data:
        if not isinstance(d, dict):
            errores.append(f"Entrada inválida ignorada: {d}")
            continue

        # 💣 Filtro: excluir facturas con forma de pago "Contado"
        if d.get("detFormaPagoLeyenda", "").strip().lower() == "contado":
            continue  # se omite la carga de esta factura

        try:
            folio = int(d["detNroDoc"])
            rut_emisor = proveedor.rut
            rut_receptor = normalizar_rut(f"{d['detRutDoc']}-{d['detDvDoc']}")

            # Validación: solo subir si el proveedor logeado es el emisor
            if rut_emisor != proveedor.rut:
                errores.append(f"⚠️ RUT emisor {rut_emisor} no coincide con proveedor logeado ({proveedor.rut})")
                continue

            duplicada = db.query(FacturaDB).filter_by(
                rut_emisor=rut_emisor, rut_receptor=rut_receptor, folio=folio
            ).first()
            if duplicada:
                errores.append(f"Factura duplicada folio {folio}")
                continue

            # -------- Fechas --------
            # Emisión (obligatoria en el JSON)
            fecha_emision = datetime.strptime(d["detFchDoc"], FMT_DOC).date()

            # Recepción (puede venir con hora; si no parsea, intentamos sin hora)
            fecha_recepcion = None
            recep_raw = d.get("detFecRecepcion")
            if recep_raw:
                parsed = None
                for fmt in (FMT_RECEP, FMT_DOC):
                    try:
                        parsed = datetime.strptime(recep_raw, fmt)
                        break
                    except ValueError:
                        pass
                    if parsed: 
                        fecha_recepcion = parsed.date()
            # Regla de negocio (ley 30 días):
            # - Si hay fecha de recepción => vencimiento_original = recepción + 30
            # - Si no hay recepción => vencimiento_original = emisión + 30
            base_para_venc = fecha_recepcion or fecha_emision
            fecha_vencimiento_original = base_para_venc + timedelta(days=30)

            # Inicialmente, el vencimiento vigente es igual al original
            fecha_vencimiento = fecha_vencimiento_original

            factura = FacturaDB(
                rut_emisor=rut_emisor,
                rut_receptor=rut_receptor,
                tipo_dte=str(d.get("detTipoDoc", "")),
                folio=folio,
                monto=int(d["detMntTotal"]),
                razon_social_emisor=proveedor.nombre,
                razon_social_receptor=d.get("detRznSoc", "Desconocido"),

                fecha_emision=fecha_emision,
                fecha_vencimiento=fecha_vencimiento,
                fecha_vencimiento_original=fecha_vencimiento_original,

                estado_dte="Cargada",
                confirming_solicitado=False,
                origen_confirmacion="SII",

                # Guarda el ID del proveedor (⚠️ no el RUT)
                proveedor_id=proveedor.id,

                # Opcional: guarda campos del SII si los usas en otras vistas
                detEventoReceptor=d.get("detEventoReceptor"),
                detEventoReceptorLeyenda=d.get("detEventoReceptorLeyenda"),
                dias_desde_emision=(date.today() - fecha_emision).days
            )

            db.add(factura)
            nuevas_facturas.append(factura)
        
        except Exception as e:
            errores.append(f"Error en folio {d.get('detNroDoc', 'desconocido')}: {e}")
            print(f"! Error en folio {d.get('detNroDoc')}: {e}")

    db.commit()

    # Calcula cantidad de facturas nuevas para el mensaje
    cant_nuevas = len(nuevas_facturas)
    params = urlencode({"msg": f"Se importaron {cant_nuevas} factura(s) correctamente"})
    
    return RedirectResponse(
        url=f"/proveedor/facturas?msg={params}",
        status_code=303
    )

@router.get("/ofertas-folio/{folio}")
def ver_ofertas_factura_por_folio(
    folio: int,
    request: Request,
    db: Session = Depends(get_db)
):
    rut_prov = request.session.get("proveedor_rut")
    if not rut_prov:
        return RedirectResponse("/proveedor/login", 303)

    rut_normalizado = normalizar_rut(rut_prov)

    # 1) Buscar la factura por folio Y proveedor logeado (RUT completo, sin cortar DV)
    factura = (
        db.query(FacturaDB)
        .filter(FacturaDB.folio == folio, FacturaDB.rut_emisor == rut_normalizado[:-1])  
          .first()
    )

    if not factura:
        raise HTTPException(status_code=404, detail="Factura no encontrada")

    # 2) Permitir ver ofertas si está "Confirming solicitado" o "Confirming adjudicado"
    if factura.estado_dte != "Confirming solicitado":
        raise HTTPException(status_code=400, detail="La factura no está habilitada para ver ofertas")

    # 3) Traer ofertas + financiador + fondo
    ofertas = (
        db.query(OfertaFinanciamiento)
          .options(
              joinedload(OfertaFinanciamiento.financiador)
              .joinedload(Financiador.fondo)
          )
          .filter_by(factura_id=factura.id)
          .order_by(OfertaFinanciamiento.tasa_interes.asc())
          .all()
    )

    # 4) Recalcular métricas conforme al vencimiento VIGENTE (pagador manda)
    hoy = date.today()
    dias_vigentes = 0
    if factura.fecha_vencimiento:
        dias_vigentes = max((factura.fecha_vencimiento - hoy).days, 0)

    for o in ofertas:
        tasa_total_mensual = (o.tasa_interes or 0) + (o.financiador.costo_fondos_mensual or 0)
        tasa_diaria = tasa_total_mensual / 30.0

        monto = factura.monto or 0
        comision = o.comision_flat or 0
        descuento = monto * tasa_diaria * dias_vigentes
        precio_cesion_calc = int(round(monto - descuento - comision))

        # Campos "transitorios" para que el template los use
        o._dias_vigentes = dias_vigentes
        o._tasa_total_mensual = tasa_total_mensual
        o._precio_cesion_calc = precio_cesion_calc

    # 5) Flag para deshabilitar botón si ya está adjudicada
    bloqueado = (factura.estado_dte == "Confirming adjudicado")

    return templates.TemplateResponse(
        "ofertas_proveedor.html",
        {
            "request": request,
            "factura": factura,
            "ofertas": ofertas,
            "bloqueado": bloqueado,
            "hoy": hoy,
        }
    )
    
    