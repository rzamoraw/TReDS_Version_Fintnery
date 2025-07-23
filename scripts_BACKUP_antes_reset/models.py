from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from sqlalchemy import Date, Boolean
from sqlalchemy import cast
from sqlalchemy.orm import foreign

class Proveedor(Base):
    __tablename__ = "proveedores"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    rut = Column(String, unique=True, index=True, nullable=False)
    usuario = Column(String, unique=True, index=True, nullable=False)
    clave_hash = Column(String, nullable=False)

    # Relación con facturas
    facturas = relationship("FacturaDB", back_populates="proveedor")

class Pagador(Base):
    __tablename__ = "pagadores"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    rut = Column(String, unique=True, index=True, nullable=False)
    usuario = Column(String, unique=True, index=True, nullable=False)
    clave_hash = Column(String, nullable=False)

    # Relación con facturas recibidas
    facturas = relationship("FacturaDB", back_populates="pagador")

class CondicionesPorPagador(Base):
    __tablename__ = "condiciones_por_pagador"

    id = Column(Integer, primary_key=True, index=True)
    financiador_id = Column(Integer, ForeignKey("financiadores.id"), nullable=False)
    rut_pagador = Column(String, nullable=False)
    nombre_pagador = Column(String, nullable=False)
    spread = Column(Float, default=0.0)
    dias_anticipacion = Column(Integer, default=0)
    comisiones = Column(Float, default=0.0)
    nombre_financiador = Column(String, nullable=True)  # ✅ agregada

    financiador = relationship("Financiador", back_populates="condiciones")

class Fondo(Base):
    __tablename__ = "fondos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    descripcion = Column(String)
    activo = Column(Boolean, default=True)

    financiadores = relationship("Financiador", 
        back_populates="fondo",
        cascade="all, delete"
    )

class Financiador(Base):
    __tablename__ = "financiadores"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    usuario = Column(String, unique=True, index=True, nullable=False)
    clave_hash = Column(String, nullable=False)

    fondo_id = Column(Integer, ForeignKey("fondos.id"), nullable=False)
    fondo = relationship("Fondo", back_populates="financiadores")

    # ←─ NUEVO: indica si el usuario es administrador dentro del rol financiador
    es_admin = Column(Boolean, default=False) 

    # ✅ Costo de fondos mensual (reemplaza al anterior)
    costo_fondos_mensual = Column(Float, default=0.0)  # ← Explicita unidad mensual
    fecha_costo_fondos = Column(Date, default=None)    # ← Fecha de carga más reciente

    # ↓ Pega esto al final de la clase Financiador (antes de la siguiente clase)
    condiciones = relationship(
        "CondicionesPorPagador",
        back_populates="financiador",
        cascade="all, delete-orphan"
    )
    # Relación con ofertas realizadas
    ofertas = relationship("OfertaFinanciamiento", back_populates="financiador")

class FacturaDB(Base):
    __tablename__ = "facturas"

    id = Column(Integer, primary_key=True, index=True)
    rut_emisor = Column(String, index=True)
    rut_receptor = Column(String)
    tipo_dte = Column(String)
    folio = Column(Integer)
    monto = Column(Integer)
    estado_dte = Column(String)
    razon_social_emisor = Column(String)
    razon_social_receptor = Column(String)
    fecha_emision = Column(Date)
    fecha_vencimiento = Column(Date)
    fecha_vencimiento_original = Column(Date, nullable=True)
    modificacion_aceptada_por_proveedor = Column(Boolean, nullable=True, default=None)
    confirming_solicitado = Column(Boolean, default=False)
    origen_confirmacion = Column(String, default="Desconocido")
    financiador_adjudicado = Column(Integer, ForeignKey("financiadores.id"), nullable=True)
    
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"))
    proveedor = relationship("Proveedor", back_populates="facturas")

    pagador_id = Column(Integer, ForeignKey("pagadores.id"))
    pagador = relationship("Pagador", back_populates="facturas")

    ofertas = relationship("OfertaFinanciamiento", back_populates="factura")

    financiador = relationship(
        "Financiador",
        primaryjoin=Financiador.id == foreign(cast(financiador_adjudicado, Integer)), viewonly=True,
        uselist=False,
    )

class OfertaFinanciamiento(Base):
    __tablename__ = "ofertas_financiamiento"

    id = Column(Integer, primary_key=True, index=True)
    tasa_interes = Column(Float)
    dias_anticipacion = Column(Integer)
    monto_total = Column(Float)
    comision_flat = Column(Float, default=0.0)
    precio_cesion = Column(Float)
    estado = Column(String, default="Oferta realizada")

    factura_id = Column(Integer, ForeignKey("facturas.id"))
    financiador_id = Column(Integer, ForeignKey("financiadores.id"))

    factura = relationship("FacturaDB", back_populates="ofertas")
    financiador = relationship("Financiador", back_populates="ofertas")    
                           
                              
