import json
from sqlalchemy import text
from db.db_connection import get_engine


# claves primarias SAP por tabla
PRIMARY_KEYS = {
    "MARA": ["MATNR"],
    "MAKT": ["MANDT", "MATNR", "SPRAS"],
    "MARD": ["MANDT", "MATNR", "WERKS", "LGORT"],
    "MBEW": ["MATNR", "BWKEY"],
    "T001L": ["MANDT", "WERKS", "LGORT"]
}


def build_merge(table, target, fields):
    """
    Construye un SQL MERGE seguro:
    - Evita insertar duplicados de staging
    - Actualiza registros existentes
    - Inserta solo los nuevos
    """
    keys = PRIMARY_KEYS[table]

    # Condición ON para el MERGE
    on_clause = " AND ".join([f"target.{k} = src.{k}" for k in keys])

    # Campos a actualizar (excluyendo la clave primaria)
    update_fields = [f for f in fields if f not in keys]
    update_clause = ",\n        ".join([f"{f} = src.{f}" for f in update_fields])

    insert_fields = ", ".join(fields)
    insert_values = ", ".join([f"src.{f}" for f in fields])

    # SQL MERGE con CTE que elimina duplicados en staging
    merge_sql = f"""
    MERGE {target} AS target
    USING (
        SELECT *
        FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY {",".join(keys)}
                    ORDER BY {",".join(keys)}
                ) AS rn
            FROM stg_{table}_Data
        ) t
        WHERE rn = 1
    ) AS src
    ON {on_clause}
    WHEN MATCHED THEN
        UPDATE SET
        {update_clause}
    WHEN NOT MATCHED THEN
        INSERT ({insert_fields})
        VALUES ({insert_values});
    """

    return merge_sql

def update_progress(conn, table, rows, status):

    conn.execute(text("""
        DELETE FROM etl_progress WHERE table_name = :table
    """), {"table": table})

    conn.execute(text("""
        INSERT INTO etl_progress
        (table_name, rows_loaded, status, updated_at)
        VALUES
        (:table, :rows, :status, GETDATE())
    """), {
        "table": table,
        "rows": rows,
        "status": status
    })

def run_merges():

    engine = get_engine()

    with open("config.json", "r") as f:
        config = json.load(f)

    tables = config["tables"]
    fields = config["fields"]

    with engine.begin() as conn:

        for t in tables:

            source = t["source"]
            target = t["target"]

            table_fields = fields[source]

            print(f"Ejecutando MERGE {source}...")

            sql = build_merge(source, target, table_fields)

            # ejecuta merge
            conn.execute(text(sql))

            # limpia staging
            conn.execute(text(f"TRUNCATE TABLE stg_{target}"))

            print(f"Staging stg_{target} limpiada")