# TReDS Chile – Production Security Readiness Report

Fecha: 2025-08-15

## 1) Resumen Ejecutivo

TReDS Chile es una plataforma fintech de confirming que procesa datos financieros sensibles, documentos tributarios electrónicos (DTE) y se integra con el SII. La seguridad es crítica por:

- Riesgos de fraude (manipulación de facturas, IDOR, suplantación de identidad)
- Protección de datos personales y empresariales (Ley 19.628)
- Cumplimiento regulatorio financiero (CMF/ex SBIF) y tributario (SII)
- Confidencialidad e integridad de la información (impacto financiero y reputacional)

Hallazgos clave (alto nivel):

- Controles de autenticación y sesión básicos, sin MFA, sin rate limiting, sin CSRF.
- Varios puntos de **IDOR** y controles de autorización insuficientes.
- Manejo inseguro de cookies de Middle Office y token de reset administrativo por query.
- Subida/procesamiento de archivos sin validaciones antifraude/antimalware y con riesgo de Zip-Slip.
- Almacenamiento potencial de credenciales SII y cookies sin cifrado.
- SQLite en desarrollo (sin cifrado), sin estrategia de backups/restauración.
- Ausencia de headers de seguridad, logging de auditoría y monitoreo centralizado.

Este reporte detalla vulnerabilidades concretas, cumplimiento normativo chileno aplicable y un plan priorizado para llevar TReDS a producción con seguridad.

---

## 2) Alcance y Metodología

- Revisión de código (FastAPI + SQLAlchemy + Jinja2 + Selenium + requests)
- Análisis de rutas/roles: proveedor, pagador, financiador, marketplace, middle_office, admin
- Revisión de modelos de datos y flujos de negocio
- Evaluación de integraciones externas (SII)
- Referencia a normativa regulatoria chilena e internacionales de buenas prácticas

---

## 3) Evaluación de Vulnerabilidades (con evidencias y propuestas de mitigación)

### 3.1 Autenticación y Autorización

Riesgos:

- Solo usuario/clave con bcrypt, sin MFA ni política de contraseñas, sin bloqueo por intentos.
- Falta de rate limiting en `/login` de todos los roles.
- Ausencia de CSRF tokens en POST con sesión basada en cookies.
- Roles basados en flags de sesión sin verificación robusta por recurso.

Evidencia (login proveedor/pagador/financiador):

- Rutas `@router.post("/login")` almacenan IDs en `request.session[...]` y redirigen sin controles adicionales.

Mitigación (prioritaria):

- Incorporar proveedor de identidad (Auth0/AWS Cognito/WorkOS) con MFA, políticas de contraseña y detección de anomalías.
- Si se mantiene login propio: agregar rate limiting (SlowAPI), bloqueo temporal por intentos fallidos, MFA opcional (TOTP), passwords policy, y CSRF tokens.
- Implementar **RBAC** a nivel de recurso: cada acción debe validar la propiedad/relación (ver 3.2 IDOR).

### 3.2 Controles de Acceso/IDOR (Insecure Direct Object Reference)

Riesgo crítico: falta de verificación de pertenencia del recurso al usuario autenticado.

Ejemplos:

- Pagador confirma factura por folio sin verificar pertenencia:

```python
# routers/pagador.py
@router.post("/confirmar-factura/{folio}")
def confirmar_factura(folio: int, request: Request, db: Session = Depends(get_db)):
    pagador_id = request.session.get("pagador_id")
    if not pagador_id: return RedirectResponse("/pagador/login", 303)
    factura = db.query(FacturaDB).filter(FacturaDB.folio == folio).first()
    if factura and factura.estado_dte != "Confirmada por pagador":
        factura.estado_dte = "Confirmada por pagador"
        db.commit()
```

Mitigación: validar que `factura.rut_receptor` pertenece al pagador logueado (o relación por `pagador_id`).

- Pagador edita vencimiento solo por folio (mismo problema).
- Proveedor acepta oferta por `oferta_id` sin validar que la oferta pertenece a una factura del proveedor:

```python
# routers/proveedor.py
@router.post("/aceptar-oferta/{oferta_id}")
def aceptar_oferta(oferta_id: int, request: Request, db: Session = Depends(get_db)):
    prov_id = request.session.get("proveedor_id")
    oferta = db.query(OfertaFinanciamiento).get(oferta_id)
    # Falta validar: oferta.factura.proveedor_id == prov_id
```

Mitigación: en cada endpoint que muta estado, agregar chequeo explícito de propiedad/relación.

Checklist de mitigación IDOR:

- Siempre filtrar por `... AND owner_id == session_user_id` al consultar/mutar.
- No usar identificadores globales predecibles (folio) como único criterio.
- Preferir IDs opacos/UUID y scopes por rol.

### 3.3 Gestión de Sesiones

Riesgos:

- `SessionMiddleware` firma cookies con `SECRET_KEY` y almacena contenido en el cliente. Valor por defecto `!defaultsecret` si no existe .env.
- Configuración por defecto sin `secure`, `samesite`, `httponly` explícitos.
- Middle Office utiliza cookies legibles/forjables (`middle_auth=ok`, `usuario_admin=admin`) sin protección.

Mitigación:

- Configurar `SessionMiddleware(cookie_name, secure=True, httponly=True, samesite='lax'|'strict', max_age)`. Usar **cookies de sesión distintas por rol** o unificar con claims de rol firmados.
- Migrar a **sesiones server-side** (Redis) o a **JWT** con scopes. Rotar `SECRET_KEY` y gestionarlo vía secreto seguro.
- Middle Office: reemplazar cookies sin firma por sesiones/claims firmados y verificación en backend (nunca confiar en valores de cookies del cliente).

### 3.4 Subida y Procesamiento de Archivos (XML/ZIP)

Riesgos:

- Acepta ZIP y extrae con `ZipFile.extractall()` en `uploads/` sin validación → riesgo **Zip-Slip** (escritura fuera del directorio destino) y ejecución lateral.
- Persistencia de archivos con nombres de usuario sin sanitizar.
- Falta de límite de tamaño y tipo; sin antivirus/antimalware.
- Parsing XML con `xml.etree.ElementTree` sin defensa ante payloads maliciosos (e.g. bomb XML). Si bien ET no resuelve entidades externas por defecto, se recomienda parser seguro.

Evidencia (extracto):

```python
# routers/proveedor.py
if archivo.filename.endswith(".zip"):
    with open(f"{UPLOAD_FOLDER}/temp.zip", "wb") as f: f.write(contenido)
    with zipfile.ZipFile(f"{UPLOAD_FOLDER}/temp.zip", "r") as zf:
        zf.extractall(UPLOAD_FOLDER)
```

Mitigación:

- Validar contenido del ZIP: rechazar rutas con `..`, rutas absolutas y enlaces simbólicos; extraer de forma segura (validación por archivo).
- Limitar tamaño (max request/body), validar MIME y extensión, renombrar a nombres aleatorios.
- Integrar escaneo AV (ClamAV) y tasa de subida.
- Usar parser XML seguro (defusedxml) y timeouts.

### 3.5 Endpoints Administrativos

Riesgo:

- `/admin/reset?token=...` protegido solo por token en query, método GET.

Mitigación:

- Requerir autenticación de administrador + MFA; usar método **POST** con **CSRF** y token secreto rotado desde **gestor de secretos**.
- Registrar auditoría (quién/cuándo/desde dónde).

### 3.6 Integración con SII (Selenium + Cookies)

Riesgos:

- Almacenamiento de cookies SII en disco `facturas_sii/cookies/cookies.json` sin cifrado.
- `Proveedor.clave_sii` almacenada en texto claro.
- Automatización Selenium susceptible a cambios UI; riesgo de credenciales en logs.

Mitigación:

- Evitar persistir credenciales SII; si fuese imprescindible, **cifrado a nivel de aplicación** (AES-GCM) con claves en gestor de secretos y rotación.
- Enmascarar/limpiar logs, usar contenedores aislados para Selenium, borrar cookies al finalizar.
- Explorar canales API oficiales/documentados del SII (cuando disponibles) y acuerdos de uso.

### 3.7 Base de Datos y Datos Sensibles

Riesgos:

- SQLite no apto para producción. Sin cifrado en reposo y sin control de acceso.
- Sin estrategia de backups, retención ni pruebas de restauración.
- Campos sensibles (e.g., `clave_sii`, cookies SII) sin cifrado.

Mitigación:

- Migrar a **PostgreSQL** administrado (cifrado en reposo, TLS en tránsito, PITR) y roles mínimos.
- Cifrado de campos sensibles (e.g., Fernet/AES-GCM con claves de Secrets Manager/Vault).
- Políticas de retención y borrado seguro, y planes de respaldo/restauración probados.

### 3.8 Entradas, Validación y Seguridad de API

Riesgos:

- Falta de validación/pydantic para formularios y parámetros (tamaños, formatos).
- Sin CORS/CSRF explícitos (menos crítico si solo SSR, pero necesario si se expone API a frontends separados).

Mitigación:

- DTOs Pydantic para todas las entradas; validaciones estrictas.
- CSRF tokens en formularios; CORS cerrado por origenes permitidos.
- Rate limiting global y por endpoint.

### 3.9 Cabeceras y Endurecimiento HTTP

Riesgos:

- No se establecen headers de seguridad.

Mitigación:

- Añadir: `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`.
- Forzar HTTPS y HSTS en producción.

### 3.10 Registro, Auditoría y Monitoreo

Riesgos:

- Sin logging estructurado ni auditoría (logins, cambios de estado, adjudicaciones).
- Sin monitoreo de seguridad ni APM.

Mitigación:

- Logging estructurado (JSON) + trazas (OpenTelemetry).
- Alertas (Sentry/Elastic/SIEM) para eventos clave: múltiples fallos de login, cambios de permisos, uso de endpoints admin.
- Métricas técnicas y de negocio (prometheus/grafana).

---

## 4) Cumplimiento Regulatorio (Chile) – Resumen y Mapeo

Nota: Referencias de alto nivel. Validar con asesoría legal/regulatoria especializada para su caso concreto.

- **CMF (ex SBIF) – Ciberseguridad y Riesgo Operacional**

  - Exige marcos de gestión de seguridad de la información, continuidad de negocio, gestión de incidentes, segregación de funciones, control de accesos y monitoreo.
  - Recomendación: Alinear con **ISO/IEC 27001/27002** y controles **NIST CSF**; políticas de ciberseguridad, gestión de terceros y pruebas periódicas (pentest, DRP/BCP).

- **Ley 19.628 – Protección de Datos Personales**

  - Principios: licitud, proporcionalidad, finalidad; derechos ARCO; medidas de seguridad adecuadas; notificación de incidentes (según normativa sectorial).
  - Recomendación: Registro de actividades de tratamiento, políticas de retención/borrado, contratos de encargado, consentimiento cuando corresponda.

- **Ley 19.799 – Firma Electrónica** (aplicable a DTE y documentos electrónicos)

  - Garantiza validez de documentos electrónicos y exigencias de integridad/autenticidad.
  - Recomendación: Preservación de integridad de DTE, sellos de tiempo, resguardo y trazabilidad.

- **SII – Normativa DTE**

  - Adopción de estándares del SII para emisión/recepción/almacenamiento DTE, integridad del documento, y plazos de conservación.
  - Recomendación: Cumplir con formatos, conservación, y controles de integridad/huellas; evitar manipulación no autorizada.

- **Ley Fintech (Ley 21.521) y normativa secundaria**
  - Lineamientos de seguridad para Open Finance e interfaces seguras, gestión de riesgos tecnológicos, protección del consumidor.
  - Recomendación: Autenticación robusta, autorización granular, cifrado extremo a extremo y gobernanza de APIs.

---

## 5) Recomendaciones de Arquitectura para Producción

### 5.1 Autenticación y Gestión de Identidad

- Adopción de **IdP gestionado** (Auth0, AWS Cognito, WorkOS): MFA, políticas de contraseña, detección de bots, flujos de recuperación, cumplimiento.
- JWT con scopes/roles e introspección; revocación y rotación de tokens; sesiones server-side (Redis) si SSR.

### 5.2 Segmentación/Microservicios (evolutiva)

- Separar portales por rol (Proveedor, Pagador, Financiador, Middle Office) con **frontends independientes** o al menos espacios de sesión separados.
- Backend modular/servicios: `core-invoices`, `offers`, `marketplace`, `admin`, `sii-adapter`.

### 5.3 Seguridad de API

- Rate limiting (SlowAPI/Envoy), protecciones contra brute force y scraping.
- Validación Pydantic exhaustiva, schemas OpenAPI, versionado de APIs.
- WAF/CDN (Cloudflare/AWS WAF) con reglas OWASP.

### 5.4 Datos y Base de Datos

- Migrar a **PostgreSQL gestionado** (TLS, at-rest encryption, PITR). Usuarios/roles mínimos.
- **Cifrado por campo** para secretos SII y datos altamente sensibles; claves en **Secrets Manager** o **Vault**.
- Backups automáticos, pruebas de restauración y retención acorde a normativa SII/CMF.

### 5.5 Infraestructura y DevSecOps

- **Containerización** (Docker) ejecutando como non-root, con `gunicorn + uvicorn workers` detrás de reverse proxy.
- **Gestión de secretos** (AWS Secrets Manager/Parameter Store/Vault). Nunca en repositorio.
- **CI/CD seguro**: SAST (Bandit/Semgrep), dependencia segura (pip-audit/safety), imagen escaneada (Trivy), secrets scanning, políticas de branch protection.
- Telemetría: logs estructurados, métricas, trazas. Alertas y dashboards.

### 5.6 Frontend/SSR

- CSRF tokens en formularios SSR y SameSite cookies.
- CSP estricta (sin inline scripts), HSTS, XFO DENY.

---

## 6) Roadmap Priorizado

### Fase 0 (0–2 semanas) – Quick Wins

- Configurar `SessionMiddleware` seguro (secure, httponly, samesite, max_age) y secreto fuerte.
- Arreglar **IDOR** críticos: validar pertenencia de facturas/ofertas en todos los endpoints de mutación.
- Proteger `/admin/reset` (POST + admin autenticado + CSRF + logging).
- Limitar uploads (tamaño/MIME), sanitizar nombres, validar ZIP seguro, usar `defusedxml`.
- Añadir rate limiting básico en `/login` y alertas por intentos fallidos.
- Añadir headers de seguridad (HSTS, CSP básica, XFO, XCTO, RP, PP).

### Fase 1 (2–6 semanas)

- Migración a **PostgreSQL** gestionado; TLS; roles mínimos; backups automáticos.
- Introducir **IdP** (MFA, password policy, bloqueo de cuenta) o fortalecer login propio con MFA.
- Sesiones server-side (Redis) o JWT con expiración corta y refresh tokens.
- Cifrado de campos sensibles (clave SII/cookies) y rotación de secretos.
- Auditoría: logs de seguridad, SIEM/Sentry, trazabilidad de cambios críticos.

### Fase 2 (6–12 semanas)

- Separación de portales por rol / microservicios ligeros.
- WAF/CDN, rate limiting avanzado, bot management.
- Pipeline CI/CD con SAST/DAST y escaneo de dependencias e imágenes.
- Políticas de retención y borrado seguro; revisiones periódicas (pentest).

---

## 7) Recomendaciones Tecnológicas (con guía de implementación)

- **Auth**: Auth0 (rápida integración, MFA, logs, detección de anomalías); alternativa AWS Cognito (menor costo, mayor configuración); WorkOS (empresas B2B/SSO).
- **Rate Limiting**: `slowapi` (Starlette/FastAPI), o Envoy/Nginx Ingress.
- **CSRF**: `starlette-wtf` o middleware personalizado con tokens por sesión.
- **DB**: PostgreSQL (RDS/Aurora/GCP Cloud SQL) con PITR, backups diarios y réplicas.
- **Cifrado de campo**: `cryptography` (Fernet/AES-GCM) + KMS/Secrets Manager.
- **Logging/Monitoreo**: Sentry + OpenTelemetry + Prometheus/Grafana + SIEM (Elastic/Splunk/CloudWatch).
- **Contenedores**: Docker + Gunicorn/Uvicorn + non-root + distroless. Escaneo con Trivy.
- **WAF/CDN**: Cloudflare/AWS WAF + reglas OWASP + bot fight mode (opcional).

---

## 8) Análisis Costo–Beneficio (resumen)

- IdP gestionado (Auth0/Cognito):
  - Beneficio: MFA, cumplimiento, menor time-to-market. Costo mensual por usuario/MAU.
- Migración a PostgreSQL gestionado:
  - Beneficio: resiliencia, cifrado, backups. Costo infra moderado.
- WAF/CDN + rate limiting:
  - Beneficio: mitigación DDoS/bots/OWASP Top 10. Costo según tráfico.
- Cifrado por campo/Secrets Manager:
  - Beneficio: reducción impacto de brechas. Costo bajo–medio.
- Logging/Monitoreo:
  - Beneficio: detección temprana, cumplimiento. Costo según stack.

ROI general: Alto, por reducción de riesgo financiero/regulatorio y continuidad operativa.
