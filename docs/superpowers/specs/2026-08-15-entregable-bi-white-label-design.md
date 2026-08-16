# Entregable BI para clientes: módulo `bi/` + dashboard white-label

Fecha: 2026-08-15 · Estado: propuesto · Rama: dev (v0.4.0 cerrado en `5dea22c`)

## Decisión de negocio (contexto)

El producto ETL→BD→DWH se vende como el servicio "Datos/BI" de Novus (https://novusit.cl):
motor ETL + DWH + entregable BI, con licencia por empresa y módulos opt-in (espejo de
NovuSuite). La promesa comercial de Novus en el pilar BI es "dashboards en Power BI".

Decisión tomada en brainstorming (2026-08-15):

1. El cliente **consume dashboards que Novus construye** — no hay auto-servicio.
2. Entorno de clientes **mixto**: algunos con Power BI, otros sin nada.
3. La BD destino del DWH es **mayoría MSSQL** (conector Power BI nativo y sin costo).
4. Clientes **sin Power BI** reciben el dashboard web FastAPI con **white-label**.
5. `config.json`/`inv_bodega` son **ejemplo**: cada empresa tiene su propio config
   adaptado; el apartado de tablas/columnas es modulable por empresa.

## Alcance (Fase 1)

Construir la capa de entregable BI sobre el estado v0.4.0:

- **`bi/`**: manifiesto de dataset + guía de conectividad + export CSV/Parquet,
  todo leído de `config['derived']` (nada hardcodeado a `inv_bodega` ni columnas SAP).
- **Dashboard white-label**: pestañas derivadas por vista, branding por config,
  monitoreo `#etl` restringido a admin (herramienta interna Novus).
- **CLI**: subcomando `cli bi` (`manifest`, `export`, `guide`).
- **Config por empresa**: validación modular contra `config.schema.json`;
  campo `modules` solo documental (bloqueo real en Fase 2 de licenciamiento).

Fuera de alcance: modelo Power BI a medida por cliente (lo arma Novus en Power BI
Desktop, es servicio facturable), licenciamiento/`product/` (Fase 2), telemetría,
adaptadores Oracle/Mongo (Fase 3).

## Principio rector

**Un solo config por empresa** alimenta ETL, DWH, dashboard y `bi/`. `derived[]` es el
contrato: cada vista = una tabla materializada + una pestaña de dashboard + una
entrada del manifiesto BI + un export. Nada se hardcodea a nombres SAP.

## Arquitectura

```
config.json (empresa) ──► ETL (tablas + fields)
                            │
                            ▼
                    BD destino (MSSQL/…)
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
   derived[] materializa           bi/manifest.py (lee derived[])
   inv_bodega, ventas, costos      bi/export.py (CSV/Parquet)
              │                           │
              ▼                           ▼
   Dashboard FastAPI            Power BI (Novus modela,
   pestañas = derived[]         medidas a medida, publica)
   branding por config
```

## Sección 1 — Módulo `bi/`

No es un segundo modelo de datos; es una capa de conectividad que lee el config de la
empresa y genera el entregable de Power BI.

1. **`bi/manifest.py`** — genera un manifiesto del dataset a partir de `config['derived']`:
   vistas derivadas, columnas, tipos, claves y sugerencias de medidas (p. ej. para
   `ValorTotal`), en JSON legible para que Novus modele en Power BI. Cubre todas las
   vistas declaradas (derived[] múltiple).
2. **`bi/guide.md`** — guía de conectividad por dialecto: MSSQL nativo (importación o
   DirectQuery), PostgreSQL/MySQL → connector ODBC, SQLite → nota de no-soportado con
   recomendación de mover el DWH a MSSQL para clientes BI. Se parametriza por empresa
   con su `derived.name`.
3. **`bi/export.py`** — exporta cada vista derivada a CSV/Parquet. Rutas de directorio
   tomadas de `config.derived.excel` como referencia. Útil para clientes con Power BI
   sin conectividad de red directa a la BD (importación por archivo).

## Sección 2 — Dashboard white-label con pestañas por vista

El dashboard pasa de una sola vista a renderizar cada entrada de `derived_views(config)`
como una pestaña.

1. **Pestañas derivadas** — cada vista declara `{ "name", "tab", ... }`. `tab` es
   **opcional**: si falta, se deriva un nombre legible de `name` (p. ej. `inv_bodega` →
   "Inv Bodega"). Retrocompatible con configs existentes.
2. **Contenido por pestaña** — filtros (de `view.inventory.filters`), KPIs resumidos
   (generalizando `_inventory_summary`: total filas, total `total_field`, alertas según
   `view.alerts`), tabla de items, export Excel (ya existe por vista).
3. **Rutas dinámicas** — `/api/derived/<name>/summary`, `/api/derived/<name>/filters`,
   `/api/derived/<name>/items`, `/api/derived/<name>/alerts`. Alias `/api/inventory*`
   apuntando a la primera vista (retrocompatibilidad).
4. **Generalización** — `_inventory_frame`, `_inventory_summary`, `_filter_inventory` se
   parametrizan por vista. Hoy asumen campos como `MATNR`; se reemplazan por metadata de
   la vista (`view.get("row_label")`, campos de resumen) con defaults retrocompatibles.
5. **Branding por config** — bloque `config["dashboard"]` (o dentro de la vista):
   `{ "title", "logo", "color", "footer" }`. La plantilla HTML lo pinta; sin branding,
   defaults neutros.
6. **Monitoreo `#etl`** — restringido a rol admin = herramienta interna Novus, no
   visible al cliente.
7. **Multi-empresa** — N configs + N servicios (nativo con `ETL_CONFIG` por servicio) o
   Docker por empresa.

## Sección 3 — Config por empresa (modulabilidad)

1. **`config.example.json` como plantilla de referencia** — se mantiene como ejemplo
   documentado, no como único config. El deploy instala con `ETL_CONFIG` por empresa.
2. **Validación modular** — `config.schema.json` valida por módulo: `source`, `database`,
   `tables`+`fields`, `derived[]` (cada vista con sus sub-bloques). Un config nuevo de
   empresa se valida contra el schema antes de arrancar.
3. **Bootstrap por empresa** — `cli bootstrap [--skip-sap] [--with-derived]` usa
   `ETL_CONFIG`. Onboarding de cliente: copiar `config.example.json` → adaptar
   `source/database/tables/fields/derived[]` → `cli migrate` → `cli bootstrap`.
4. **Módulos opt-in** — `{ "modules": ["etl", "derived", "dashboard", "bi"] }` es
   **solo documental** por ahora; el bloqueo real llega con licenciamiento (Fase 2).

## Sección 4 — CLI

Subcomando nuevo `cli bi` (no se integra en `reporte`/derived — separación clara y
testable):

- `cli bi manifest [--config PATH]` — escribe el manifiesto JSON.
- `cli bi export [--config PATH]` — escribe CSV/Parquet de cada vista.
- `cli bi guide [--config PATH]` — emite la guía de conectividad parametrizada.

## Sección 5 — Manejo de errores y testing

**Errores:**

- Vista declarada pero no materializada → el comando reporta y continúa con las demás;
  exit 0 con warnings. Si ninguna vista existe → exit 1 con mensaje accionable.
- Pestaña con vista no materializada → muestra "datos no disponibles", el resto sigue
  funcionando (`available: False` ya existente, generalizado por vista).
- Config inválido → validación contra schema en `cli bi` y `bootstrap`, error con ruta
  exacta antes de tocar la BD.

**Testing (TDD):**

- `tests/test_bi.py` — manifiesto con vista única y múltiple (columnas/tipos/claves);
  export CSV/Parquet con filas esperadas; vista faltante → warning, no aborta.
- `tests/test_dashboard.py` — `/api/derived/<name>/*` con 1 y 2+ vistas; alias
  `/api/inventory*` retrocompatible; `tab` derivado cuando falta.
- `tests/test_config_schema.py` — validación de `derived[]` múltiple y bloques por vista.
- `tests/test_cli.py` — `cli bi manifest|export|guide` con y sin `ETL_CONFIG`.
- Suite actual (207 passed, 19 skipped) debe seguir en verde.
- Lint: ruff E/F/W/I, line-length 120.

## Criterios de éxito

1. Un config nuevo de empresa (vistas y columnas distintas de `inv_bodega`) produce
   manifiesto BI, exports y pestañas de dashboard sin tocar código.
2. Cliente con Power BI (MSSQL): Novus conecta el DWH nativo, modela y publica.
3. Cliente sin Power BI: dashboard white-label con branding de su empresa.
4. Suite completa en verde + ruff limpio.
5. README/RUNBOOK documentan `cli bi` y el onboarding por empresa.
