# services/connectors/mercado_publico.py
import os, asyncio, random, time
from typing import Dict, Any
import httpx
from dotenv import load_dotenv

BASE_URL = "https://api.mercadopublico.cl/servicios/v1/Publico"

# ──────────────────────────────────────────────────────────────────────────────
# Cache (en memoria del proceso)
# ──────────────────────────────────────────────────────────────────────────────
try:
    _CACHE  # type: ignore[name-defined]
except NameError:
    _CACHE: dict[str, tuple[float, dict]] = {}

# TTLs
TTL_SECONDS     = 60 * 60 * 12   # 12 h (genérico)
TTL_PROV_SEC    = 60 * 60 * 6    # 6 h (proveedor)
TTL_OC_SECONDS  = 60 * 30        # 30 min (órdenes)
TTL_ADJ_SECONDS = 60 * 60 * 6    # 6 h (adjudicaciones)

def _cache_get(key: str) -> dict | None:
    t = _CACHE.get(key)
    if not t:
        return None
    expires_at, payload = t
    if time.time() >= expires_at:
        _CACHE.pop(key, None)
        return None
    return payload

def _cache_set(key: str, payload: dict, ttl: int = TTL_SECONDS) -> None:
    _CACHE[key] = (time.time() + ttl, payload)

def _cache_del(key: str) -> None:
    _CACHE.pop(key, None)

def _cache_key(kind: str, **params) -> str:
    items = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"mp:{kind}:{items}"

def _prov_key(rut_fmt: str) -> str:
    return f"mp:prov:{rut_fmt}"

# Mapeo rápido RUT → CodigoEmpresa (evita segunda ida a la API)
_RUT_TO_EMPRESA: dict[str, str] = {}

def _cache_empresa_put(rut_fmt: str, codigo: str | None):
    if codigo:
        _RUT_TO_EMPRESA[rut_fmt] = codigo

def _cache_empresa_get(rut_fmt: str) -> str | None:
    return _RUT_TO_EMPRESA.get(rut_fmt)

# ──────────────────────────────────────────────────────────────────────────────
# Ticket y helpers HTTP
# ──────────────────────────────────────────────────────────────────────────────
def _get_ticket() -> str:
    load_dotenv(override=True)  # recarga .env por si cambió en caliente
    return os.getenv("MP_TICKET", "")

def _rut_para_mp(rut: str) -> str:
    """
    Devuelve el RUT con puntos y guión (##.###.###-d), como lo espera MP.
    Si ya viene formateado (con puntos y guión), se respeta.
    """
    if "-" in rut and "." in rut:
        return rut
    s = "".join(ch for ch in rut if ch.isalnum())
    if not s:
        return rut
    cuerpo, dv = s[:-1], s[-1]
    grupos: list[str] = []
    while cuerpo:
        grupos.insert(0, cuerpo[-3:])
        cuerpo = cuerpo[:-3]
    return ".".join(grupos) + "-" + dv.lower()

async def _safe_get(url: str, params: Dict[str, Any], max_retries: int = 4) -> Dict[str, Any]:
    """
    Envoltura robusta para GET:
      - Inserta ticket.
      - Reintenta 5xx y Codigo=10500 con backoff exponencial + jitter.
      - Normaliza "no hay resultados" (Codigo=10200) como 404 controlado.
    """
    ticket = _get_ticket()
    if not ticket:
        return {"ok": False, "status": None, "payload": {"error": "MP_TICKET ausente"}}

    params = dict(params or {})
    params["ticket"] = ticket
    headers = {"Accept": "application/json", "User-Agent": "Fintnery/TReDS"}

    delay = 0.8
    async with httpx.AsyncClient(http2=True, timeout=30.0) as client:
        for intento in range(max_retries + 1):
            resp = await client.get(url, params=params, headers=headers)
            try:
                payload = resp.json()
            except Exception:
                payload = {"raw_text": resp.text}

            # "No hay resultados"
            if isinstance(payload, dict) and payload.get("Codigo") == 10200:
                return {"ok": True, "status": 404, "payload": payload}

            # "Peticiones simultáneas"
            if isinstance(payload, dict) and payload.get("Codigo") == 10500:
                if intento < max_retries:
                    await asyncio.sleep(delay + random.uniform(0, 0.5))
                    delay *= 1.8
                    continue
                return {"ok": False, "status": resp.status_code, "payload": payload}

            if resp.is_success:
                return {"ok": True, "status": resp.status_code, "payload": payload}

            if 500 <= resp.status_code < 600 and intento < max_retries:
                await asyncio.sleep(delay + random.uniform(0, 0.5))
                delay *= 1.8
                continue

            return {"ok": False, "status": resp.status_code, "payload": payload}

    return {"ok": False, "status": None, "payload": {"error": "sin respuesta"}}

# ──────────────────────────────────────────────────────────────────────────────
# Proveedor por RUT (con cache y force)
# ──────────────────────────────────────────────────────────────────────────────
async def fetch_proveedor_por_rut(rut: str, force: bool = False) -> Dict[str, Any]:
    """
    Busca el proveedor por RUT en MP.
    - rut: puede venir en cualquier formato; se normaliza al esperado por MP.
    - force=True invalida el cache para este RUT.
    """
    rut_fmt = _rut_para_mp(rut)

    # 1) cache hit (solo si no forzamos)
    if not force:
        cached = _cache_get(rut_fmt)
        if cached is not None:
            return cached
   
    # 2) llamada a API
    url = f"{BASE_URL}/Empresas/BuscarProveedor"
    res = await _safe_get(url, {"rutempresaproveedor": rut_fmt})

    if not res["ok"]:
        out = {"encontrado": False, "rut_consultado": rut_fmt, "error": res["payload"]}
        # guarda igual en cache para evitar golpear la API en error repetido
        _cache_set(rut_fmt, out)
        return out

    p = res["payload"] if isinstance(res["payload"], dict) else {}
    lista = p.get("listaEmpresas") or p.get("Listado") or p.get("listado") or []

    if isinstance(lista, list) and len(lista) > 0:
        e = lista[0]
        out = {
            "encontrado": True,
            "rut_consultado": rut_fmt,
            "codigo_empresa": e.get("CodigoEmpresa"),
            "nombre_empresa": e.get("NombreEmpresa") or e.get("RazonSocial"),
            "raw": p,
        }
        _cache_set(rut_fmt, out)
        return out

    # Código “no hay resultados”
    if p.get("Codigo") == 10200:
        out = {"encontrado": False, "rut_consultado": rut_fmt, "raw": p}
        _cache_set(rut_fmt, out)
        return out

    out = {"encontrado": False, "rut_consultado": rut_fmt, "raw": p}
    _cache_set(rut_fmt, out)
    return out

# ──────────────────────────────────────────────────────────────────────────────
# Helpers: CodigoEmpresa por RUT (usa fetch_proveedor_por_rut)
# ──────────────────────────────────────────────────────────────────────────────
async def _codigo_empresa_por_rut(rut: str, force: bool = False) -> str | None:
    """
    Devuelve CodigoEmpresa (string) consultando fetch_proveedor_por_rut si hace falta.
    Respeta `force` para bypassear cache.
    """
    rut_fmt = _rut_para_mp(rut)
    if not force:
        cod = _cache_empresa_get(rut_fmt)
        if cod:
            return cod
    info = await fetch_proveedor_por_rut(rut_fmt, force=force)
    if info.get("encontrado") and info.get("codigo_empresa"):
        _cache_empresa_put(rut_fmt, info["codigo_empresa"])
        return info["codigo_empresa"]
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Órdenes de compra por RUT proveedor
# ──────────────────────────────────────────────────────────────────────────────
async def fetch_ordenes_de_compra_por_rut(
    rut: str,
    desde: str | None = None,   # "YYYY-MM-DD"
    hasta: str | None = None,   # "YYYY-MM-DD"
    limit: int = 50,
    force: bool = False,
) -> dict:
    """
    Trae un listado (acotado) de Órdenes de Compra para un proveedor (por RUT).
    Devuelve un resumen y hasta 'limit' ítems crudos de la API.
    """
    rut_fmt = _rut_para_mp(rut)
    codigo = await _codigo_empresa_por_rut(rut_fmt, force=force)
    if not codigo:
        return {"ok": False, "reason": "sin_codigo_empresa", "rut": rut_fmt}

    key = _cache_key("oc", rut=rut_fmt, desde=desde or "", hasta=hasta or "", limit=limit)
    if not force:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    # Endpoint ref: Ordenes de compra públicas
    url = f"{BASE_URL}/OrdenesDeCompra"
    params = {
        "proveedor": codigo,                         # algunos ambientes usan "CodigoEmpresaProveedor" o "proveedor"
        "pagina": 1,
        "cantidad": max(1, min(limit, 100)),        # cap 100
    }
    if desde: params["fechadesde"] = desde
    if hasta: params["fechahasta"] = hasta

    res = await _safe_get(url, params)
    if not res["ok"]:
        out = {"ok": False, "rut": rut_fmt, "codigo_empresa": codigo, "error": res["payload"]}
        _cache_set(key, out, TTL_OC_SECONDS)
        return out

    payload = res["payload"] if isinstance(res["payload"], dict) else {}
    lista = payload.get("Listado") or payload.get("lista") or payload.get("Ordenes") or []

    total_monto = 0.0
    for it in lista:
        try:
            total_monto += float(it.get("MontoNeto", 0) or 0)
        except Exception:
            pass

    out = {
        "ok": True,
        "rut": rut_fmt,
        "codigo_empresa": codigo,
        "resumen": {
            "cantidad": len(lista),
            "monto_neto_total": round(total_monto, 2),
            "periodo": {"desde": desde, "hasta": hasta},
        },
        "items": lista[:limit],
        "raw": payload,
    }
    _cache_set(key, out, TTL_OC_SECONDS)
    return out

# ──────────────────────────────────────────────────────────────────────────────
# Adjudicaciones por RUT proveedor
# ──────────────────────────────────────────────────────────────────────────────
async def fetch_adjudicaciones_por_rut(
    rut: str,
    desde: str | None = None,   # "YYYY-MM-DD"
    hasta: str | None = None,   # "YYYY-MM-DD"
    limit: int = 50,
    force: bool = False,
) -> dict:
    """
    Licitaciones adjudicadas al proveedor (por RUT/código empresa).
    """
    rut_fmt = _rut_para_mp(rut)
    codigo = await _codigo_empresa_por_rut(rut_fmt, force=force)
    if not codigo:
        return {"ok": False, "reason": "sin_codigo_empresa", "rut": rut_fmt}

    key = _cache_key("adj", rut=rut_fmt, desde=desde or "", hasta=hasta or "", limit=limit)
    if not force:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    url = f"{BASE_URL}/Licitaciones/BuscarAdjudicaciones"
    params = {
        "proveedor": codigo,
        "pagina": 1,
        "cantidad": max(1, min(limit, 100)),
    }
    if desde: params["fechadesde"] = desde
    if hasta: params["fechahasta"] = hasta

    res = await _safe_get(url, params)
    if not res["ok"]:
        out = {"ok": False, "rut": rut_fmt, "codigo_empresa": codigo, "error": res["payload"]}
        _cache_set(key, out, TTL_ADJ_SECONDS)
        return out

    payload = res["payload"] if isinstance(res["payload"], dict) else {}
    lista = payload.get("Listado") or payload.get("Resultados") or []

    total_adjudicado = 0.0
    for it in lista:
        try:
            total_adjudicado += float(it.get("MontoAdjudicado", 0) or 0)
        except Exception:
            pass

    out = {
        "ok": True,
        "rut": rut_fmt,
        "codigo_empresa": codigo,
        "resumen": {
            "cantidad": len(lista),
            "monto_adjudicado_total": round(total_adjudicado, 2),
            "periodo": {"desde": desde, "hasta": hasta},
        },
        "items": lista[:limit],
        "raw": payload,
    }
    _cache_set(key, out, TTL_ADJ_SECONDS)
    return out

async def resumen_mercado_publico(rut: str, limit: int = 10, force: bool = False) -> dict:
    """Devuelve un resumen combinando proveedor, adjudicaciones y OC."""
    prov = await fetch_proveedor_por_rut(rut, force=force)
    adj  = await fetch_adjudicaciones_por_rut(rut, limit=limit, force=force)
    oc   = await fetch_ordenes_de_compra_por_rut(rut, limit=limit, force=force)
    return {
        "encontrado": bool(prov.get("encontrado")),
        "rut_consultado": prov.get("rut_consultado") or rut,
        "proveedor": prov,
        "adjudicaciones": adj,
        "ordenes_compra": oc,
    }