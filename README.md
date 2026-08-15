📊 ETL SAP → SQL Server (Linux + systemd + Flask)

Sistema ETL desarrollado en Python para la extracción de datos desde SAP mediante RFC, transformación con pandas y carga en SQL Server, con ejecución automatizada en Linux mediante systemd y control manual vía interfaz web en Flask.


---

🚀 Características principales

Extracción de datos desde SAP usando RFC_READ_TABLE

Transformación de datos mediante pandas

Carga eficiente a SQL Server usando SQLAlchemy

Uso de tablas staging para integridad de datos

Aplicación de MERGE dinámico para sincronización incremental

Ejecución automática cada 45 minutos con systemd timer

Ejecución manual mediante interfaz web en Flask

Control de concurrencia doble:

Lock file (/tmp/etl_sap.lock)

Control en base de datos (etl_execution)


Monitoreo de estado en tiempo real (etl_state.json)

Sistema de logs persistente (etl.log)

Estado y lock en base de datos (etl_execution / etl_progress), con recuperación de runs huérfanos

Aislamiento de errores por tabla (una tabla fallida no aborta el job)

Extracción incremental opt-in por tabla (config `incremental.field`, filtro OPTIONS en SAP)

Full-load de tablas grandes por rangos de clave (config `load_mode: "range"`, idempotente y acotado)

Particionado automático de campos si la fila supera 512 chars (límite de RFC_READ_TABLE)



---

🧱 Arquitectura

El sistema está compuesto por los siguientes componentes:

Orquestación

systemd service

systemd timer

Script bash (run_etl.sh)


Core ETL (Python)

Extracción de datos desde SAP usando RFC_READ_TABLE (conector sources/sap)

Transformación (pandas)

Carga staging (staging_loader.py)

Merge final (merge_runner.py)


Persistencia

SQL Server:

Tablas staging

Tablas finales

etl_execution

etl_progress



Interfaz

Aplicación web en Flask


Observabilidad

Logs (logs/etl.log)

Estado (/tmp/etl_state.json)




---

⚙️ Instalación

1. Clonar repositorio

git clone https://github.com/misttrall/tablas_linux.git

---

2. Crear entorno virtual

python3 -m venv venv

source venv/bin/activate

pip install -r requirements.txt


---

3. Configurar variables SAP

Asegúrate de tener instalado el SDK de SAP RFC:

export SAPNWRFC_HOME=/opt/sap/nwrfcsdk

export LD_LIBRARY_PATH=/opt/sap/nwrfcsdk/lib:$LD_LIBRARY_PATH


---

4. Configuración del sistema

Editar config.json con:

Credenciales SAP

Conexión a SQL Server

Tablas a procesar

Campos por tabla


🔬 Full-load por rangos (`load_mode: "range"`)

RFC_READ_TABLE paginado con ROWSKIPS no es determinista sin ORDER BY (SAP no lo
soporta). Para cargar tablas grandes de forma completa y segura se particiona la
clave (por defecto `MATNR`) en rangos disjuntos, uno por condición OPTIONS:

    "load_mode": "range",
    "range": {
      "key": "MATNR",
      "sentinel": "~~~~~~~~~~~~~~~~~~"
    }

Cada rango es acotado e idempotente (re-correr = mismo resultado, el merge
upsert absorbe cualquier duplicado). En PRD el guard exige `filters` o
`load_mode: "range"` para tablas grandes.

Límites de RFC_READ_TABLE en este sistema:

Una línea OPTIONS admite a lo sumo dos predicados (un solo `AND`); OR mezclado
con AND no es parseable. Por eso el modo range no se combina con `incremental`
(que agrega su propio filtro): el full-load inicial usa `load_mode: "range"` y
la operación continua usa `incremental` (o repite el modo range).

El literal `sentinel` debe tener la longitud del campo clave (18 chars para
MATNR, 4 para WERKS). Si no se indica, se usa uno de 18 chars válido para MATNR.



---

📦 Modelo derivado (inventario de bodega)

Además de la extracción cruda, el proyecto puede materializar una visión de
negocio (ej.: stock de insumos por material/planta/almacén) en una tabla
derivada y exportarla a Excel replicando la estructura del reporte del cliente,
sin depender de vistas SQL hechas a mano. La lógica se declara en
`config.derived`:

    "derived": {
      "name": "inv_bodega",
      "text_lang": "ES",
      "dominio": {
        "registry_table": "material_centro_almacen",
        "registry_columns": { "material": "material", "centro": "centro", "almacen": "almacen" },
        "filters": [ { "field": "MTART", "in": ["ROH", "VERP"] } ]
      },
      "precio": { "field": "VERPR" },
      "valor": { "field": "VERPR" },
      "area": {
        "reference_table": "material_area",
        "join": { "table": "area", "on_local": "area_id", "on_foreign": "id" },
        "columns": { "key": "material", "value": "nombre" }
      },
      "stock_minimo": {
        "reference_table": "stock_minimo",
        "key_columns": ["material", "centro", "almacen"],
        "value_column": "stock_minimo"
      },
      "keys": ["MATNR", "WERKS", "LGORT"],
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
        "path": "output/inventario_bodega.xlsx",
        "sheet": "Reporte",
        "alerts_sheet": "StockBajo",
        "columns": [
          { "as": "Columna1", "source": "MATNR" },
          { "as": "DescripcionMaterial", "source": "Descripcion" },
          { "as": "Centro", "source": "Centro" },
          { "as": "NumeroAlmacen", "source": "Almacen" },
          { "as": "DescripcionAlmacen", "source": "AlmacenDesc" },
          { "as": "Stock", "source": "StockLibre" },
          { "as": "UMB", "source": "UMB" },
          { "as": "ValorUnitario", "source": "Precio" },
          { "as": "ValorizacionTotal", "source": "ValorTotal" }
        ]
      }
    }

Cómo funciona:

El dominio (qué material × centro × almacén entran al inventario) se toma de
una tabla de registro en la BD destino (ej.: `material_centro_almacen`, la que
mantiene la aplicación cliente) si existe; si no, de los filtros declarados
(ej.: `MTART` en los tipos de insumo del cliente, `WERKS`/`LGORT` para acotar
la bodega). Cada empresa = cambiar config, nunca SQL.

Stock: `MARD.LABST` (StockLibre), `MBEW` (Precio/ValorUnitario = `VERPR`
—precio móvil— o `STPRS`). El valor se cruza por `BWKEY = WERKS` (planta) o se
agrega por material (`"by": "aggregate"`). Cualquier columna de salida puede
calcularse con `"compute"` (p. ej. `ValorTotal = LABST * VERPR`, igual que el
reporte del cliente). Descripción desde `MAKT` en el idioma de `text_lang`;
`AlmacenDesc` desde `T001L.LGOBE`; `UMB` desde `MARA.MEINS`.

Area y stock_minimo se leen de tablas de referencia en la BD destino si existen
(soporta join simple, ej. material_area → area); si no, de `mapping` en config o
del campo `MARD.LMINB` (`source_field`). Stock sin dato se muestra como vacío.

La matriz de planificación del cliente (ej. `Stock Mínimos 2026.xlsx`, hoja
`PLANTA MINIMOS 2026`) trae el stock mínimo y el área por material; se importa a
la BD destino como tabla `stock_minimo` (material → stock_minimo/area):

    python -m cli importar-minimos --archivo "output/Stock Mínimos 2026.xlsx" \
        --hoja "PLANTA MINIMOS 2026" \
        --col-material CODIGO --col-stock "STOCK MÍNIMO" --col-area AREA

`--hoja` es obligatorio y las columnas se mapean con `--col-*` (datos del
cliente). Y en config basta apuntar el modelo derivado a esa tabla (ver bloque
de arriba): `stock_minimo.reference_table` + `area.reference_table` =
`stock_minimo`. El import es idempotente (reemplaza el contenido de la tabla
cada vez).

`config.derived` acepta un objeto (una visión) o una lista (varias visiones,
ej. inventario por bodega + resumen por centro); cada visión materializa su
propia tabla (nombre en `name`) y su Excel (`excel.path`). La telemetría se
registra por visión en `etl_execution_tables`.

Al final de cada corrida el ETL materializa la tabla derivada (con PRIMARY KEY
sobre `keys`) y escribe el Excel. La hoja principal (por defecto `Reporte`)
replica la estructura del reporte del cliente —`excel.columns` proyecta/renombra
las columnas de la tabla derivada, p. ej. `Columna1, DescripcionMaterial,
Centro, NumeroAlmacen, DescripcionAlmacen, Stock, UMB, ValorUnitario,
ValorizacionTotal`— con autofiltro. La hoja `StockBajo` lista los materiales
cuyo stock es menor al mínimo, más el conteo y el valor total en riesgo. Si la
estructura de columnas cambia, la tabla derivada se recrea automáticamente.

El Excel se puede regenerar sin tocar SAP:

    python -m cli reporte            # todas las visiones
    python -m cli reporte --tabla inv_bodega   # solo una visión

Replicas el comportamiento de una vista de inventario pero sin escribir vistas
por cliente: el mecanismo es estándar y los datos del cliente van en config.


---

📄 Contrato de config.json

El config se valida al cargar contra `schemas/config.schema.json` (fail-fast con
errores legibles). Claves top-level:

- `environment`: `qa` | `prd` (en `prd` el guard exige `filters` o
  `load_mode: "range"` para tablas grandes).
- `guard.large_tables`: tablas que no admiten full-scan pelado en `prd`.
- `source`: `{ "type": "sap"|"csv"|"http", "config": {...} }`.
- `database`: `{ "dialect": "mssql"|"sqlite"|"postgresql"|"mysql", ... }`.
- `tables[]`: por tabla `{ source, target, keys[], load_mode?, range?, incremental?, filters? }`.
- `fields`: `{ "<SOURCE>": ["CAMPO", ...] }`.
- `derived`: objeto (una visión) o lista (varias visiones). Cada visión:
  - `name` (tabla derivada, único), `text_lang`, `keys` (PK de la tabla).
  - `dominio`: `registry_table` + `registry_columns`, o `filters[]`
    (`field` + `op`: `in`/`not_in`/`eq`/`neq`).
  - `precio`/`valor`: `{ "field": "VERPR" | "STPRS" | "SALK3", "by": "aggregate"? }`.
  - `area` y `stock_minimo`: `reference_table` (+ `columns`/`key_columns`/
    `value_column`), `mapping`, o `source_field` (ej. `LMINB`).
  - `columns[]`: `{ "as": ..., "source": ... }` o `{ "as": ..., "compute": "LABST * VERPR" }`.
  - `alerts`: `{ "enabled": true, "min_field": "stock_minimo", "qty_field": "StockLibre", "total_field": "ValorTotal" }`.
  - `inventory`: `{ "filters": { "centro": "Centro", "almacen": "Almacen", "area": "Area" } }`
    (columnas del dashboard de inventario; opcional, usa estos defaults).
  - `excel`: `{ "path", "sheet", "alerts_sheet", "columns[]" }` (proyección del reporte).

Cada empresa/cliente = un `config.json` + sus datos; el código no cambia.


---

▶️ Ejecución manual

CLI (recomendado):

python -m cli run [--tables T001L,MARA] [--config ruta]

O mediante script:

./run_etl.sh [--tables T001L,MARA]


⚙️ CLI

Operaciones disponibles:

python -m cli run [--job etl] [--tables A,B] [--config ruta]   Ejecuta el pipeline
python -m cli migrate [--config ruta]   Aplica las migraciones de la BD destino (idempotente)
python -m cli status [--last N] [--config ruta]   Muestra últimas corridas y progreso por tabla
python -m cli bootstrap [--with-derived] [--skip-sap] [--config ruta]   Onboarding: valida config, conectividad y deja la BD lista
python -m cli reporte [--tabla nombre] [--config ruta]   Regenera los Excel del modelo derivado desde la BD destino (sin SAP)
python -m cli importar-minimos --archivo ruta.xlsx --hoja NOMBRE_HOJA [--tabla stock_minimo] [--col-material X] [--col-stock Y] [--col-area Z] [--config ruta]   Importa la matriz de stock mínimo del cliente a la BD destino


🕐 Programación (cron)

Agregar al crontab (la extracción SAP requiere el SDK NW RFC y la red corporativa):

0 2 * * * /opt/etl/tablas_linux/run_etl.sh >> /opt/etl/tablas_linux/logs/etl_cron.log 2>&1

Notas de operación:

Antes del primer run aplicar las migraciones: python -m cli migrate

Las tablas destino se crean automáticamente (con PRIMARY KEY sobre las
claves del config) en la primera corrida; la carga es idempotente (MERGE).

El lock evita corridas concurrentes: la segunda corrida sale con código 1
y mensaje EtlAlreadyRunning; huérfanos de más de 60 min se reemplazan.

Los errores por tabla quedan en etl_progress/etl_execution (status failed) y
el job termina con exit != 0 para alertar al monitor.


📦 Dashboard web (FastAPI)

Panel de monitoreo que lee etl_execution/etl_progress de la base de datos destino.
No requiere el SDK de SAP; solo acceso de lectura a la BD.

Levantarlo:

./run_dashboard.sh            # escucha en 0.0.0.0:8000

O en desarrollo:

python -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000

Endpoints:

/api/health         Estado del servicio
/api/executions     Últimas corridas (default 10, ?last=N)
/api/progress       Progreso por tabla
/api/live           Estado en vivo de la extracción (tabla, chunk x/N, filas)
/api/tables         Stats por tabla de una corrida (?run_id=N)
/api/inventory      Resumen de la primera visión derivada (materiales, valor, alertas, riesgo)
/api/inventory/filters   Valores distintos de centro/almacén/área para los filtros del dashboard
/api/inventory/items   Inventario completo paginado (?centro=&almacen=&area=&low_only=&q=&limit=&offset=)
/api/inventory/alerts   Filas bajo mínimo de la visión derivada (?limit=N, ?q=texto)
/api/etl/trigger    POST: dispara el ETL bajo demanda (409 si ya hay una corrida activa)
/api/dashboard      Agregado para el panel web
/                   Página HTML con auto-refresh

La BD destino se toma de ETL_CONFIG (o config.json por defecto). El estado en
vivo de la extracción se comparte vía archivo atómico (ETL_LIVE_FILE,
default /tmp/etl_live.json); en Docker hay que exponerlo como volumen para
que runner y dashboard compartan el mismo path.

### Dos vistas (pestañas)

La interfaz tiene dos pestañas con hash URL (`#etl` / `#inventario`):

- **ETL**: corridas recientes, progreso por tabla, extracción en vivo y
  detalle por corrida.
- **Inventario**: cards de resumen (materiales, valor, bajo mínimo, valor en
  riesgo) + filtros por **centro, almacén y área** (valores reales desde la
  tabla derivada), búsqueda de texto, checkbox **"Solo bajo stock"** y tabla
  paginada con las filas bajo mínimo resaltadas.

Botón **Sincronizar**: dispara `POST /api/etl/trigger`, que lanza el ETL
completo como subproceso desprendido (mismo `ETL_CONFIG` y `ETL_LIVE_FILE`);
mientras corre, el botón queda deshabilitado y se muestra el progreso en
vivo; al terminar se refrescan inventario y corridas. Si ya hay una ejecución
activa responde 409 y la UI lo indica (el lock en BD es la protección real).

**Auto-recuperación**: si el subproceso muere o se cuelga (crash, señal, corte
de red), `/api/live` lo detecta (el hijo desaparece, o el estado no avanza en
>120 s) y limpia solo: marca la corrida como `failed`, elimina el lock local
`/tmp/etl_sap.lock` si su dueño ya no existe, y deja el estado `idle` para
poder reintentar. La UI se desatasca sola en pocos segundos.

> Nota: el botón requiere que el host del dashboard tenga el SDK SAP + pyrfc
> para poder ejecutar `cli run` (p. ej. el entorno on-premise o el contenedor
> donde se monta el SDK). En la imagen Docker ligera (sin pyrfc) devolvería
> un error visible y no lanzaría nada.


🐳 Docker

Imagen ligera (solo dashboard + CLI, sin pyrfc; el SDK SAP se monta en runtime):

docker build -t etl-dashboard .
docker run -p 8000:8000 \
  -v /opt/etl/config.json:/opt/etl/config.json:ro \
  -v /opt/sap/nwrfcsdk:/opt/sap/nwrfcsdk:ro \
  etl-dashboard

O con docker-compose (dashboard + ejecución de jobs y reportes):

docker compose up -d                     # dashboard en :8000
docker compose run --rm etl python -m cli bootstrap
docker compose run --rm etl python -m cli migrate
docker compose run --rm etl python -m cli run
docker compose run --rm etl python -m cli importar-minimos --archivo /opt/etl/output/Stock\ Mínimos\ 2026.xlsx --hoja "PLANTA MINIMOS 2026" --col-material CODIGO --col-stock "STOCK MÍNIMO" --col-area AREA
docker compose run --rm etl python -m cli reporte

Variables esperadas en `.env`: `ETL_CONFIG`, `ETL_LIVE_FILE` y las del SDK
(`SAPNWRFC_HOME`, `LD_LIBRARY_PATH`). El volumen `./output` guarda los Excel
generados; en config la ruta del reporte debe apuntar allí (ej.:
`/opt/etl/output/inventario_bodega.xlsx`).

Nota: la imagen NO incluye el SDK NW RFC (licenciado); para ejecutar `etl run`
contra SAP hay que montarlo y configurar SAPNWRFC_HOME/LD_LIBRARY_PATH.

CI: GitHub Actions ejecuta pytest + ruff con requirements-ci.txt (sin pyrfc).


---

🧭 Incorporar otro cliente SAP (onboarding)

1. Copiar config.example.json a config.json y completar: credenciales SAP,
   conexión a la BD destino y tablas a extraer (source/target/keys/load_mode).
2. Onboarding automatizado (valida config, conectividad, migraciones y smoke
   extract T001L): python -m cli bootstrap.
3. Primera extracción: python -m cli run.
4. Definir el inventario en config.derived (dominio, área, mínimos, columnas) e
   importar la matriz de mínimos si existe. Re-correr o regenerar los Excel:
   python -m cli reporte.
5. Programar con cron/systemd y levantar el dashboard.

No hay SQL por cliente: solo datos en config (qué MTART/MATKL son insumos,
qué plantas/almacenes, tablas de área y mínimos).


---

🔁 Automatización con systemd

Servicio (/etc/systemd/system/etl.service)

[Unit]

Description=ETL SAP Job

[Service]

ExecStart=/opt/etl/tablas_linux/run_etl.sh

Restart=always


---

Timer (/etc/systemd/system/etl.timer)

[Unit]

Description=Run ETL every 45 minutes

[Timer]

OnBootSec=5min

OnUnitActiveSec=45min

[Install]

WantedBy=timers.target


---

Activación

sudo systemctl daemon-reexec

sudo systemctl daemon-reload

sudo systemctl enable etl.timer

sudo systemctl start etl.timer


---

🌐 Interfaz Web (Flask)

La aplicación Flask permite:

Disparar ejecución manual del ETL

Visualizar estado actual (etl_state.json)

Evitar ejecuciones simultáneas



---

🔐 Control de concurrencia

El sistema implementa doble validación:

1. Lock file (nivel sistema operativo)

/tmp/etl_sap.lock

Evita ejecuciones simultáneas físicas.


---

2. Control en base de datos

Tabla: etl_execution

SELECT COUNT(*) FROM etl_execution WHERE status='running'

Evita ejecuciones lógicas duplicadas.


---

🔄 Flujo ETL

1. Validación de ejecución activa


2. Creación de lock file


3. Conexión a SAP


4. Extracción de tablas


5. Transformación a DataFrame


6. Carga a staging


7. Ejecución de MERGE


8. Limpieza de staging


9. Actualización de estado y logs


10. Liberación de lock




---

📂 Estructura del proyecto

tablas_linux/

│

├── etl_runner.py

├── cli.py

├── pyproject.toml

│

├── sources/

│ ├── base.py

│ ├── sap/

│ │ ├── connector.py

│ │ └── rfc.py

│ └── generic/

│   ├── http.py

│   └── csv.py

│

│

├── db/

│ ├── db_connection.py

│ ├── staging_loader.py

│ ├── merge_runner.py

│ └── sinks/

│   ├── base.py

│   ├── sqlserver.py

│   ├── postgres.py

│   ├── mysql.py

│   └── sqlite.py

│

├── derived/

│ ├── materializer.py

│ ├── excel_export.py

│ ├── minimos_import.py

│ ├── views.py

│ └── db.py

│

├── schemas/

│ └── config.schema.json

│

├── utils/

│ ├── config_loader.py

│ ├── config_validation.py

│ ├── logger.py

│ └── etl_state.py

│

├── migrations/

│ ├── mssql/

│ ├── postgresql/

│ ├── mysql/

│ └── sqlite/

│
├── tests/

│

├── config.json

└── config.example.json

---

📊 Diagramas del sistema:

Diagrama de Arquitectura


<img width="900" alt="Diagrama de arquitectura" src="https://github.com/user-attachments/assets/10eb6edd-abcd-474e-a6e4-efa3d52d81f6" />


Diagrama Arquitectura lógica


<img width="900" alt="Arquitectura Lógica" src="https://github.com/user-attachments/assets/07d60ab6-1d33-41b6-905a-63b4538e5893" />


Diagrama de flujo


<img width="900" alt="Flujo Etl" src="https://github.com/user-attachments/assets/c0e3fa9e-765f-4a72-b74f-a298b94f5aba" />


Diagrama Control de Concurrencia


<img width="900" alt="Control de Concurrencia" src="https://github.com/user-attachments/assets/9fd0ece7-bc82-4993-9a44-908b736b2fec" />


Diagrama de Secuencia


<img width="900" alt="ETL_SAP" src="https://github.com/user-attachments/assets/cae613eb-a59f-42f6-b2b6-eb83a3ad6c2a" />


Diagrama de Despliegue


<img width="900" alt="ETL_SAP_Despliegue" src="https://github.com/user-attachments/assets/b553dfd0-ab5a-445c-a0cf-1edd7f6cadcb" />


---

📊 Justificación técnica

systemd vs cron

systemd permite control de estado, reinicio automático y mejor trazabilidad.

Uso de staging

Permite aislar datos crudos, evitar inconsistencias y aplicar transformaciones seguras.

MERGE dinámico

Sincronización eficiente evitando duplicados y manteniendo integridad.

RFC_READ_TABLE

Método estándar de extracción SAP sin necesidad de desarrollo ABAP adicional.

Control de concurrencia doble

Garantiza robustez frente a ejecuciones simultáneas desde múltiples puntos.



---

📈 Posibles mejoras

Integración con herramientas de monitoreo (Prometheus, Grafana)

Containerización con Docker

Escalabilidad mediante colas (RabbitMQ, Kafka)



---

👨‍💻 Autor

Desarrollado como solución ETL empresarial en entorno Linux para integración SAP → SQL Server.


---
