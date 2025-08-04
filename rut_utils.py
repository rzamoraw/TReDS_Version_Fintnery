# rut_utils.py

def normalizar_rut(rut: str) -> str:
    """
    Normaliza un RUT chileno eliminando puntos y guiones, 
    convierte letras a mayúsculas, y elimina espacios.
    """
    if not rut:
        return ""
    return rut.replace(".", "").replace("-", "").upper().strip()