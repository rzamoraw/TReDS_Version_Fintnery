# services/resolvers/nombres.py
from collections import Counter
from models import PagadorProfile, FacturaDB
from services.connectors.mercado_publico import fetch_mp_minimo

async def resolve_display_name(rut_norm: str, db) -> tuple[str, dict]:
    """
    Retorna (display_name, mp_minimo_dict).
    mp_minimo_dict te sirve igual para la sección de Mercado Público que ya pintas.
    """
    # 1) Perfil en BD
    perfil = db.query(PagadorProfile).filter(PagadorProfile.rut == rut_norm).first()
    if perfil:
        name = getattr(perfil, "razon_social", None) or getattr(perfil, "nombre_fantasia", None)
        if name:
            # intenta también obtener mp (lo usas más abajo de todos modos)
            try:
                mp = await fetch_mp_minimo(rut_norm)
            except Exception:
                mp = {}
            return name, (mp or {})

    # 2) Facturas locales (razón social receptor más frecuente)
    filas = (
        db.query(FacturaDB.razon_social_receptor)
          .filter(FacturaDB.rut_receptor == rut_norm, FacturaDB.razon_social_receptor.isnot(None))
          .all()
    )
    if filas:
        rs_list = [r[0] for r in filas if (r and r[0])]
        if rs_list:
            name = Counter(rs_list).most_common(1)[0][0]
            try:
                mp = await fetch_mp_minimo(rut_norm)
            except Exception:
                mp = {}
            return name, (mp or {})

    # 3) Mercado Público (mínimo)
    try:
        mp = await fetch_mp_minimo(rut_norm)
    except Exception:
        mp = {}

    name = (mp.get("razon_social") or mp.get("nombre_fantasia") or "(Sin registro)")
    return name, (mp or {})