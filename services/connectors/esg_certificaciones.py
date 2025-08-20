# conectores/esg_certificaciones.py
from typing import Dict, Any, List, Tuple, Optional
from rut_utils import normalizar_rut

# ---- 1) PUNTOS DE DATOS QUE TÚ YA TIENES (ajusta estas tres funciones) ----
def _ventas_24m_por_pagador(rut: str) -> List[Tuple[str, float]]:
    """
    Retorna [(rut_pagador, monto_total_24m), ...] usando TU tabla de facturas.
    IMPLEMENTA llamando tus repositorios existentes.
    """
    return []

def _descripcion_y_unspsc_24m(rut: str) -> Tuple[str, List[str]]:
    """
    Retorna (texto_concatenado_descripciones, [unspsc_unicos]) de OC/facturas últimos 24m.
    IMPLEMENTA leyendo tus tablas de OCs o facturas.
    """
    return "", []

def _leer_esg_inputs_publicados(rut: str) -> Dict[str, List[Dict]]:
    """
    Lee de tus tablas 'input pagador' los REGISTROS PUBLICADOS (indicadores, iniciativas, certificaciones),
    solo con evidencia_url no nula.
    Si aún no tienes tablas ESG, deja listas vacías y más tarde conectas.
    """
    return {"indicadores": [], "iniciativas": [], "certificaciones": []}

# ---- 2) MAESTROS LIGEROS (si no tienes aún DB, lee CSV luego) ----
_PAGADORES_MINEROS = set([
    # RUTs normalizados (sin puntos ni guion). Puedes moverlos a DB/CSV más adelante.
    "61704000K",  # Codelco
    "61403000K",  # ENAMI
    "968139204",  # Escondida
    "969283001",  # SQM Salar
    "761467173",  # Albemarle Chile
])

_KEYWORDS_MINEROS = ("relaves","lixivi","faena","chancad","perfor","tronadur","sxew","celdas","concentrador","fundicion","refineria","salar","litio")

_UNSPSC_MINEROS = [(20100000, 20142100), (23151600, 23151699), (23153200, 23153299), (25170000, 25179999), (20122300, 20122399)]

# ---- 3) LÓGICA SUAVE (sin depender aún de otros módulos) ----
def _score_keywords(texto: str) -> int:
    t = (texto or "").lower()
    if any(bad in t for bad in ("mineria de datos","data mining","crypto mining","bitcoin")):
        return 0
    pts=0
    for kw in _KEYWORDS_MINEROS:
        if kw in t:
            pts += 15
            if pts>=60: break
    return min(60, pts)

def _score_unspsc(codes: List[str]) -> int:
    seen=set()
    pts=0
    for c in set(codes or []):
        try:
            n=int(c)
        except:
            continue
        for a,b in _UNSPSC_MINEROS:
            if a <= n <= b and (a,b) not in seen:
                pts += 12
                seen.add((a,b))
                if len(seen)>=2:  # tope dos rangos
                    break
    return min(24, pts)

# ---- 4) API PÚBLICA DEL CONECTOR ----
def detectar_sector(rut: str) -> Dict[str, Any]:
    """Devuelve clasificacion MINERIA/PROBABLE/NO + confianza y evidencias."""
    rutn = normalizar_rut(rut)
    ventas = _ventas_24m_por_pagador(rutn)
    total = sum(m for _,m in ventas) or 0.0
    mineras = 0.0
    evidencias=[]
    for rp, m in ventas:
        try:
            rpn = normalizar_rut(rp)
        except:
            continue
        if rpn in _PAGADORES_MINEROS:
            mineras += m
            evidencias.append(f"{m:.0f} CLP a pagador minero {rpn}")
    pct = round((mineras/total)*100,2) if total>0 else 0.0

    clas="NO"; conf=0
    if pct >= 40.0:
        clas="MINERIA"; conf=80
    elif 20.0 <= pct < 40.0:
        conf=30

    texto, unspsc = _descripcion_y_unspsc_24m(rutn)
    conf = max(conf, _score_keywords(texto) + _score_unspsc(unspsc))

    if clas!="MINERIA":
        if conf>=60: clas="MINERIA"
        elif 40<=conf<60: clas="PROBABLE"
        else: clas="NO"

    return {
        "clasificacion": "MINERIA" if clas=="MINERIA" else ("PROBABLE MINERIA" if clas=="PROBABLE" else "NO MINERIA"),
        "confianza": min(100, conf),
        "evidencias": [ {"tipo":"ventas", "valor": f"{pct}% ult.24m"} ] + [{"tipo":"detalle","valor":e} for e in evidencias]
    }

def obtener_esg(rut: str) -> Dict[str, Any]:
    """
    Arma el bloque ESG unificado para la Vista 360.
    Hoy: usa inputs publicados; más adelante enchufas Sistema B, HuellaChile, Alta Ley.
    """
    rutn = normalizar_rut(rut)
    sector = detectar_sector(rutn)
    data = _leer_esg_inputs_publicados(rutn)
    # Calcula estados de vigencia rápidos
    from datetime import date
    today = date.today()
    for c in data["certificaciones"]:
        fin = c.get("vigencia_fin")
        estado = "pendiente"
        if fin:
            try:
                df = date.fromisoformat(str(fin))
                delta=(df - today).days
                if delta < 0: estado="vencida"
                elif delta <= 90: estado="por_vencer"
                else: estado="vigente"
            except:
                pass
        c["estado"] = c.get("estado") or estado
    # Score muy simple (lo puedes reemplazar por el detallado luego)
    score = 0
    score += 10 if any(c.get("certificacion","").startswith("ISO 14001") and c["estado"] in ("vigente","por_vencer") for c in data["certificaciones"]) else 0
    score += 10 if any(c.get("certificacion","").startswith("ISO 45001") and c["estado"] in ("vigente","por_vencer") for c in data["certificaciones"]) else 0
    score += 5 * min(5, len([i for i in data["indicadores"] if i.get("evidencia_url")]))
    score = max(0, min(100, score))

    return {
        "sector": sector,
        "score": {"total": score},
        "indicadores": data["indicadores"],
        "iniciativas": data["iniciativas"],
        "certificaciones": data["certificaciones"],
        "fuentes_externas": {}  # luego: systemab/huellachile/altaley
    }

# 1) LEGADO (si ya existe, déjalo igual):
def get_certificaciones(rut: str) -> List[Dict]:
    """Formato legacy que ya consume tu 360. NO tocar si está en uso."""
    ...

# 2) NUEVO – devuelve el bloque completo para la Vista 360:
def get_esg_payload(rut: str) -> Dict[str, Any]:
    """
    Retorna TODO lo que la 360 necesita renderizar del bloque ESG, en un único dict:
    {
      "sector": {"clasificacion": "...", "confianza": 0-100, "evidencias": [...]},
      "score": {"total": 0-100, "nivel": "A..E", "detalle": {...}, "ultima_actualizacion": "..."},
      "indicadores": [...],        # solo publicados + con evidencia
      "iniciativas": [...],        # solo publicadas + con evidencia
      "certificaciones": [...],    # ordenadas por vigencia + estado calculado
      "fuentes_externas": { ... }  # cuando conectes SistemaB/Huella/AltaLey
    }
    """
    ...

# 3) (Opcional) SOLO badge rápido si lo necesitas en otra parte de la página:
def get_esg_score(rut: str) -> Dict[str, Any]:
    """Atajo: {"total": 76, "nivel": "B"} – lo toma de get_esg_payload para no recalcular."""
    ...