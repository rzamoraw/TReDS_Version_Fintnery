# rut_utils.py
# Utilidades para RUT chileno: limpieza, validación (módulo 11) y formato.

import re
import unicodedata

_RUT_RE = re.compile(r"^(\d{1,9})([0-9Kk])$")  # cuerpo + DV

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )

def limpiar_rut(rut: str) -> str:
    """
    Limpia un RUT: elimina puntos/guiones/espacios, mayúsculas, quita acentos.
    NO valida DV.
    """
    if not rut:
        return ""
    s = _strip_accents(rut).upper().replace(".", "").replace("-", "").strip()
    # también colapsa espacios internos por si vinieran pegados
    s = re.sub(r"\s+", "", s)
    return s

def calcular_dv(cuerpo: str) -> str:
    """
    Calcula DV por módulo 11 para un cuerpo numérico (sin DV).
    Retorna '0'..'9' o 'K'.
    """
    if not cuerpo.isdigit():
        raise ValueError("El cuerpo del RUT debe ser numérico.")
    secuencia = [2, 3, 4, 5, 6, 7]
    i = 0
    total = 0
    for d in reversed(cuerpo):
        total += int(d) * secuencia[i % len(secuencia)]
        i += 1
    resto = 11 - (total % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)

def es_rut_valido(rut: str) -> bool:
    """
    Valida estructura y DV. Acepta entradas con o sin puntos/guion.
    """
    s = limpiar_rut(rut)
    m = _RUT_RE.match(s)
    if not m:
        return False
    cuerpo, dv = m.group(1), m.group(2).upper()
    try:
        return calcular_dv(cuerpo) == dv
    except ValueError:
        return False

def normalizar_rut(rut: str) -> str:
    """
    Normaliza y **valida** un RUT. Retorna 'CCCCCCCCDV' (sin puntos ni guion, DV mayúscula).
    Lanza ValueError si el RUT es inválido (formato o DV incorrecto).
    """
    s = limpiar_rut(rut)
    m = _RUT_RE.match(s)
    if not m:
        raise ValueError("RUT con formato inválido. Use cuerpo+DV (p.ej., 12345678K).")
    cuerpo, dv = m.group(1), m.group(2).upper()
    dv_calc = calcular_dv(cuerpo)
    if dv != dv_calc:
        raise ValueError(f"RUT con DV incorrecto (esperado {dv_calc}).")
    return f"{cuerpo}{dv}"

def formatear_rut(rut: str, con_puntos: bool = True) -> str:
    """
    Da formato humano a un RUT ya limpio/validado: '12.345.678-K' (por defecto) o '12345678-K'.
    Si recibes uno crudo, lo valida primero.
    """
    s = normalizar_rut(rut)  # valida
    cuerpo, dv = s[:-1], s[-1]
    if not con_puntos:
        return f"{cuerpo}-{dv}"
    # agrega puntos cada 3 desde la derecha
    partes = []
    while cuerpo:
        partes.append(cuerpo[-3:])
        cuerpo = cuerpo[:-3]
    return f"{'.'.join(reversed(partes))}-{dv}"