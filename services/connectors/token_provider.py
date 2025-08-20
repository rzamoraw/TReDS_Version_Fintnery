# services/connectors/token_provider.py
import os, time, base64
import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

# cache simple en memoria
_CACHE = {
    "prd": {"token": None, "exp": 0},
    "da":  {"token": None, "exp": 0},
}

def _now() -> int:
    return int(time.time())

def _auth_basic_header(client_id: str, client_secret: str) -> str:
    pair = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(pair).decode("ascii")

async def _fetch_token(url, cid, sec, grant):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            url,
            data={"grant_type": grant, "client_id": cid, "client_secret": sec},
            headers={"Accept": "application/json"}
        )
        body_preview = (r.text or "")[:200]
        if r.status_code >= 400:
            print(f"[TOKEN] {r.status_code} body[:200]=\"{body_preview}\"")
            return None, 0  # <--- clave: no levantes excepción
        data = r.json()
        return data.get("access_token"), int(time.time()) + int(data.get("expires_in", 0))

async def _get_token_cached(kind: str) -> str:
    """
    kind ∈ {'prd','da'}
    Lee de cache si no está por expirar; si no, pide uno nuevo.
    """
    cfg = {
        "prd": {
            "url": os.getenv("MP_TOKEN_URL_PRD", "").strip(),
            "cid": os.getenv("MP_CLIENT_ID_PRD", "").strip(),
            "sec": os.getenv("MP_CLIENT_SECRET_PRD", None),
            "gt":  os.getenv("MP_GRANT_TYPE_PRD", "client_credentials").strip(),
        },
        "da": {
            "url": os.getenv("MP_TOKEN_URL_DA", "").strip(),
            "cid": os.getenv("MP_CLIENT_ID_DA", "").strip(),
            "sec": os.getenv("MP_CLIENT_SECRET_DA", None),
            "gt":  os.getenv("MP_GRANT_TYPE_DA", "client_credentials").strip(),
        }
    }[kind]
    if cfg["sec"] is not None:
        cfg["sec"] = cfg["sec"].strip() or None  # normaliza "" -> None

    # cache válido?
    cached = _CACHE[kind]
    if cached["token"] and _now() < (cached["exp"] - 10):
        return cached["token"]

    # pide nuevo
    if not cfg["url"] or not cfg["cid"]:
        raise RuntimeError(f"[TOKEN] Faltan envs para {kind.upper()}: URL o CLIENT_ID")

    tok, exp = await _fetch_token(cfg["url"], cfg["cid"], cfg["sec"], cfg["gt"])
    _CACHE[kind] = {"token": tok, "exp": exp}
    return tok

# API pública
async def get_prd_token() -> str:
    return await _get_token_cached("prd")

async def get_da_token() -> str:
    return await _get_token_cached("da")