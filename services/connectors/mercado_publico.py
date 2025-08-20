# services/connectors/mercado_publico.py
import os
import httpx
from dotenv import load_dotenv

print("[MP] modulo cargado desde:", __file__)
load_dotenv(override=True)

# Trae emisores de token (no toco tu provider)
from services.connectors.token_provider import get_prd_token, get_da_token

BASE_PRD = "https://servicios-prd.mercadopublico.cl"
BASE_DA  = "https://mserv-datos-abiertos.chilecompra.cl"


def _rut_for_api(r: str) -> str:
    """Normaliza RUT para endpoints MP: sin puntos y con guion final."""
    s = (r or "").replace(".", "").strip()
    if "-" not in s and len(s) > 1:
        s = f"{s[:-1]}-{s[-1]}"
    return s


# =======================
#  Headers / HTTP helpers
# =======================
async def _headers_prd() -> dict:
    """
    Usa BEARER_TOKEN_PRD del entorno si existe; si no, intenta get_prd_token().
    No levanta excepción; loggea y retorna Authorization vacío si no hay token.
    """
    tok_env = (os.getenv("BEARER_TOKEN_PRD") or "").strip()
    used = "ENV"
    tok = tok_env
    if not tok:
        try:
            tok = await get_prd_token()
            used = "AUTO" if tok else "NONE"
        except Exception as e:
            print(f"[MP] get_prd_token() error: {e}")
            tok = ""

    ok = bool(tok)
    print(f"[MP] PRD bearer? {ok} src={used} len={len(tok) if ok else 0}")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Pagador360",
    }
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


async def _headers_da() -> dict:
    """
    Datos Abiertos: intenta token (si tienes client_credentials). Si no, va sin Authorization.
    """
    tok = ""
    try:
        tok = await get_da_token() or ""
    except Exception as e:
        print(f"[MP] get_da_token() error: {e}")
    print(f"[MP] DA  bearer? {bool(tok)} len={len(tok) if tok else 0}")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Pagador360",
    }
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers


async def _get_json_prd(path: str):
    """GET a PRD; nunca levanta excepción. Devuelve dict suave con 'ok' en errores."""
    url = BASE_PRD + path
    headers = await _headers_prd()

    # Si no hay bearer, evita el 401 inútil
    if not headers.get("Authorization"):
        print(f"[MP] SKIP {url} -> missing bearer")
        return {"ok": False, "error": "missing_bearer", "payload": None}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers=headers)
        body_preview = (r.text or "")[:180].replace("\n", " ")
        print(f"[MP] GET {url} -> {r.status_code} body[:180]='{body_preview}'")
        if r.status_code >= 400:
            return {"ok": False, "status": r.status_code, "raw": r.text, "payload": None}
        try:
            return r.json()
        except Exception:
            return {"ok": False, "status": r.status_code, "raw": r.text, "payload": None}


async def _get_json_da(path: str):
    """GET a Datos Abiertos; intenta reintentar en 401 si renuevas token dentro de get_da_token()."""
    url = BASE_DA + path
    async with httpx.AsyncClient(timeout=30) as client:
        headers = await _headers_da()
        r = await client.get(url, headers=headers)
        body_preview = (r.text or "")[:180].replace("\n", " ")
        print(f"[MP] GET {url} -> {r.status_code} body[:180]='{body_preview}'")

        if r.status_code == 401:
            print("[MP] 401 DA: renovando token y reintentando…")
            headers = await _headers_da()
            r = await client.get(url, headers=headers)
            body_preview = (r.text or "")[:180].replace("\n", " ")
            print(f"[MP] RETRY {url} -> {r.status_code} body[:180]='{body_preview}'")

        if r.status_code >= 400:
            return {"ok": False, "status": r.status_code, "raw": r.text}
        try:
            return r.json()
        except Exception:
            return {"ok": False, "status": r.status_code, "raw": r.text}


# ============================
#  Consolidadores para la vista
# ============================
async def fetch_mp_core(rut_norm: str) -> dict:
    """
    Consolida datos esenciales de MP + Datos Abiertos para la Ficha 360.
    Siempre retorna un dict con las llaves esperadas por el template.
    """
    rut_api = _rut_for_api(rut_norm)

    # Defaults (nunca faltan claves)
    sellos_list = []
    ent_code = None
    habilitado = None
    score_promedio = None
    oc_24m = 0
    razon = None
    fantasia = None
    ventas_12m = 0
    rango = None

    # ---- SELL0S (PRD) ----
    sellos_json = await _get_json_prd(f"/v1/sello/sellos-proveedor/{rut_api}")
    if isinstance(sellos_json, dict) and (sellos_json.get("success") == "OK"):
        sellos_list = ((sellos_json.get("payload") or {}).get("sellos") or []) or []
        if sellos_list and isinstance(sellos_list[0], dict):
            ent_code = sellos_list[0].get("entCode") or ent_code

    # ---- ESTADO/HABIL + identidad (PRD) ----
    estado_json = await _get_json_prd(f"/v3/proveedor/estado/{rut_api}/0")
    if isinstance(estado_json, dict) and (estado_json.get("success") == "OK"):
        p = estado_json.get("payload") or {}
        hp = (p.get("habilidadProveedor") or "").strip().upper()
        habilitado = True if hp == "HABIL" else False if hp else None
        razon = p.get("razonSocial") or razon
        fantasia = p.get("nombreFantasia") or fantasia

    # ---- SUMMARY (PRD): score y oc24 ----
    sum_json = await _get_json_prd(f"/v1/proveedor/summaryficha/{rut_api}")
    if isinstance(sum_json, dict) and (sum_json.get("success") == "OK"):
        p = sum_json.get("payload") or {}
        score_promedio = p.get("comportamientoContractual")  # 0..5
        oc_24m = p.get("oc24meses") or 0

    # ---- Datos Abiertos: ventas 12m ----
    da_json = await _get_json_da(f"/v1/organismSupplier/get12MesesVentasProveedor/{rut_api}")
    if isinstance(da_json, dict):
        pr = da_json.get("payload") or {}
        ventas_12m = int(pr.get("montoUltimos12Meses") or pr.get("montoTotal") or 0)
        if pr.get("agno1") and pr.get("agno2"):
            rango = {
                "agno1": pr.get("agno1"),
                "nroMes1": pr.get("nroMes1"),
                "agno2": pr.get("agno2"),
                "nroMes2": pr.get("nroMes2"),
            }

    res = {
        "ok": True,                              # el consolidado no rompe aunque falte algo
        "registrado": bool(sellos_list),
        "habilitado": habilitado,               # None/True/False
        "score": score_promedio,                # alias
        "score_promedio": score_promedio,       # compat template
        "ventas_12m": ventas_12m or 0,
        "rango": rango,                         # dict o None
        "sellos": sellos_list or [],
        "razon_social": razon,
        "nombre_fantasia": fantasia,
        "oc_24m": oc_24m or 0,
        "entCode": ent_code,
    }

    print(
        f"[MP360] ok={res['ok']} hab={res['habilitado']} "
        f"score={res['score_promedio']} ventas12m={res['ventas_12m']} "
        f"sellos={len(res['sellos'])} entCode={res['entCode']}"
    )
    return res


async def fetch_mp_ficha_basica(rut_norm: str) -> dict:
    """
    Variante que también intenta sacar razón social/nombre fantasía desde 'ficha/direccion'.
    Retorna llaves con nombres ligeramente distintos para el rango de ventas (rango_ventas).
    """
    rut_api = _rut_for_api(rut_norm)

    def _ok_dict(d):
        return d if isinstance(d, dict) else {}

    def _payload_ok(d):
        d = _ok_dict(d)
        return d.get("payload") or {}

    # Identidad desde 'ficha/direccion'
    ficha_json = await _get_json_prd(f"/v1/proveedor/ficha/direccion/{rut_api}/0")
    razon_social = None
    nombre_fantasia = None
    habil_str = None
    if isinstance(ficha_json, dict) and ficha_json.get("success") == "OK":
        fp = ficha_json.get("payload") or {}
        razon_social = fp.get("razonSocial")
        nombre_fantasia = fp.get("nombreFantasia")
        habil_str = fp.get("habilidadProveedor")

    # Sellos
    sellos_json = await _get_json_prd(f"/v1/sello/sellos-proveedor/{rut_api}")
    sellos_payload = _payload_ok(sellos_json)
    sellos_list = sellos_payload.get("sellos") or []

    codigo_empresa = None
    if sellos_list and isinstance(sellos_list[0], dict):
        codigo_empresa = sellos_list[0].get("entCode")

    # Estado/habilitación (otra fuente)
    estado_json = await _get_json_prd(f"/v3/proveedor/estado/{rut_api}/0")
    estado_payload = {}
    habilitado = None
    registrado = False
    if isinstance(estado_json, dict) and estado_json.get("success") == "OK":
        estado_payload = estado_json.get("payload") or {}
        registrado = True
        if isinstance(estado_payload, dict) and "habilitado" in estado_payload:
            habilitado = estado_payload.get("habilitado")

    # Score + oc24 + monto mp
    sum_json = await _get_json_prd(f"/v1/proveedor/summaryficha/{rut_api}")
    score_promedio = None
    oc_24m = None
    monto_mp = None
    if isinstance(sum_json, dict) and sum_json.get("success") == "OK":
        sp = sum_json.get("payload") or {}
        score_promedio = sp.get("comportamientoContractual")
        oc_24m = sp.get("oc24meses")
        monto_mp = sp.get("montoMP")

    # Ventas DA
    v12_json = await _get_json_da(f"/v1/organismSupplier/get12MesesVentasProveedor/{rut_api}")
    ventas_12m = 0
    rango_ventas = {}
    if isinstance(v12_json, dict):
        p = v12_json.get("payload") or {}
        monto = p.get("montoUltimos12Meses", p.get("montoTotal"))
        ventas_12m = int((monto or 0) or 0)
        rango_ventas = {
            "agno1":   p.get("agno1"),
            "nroMes1": p.get("nroMes1"),
            "agno2":   p.get("agno2"),
            "nroMes2": p.get("nroMes2"),
        }

    ok_flag = bool(sellos_list or (score_promedio is not None) or ventas_12m)

    result = {
        "ok": ok_flag,
        "registrado": registrado,
        "habilitado": habilitado,
        "habil_str": habil_str,
        "score_promedio": score_promedio,
        "sellos": sellos_list,
        "ventas_12m": ventas_12m,
        "rango_ventas": rango_ventas,
        "codigo_empresa": codigo_empresa,
        "razon_social": razon_social,
        "nombre_fantasia": nombre_fantasia,
        "oc_24m": oc_24m,
        "monto_mp": monto_mp,
    }

    print(
        f"[MP360] MP ok={result['ok']} reg={result['registrado']} "
        f"hab={result['habilitado']} score={result['score_promedio']} "
        f"ventas={result['ventas_12m']} sellos={len(result['sellos'])}"
    )
    return result


# ==========================
#  Compatibilidad con router
# ==========================
# Alias para no tocar routers antiguos:
fetch_mp_minimo = fetch_mp_core


def build_mp_context(mp: dict) -> dict:
    """
    Helper opcional para el router:
    arma mp_oc/mp_adj/mp_ventas coherentes con el template.
    """
    mp = mp or {}
    mp_oc = {"ok": False, "resumen": {"cantidad": 0, "monto_neto_total": 0}, "items": []}
    mp_adj = {"ok": False, "resumen": {"cantidad": 0, "monto_adjudicado_total": 0}, "items": []}
    mp_ventas = {
        "ok": bool(mp.get("rango") or mp.get("rango_ventas")),
        "ventas_mp_ultimo_anio": mp.get("ventas_12m") or 0,
        "rango": mp.get("rango") or mp.get("rango_ventas") or {},
    }
    return {"mp_oc": mp_oc, "mp_adj": mp_adj, "mp_ventas": mp_ventas}
