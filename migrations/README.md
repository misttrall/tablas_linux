# Migraciones

Este directorio contiene los scripts DDL para crear las **tablas de control del ETL**
(`etl_execution` y `etl_progress`). Ejecutá únicamente el script que corresponde al
dialecto de la base de datos destino, en orden (`001` y luego `002`).

- `mssql/` → SQL Server
- `postgresql/` → PostgreSQL
- `mysql/` → MySQL / MariaDB
- `sqlite/` → SQLite (solo desarrollo / pruebas locales)

- `001_control_tables.sql` → crea `etl_execution` y `etl_progress`
- `002_etl_progress_delta.sql` → agrega `etl_progress.last_delta_value` (extracción incremental)

## Notas por dialecto

**SQL Server**: ejecutar en SSMS o con `sqlcmd -i 001_control_tables.sql -i 002_etl_progress_delta.sql`.

**PostgreSQL**: `psql -d <base> -f 001_control_tables.sql -f 002_etl_progress_delta.sql`

**MySQL**: `mysql -u <user> -p <base> < 001_control_tables.sql && mysql -u <user> -p <base> < 002_etl_progress_delta.sql`

**SQLite**: `sqlite3 <base>.db < 001_control_tables.sql && sqlite3 <base>.db < 002_etl_progress_delta.sql`

## Limitaciones conocidas

**MySQL — deprecación de `VALUES()`**: el upsert usa `ON DUPLICATE KEY UPDATE` con
`VALUES(columna)`, que está deprecado desde MySQL 8.0.20 (aún funcional, puede emitir
advertencias). Al exigir MySQL 8+, migrar a la sintaxis `AS new ... alias` cuando se
modernice el generador de SQL.

**MySQL — carga no atómica**: el sink de MySQL usa `DELETE FROM` para vaciar staging
(no `TRUNCATE`), por lo que la carga no es transaccional a nivel DDL; si falla a mitad,
el staging puede quedar parcialmente cargado. El MERGE deduplica por clave, así que un
staging parcial no corrompe la tabla destino.

## Tablas destino

Las tablas destino de los jobs (ej. `Mara_Data`) deben existir previamente y tener una
restricción `PRIMARY KEY` o `UNIQUE` sobre las columnas `keys` definidas en `config.json`.
Sin esa restricción, el *upsert* (ON CONFLICT / ON DUPLICATE KEY / MERGE) no puede
detectar registros existentes.

Las tablas staging (`stg_*`) se crean automáticamente durante la carga.
