# services/connectors/snifa.py
# Conector a datos abiertos de la SMA (SNIFA) vía CKAN
# - Resume: fiscalizaciones, procedimientos activos y sanciones firmes
# - Filtros por RUT y/o razón social (con defensas por columnas variables)
# - Devuelve contadores + algunas filas de muestra + URLs de evidencia

from __future__ import annotations
import aiohttp, asyncio, os, json, unicodedata, time
from typing import Dict, Any, List, Optional, Tuple

# Puedes sobreescribir la URL vía variable de entorno:
# export SNIFA_CKAN_BASE="https://<tu-endpoint-ckan>/api/3/action"
CKAN_BASE = os.getenv("SNIFA_CKAN_BASE", "https://datos.sma.gob.cl/api/3/action")

# Intento de slugs (pueden variar según el portal). Si alguno falla,
# el conector intenta buscar paquetes por palabras clave.
PKG_HINTS: Dict[str, List[str]] = {
    # clave interna -> posibles slugs o keywords para buscar
    "fiscalizaciones": [
        "fiscalizaciones",
        "fiscalizacion",
        "inspecciones",
        "fiscalizaciones-ambientales",
        "snifa-fiscalizaciones",
    ],
    "sancionatorios": [
        "procedimientos-sancionatorios",
        "sancionatorios",
        "snifa-procedimientos-sancionatorios",
        "expedientes-sancionatorios",
    ],
    "sanciones_firmes": [
        "sanciones-firmes",
        "resoluciones-sancionatorias-firmes",
        "snifa-sanciones-firmes",
    ],
}

# Cache ultra simple en memoria
_cache: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL = 6 * 3600  # 6 horas


# ---------------------------
# Utilidades
# ---------------------------
def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    s = str(s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s.strip().lower()


def _clean_rut(r: Optional[str]) -> str:
    if not r:
        return ""
    r = r.replace(".", "").replace("-", "").strip().upper()
    return r


async def _ckan_get(session: aiohttp.ClientSession, path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    url = f"{CKAN_BASE}/{path}"
    async with session.get(url, params=params or {}, timeout=30) as r:
        r.raise_for_status()
        return await r.json()


async def _package_show(session: aiohttp.ClientSession, pkg_id: str) -> Dict[str, Any]:
    return await _ckan_get(session, "package_show", params={"id": pkg_id})


async def _package_list(session: aiohttp.ClientSession) -> List[str]:
    data = await _ckan_get(session, "package_list")
    return data.get("result", []) or []


async def _resolve_resource_id(session: aiohttp.ClientSession, hints: List[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Intenta resolver un resource_id (datastore activo) a partir de una lista de
    slugs o keywords. Devuelve (resource_id, evidencia_url_dataset).
    """
    # 1) prueba por slug directo
    for slug in hints:
        try:
            pkg = await _package_show(session, slug)
            for res in pkg.get("result", {}).get("resources", []) or []:
                if res.get("datastore_active") is True:
                    rid = res.get("id")
                    evid = f"{CKAN_BASE.replace('/api/3/action','')}/dataset/{pkg['result'].get('name')}"
                    return rid, evid
        except Exception:
            continue

    # 2) si no, busca en package_list por keywords
    try:
        pkgs = await _package_list(session)
        for p in pkgs:
            if any(h in p for h in hints):
                try:
                    pkg = await _package_show(session, p)
                    for res in pkg.get("result", {}).get("resources", []) or []:
                        if res.get("datastore_active") is True:
                            rid = res.get("id")
                            evid = f"{CKAN_BASE.replace('/api/3/action','')}/dataset/{pkg['result'].get('name')}"
                            return rid, evid
                except Exception:
                    continue
    except Exception:
        pass

    return None, None


async def _datastore_search_all(
    session: aiohttp.ClientSession,
    resource_id: str,
    filters: Dict[str, Any] | None = None,
    q: Optional[str] = None,
    limit: int = 2000,
) -> List[Dict[str, Any]]:
    """
    Lee de datastore_search paginando hasta 'limit'.
    Usa 'filters' (match exacto) y/o 'q' (buscador) si corresponde.
    """
    filters_json = json.dumps(filters, ensure_ascii=False) if filters else None
    out, off = [], 0
    while len(out) < limit:
        params = {
            "resource_id": resource_id,
            "limit": min(500, limit - len(out)),
            "offset": off,
        }
        if filters_json:
            params["filters"] = filters_json
        if q:
            params["q"] = q

        data = await _ckan_get(session, "datastore_search", params=params)
        recs = data.get("result", {}).get("records", []) or []
        out.extend(recs)
        if not recs:
            break
        off += len(recs)
    return out


def _record_matches(rec: Dict[str, Any], rut: Optional[str], razon: Optional[str]) -> bool:
    """
    Verifica si un registro calza por RUT y/o razón social.
    Columnas candidatas típicas (pueden variar):
      - para RUT: ["rut", "RUT", "Rut", "RUT Empresa", "RUT Fiscalizado"]
      - para Razón: ["razon social", "Razón social", "Empresa", "Titular", "Nombre"]
    """
    if rut:
        rut_clean = _clean_rut(rut)
        for k in list(rec.keys()):
            kn = _norm(k)
            if "rut" in kn:
                val = _clean_rut(str(rec.get(k, "")))
                if rut_clean and rut_clean == val:
                    # Si además hay razón y no calza, seguimos validando más abajo
                    break
        else:
            # No encontramos columna RUT que calce exacto
            return False

    if razon:
        razon_n = _norm(razon)
        # acepta igual por startswith para tolerar denominaciones
        for k in list(rec.keys()):
            kn = _norm(k)
            if any(w in kn for w in ["razon social", "empresa", "titular", "nombre"]):
                val = _norm(str(rec.get(k, "")))
                if val == razon_n or val.startswith(razon_n):
                    return True
        # Si se pidió RUT y ya calzó por RUT, aceptamos aunque razón no matchee
        return bool(rut)

    # si no se pidió razón (solo RUT) y RUT calzó arriba, aceptamos
    return True


def _pick_cols(rec: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    """elige la primera columna existente de 'candidates'"""
    for c in candidates:
        if c in rec:
            return c
    # intenta modo case-insensitive
    kl = {k.lower(): k for k in rec.keys()}
    for c in candidates:
        if c.lower() in kl:
            return kl[c.lower()]
    return None


def _compact_row(rec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Devuelve una fila 'compacta' para mostrar en la UI sin depender de
    nombres exactos de columnas.
    """
    out = {}
    # fecha
    fecha_col = _pick_cols(rec, ["fecha", "Fecha", "Fecha Fiscalización", "Fecha Notificación", "fecha_inicio", "Fecha Inicio"])
    out["fecha"] = rec.get(fecha_col) if fecha_col else None
    # rut
    rut_col = _pick_cols(rec, ["RUT", "rut", "RUT Empresa", "RUT Fiscalizado"])
    out["rut"] = rec.get(rut_col) if rut_col else None
    # razon
    razon_col = _pick_cols(rec, ["Razón social", "razon social", "Empresa", "Titular", "Nombre"])
    out["razon_social"] = rec.get(razon_col) if razon_col else None
    # unidad / establecimiento
    uni_col = _pick_cols(rec, ["Unidad Fiscalizable", "Unidad", "Establecimiento", "Nombre Unidad", "Proyecto"])
    out["unidad"] = rec.get(uni_col) if uni_col else None
    # region/comuna
    reg_col = _pick_cols(rec, ["Región", "region", "Region"])
    com_col = _pick_cols(rec, ["Comuna", "comuna"])
    out["region"] = rec.get(reg_col) if reg_col else None
    out["comuna"] = rec.get(com_col) if com_col else None
    # estado/procedimiento
    est_col = _pick_cols(rec, ["Estado", "estado", "Estado Procedimiento", "Estado Sancionatorio"])
    out["estado"] = rec.get(est_col) if est_col else None
    # detalle/código
    cod_col = _pick_cols(rec, ["Código", "Codigo", "codigo", "Código Procedimiento", "ID Procedimiento"])
    out["codigo"] = rec.get(cod_col) if cod_col else None
    return out


# ---------------------------
# Núcleo público
# ---------------------------
async def fetch_snifa_resumen_por_rut_razon(
    *,
    rut: Optional[str],
    razon_social: Optional[str],
    limit_por_tabla: int = 1500,
    muestras: int = 5,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Devuelve un resumen SNIFA:
    {
      ok: bool,
      counters: {
        fiscalizaciones: int,
        sancionatorios_activos: int,
        sanciones_firmes: int
      },
      muestras: {
        fiscalizaciones: [ {fecha, rut, razon_social, unidad, region, comuna, estado, codigo} ... ],
        sancionatorios: [ ... ],
        sanciones_firmes: [ ... ]
      },
      evidencias: { fiscalizaciones: <url>, sancionatorios: <url>, sanciones_firmes: <url> }
    }
    """
    rut_c = _clean_rut(rut) if rut else ""
    razon_n = _norm(razon_social) if razon_social else ""
    cache_key = f"{rut_c}|{razon_n}"
    now = time.time()

    if not force and cache_key in _cache and (now - _cache[cache_key]["ts"] < _CACHE_TTL):
        return _cache[cache_key]["data"]

    async with aiohttp.ClientSession() as session:
        # resolver resource_id de las 3 familias
        rids: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
        for clave in ("fiscalizaciones", "sancionatorios", "sanciones_firmes"):
            rid, evid = await _resolve_resource_id(session, PKG_HINTS[clave])
            rids[clave] = (rid, evid)

        out_counters = {
            "fiscalizaciones": 0,
            "sancionatorios_activos": 0,
            "sanciones_firmes": 0,
        }
        out_samples = {
            "fiscalizaciones": [],
            "sancionatorios": [],
            "sanciones_firmes": [],
        }
        evidencias = {
            "fiscalizaciones": rids["fiscalizaciones"][1],
            "sancionatorios": rids["sancionatorios"][1],
            "sanciones_firmes": rids["sanciones_firmes"][1],
        }

        # --- Fiscalizaciones ---
        rid_fis = rids["fiscalizaciones"][0]
        if rid_fis:
            # intentamos primero con filters exactos (si conocemos columnas)
            recs = await _datastore_search_all(session, rid_fis, limit=limit_por_tabla)
            # filtrado local por RUT/razón
            recs = [r for r in recs if _record_matches(r, rut, razon_social)]
            out_counters["fiscalizaciones"] = len(recs)
            out_samples["fiscalizaciones"] = [_compact_row(r) for r in recs[:muestras]]

        # --- Procedimientos sancionatorios (activos) ---
        rid_ps = rids["sancionatorios"][0]
        if rid_ps:
            recs = await _datastore_search_all(session, rid_ps, limit=limit_por_tabla)
            recs = [r for r in recs if _record_matches(r, rut, razon_social)]
            # considerar "activos" según una columna de estado; si no existe, contamos todos
            activos = []
            for r in recs:
                est_col = _pick_cols(r, ["Estado", "estado", "Estado Procedimiento", "Situación"])
                est = str(r.get(est_col, "")).strip().lower() if est_col else ""
                if not est_col:
                    activos.append(r)
                elif any(x in est for x in ["en trámite", "en tramite", "abierto", "vigente", "activo"]):
                    activos.append(r)
            out_counters["sancionatorios_activos"] = len(activos)
            out_samples["sancionatorios"] = [_compact_row(r) for r in activos[:muestras]]

        # --- Sanciones firmes ---
        rid_sf = rids["sanciones_firmes"][0]
        if rid_sf:
            recs = await _datastore_search_all(session, rid_sf, limit=limit_por_tabla)
            recs = [r for r in recs if _record_matches(r, rut, razon_social)]
            out_counters["sanciones_firmes"] = len(recs)
            out_samples["sanciones_firmes"] = [_compact_row(r) for r in recs[:muestras]]

        data = {
            "ok": True,
            "counters": out_counters,
            "muestras": out_samples,
            "evidencias": evidencias,
            "rut": rut,
            "razon_social": razon_social,
        }
        _cache[cache_key] = {"ts": now, "data": data}
        return data