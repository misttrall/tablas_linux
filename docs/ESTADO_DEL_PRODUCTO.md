# Estado del Producto — Novus ETL (tablas-etl 0.4.0)

> Snapshot verificado contra código (rama `dev`, 2026-08-17). Este documento describe **lo que existe realmente**; ante conflicto con otros docs, este prevalece.
> Discrepancias detectadas en README/RUNBOOK: ver sección 10.

## 1. Visión general

Motor ETL multi-ERP → DWH → Dashboard, con capa BI y licenciamiento de producto:

- **Fuentes**: SAP RFC, CSV, HTTP (REST)
- **Destinos**: SQL Server (mssql), PostgreSQL, MySQL, SQLite
- **Pipeline**: extracción (full/rangos/delta) → staging (`stg_<tabla>`) → MERGE idempotente → modelos derivados → Excel/BI
- **Producto licenciable**: módulos opt-in (`derived`, `dashboard`, `bi`) con JWT ed25519 y gracia offline

## 2. Módulos

| Módulo | Responsabilidad |
|---|---|
| `sources/` | Conectores de origen (ABC `SourceConnector`): `sap/` (pyrfc), `generic/csv.py`, `generic/http.py`; `partitioning.py` extracción por rangos |
| `db/` | Persistencia: engine por dialecto, `control.py` (locks BD, deltas), `staging_loader.py`, `merge_runner.py`, `sinks/` por dialecto (mysql, postgres, sqlite, sqlserver) |
| `derived/` | Modelos derivados declarativos (`config['derived']`, 1..N vistas): `materializer.py`, `views.py`, `excel_export.py`, `minimos_import.py` |
| `bi/` | Entregable BI: `manifest.py`, `export.py` (CSV siempre / Parquet si pyarrow), `guide.py` (Power BI) |
| `dashboard/` | FastAPI + auth JWT (cookie `etl_session`, bcrypt, rate limit) + gating por licencia |
| `licensing/` | Cliente de licencias: `LicenseManager`, caché firmada `~/.novus/license-<customer>.json`, validación ed25519 |
| `license_server/` | Servidor de licencias: API `/api/activate`, SQLite `novus_license.db`, firma ed25519 |
| `utils/` | config loader + JSON Schema, estado ETL (`/tmp/etl_state.json`), live (`/tmp/etl_live.json`), logger |
| `cli.py` | CLI `etl` (ver §3) + runner de migraciones SQL |
| `etl_runner.py` | Orquestador: locks (archivo + BD), extrae, staging, merge, derived, state/live |

## 3. CLI `etl` (completo)

```
etl run                     [--job] [--tables] [--config]
etl migrate                 [--config]          # migrations/<dialect>/*.sql → schema_migrations
etl status                  [--last N] [--config]
etl reporte                 [--tabla] [--config] # regenera Excel derivados (sin SAP)
etl bootstrap               [--with-derived] [--skip-sap] [--config]
etl importar-minimos        --archivo --hoja [--tabla stock_minimo] [--col-material] [--col-stock] [--col-area]
etl bi {manifest|export|guide}                   # export: --out-dir (default output/bi)
etl users {add|list|set-password}                # add: --username --password --role {user,admin} [--root] [--no-force-password-change]
etl license {status|inspect|activate|validate|clear-cache}
```

- `users add` y `POST /api/admin/users` respetan el límite `users` de la licencia.
- `reporte`, `bootstrap --with-derived` y la materialización de `etl run` requieren módulo `derived`; `bi` requiere módulo `bi`.

## 4. Dashboard — endpoints

**Públicos**: `GET /api/health`, `GET /api/branding`, `GET /login` (HTML), `GET /derivadas` (si licencia bloqueada → `license.html`).

**Auth (`/api/auth/*`, requieren sesión)**: `POST login` (rate limit 10/min/IP), `POST logout`, `GET me`, `POST password`.

**Admin (`/api/admin/*`)**: `GET/POST /users` (POST con límite de licencia), `PATCH/DELETE /users/{id}`, `POST /users/{id}/password`.

**Datos (sesión + módulo `dashboard`)**:
- Admin-only: `/api/executions`, `/api/progress`, `/api/dashboard`, `/api/tables`, `POST /api/etl/trigger`, `/api/onboarding/{status,test-sap,save-sap}`
- Usuario: `/api/live`, `/api/last-sync`, `/api/inventory*`, `/api/derived/{name}/{summary,filters,items,alerts,export/excel,export/csv}`, `/api/derived-views`
- `GET /api/license` (sesión, sin gate de módulo)

**BI (sesión + módulo `bi`)**: `/api/bi/{manifest,guide,export}`, `/api/bi/download/{view}/parquet|csv`, `/api/bi/download/{manifest,guide}`, `/api/bi/download-zip`.

**Páginas**: `/` (redirect según sesión), `/login`, `/panel` (admin), `/etl` (admin), `/derivadas`, `/inventario` (redirect retro-compat). Templates en `dashboard/templates/`: login, panel, etl, derivadas, license.

## 5. License server

**API**: `GET /api/health`, `POST /api/activate` (`{customer_id, api_key}`, rate limit 30/min). Puerto 8080 (`scripts/run_license_server.sh`, requiere `NOVUS_LICENSE_SERVER_SECRET`).

**CLI**:
```
license-server keygen
license-server customer {add --id --name --api-key | list | disable --id}
license-server license {issue --customer --license-id --valid-until [--valid-from] [--grace-days=7] --modules ... [--limit users=N]
                        | renew --license-id --valid-until [...] | suspend --license-id | revoke --license-id
                        | show --license-id | list [--customer]}
```

**Seguridad**: api_key se almacena como **HMAC-SHA256 con pepper `NOVUS_LICENSE_SERVER_SECRET`** (comparación constant-time). ⚠️ Perder/rotar el pepper invalida todos los hashes. Clave privada en `license_server/private_key.pem` (0600, gitignored).

**Comportamiento del cliente**: caché firmada con `refresh_minutes` (default 720 = 12 h). El dashboard (singleton) sirve el caché hasta 12 h aunque se revoque en el servidor; detecta cambio de mtime del archivo (re-activar en el mismo host sí se propaga). Una revocación server-side tarda hasta 12 h en reflejarse sin restart.

## 6. Config (`schemas/config.schema.json`)

Top-level: `environment` (`qa|prd`), `guard.large_tables`, `source` (`type`: `sap|csv|http`), `sap` (legacy), `database` (`dialect`: `mssql|sqlite|postgresql|mysql`), `tables[]`, `fields`, `derived` (objeto o lista de vistas), `dashboard` (title/logo/color/footer), `license` (server, customer_id, api_key, public_key, cache_path, refresh_minutes — **sin bloque = todo habilitado, modo dev/CI**).

## 7. Migraciones

001_control_tables, 002_etl_progress_delta, 003_etl_execution_tables, 004_app_users.
⚠️ 003 solo existe en `mssql/` y `sqlite/` (no en mysql/postgresql).

## 8. Tests

30 archivos, **313 tests** (298 pass + 19 skipped SAP/PG/MySQL live en última corrida). Cobertura: sinks por dialecto, auth/seguridad, gating de licencias, simulación E2E de licenciamiento, onboarding, bootstrap, dashboard, BI, particionado.

## 9. Deploy / scripts

- `deploy/install.sh` (systemd, puerto **8000**), `etl-sync.timer` (hourly :45), `etl-docker.sh` (systemd en contenedor), `docker-entrypoint.sh`
- `scripts/`: `run_demo.sh` (demo puerto **8001**), `run_license_server.sh` (8080), `run_license_sandbox.sh` (sandbox 8082/8083, admin/admin), `init_demo_data.py` (usuarios demo: **admin/admin, analista/demo1234**), `simulate_licensing.py`, `verify_dashboard.py`
- `Dockerfile` (python:3.12-slim), `docker-compose.yml`, requirements por perfil (base/ci/etl/sap/web)

## 10. Discrepancias conocidas (docs vs código)

> **Resueltas el 2026-08-17**: README.md y RUNBOOK.md fueron corregidos y la información de `DOCUMENTACION_GENERAL_SISTEMA.md`, `DESPLIEGUE_DOCKER.md` y `SIMULACION_LICENCIAMIENTO.md` fue condensada e integrada en ellos (esos archivos fueron eliminados). La tabla siguiente se conserva como registro histórico de la auditoría.

| Severidad | Doc | Problema |
|---|---|---|
| Alta | README:24,368; RUNBOOK:93,126 | Botón Sincronizar documentado para rol `user` y pestaña inventario; en realidad `POST /api/etl/trigger` es **admin-only** y `/derivadas` no tiene botón sync |
| Media | RUNBOOK:184 | Login documentado como `GET /api/auth/login`; es **POST** |
| Media | RUNBOOK:184 (backup) | Tablas `etl_control`/`etl_execution_table` inexistentes (reales: `etl_execution`, `etl_progress`, `etl_execution_tables`, `app_users`, `schema_migrations`) |
| Media | README:619+ (árbol) | Árbol desactualizado: HTML vive en `dashboard/templates/` (no en static/); faltan `bi/`, `licensing/`, `license_server/`, `scripts/`, `docs/` |
| Media | README:345 | Ejemplo verify_dashboard usa usuario `demo`; el demo crea `analista`/`demo1234` |
| Media | docs/DOCUMENTACION_GENERAL_SISTEMA.md | Llama "puerto principal" al 8001 (es el demo); producción es 8000 |
| Media | README branding | White-label no cubre `<title>` (hardcodeado "Novus BI"), favicon ni algunos textos (license.html soporte) |
| Media | README/RUNBOOK | No documentan HMAC+pepper de api_key ni la propagación de 12 h de revocaciones |
| Baja | README | Falta `etl license inspect`, endpoints BI/onboarding/branding/license, rate limits, CLI completo del license server; conteo de tests (20→31); dominio lic.novusit.cl vs licencias.novusit.cl |

## 11. Limitaciones conocidas del producto

1. **White-label parcial**: titles/favicon/textos Novus hardcodeados en templates.
2. **Propagación de licencia**: revocación server-side tarda hasta `refresh_minutes` (12 h default) en afectar al dashboard; re-emisión en el mismo host se detecta por mtime.
3. **Migración 003** ausente en mysql/postgresql.
4. **License server**: SQLite single-node; sin admin REST API (solo CLI).
