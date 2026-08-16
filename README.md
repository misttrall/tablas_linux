# Motor ETL + DWH + Dashboard

Motor ETL multi-fuente escrito en Python que extrae datos desde **SAP** (vía `RFC_READ_TABLE`), **CSV** o **HTTP**, los transforma con pandas y los carga en **SQL Server**, **PostgreSQL**, **MySQL** o **SQLite** mediante staging + MERGE. Sobre los datos crudos materializa un modelo derivado (inventario de bodega con stock, valorización y alertas de stock mínimo) y lo exporta a Excel. Un dashboard web con autenticación (JWT + bcrypt) permite monitorear las corridas, consultar el inventario y disparar sincronizaciones bajo demanda.

Se instala como servicios systemd en Linux o como contenedor Docker.

## Contexto comercial

Producto de **Novus IT** ([novusit.cl](https://novusit.cl)) dentro del pilar **Datos/BI**. El alcance actual del producto en este repositorio son tres piezas: el motor ETL multi-fuente, el modelo derivado (DWH de inventario) y el dashboard web. Cada cliente se incorpora con un `config.json` propio; el código no cambia por cliente.

## Características

- **Fuentes**: SAP vía `RFC_READ_TABLE` (pyrfc), CSV y HTTP.
- **Destinos**: SQL Server (pyodbc), PostgreSQL (psycopg2), MySQL (pymysql) y SQLite.
- **Carga en dos etapas**: staging (`stg_*`) + MERGE dinámico por dialecto (upsert idempotente).
- **Extracción incremental opt-in** por tabla (`incremental.field`): agrega la condición `field >= <último valor>` a los filtros de SAP.
- **Full-load de tablas grandes por rangos de clave** (`load_mode: "range"`), acotado e idempotente.
- **Particionado automático de campos** cuando la fila supera 512 caracteres (límite de `RFC_READ_TABLE`).
- **Control de concurrencia doble**: lock file (`/tmp/etl_sap.lock`) + fila `running` en `etl_execution`.
- **Auto-recovery**: los runs huérfanos (lock vencido a los 60 minutos) se marcan como `failed`; el dashboard además limpia procesos colgados del botón Sincronizar.
- **Aislamiento de errores por tabla**: una tabla fallida no aborta el job; el job termina con exit != 0 para alertar al monitor.
- **Migraciones idempotentes por dialecto** (`migrations/`), registradas en `schema_migrations`.
- **Modelo derivado declarativo por cliente** (`config.derived`): sin vistas SQL por cliente.
- **Dashboard FastAPI** con auth (JWT + bcrypt), pestañas `#etl` e `#inventario`, y botón Sincronizar.
- **Observabilidad**: estado en vivo compartido runner/dashboard (`ETL_LIVE_FILE`), estado general (`/tmp/etl_state.json`) y logs persistentes (`logs/etl.log`).

## Arquitectura

| Componente | Piezas |
|---|---|
| Orquestación | `etl_runner.py` (pipeline), `cli.py` (interfaz), systemd (timer + service), `run_etl.sh` |
| Core ETL | `sources/` (conectores SAP/CSV/HTTP), `sources/partitioning.py` (rangos), pandas |
| Persistencia | `db/staging_loader.py` (staging), `db/merge_runner.py` (MERGE), `db/sinks/` (por dialecto), `db/control.py` (locks, progreso, telemetría) |
| Modelo derivado | `derived/materializer.py`, `derived/excel_export.py`, `derived/minimos_import.py` |
| Dashboard | `dashboard/app.py` (FastAPI), `dashboard/auth/` (JWT + bcrypt), `dashboard/static/` (HTML/JS) |
| Migraciones | `migrations/{mssql,mysql,postgresql,sqlite}/` |
| Observabilidad | `utils/live.py` (estado en vivo), `utils/etl_state.py`, `utils/logger.py` |

El flujo de una corrida: lock local → fila `running` en BD → conectar fuente → por tabla: extraer (plana o por rangos) → cargar staging → MERGE a destino → actualizar progreso/delta → materializar visiones derivadas y Excel → cerrar corrida y liberar locks.

## Requisitos

- **Python >= 3.10** (la CI y el Dockerfile usan 3.12).
- **Linux con systemd** para el despliegue nativo.
- **Extracción SAP**: SDK NW RFC (licenciado por SAP) montado en `SAPNWRFC_HOME` y el binding `pyrfc` (no está en PyPI; se instala desde el wheel de SAP). Sin SDK, el motor funciona igual con fuentes CSV/HTTP y el dashboard corre sin problema.
- **Drivers de BD**: pyodbc (SQL Server), psycopg2 (PostgreSQL), pymysql (MySQL). SQLite no requiere driver.

## Instalación

### Entorno virtual (desarrollo o servidor)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

Esto instala el paquete `tablas-etl` y el comando `etl` (equivalente a `python -m cli`). También se puede ejecutar sin instalar: `python -m cli ...`.

### Instalación por perfiles (requirements-*.txt)

No existe `requirements.txt`; las dependencias están separadas por perfil:

| Archivo | Contenido | Para qué |
|---|---|---|
| `requirements-base.txt` | pandas, openpyxl, SQLAlchemy >= 2.0, jsonschema, drivers de BD, python-dotenv, requests | Núcleo común |
| `requirements-etl.txt` | `-r requirements-base.txt` | Solo ETL (sin dashboard) |
| `requirements-sap.txt` | `-r requirements-etl.txt` + pyrfc | ETL con extracción SAP (requiere el wheel de SAP) |
| `requirements-web.txt` | `-r requirements-base.txt` + FastAPI, uvicorn, PyJWT, bcrypt | Dashboard |
| `requirements-ci.txt` | `-r requirements-web.txt` + pytest, httpx | CI (sin pyrfc) |

```bash
# ETL sin SAP
pip install -r requirements-etl.txt

# ETL con SAP (el wheel pyrfc debe estar disponible)
pip install -r requirements-sap.txt

# Dashboard
pip install -r requirements-web.txt
```

### Onboarding rápido

1. Copiar `config.example.json` a `config.json` y completar fuente, BD destino y tablas.
2. `python -m cli bootstrap` (valida config, conectividad, migraciones y un smoke extract de `T001L`).
3. `python -m cli run` (primera extracción).

## Configuración

`config.json` se valida al cargar contra `schemas/config.schema.json` (fail-fast con errores legibles). Claves top-level:

| Clave | Descripción |
|---|---|
| `environment` | `qa` \| `prd`. En `prd`, el guard exige `filters` o `load_mode: "range"` para las tablas grandes declaradas en `guard.large_tables` (prohibido el full-scan pelado). |
| `guard.large_tables` | Tablas que no admiten full-scan sin filtros en `prd` (default: `MARA`, `MARD`, `MBEW`, `MAKT`). |
| `source` | `{ "type": "sap" \| "csv" \| "http", "config": {...} }`. Formato legacy: `config["sap"]` directo. |
| `database` | `{ "dialect": "mssql" \| "sqlite" \| "postgresql" \| "mysql", server, database, user, password, port, driver }`. |
| `tables[]` | Por tabla: `{ source, target, keys[], load_mode?, range?, incremental?, filters? }`. |
| `fields` | `{ "<SOURCE>": ["CAMPO", ...] }` (campos a extraer por tabla). |
| `derived` | Objeto (una visión) o lista (varias visiones). Ver [Modelo derivado](#modelo-derivado-inventario-de-bodega). |

`config.example.json` contiene un ejemplo completo (SAP + SQL Server + visión derivada). Cada empresa/cliente es un `config.json` + sus datos; el código no cambia.

### Full-load por rangos

`RFC_READ_TABLE` paginado con `ROWSKIPS` no es determinista sin `ORDER BY` (SAP no lo soporta). Para cargar tablas grandes de forma completa y segura se particiona la clave (por defecto `MATNR`) en rangos disjuntos, uno por condición `OPTIONS`:

```json
"load_mode": "range",
"range": {
  "key": "MATNR",
  "sentinel": "~~~~~~~~~~~~~~~~~~"
}
```

- Cada rango es acotado e idempotente: re-correr produce el mismo resultado y el MERGE upsert absorbe cualquier duplicado.
- Restricción del parser: una línea `OPTIONS` admite a lo sumo dos predicados (un solo `AND`); no combina `OR` con `AND`. Por eso, cuando hay filtros base o incrementales la lectura ya queda acotada y no se particiona.
- El `sentinel` debe tener la longitud del campo clave (18 chars para `MATNR`, 4 para `WERKS`). Si no se indica, se usa uno de 18 chars válido para `MATNR`.
- `prefixes` (opcional) restringe los límites a los primeros caracteres indicados.

### Extracción incremental

Por tabla:

```json
"incremental": { "field": "LAEDA" }
```

El runner guarda el último valor en `etl_progress.last_delta_value` y en la corrida siguiente agrega la condición `field >= '<valor>'` a los filtros de SAP. El campo debe estar declarado en `fields` de esa tabla.

### Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `ETL_CONFIG` | `config.json` | Ruta del config del cliente (dashboard, scheduler y CLI) |
| `ETL_LIVE_FILE` | `/tmp/etl_live.json` | Estado en vivo compartido entre runner y dashboard (en Docker debe ser un volumen común) |
| `ETL_SECRET` | (obligatorio) | Clave HMAC de las sesiones JWT; la genera `deploy/install.sh` |
| `ETL_TOKEN_TTL_HOURS` | `12` | Vigencia de la sesión del dashboard |
| `ETL_COOKIE_SECURE` | ninguno | `1`/`true`/`yes` marca la cookie de sesión como Secure (para servir por HTTPS detrás de un proxy) |
| `SAPNWRFC_HOME` | `/opt/sap/nwrfcsdk` | SDK NW RFC para extracción SAP y para el botón Sincronizar |
| `LD_LIBRARY_PATH` | — | Normalmente `$SAPNWRFC_HOME/lib` |

## Uso de la CLI

Todas las operaciones están en `cli.py`. Se invocan con `python -m cli <comando>` o, tras `pip install -e .`, con `etl <comando>`.

| Comando | Flags | Descripción |
|---|---|---|
| `run` | `[--job etl] [--tables A,B] [--config ruta]` | Ejecuta el pipeline ETL completo (o solo las tablas indicadas, por source o target) |
| `migrate` | `[--config ruta]` | Aplica las migraciones de la BD destino (idempotente, registra en `schema_migrations`) |
| `status` | `[--last N] [--config ruta]` | Muestra las últimas corridas (`etl_execution`) y el progreso por tabla (`etl_progress`) |
| `reporte` | `[--tabla nombre] [--config ruta]` | Regenera los Excel del modelo derivado desde la BD destino, sin tocar SAP |
| `bootstrap` | `[--with-derived] [--skip-sap] [--config ruta]` | Onboarding: valida config, conectividad, aplica migraciones y hace un smoke extract de `T001L` |
| `importar-minimos` | `--archivo ruta.xlsx --hoja NOMBRE_HOJA [--tabla stock_minimo] [--col-material X] [--col-stock Y] [--col-area Z] [--config ruta]` | Importa la matriz de stock mínimo del cliente (Excel) a una tabla de referencia de la BD destino |
| `users add` | `--username U --password P [--role user\|admin] [--root] [--no-force-password-change] [--config ruta]` | Crea un usuario del dashboard |
| `users list` | `[--config ruta]` | Lista los usuarios del dashboard |
| `users set-password` | `--username U --password P [--config ruta]` | Cambia la password de un usuario |

Ejemplos:

```bash
# Primera vez
python -m cli migrate
python -m cli bootstrap --with-derived

# Corrida normal
python -m cli run

# Solo algunas tablas
python -m cli run --tables T001L,MARA

# Estado
python -m cli status --last 5

# Regenerar el Excel del inventario sin SAP
python -m cli reporte --tabla inv_bodega

# Importar la matriz de mínimos del cliente
python -m cli importar-minimos \
  --archivo "output/Stock Mínimos 2026.xlsx" \
  --hoja "PLANTA MINIMOS 2026" \
  --col-material CODIGO --col-stock "STOCK MÍNIMO" --col-area AREA
```

Notas de operación:

- Las tablas destino se crean automáticamente en la primera corrida (con `PRIMARY KEY` sobre las `keys` del config); la carga es idempotente (MERGE).
- El lock evita corridas concurrentes: la segunda corrida sale con código 1, sea por el lock local (`/tmp/etl_sap.lock`) o por la excepción `EtlAlreadyRunning` del lock en BD; los huérfanos de más de 60 minutos se reemplazan.
- Los errores por tabla quedan en `etl_progress`/`etl_execution` (status `failed`) y el job termina con exit != 0.

## Modelo derivado (inventario de bodega)

Además de la extracción cruda, el proyecto materializa una visión de negocio (stock por material/centro/almacén/área, con stock mínimo y valorización) en una tabla derivada y la exporta a Excel replicando la estructura del reporte del cliente. La lógica se declara en `config.derived`; no hay SQL por cliente.

Una visión se define así (bloque completo en `config.example.json`):

```json
"derived": {
  "name": "inv_bodega",
  "text_lang": "ES",
  "dominio": {
    "registry_table": "material_centro_almacen",
    "registry_columns": { "material": "material", "centro": "centro", "almacen": "almacen" },
    "filters": [
      { "field": "MTART", "in": ["ROH", "VERP"] },
      { "field": "WERKS", "op": "eq", "value": "P01" }
    ]
  },
  "precio": { "field": "VERPR" },
  "valor": { "field": "VERPR" },
  "area": {
    "reference_table": "stock_minimo",
    "columns": { "key": "material", "value": "area" }
  },
  "stock_minimo": {
    "reference_table": "stock_minimo",
    "key_columns": ["material"],
    "value_column": "stock_minimo"
  },
  "keys": ["MATNR", "WERKS", "LGORT"],
  "inventory": { "filters": { "centro": "Centro", "almacen": "Almacen", "area": "Area" } },
  "columns": [
    { "as": "MATNR", "source": "MATNR" },
    { "as": "Descripcion", "source": "MAKTX" },
    { "as": "Centro", "source": "WERKS" },
    { "as": "Almacen", "source": "LGORT" },
    { "as": "AlmacenDesc", "source": "LGOBE" },
    { "as": "StockLibre", "source": "LABST" },
    { "as": "UMB", "source": "MEINS" },
    { "as": "Precio", "source": "VERPR" },
    { "as": "ValorTotal", "compute": "LABST * VERPR" },
    { "as": "Area", "source": "AREA" },
    { "as": "stock_minimo", "source": "STOCK_MINIMO" }
  ],
  "excel": {
    "path": "output/inventario.xlsx",
    "sheet": "Stock",
    "alerts_sheet": "StockBajo"
  }
}
```

Cómo funciona:

- **Dominio** (qué material × centro × almacén entra al inventario): se toma de una tabla de registro en la BD destino (`dominio.registry_table`, la que mantiene la aplicación cliente) si existe; si no, de los filtros declarados (`dominio.filters`, operadores `in`/`not_in`/`eq`/`neq`).
- **Base**: `MARD` (StockLibre `LABST`). Se enriquecen con `MARA` (UMB `MEINS`), `MAKT` (descripción en `text_lang`), `MBEW` (precio/valor, cruzado por `BWKEY = WERKS` o agregado por material con `"by": "aggregate"`) y `T001L` (descripción de almacén `LGOBE`).
- **Precio/valor**: `precio.field` y `valor.field` (`VERPR` precio móvil, `STPRS`, `SALK3`). Cualquier columna de salida puede calcularse con `"compute"` (ej. `ValorTotal = LABST * VERPR`, igual que el reporte del cliente).
- **Área y stock mínimo**: se leen de tablas de referencia en la BD destino si existen (`area.reference_table` con `join`/`columns` opcionales; `stock_minimo.reference_table` con `key_columns`/`value_column`); si no, de `mapping` en config o, para el mínimo, del campo `MARD.LMINB` (`source_field`). Stock sin dato se muestra como vacío.
- **Alertas**: `alerts` (opcional) define `min_field` (default `stock_minimo`), `qty_field` (default `StockLibre`) y `total_field` (default `ValorTotal`). Habilitadas por defecto.
- **Columnas del dashboard**: cada entrada de `derived.columns` admite `label` (etiqueta amigable de la columna), `hide` (true oculta la columna del listado web, útil para campos internos) y `fallback` (columna alternativa si la principal viene vacía, p. ej. mostrar `AlmacenDesc` con respaldo `Almacen`). Sin estos campos se muestran todas las columnas con su nombre `as`.
- **Excel**: `excel.path`, hoja principal `excel.sheet` (default `Stock`) y hoja de alertas `excel.alerts_sheet` (default `StockBajo`). `excel.columns` proyecta/renombra las columnas de la tabla derivada para replicar la estructura del reporte del cliente. La hoja `StockBajo` lista los materiales con stock bajo el mínimo y agrega el conteo y el valor total en riesgo.
- **Varias visiones**: `config.derived` acepta un objeto o una lista; cada visión materializa su propia tabla (`name`, único) y su Excel. La telemetría se registra por visión en `etl_execution_tables`.
- La tabla derivada se recrea automáticamente si cambia su estructura de columnas. Al final de cada corrida el ETL la materializa (con `PRIMARY KEY` sobre `keys`) y escribe el Excel.

Importar la matriz de mínimos del cliente:

```bash
python -m cli importar-minimos --archivo "output/Stock Mínimos 2026.xlsx" \
  --hoja "PLANTA MINIMOS 2026" \
  --col-material CODIGO --col-stock "STOCK MÍNIMO" --col-area AREA
```

`--hoja` es obligatorio; las columnas se mapean con `--col-*`. El import reemplaza el contenido de la tabla de referencia (default `stock_minimo`) en cada ejecución.

Regenerar el Excel sin tocar SAP (desde la BD destino):

```bash
python -m cli reporte              # todas las visiones
python -m cli reporte --tabla inv_bodega   # solo una visión
```

## Entregable BI

El servicio "Datos/BI" de Novus cierra con un entregable de Power BI por empresa, modelado por Novus sobre el DWH y parametrizado por `config.derived` (sin nada hardcodeado a `inv_bodega` ni a columnas SAP). El módulo `bi/` genera el material, invocable con `etl bi`:

| Comando | Qué produce |
|---|---|
| `etl bi manifest [--config ruta]` | Manifiesto del dataset (JSON): vistas, columnas, tipos, claves y medidas sugeridas, para modelar en Power BI Desktop |
| `etl bi export [--config ruta]` | Exporta cada vista derivada a CSV y Parquet en `output/bi/` (útil para clientes sin conectividad directa a la BD) |
| `etl bi guide [--config ruta]` | Guía de conectividad de Power BI por dialecto |

La guía de conectividad (`etl bi guide`) parametriza las instrucciones por la BD destino de la empresa: MSSQL con el conector nativo (modo Importación, DirectQuery si el volumen lo exige, gateway para on-premise), PostgreSQL/MySQL vía driver ODBC, y SQLite como no soportado por Power BI (recomienda migrar el DWH a MSSQL para clientes BI).

El dashboard web es la alternativa white-label para clientes sin Power BI. Su branding vive en `config.dashboard` (bloque opcional: `title`, `logo`, `color`, `footer`), y cada vista derivada declara su pestaña en `tab` y su columna rótulo en `row_label` (opcionales; sin `tab` se deriva un nombre legible de `name`).

Onboarding de un cliente BI: config `config.json` por empresa → `python -m cli migrate` → `python -m cli bootstrap` → materializar y entregar (`python -m cli reporte` + `etl bi manifest|export|guide`, o el dashboard white-label).

Spec del entregable: `docs/superpowers/specs/2026-08-15-entregable-bi-white-label-design.md`.

## Dashboard web

Dashboard FastAPI (`dashboard/app.py`) que lee `etl_execution`, `etl_progress` y `etl_execution_tables` de la BD destino. No requiere el SDK de SAP; solo acceso a la BD.

Levantarlo:

```bash
./run_dashboard.sh                 # escucha en 0.0.0.0:8000
# o en desarrollo:
python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
```

La BD destino se toma de `ETL_CONFIG` (o `config.json` por defecto).

### Autenticación y usuarios

- Login con **JWT (HS256)** + **bcrypt** (costo 12); la sesión viaja en la cookie `etl_session` (HttpOnly, SameSite=Lax, Secure opcional vía `ETL_COOKIE_SECURE`).
- Los usuarios viven en la tabla `app_users` de la BD destino (migración `004_app_users.sql`).
- Roles: `user` (Vistas) y `admin` (además: ETL, panel de ejecuciones, progreso, agregados y gestión de usuarios). El usuario raíz (`is_root`) no se puede borrar ni degradar, y solo él cambia su propia password.
- En el primer login, un usuario con `must_change_password` debe cambiar su password (mínimo 8 caracteres).
- El instalador crea el admin raíz `admin` (password inicial `extractor`) si no existen usuarios.
- Gestión de usuarios: `python -m cli users add|list|set-password` o desde `/panel` (admin).

### Páginas

| Ruta | Acceso | Contenido |
|---|---|---|
| `/` | redirige | A `/login`, `/panel` (admin) o `/derivadas` (user) |
| `/login` | público | Login |
| `/derivadas` | user y admin | Vistas: listado curado de la vista derivada con filtros |
| `/etl` | admin | Monitoreo de corridas y botón **Sincronizar** (dispara el ETL) |
| `/panel` | admin | Panel de administración y gestión de usuarios |
| `/inventario` | — | Retrocompat: redirige a `/derivadas` |

Navegación por rol: **admin** = `ETL / Panel / Vistas`; **user** = `Vistas`.

- **Vistas** (`/derivadas`): cards de resumen (filas, total, alertas), filtros por **centro, almacén y área** (valores reales desde la tabla derivada), búsqueda de texto, checkbox **"Solo bajo stock"** y tabla paginada con las filas bajo mínimo resaltadas. Las columnas mostradas, sus etiquetas y las columnas ocultas se declaran por vista en `derived.columns` (`label`, `hide`, `fallback`).
- **ETL** (`/etl`, admin): últimas corridas, progreso por tabla, extracción en vivo (fase, tabla, filas, chunk x/N) y botón **Sincronizar** que dispara el pipeline.
- **Panel** (`/panel`, admin): ejecuciones y gestión de usuarios.

### Demo y verificación E2E

Levantar el demo en el puerto 8001 (no toca instancias ajenas; puerto 8000 queda intacto):

```bash
scripts/run_demo.sh start     # start | stop | status | log
ETL_SECRET=... scripts/run_demo.sh start   # secret sobreescribible
```

Verificar el dashboard con Playwright (login, branding, navegación por rol, redirecciones, columnas de Vistas, filtros, botón Sincronizar y ausencia de errores JS):

```bash
.venv/bin/python scripts/verify_dashboard.py            # contra http://127.0.0.1:8001
.venv/bin/python scripts/verify_dashboard.py --base http://127.0.0.1:9000 --username demo --password demo1234
```


### Endpoints de la API

Públicos:

| Endpoint | Descripción |
|---|---|
| `GET /api/health` | Healthcheck (verifica la conexión a la BD destino) |
| `POST /api/auth/login` | Login; fija la cookie `etl_session` |
| `GET /static/*` | Assets estáticos |

Requieren sesión (`user`):

| Endpoint | Descripción |
|---|---|
| `POST /api/auth/logout` | Cierra la sesión |
| `GET /api/auth/me` | Usuario actual |
| `POST /api/auth/password` | Cambia la password propia (`current_password` + `new_password`) |
| `GET /api/last-sync` | Última corrida registrada |
| `GET /api/live` | Estado en vivo de la extracción (dispara la auto-recuperación) |
| `POST /api/etl/trigger` | Dispara el ETL bajo demanda; `409` con `already_running` si hay una corrida activa |
| `GET /api/inventory` | Resumen de la primera visión derivada (materiales, valor, alertas, riesgo) |
| `GET /api/inventory/filters` | Valores distintos de centro/almacén/área para los filtros |
| `GET /api/inventory/items` | Inventario paginado (`?centro=&almacen=&area=&low_only=&q=&limit=&offset=`) |
| `GET /api/inventory/alerts` | Filas bajo mínimo (`?limit=N`, `?q=texto`) |

Requieren `admin`:

| Endpoint | Descripción |
|---|---|
| `GET /api/executions` | Últimas corridas (`?last=N`, default 10) |
| `GET /api/progress` | Progreso por tabla |
| `GET /api/dashboard` | Agregado para el panel web |
| `GET /api/tables` | Stats por tabla de una corrida (`?run_id=N`) |
| `GET /api/admin/users` | Lista usuarios |
| `POST /api/admin/users` | Crea usuario |
| `PATCH /api/admin/users/{user_id}` | Cambia rol / activa o desactiva |
| `DELETE /api/admin/users/{user_id}` | Elimina usuario (root protegido) |
| `POST /api/admin/users/{user_id}/password` | Resetea password |

### Botón Sincronizar y auto-recuperación

El botón **Sincronizar** (pestañas `#etl` y `#inventario`) dispara `POST /api/etl/trigger`, que lanza `cli run` como subproceso desprendido con el mismo `ETL_CONFIG` y `ETL_LIVE_FILE`. Mientras corre, el botón queda deshabilitado y se muestra el progreso en vivo; al terminar se refrescan inventario y corridas. Si ya hay una ejecución activa, responde `409` y la UI lo indica (el lock en BD es la protección real). Los logs del subproceso van a `logs/etl_sync.log`.

> El botón requiere que el host del dashboard tenga el SDK SAP + pyrfc para poder ejecutar `cli run` (entorno on-premise o contenedor con el SDK montado). En la imagen Docker ligera (sin pyrfc) devolvería un error visible y no lanzaría nada.

**Auto-recuperación**: si el subproceso muere o se cuelga (crash, señal, corte de red), `/api/live` y `/api/etl/trigger` lo detectan (el hijo desaparece, o el estado no avanza en más de 120 segundos) y limpian solos: marcan la corrida como `failed`, eliminan el lock local `/tmp/etl_sap.lock` si su dueño ya no existe, y dejan el estado `idle` para poder reintentar. La UI se desatasca sola en pocos segundos.

## Migraciones

DDL por dialecto en `migrations/{mssql,mysql,postgresql,sqlite}/`, aplicadas con `python -m cli migrate` (idempotente: registra cada archivo en `schema_migrations`; si el schema ya existe en la base, lo marca como `[ok-baseline]`).

| Archivo | Crea |
|---|---|
| `001_control_tables.sql` | `etl_execution` y `etl_progress` |
| `002_etl_progress_delta.sql` | `etl_progress.last_delta_value` (extracción incremental) |
| `003_etl_execution_tables.sql` | `etl_execution_tables` (stats por tabla por corrida; disponible en mssql y sqlite) |
| `004_app_users.sql` | `app_users` (usuarios del dashboard) |

`migrations/README.md` documenta las limitaciones conocidas por dialecto (deprecación de `VALUES()` en MySQL, carga no atómica del staging en MySQL).

## Despliegue nativo (systemd)

```bash
sudo apt install -y python3 python3-venv openssl rsync
sudo ./deploy/install.sh
```

Opciones del instalador:

```bash
sudo ./deploy/install.sh \
  --etl-dir=/opt/etl/tablas_linux \   # directorio de instalación
  --user=etl \                        # usuario de servicio
  --python=python3.12 \               # intérprete para el venv
  --with-sap                          # instala pyrfc (wheel de SAP)
  --no-start                          # instala pero no arranca servicios
```

Qué hace: copia el código a `--etl-dir` (preservando `.env` y `config.json`), crea el usuario de servicio, crea el venv e instala `requirements-{base,etl,web}.txt` (+ `requirements-sap.txt` con `--with-sap`), genera `ETL_SECRET` en `<etl-dir>/.env` (modo 600), copia `config.example.json` si falta, aplica las migraciones, crea el admin raíz `admin`/`extractor` si no hay usuarios, e instala y arranca las unidades systemd.

Servicios instalados:

| Unidad | Rol |
|---|---|
| `etl-dashboard.service` | Dashboard uvicorn en `0.0.0.0:8000` (heredando `SAPNWRFC_HOME`/`LD_LIBRARY_PATH` del `.env` para el botón Sincronizar) |
| `etl-sync.timer` | Scheduler horario: `OnCalendar=*-*-* *:45:00` (cada hora en el minuto 45, `Persistent=true`) |
| `etl-sync.service` | Oneshot que ejecuta `deploy/etl_sync_run.sh`; `SuccessExitStatus=42` |

El script `deploy/etl_sync_run.sh` chequea primero el lock local (< 60 min) y luego la fila `running` no vencida en `etl_execution`; si hay una corrida activa sale con **exit 42 (pospuesta)** sin reintentar, y espera el siguiente slot de las :45.

| Código de salida | Significado |
|---|---|
| `0` | Corrida OK |
| `42` | Pospuesta (ya había una corrida activa); no es un fallo |
| `1` | La corrida falló; revisar `journalctl -u etl-sync` |

Operación:

```bash
sudo systemctl status etl-dashboard.service
sudo systemctl status etl-sync.timer
sudo systemctl list-timers etl-sync.timer
journalctl -u etl-dashboard -f
journalctl -u etl-sync -f
```

El runbook completo de operación (instalación, primer arranque, usuarios y roles, upgrade, backup, solución de problemas, rutas y seguridad) está en **`RUNBOOK.md`**.

## Docker

**Imagen ligera** (`Dockerfile`): `python:3.12-slim`, solo dashboard + CLI, sin pyrfc; el SDK NW RFC (licenciado) se monta en runtime en `/opt/sap/nwrfcsdk`. `HEALTHCHECK` contra `/api/health`; comando por defecto `uvicorn dashboard.app:app`.

```bash
docker build -t etl-dashboard .
docker run -p 8000:8000 \
  -v /opt/etl/config.json:/opt/etl/config.json:ro \
  -v /opt/sap/nwrfcsdk:/opt/sap/nwrfcsdk:ro \
  etl-dashboard
```

**docker-compose.yml** (dashboard + ejecución de jobs y reportes):

```bash
docker compose up -d                        # dashboard en :8000
docker compose run --rm etl python -m cli bootstrap
docker compose run --rm etl python -m cli migrate
docker compose run --rm etl python -m cli run
docker compose run --rm etl python -m cli reporte
```

Variables esperadas en `.env`: `ETL_CONFIG`, `ETL_LIVE_FILE` y las del SDK (`SAPNWRFC_HOME`, `LD_LIBRARY_PATH`). El volumen `./output` guarda los Excel generados; en config la ruta del reporte debe apuntar allí (ej. `/opt/etl/output/inventario.xlsx`). La imagen NO incluye el SDK NW RFC; para ejecutar `etl run` contra SAP hay que montarlo.

**Variante con systemd dentro del contenedor** (pruebas locales): `deploy/Dockerfile` + `deploy/docker-entrypoint.sh` + `deploy/etl-docker.sh` (comandos `build|up|down|logs|status|shell`). El entrypoint reconstruye `config.json` apuntando a un SQLite persistente en `/var/lib/etl/db.sqlite`, genera `ETL_SECRET`, aplica migraciones y crea los usuarios `admin`/`extractor`. Requiere `--privileged --cgroupns=host` (systemd en cgroup v2), por eso no va por docker-compose.

## Testing y CI

- **Tests**: `tests/` (pytest; 20 archivos: runners, sinks por dialecto, fuentes, particionado, config, derived, dashboard, auth, live).
- **CI**: `.github/workflows/ci.yml` ejecuta sobre Python 3.12:
  1. `pip install -r requirements-ci.txt` (sin pyrfc).
  2. `python -m pytest -q`.
  3. `ruff check .` (reglas E, F, W, I; line-length 120).

## Onboarding de un cliente

1. Copiar `config.example.json` a `config.json` y completar: fuente (SAP/CSV/HTTP), BD destino y tablas (`source`/`target`/`keys`/`load_mode`).
2. `python -m cli bootstrap` (valida config, conectividad, migraciones y smoke extract `T001L`).
3. Primera extracción: `python -m cli run`.
4. Definir el inventario en `config.derived` (dominio, área, mínimos, columnas) e importar la matriz de mínimos si existe. Regenerar los Excel: `python -m cli reporte`.
5. Programar con systemd (`deploy/install.sh` + timer `etl-sync.timer`) o Docker, y levantar el dashboard.

No hay SQL por cliente: solo datos en config (qué `MTART`/`MATKL` son insumos, qué plantas/almacenes, tablas de área y mínimos).

## Estructura del proyecto

```
tablas_linux/
├── cli.py                     # interfaz de línea de comandos
├── etl_runner.py              # orquestación de una corrida ETL
├── pyproject.toml             # paquete tablas-etl (comando `etl`)
├── config.json                # config del cliente (no versionado)
├── config.example.json        # plantilla documentada
├── run_etl.sh                 # helper: cli run con SDK SAP
├── run_dashboard.sh           # helper: uvicorn con ETL_CONFIG/ETL_LIVE_FILE
├── docker-compose.yml         # dashboard + CLI en un servicio
├── Dockerfile                 # imagen ligera (dashboard + CLI, sin pyrfc)
├── RUNBOOK.md                 # runbook de operación del despliegue nativo
├── LICENSE
├── sources/                   # conectores de origen
│   ├── base.py                # contrato SourceConnector
│   ├── config_resolver.py     # resolución de source + validación de entorno prd
│   ├── partitioning.py        # full-load por rangos (load_mode: "range")
│   ├── sap/                   # conector SAP (RFC_READ_TABLE, pyrfc)
│   │   ├── connector.py
│   │   └── rfc.py
│   └── generic/
│       ├── csv.py
│       └── http.py
├── db/                        # persistencia
│   ├── db_connection.py       # connection strings por dialecto
│   ├── control.py             # locks en BD, progreso, deltas, telemetría
│   ├── staging_loader.py      # carga a stg_*
│   ├── merge_runner.py        # MERGE staging → destino
│   └── sinks/                 # estrategias por dialecto
│       ├── base.py
│       ├── sqlserver.py
│       ├── postgres.py
│       ├── mysql.py
│       └── sqlite.py
├── derived/                   # modelo derivado (inventario de bodega)
│   ├── materializer.py        # construye y materializa las visiones
│   ├── excel_export.py        # Excel (hoja Stock + hoja StockBajo)
│   ├── minimos_import.py      # importa la matriz de mínimos del cliente
│   ├── views.py               # normaliza config.derived
│   └── db.py                  # lectura de tablas de la BD destino
├── dashboard/                 # dashboard FastAPI
│   ├── app.py                 # rutas y endpoints de la API
│   ├── auth/                  # JWT + bcrypt; usuarios en app_users
│   │   ├── router.py
│   │   ├── dependencies.py
│   │   ├── engine.py
│   │   ├── security.py
│   │   └── users.py
│   └── static/                # login.html, etl.html, inventario.html, panel.html, common.css, common.js
├── migrations/                # DDL por dialecto (idempotentes)
│   ├── mssql/
│   ├── postgresql/
│   ├── mysql/
│   ├── sqlite/
│   └── README.md
├── schemas/
│   └── config.schema.json     # contrato de config.json
├── utils/
│   ├── config_loader.py       # carga y validación de config
│   ├── config_validation.py
│   ├── logger.py              # logs/etl.log
│   ├── etl_state.py           # /tmp/etl_state.json
│   └── live.py                # /tmp/etl_live.json (ETL_LIVE_FILE)
├── deploy/                    # despliegue nativo y Docker
│   ├── install.sh             # instalador systemd
│   ├── etl-dashboard.service
│   ├── etl-sync.service
│   ├── etl-sync.timer         # scheduler horario (:45)
│   ├── etl_sync_run.sh        # corrida programada (exit 42 = pospuesta)
│   ├── Dockerfile             # contenedor con systemd (pruebas locales)
│   ├── docker-entrypoint.sh
│   ├── etl-docker.sh
│   └── wheels/
├── requirements-{base,etl,sap,web,ci}.txt
├── tests/                     # pytest (20 archivos)
└── .github/workflows/ci.yml   # pytest + ruff
```

## Licencia

MIT (ver `LICENSE`).
