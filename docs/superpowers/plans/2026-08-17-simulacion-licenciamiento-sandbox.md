# Entorno de Pruebas y Simulación de Licenciamiento Implementation Plan

> **Goal:** Proveer una herramienta de simulación de licenciamiento (`scripts/simulate_licensing.py`), un entorno sandbox aislado de ejecución (`scripts/run_license_sandbox.sh`), suite de pruebas E2E automatizada (`tests/test_licensing_simulation_e2e.py`), reactividad en tiempo real de caché en `LicenseManager`, blindaje de rutas contra bypass de autenticación y documentación operativa.

**Architecture:** Matriz de 12 escenarios (`E01` a `E12`) con generador JWT Ed25519; sandbox aislado en `/tmp/etl_sandbox/` (License Server en `:8082`, Dashboard en `:8083`); `LicenseManager` con detección por `mtime` en `licensing/client.py`; templates privados en `dashboard/templates/` y gating estricto en todas las rutas y APIs.

**Tech Stack:** Python 3.10+, FastAPI, Ed25519 (PyJWT + cryptography), SQLite, Bash, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-17-simulacion-licenciamiento-sandbox-design.md`

---

## Tareas Ejecutadas y Verificadas

- [x] **Task 1: Herramienta de Simulación Matricial (`scripts/simulate_licensing.py`)**
  - Implementación de los 12 escenarios de licenciamiento (`E01` a `E12`).
  - Subcomandos: `run-all` (con salida estándar, `--md` y `--json`), `scenario <ID>`, `token` y `server`.
  - Detección automática de clave privada Ed25519 co-localizada.
  - Limpieza de managers en memoria durante inyección de escenarios.

- [x] **Task 2: Orquestador de Sandbox Aislado (`scripts/run_license_sandbox.sh`)**
  - Despliegue en `/tmp/etl_sandbox/` en puertos no colisionantes (`:8082` y `:8083`).
  - Generación de claves Ed25519 efímeras y fixtures ERP sintéticos (MARA, MARD, MBEW, MAKT, T001L).
  - Inicialización idempotente del License Server (`server.db`) y creación garantizada del usuario `admin` / `admin`.
  - Comandos: `start`, `stop`, `restart`, `status`, `scenario <ID>`, `log`, `clean`.

- [x] **Task 3: Reactividad de Licencia en Tiempo Real (`licensing/client.py`)**
  - Implementación de `_disk_cache_mtime()` en `LicenseManager`.
  - Detección automática de cambios en disco en `get_license()` y `validate()`.
  - Reflejo instantáneo de cambios de estado (`ACTIVE`, `SUSPENDED`, `GRACE`, `EXPIRED`) en la siguiente petición HTTP sin reiniciar servidores.

- [x] **Task 4: Blindaje de Rutas y Separación de Templates (`dashboard/app.py` y `dashboard/auth/router.py`)**
  - Reubicación de archivos HTML en `dashboard/templates/` privado (previene bypass de login mediante `/static/*.html`).
  - Redirección `307` a `/login` para accesos no autenticados en `/`, `/panel`, `/etl`, `/derivadas`, `/inventario`.
  - Gating hacia `license.html` en `/panel`, `/etl` y `/derivadas` ante licencias bloqueadas (`SUSPENDED`, `EXPIRED`, `REVOKED`) o sin módulo contratado.
  - Respuestas `403 Forbidden` en todas las APIs de datos (`/api/dashboard`, `/api/executions`, `/api/progress`, `/api/tables`, `/api/live`, `/api/last-sync`, `/api/etl/trigger`, `/api/admin/users*`).

- [x] **Task 5: Comando de Inspección en CLI (`cli.py`)**
  - Subcomando `etl license inspect` con diagnóstico completo de vigencia, días restantes de gracia, frescura de caché, límites de usuario y estado modular.

- [x] **Task 6: Suite E2E Automatizada y Documentación**
  - Suite `tests/test_licensing_simulation_e2e.py` (10 tests E2E, 100% aprobados).
  - Guía operativa: `docs/SIMULACION_LICENCIAMIENTO.md`.
  - Actualización de `RUNBOOK.md` (Sección 12).
  - Validación completa del repositorio: 308 tests aprobados, 19 omitidos, 0 fallos.
