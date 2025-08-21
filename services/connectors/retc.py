# services/connectors/retc.py
import aiohttp, asyncio, unicodedata, json, math, time
from typing import Dict, Any, List

RETC_DATASTORE = "https://datosretc.mma.gob.cl/api/3/action/datastore_search"
RETC_RESOURCE_ID = "d1682353-3e5f-4100-9a53-f4b9650e2984"  # Establecimientos industriales
RETC_RESOURCE_URL = f"https://datosretc.mma.gob.cl/dataset/establecimientos/resource/{RETC_RESOURCE_ID}"

# cache simple en memoria (clave = razon_normalizada)
_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 7 * 24 * 3600  # 7 días

def _strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def _norm_nombre(s: str) -> str:
    if not s:
        return ""
    s = s.upper().strip()
    s = _strip_accents(s)
    # quitar puntuación y denominaciones
    for tok in [" S.A.", " SA ", " LTDA ", " LIMITADA ", " SOCIEDAD ANONIMA ",
                " CIA ", " COMPANIA ", ".", ",", ";", "  "]:
        s = s.replace(tok, " ")
    s = " ".join(s.split())
    return s

def _to_float(x) -> float:
    try:
        if x is None or x == "":
            return 0.0
        return float(x)
    except Exception:
        return 0.0

def _badge_number(val: float, *, prefer_int=False) -> str:
    if prefer_int:
        return f"{int(round(val)):,}".replace(",", ".")
    # gases: 1 decimal si <100; si no, entero
    if val < 100:
        return f"{val:.1f}".rstrip("0").rstrip(".")
    return f"{int(round(val)):,}".replace(",", ".")

async def _retc_query(params: Dict[str, Any]) -> Dict[str, Any]:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
        async with s.get(RETC_DATASTORE, params=params) as r:
            r.raise_for_status()
            return await r.json()

def _best_matches(records: List[Dict[str, Any]], target_norm: str) -> List[Dict[str, Any]]:
    """filtra por similitud de nombre (campo 'Razón social' o 'Empresa')"""
    out = []
    for rec in records:
        nombre = rec.get("Razón social") or rec.get("Empresa")
        n = _norm_nombre(str(nombre) if nombre else "")
        # coincidencia exacta o empieza por…
        if n == target_norm or (target_norm and n.startswith(target_norm)):
            out.append(rec)
    return out

async def fetch_emisiones_totales_por_razon_social(razon_social: str, *, limit: int = 1000, force: bool = False) -> Dict[str, Any]:
    """
    Retorna totales por tipo de emisión para una razón social:
    {
      ok: bool,
      etiqueta: "RETC 2019 · CO2: X t/año · NOx: Y t/año · ... (N est.)",
      totales: {co2, nox, so2, mp, res_pelig, res_no_pelig},
      n_est: int,
      evidencia_url: <link recurso>,
      matches: [ .. filas resumidas .. ]
    }
    """
    if not razon_social:
        return {"ok": False, "etiqueta": "Sin datos RETC", "totales": {}, "n_est": 0, "evidencia_url": RETC_RESOURCE_URL, "matches": []}

    key = _norm_nombre(razon_social)
    now = time.time()
    if not force and key in _cache and now - _cache[key]["ts"] < _CACHE_TTL:
        return _cache[key]["data"]

    # 1) intento exacto con filters
    params = {
        "resource_id": RETC_RESOURCE_ID,
        "filters": json.dumps({"Razón social": razon_social}),
        "limit": limit,
    }
    try:
        j = await _retc_query(params)
    except Exception:
        j = {"result": {"total": 0, "records": []}}

    records = j.get("result", {}).get("records", []) or []

    # 2) si vacío, búsqueda por q y filtrado local
    if not records:
        params2 = {"resource_id": RETC_RESOURCE_ID, "q": razon_social, "limit": limit}
        try:
            j2 = await _retc_query(params2)
            rec2 = j2.get("result", {}).get("records", []) or []
        except Exception:
            rec2 = []
        records = _best_matches(rec2, key)

    if not records:
        data = {"ok": False, "etiqueta": "Sin datos RETC", "totales": {}, "n_est": 0, "evidencia_url": RETC_RESOURCE_URL, "matches": []}
        _cache[key] = {"ts": now, "data": data}
        return data

    # 3) agregación
    co2 = sum(_to_float(r.get("CO2")) for r in records)
    nox = sum(_to_float(r.get("NOX")) for r in records)
    so2 = sum(_to_float(r.get("SO2")) for r in records)
    mp  = sum(_to_float(r.get("MP"))  for r in records)
    respel   = sum(_to_float(r.get("RESPEL"))   for r in records)
    resnopel = sum(_to_float(r.get("RESONOPEL")) for r in records)

    n_est = len(records)

    # 4) etiqueta compacta (2019 es el año de este recurso)
    etiqueta = (
        f"RETC 2019 · "
        f"CO₂: {_badge_number(co2)} t/año · "
        f"NOx: {_badge_number(nox)} t/año · "
        f"SO₂: {_badge_number(so2)} t/año · "
        f"MP: {_badge_number(mp)} t/año · "
        f"Res. Pelig.: {_badge_number(respel, prefer_int=True)} t/año · "
        f"Res. No Pelig.: {_badge_number(resnopel, prefer_int=True)} t/año "
        f"· ({n_est} est.)"
    )

    # matches resumidos para tabla (si quieres mostrar detalle)
    matches = []
    for r in records:
        matches.append({
            "rut": r.get("RUT") or None,
            "razon_social": r.get("Razón social") or r.get("Empresa"),
            "establecimiento": r.get("Nombre de Establecimiento") or r.get("Establecim"),
            "comuna": r.get("Comuna"),
            "region": r.get("Región") or r.get("Region"),
            "rubro": r.get("Rubro RETC") or r.get("Rubro"),
        })

    data = {
        "ok": True,
        "etiqueta": etiqueta,
        "totales": {
            "co2": co2, "nox": nox, "so2": so2, "mp": mp,
            "res_pelig": respel, "res_no_pelig": resnopel
        },
        "n_est": n_est,
        "evidencia_url": RETC_RESOURCE_URL,
        "matches": matches,
    }
    _cache[key] = {"ts": now, "data": data}
    return data