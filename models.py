from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
from sqlalchemy import Date, Boolean, DateTime, JSON
from sqlalchemy import cast, Text
from sqlalchemy.orm import foreign
from sqlalchemy import UniqueConstraint
from sqlalchemy.sql import func


class Proveedor(Base):
    __tablename__ = "proveedores"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    rut = Column(String, unique=True, index=True, nullable=False)
    usuario = Column(String, unique=True, index=True, nullable=False)
    clave_hash = Column(String, nullable=False)
    razon_social = Column(String, nullable=True)

    # 🆕 Campos para conexión con SII:
    clave_sii = Column(String, nullable=True)          # opcional, puede ir en texto plano o cifrada
    cookies_sii_path = Column(String, nullable=True)   # ejemplo: "cookies/cookies_76262370-6.json"

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
    fecha_confirmacion = Column(Date, nullable=True)
    fecha_recepcion = Column(Date, nullable=True)
    modificacion_aceptada_por_proveedor = Column(Boolean, nullable=True, default=None)
    confirming_solicitado = Column(Boolean, default=False)
    origen_confirmacion = Column(String, default="Desconocido")
    financiador_adjudicado = Column(Integer, ForeignKey("financiadores.id"), nullable=True)

    # Nuevos campos auxiliares desde importación SII
    dias_desde_emision = Column(Integer, nullable=True)
    detEventoReceptor = Column(String, nullable=True)
    detEventoReceptorLeyenda = Column(String, nullable=True)

    # NUEVO (para métricas de comportamiento del pagador):
    estado_confirmacion = Column(String, default="Pendiente")   # Pendiente | Confirmada | Rechazada
    fecha_confirmacion = Column(DateTime, nullable=True)
    fecha_pago_real = Column(Date, nullable=True)               # si manejas pago real
    
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

class PagadorProfile(Base):
    __tablename__ = "pagador_profiles"
    rut = Column(String, primary_key=True)  # RUT normalizado, mismo que en tu sistema
    razon_social = Column(String)
    nombre_fantasia = Column(String, nullable=True)
    sector_ciiu = Column(String, nullable=True)
    email_tesoreria = Column(String, nullable=True)
    telefono = Column(String, nullable=True)
    sitio_web = Column(String, nullable=True)
    esg_json = Column(JSON, default={})     # indicadores básicos si no quieres tablas separadas

class EsgCertificacion(Base):
    __tablename__ = "esg_certificaciones"
    id = Column(Integer, primary_key=True)
    rut = Column(String, index=True)           # RUT del pagador
    tipo = Column(String)                      # ISO 9001, ISO 14001, ISO 27001, B-Corp, etc.
    emisor = Column(String, nullable=True)     # entidad certificadora
    valido_hasta = Column(Date, nullable=True)
    enlace = Column(String, nullable=True) 

class ESGCriterion(Base):
    __tablename__ = "esg_criterios"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False)   # p.ej. "G-ANTI_CORR"
    nombre = Column(String(255), nullable=False)
    categoria = Column(String(1), nullable=False)            # "E","S","G"
    peso = Column(Float, default=1.0)
    answer_type = Column(String(20), default="bool")         # "bool","choice","number","text"
    options_json = Column(JSON, nullable=True)               # metadatos de opciones/umbrales
    activo = Column(Boolean, default=True)

class ESGAssessment(Base):
    __tablename__ = "esg_evaluaciones"
    id = Column(Integer, primary_key=True)
    pagador_rut = Column(String(20), index=True, nullable=False)  # RUT normalizado
    periodo_anio = Column(Integer, nullable=False)
    periodo_mes = Column(Integer, nullable=False)
    estado = Column(String(20), default="en_proceso")  # en_proceso | enviado | certificado
    puntaje_total = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ESGAnswer(Base):
    __tablename__ = "esg_respuestas"
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("esg_evaluaciones.id"), nullable=False, index=True)
    criterio_id = Column(Integer, ForeignKey("esg_criterios.id"), nullable=False, index=True)
    valor_bool = Column(Boolean, nullable=True)
    valor_number = Column(Float, nullable=True)
    valor_text = Column(Text, nullable=True)
    evidencia_url = Column(String(500), nullable=True)
    puntaje = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint('assessment_id', 'criterio_id', name='uq_assessment_criterio'),
    )

class ESGEvidence(Base):
    __tablename__ = "esg_evidencias"
    id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("esg_evaluaciones.id"), nullable=False, index=True)
    criterio_id = Column(Integer, ForeignKey("esg_criterios.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    path = Column(String(500), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())


                           
                              
