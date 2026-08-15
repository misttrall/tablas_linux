from db.sinks import get_sink


def load_staging(df, table, engine, sink=None):
    if sink is None:
        sink = get_sink(engine)
    staging_table = f"stg_{table}"
    return sink.load(df, staging_table)
