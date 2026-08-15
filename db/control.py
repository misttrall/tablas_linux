DEFAULT_STALE_MINUTES = 60


class EtlAlreadyRunning(Exception):
    """Ya hay una ejecución ETL activa (lock no vencido)."""


def start_run(engine, sink, source, stale_minutes=DEFAULT_STALE_MINUTES):
    """Adquiere el lock en BD: crea la fila 'running' y reemplaza huérfanos.

    Lanza EtlAlreadyRunning si existe una ejecución 'running' reciente.
    Los registros 'running' con lock vencido se marcan como 'failed'.
    """
    with engine.begin() as conn:
        active = sink.get_active_run(conn, stale_minutes * 60)
        if active is not None:
            raise EtlAlreadyRunning(
                f"ETL ya en ejecución (run id={active['id']} desde {active['start_time']})"
            )
        for orphan in sink.orphaned_runs(conn, stale_minutes * 60):
            sink.fail_execution(
                conn, orphan["id"], f"Abortado: run huérfano (lock vencido, run id={orphan['id']})"
            )
        return sink.insert_execution(conn, source)


def finish_run(engine, sink, run_id):
    with engine.begin() as conn:
        sink.finish_execution(conn, run_id)


def fail_run(engine, sink, run_id, message):
    with engine.begin() as conn:
        sink.fail_execution(conn, run_id, message)


def mark_table_ok(engine, sink, table_name, rows_loaded, last_delta_value=None):
    with engine.begin() as conn:
        sink.upsert_progress(conn, table_name, rows_loaded, "ok", last_delta_value)


def mark_table_failed(engine, sink, table_name):
    with engine.begin() as conn:
        sink.upsert_progress(conn, table_name, None, "failed", None)


def get_table_progress(engine, sink, table_name):
    with engine.connect() as conn:
        return sink.get_progress(conn, table_name)


def upsert_execution_table(engine, sink, run_id, table_name, **stats):
    """Registra las estadísticas de extracción de una tabla dentro de una corrida."""
    with engine.begin() as conn:
        sink.upsert_execution_table(conn, run_id, table_name, **stats)


def build_delta_filters(table, last_delta_value):
    """Construye los filtros de extracción incremental (SAP) para una tabla.

    Si la tabla está configurada con `incremental.field` y existe un último
    valor conocido, agrega la condición `field >= '<valor>'` a los filtros.
    """
    base = table.get("filters")
    incremental = table.get("incremental")
    if not incremental or not last_delta_value:
        return base
    field = incremental.get("field")
    if not field:
        return base
    return (base or []) + [f"{field} >= '{last_delta_value}'"]


def update_last_delta(df, table):
    """Devuelve el nuevo último valor incremental (máximo del campo), o None."""
    incremental = table.get("incremental")
    if not incremental:
        return None
    field = incremental.get("field")
    if not field or field not in df.columns or len(df) == 0:
        return None
    return str(df[field].max())
