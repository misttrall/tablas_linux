from sqlalchemy import text

def load_staging(df, source_table, engine):

    staging_table = f"stg_{source_table}"

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {staging_table}"))
    df = df.replace('', None)
    df.to_sql(
        staging_table,
        engine,
        if_exists="append",
        index=False,
        chunksize=10000
    )

    print(f"{len(df)} registros cargados en {staging_table}")