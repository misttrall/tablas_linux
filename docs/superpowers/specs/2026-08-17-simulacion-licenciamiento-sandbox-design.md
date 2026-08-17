# Entorno de Pruebas, Simulación y Sandbox de Licenciamiento Novus

Fecha: 2026-08-17 · Estado: aprobado e implementado · Rama: dev · Espec padre: `2026-08-16-licenciamiento-product.md`

---

## 1. Decisión de Negocio y Contexto

Para garantizar la fiabilidad del sistema de licenciamiento criptográfico (Ed25519) implementado en la Fase 2, se requiere:
1. Un **catálogo formal de escenarios de prueba** que evalúe exhaustivamente todos los estados de validez, modularidad, períodos de gracia, degradación ante fallas de red, intentos de adulteración y límites de usuarios.
2. Un **entorno sandbox aislado y reproducible** que permita levantar servicios independientes (License Server y Dashboard Web) en puertos dedicados (`:8082` y `:8083`), sin colisionar con entornos de producción (`:8000`) o demos existentes (`:8001`).
3. **Reactividad en tiempo real**: Los cambios de licencia inyectados (por ejemplo, suspensión por mora o reactivación tras pago) deben surtir efecto inmediatamente en el Dashboard Web sin necesidad de reiniciar procesos.
4. **Protección estricta de rutas y templates**: Blindaje total contra bypass de inicio de sesión y acceso a vistas protegidas cuando la licencia no está activa o el usuario no está autenticado.

---

## 2. Arquitectura del Sistema de Simulación

```
                        ┌─────────────────────────────────────────────────────────┐
                        │        SIMULADOR CLI (scripts/simulate_licensing.py)    │
                        │  - run-all (evalúa matriz E01..E12)                     │
                        │  - scenario <ID> (inyección de caché en caliente)       │
                        │  - token (generador JWT Ed25519 ad-hoc)                 │
                        │  - server (License Server mock efímero en :8082)        │
                        └───────────────────────────┬─────────────────────────────┘
                                                    │ Inyecta estado / token
                                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ SANDBOX AISLADO (/tmp/etl_sandbox/ · scripts/run_license_sandbox.sh)                    │
│                                                                                         │
│  ┌──────────────────────────────┐                ┌───────────────────────────────────┐  │
│  │ License Server (:8082)       │                │ ETL Dashboard (:8083)             │  │
│  │ - server.db (SQLite)         │ ◄────────────► │ - dashboard/app.py                │  │
│  │ - Claves Ed25519 efímeras    │   HTTP / JWT   │ - sandbox_db.sqlite (ERP fixtures)│  │
│  │ - Endpoints /api/activate, / │                │ - LicenseManager (mtime watcher)  │  │
│  └──────────────────────────────┘                └─────────────────┬─────────────────┘  │
└────────────────────────────────────────────────────────────────────┼────────────────────┘
                                                                     │
                                     ┌───────────────────────────────┴────────────────────┐
                                     │ CAPA DE SEGURIDAD Y PROTECCIÓN DE RUTAS            │
                                     │  • Templates privados en dashboard/templates/      │
                                     │  • Static público restringido a .css/.js/.png      │
                                     │  • Redirección 307 a /login si no hay sesión       │
                                     │  • Gating a license.html en estados bloqueados     │
                                     │  • 403 Forbidden en APIs ante licencia bloqueada   │
                                     └────────────────────────────────────────────────────┘
```

---

## 3. Matriz de 12 Escenarios de Licenciamiento

| ID | Escenario | Estado Esperado | Módulos (`der`/`dash`/`bi`) | Límites | Comportamiento del Sistema |
|:---:|:---|:---:|:---:|:---:|:---|
| **E01** | **Licencia Completa Activa** | `ACTIVE` | ✅ / ✅ / ✅ | 10 usuarios | Operación normal al 100%. Todas las vistas y APIs habilitadas. |
| **E02** | **Modular: Solo Dashboard** | `ACTIVE` | ❌ / ✅ / ❌ | 5 usuarios | Dashboard habilitado. `cli reporte` y `cli bi` bloqueados con `LicenseNotEntitled`. |
| **E03** | **Modular: Sin Dashboard** | `ACTIVE` | ✅ / ❌ / ✅ | 5 usuarios | CLI reporte y BI operativos. Dashboard web redirige a `license.html`. |
| **E04** | **Límite de Usuarios Alcanzado** | `ACTIVE` | ✅ / ✅ / ✅ | 2 usuarios | Permite 2 usuarios activos. Creación de 3er usuario rechazada con HTTP 403 `limite_usuarios`. |
| **E05** | **Período de Gracia (Grace Period)** | `GRACE` | ✅ / ✅ / ✅ | 5 usuarios | `valid_until` vencido pero `now <= offline_until`. Servicio operativo con banner de advertencia. |
| **E06** | **Licencia Vencida (Expired)** | `EXPIRED` | ❌ / ❌ / ❌ | 5 usuarios | `now > offline_until`. Bloqueo total de módulos opt-in; datos conservados. |
| **E07** | **Licencia Suspendida** | `SUSPENDED` | ❌ / ❌ / ❌ | 5 usuarios | Suspensión comercial por Novus. Bloqueo total inmediato. |
| **E08** | **Licencia Revocada** | `REVOKED` | ❌ / ❌ / ❌ | 5 usuarios | Anulación total inmediata del contrato. |
| **E09** | **Servidor Inaccesible con Caché** | `ACTIVE` | ✅ / ✅ / ✅ | 10 usuarios | Caída de red; el caché local permite continuar operando sin interrupción. |
| **E10** | **Servidor Inaccesible sin Caché** | `UNREACHABLE` | ❌ / ❌ / ❌ | - | Sin caché local y sin conexión al servidor; rechazo controlado con `LicenseUnreachable`. |
| **E11** | **Manipulación / Firma Adulterada** | `INVALID` | ❌ / ❌ / ❌ | - | Token alterado o clave falsa; rechazo criptográfico inmediato con `LicenseInvalid`. |
| **E12** | **Modo Sin Licencia (Open)** | `NO_LICENSE` | ✅ / ✅ / ✅ | Ilimitado | Configuración de desarrollo sin bloque `license`. Todo habilitado. |

---

## 4. Decisiones de Diseño Clave

### 4.1 Reactividad en Tiempo Real (`mtime` Cache Watcher)
- **Problema previo**: `LicenseManager` almacenaba el token en memoria (`self._cached`) durante el ciclo de vida del proceso uvicorn (hasta 12h), ignorando actualizaciones del archivo `license_cache.json` en disco realizadas por procesos CLI externos.
- **Solución implementada**: `LicenseManager.get_license()` y `validate()` inspeccionan `os.path.getmtime(self._cache_path)`. Si el timestamp difiere de `self._cached_mtime`, se recarga y valida el token desde disco en la misma petición (< 0.05 ms).

### 4.2 Separación Estricta de Templates y Archivos Estáticos
- **Problema previo**: Los archivos HTML residían en `dashboard/static/`, permitiendo acceso directo a `/static/panel.html` sin autenticación ni validación de licencias.
- **Solución implementada**:
  - Los archivos HTML se ubicaron en `dashboard/templates/` privado.
  - `FastAPI.mount("/static", ...)` solo expone `.css`, `.js`, `.png`.
  - Rutas de página (`/panel`, `/etl`, `/derivadas`, `/login`, `/`) exigen sesión activa (`307 Redirect` a `/login`).
  - Si la licencia está bloqueada (`SUSPENDED`, `EXPIRED`, `REVOKED`) o carece del módulo `dashboard`, todas las rutas de interfaz retornan `license.html`.
  - APIs de backend (`/api/dashboard`, `/api/executions`, `/api/progress`, `/api/live`, `/api/admin/users*`) devuelven `403 Forbidden` (`{"detail": "licencia:SUSPENDED"}`).

### 4.3 Inicialización Idempotente del Sandbox
- El script `scripts/run_license_sandbox.sh` inicializa la base del License Server y genera el caché inicial (`E01`) **antes** de invocar migraciones o crear usuarios, asegurando que `admin` / `admin` siempre esté presente y operativo.

---

## 5. Herramientas y Artefactos Producidos

1. **`scripts/simulate_licensing.py`**: CLI de evaluación matricial, inyección de escenarios y generación de tokens JWT Ed25519.
2. **`scripts/run_license_sandbox.sh`**: Orquestador de sandbox aislado con base de datos SQLite y datos ERP sintéticos (MARA, MARD, MBEW, MAKT, T001L).
3. **`tests/test_licensing_simulation_e2e.py`**: Suite de 10 tests E2E que valida la matriz completa, endpoints FastAPI y comandos CLI.
4. **`cli.py` (`etl license inspect`)**: Comando CLI de inspección diagnóstica del estado de la licencia, frescura de caché y límites de usuarios.
5. **`docs/SIMULACION_LICENCIAMIENTO.md`**: Guía operativa detallada de simulación y sandbox.
