import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from db.control import (
    EtlAlreadyRunning,
    build_delta_filters,
    fail_run,
    finish_run,
    get_table_progress,
    mark_table_failed,
    mark_table_ok,
    start_run,
    update_last_delta,
    upsert_execution_table,
)
from db.db_connection import get_engine
from db.merge_runner import run_merges
from db.sinks import get_sink
from db.staging_loader import load_staging
from sources import get_source, resolve_source_config, validate_environment, validate_prd_limits
from sources.partitioning import extract_in_ranges
from utils.config_loader import load_config
from utils.etl_state import update_state
from utils.live import update_live
from utils.logger import get_logger

logger = get_logger()

LOCK_FILE = "/tmp/etl_sap.lock"
LOCK_STALE_SECONDS = 60 * 60


def acquire_lock():

    if os.path.exists(LOCK_FILE):
        age = time.time() - os.path.getmtime(LOCK_FILE)
        if age < LOCK_STALE_SECONDS:
            logger.warning("ETL ya en ejecución")
            sys.exit(1)
        logger.warning("Lock local huérfano detectado; se reemplaza")

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def release_lock():

    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


def run_etl_job(config_path=None, tables=None):

    acquire_lock()

    connector = None
    engine = None
    run_id = None

    try:

        config = load_config(config_path)

        validate_environment(config)

        validate_prd_limits(config)

        engine = get_engine(config)
        sink = get_sink(engine)

        source_config = resolve_source_config(config)

        try:
            run_id = start_run(engine, sink, source_config["type"])
        except EtlAlreadyRunning as e:
            logger.warning(str(e))
            sys.exit(1)

        connector = get_source(source_config)

        logger.info(f"Conectando a fuente: {connector.type}")

        connector.connect()

        tables_config = config["tables"]
        if tables:
            wanted = set(tables)
            tables_config = [
                t for t in tables_config
                if t["source"] in wanted or t["target"] in wanted
            ]
            missing = wanted - {t["source"] for t in config["tables"]} - {t["target"] for t in config["tables"]}
            if missing:
                raise ValueError(f"Tablas no encontradas en config: {sorted(missing)}")
            if not tables_config:
                raise ValueError("Ninguna tabla seleccionada con --tables")

        total = len(tables_config)

        logger.info("ETL iniciado")

        start_run_time = time.time()

        update_state(
            running=True,
            progress=0,
            status="Iniciando ETL"
        )

        successful = []
        failures = {}

        for i, table in enumerate(tables_config):

            source = table["source"]
            target = table["target"]
            fields = config["fields"][source]

            table_start = time.time()

            try:

                if run_id is not None:
                    upsert_execution_table(engine, sink, run_id, target, status="running")

                last_delta = None
                incremental = table.get("incremental")

                if incremental:
                    progress_row = get_table_progress(engine, sink, target)
                    last_delta = (progress_row or {}).get("last_delta_value")
                    delta_field = incremental.get("field")
                    if delta_field and delta_field not in fields:
                        raise ValueError(
                            f"Campo incremental '{delta_field}' no está en fields de {source}"
                        )

                filters = build_delta_filters(table, last_delta)

                logger.info(f"Extrayendo {source}")

                if table.get("load_mode") == "range":
                    range_cfg = table.get("range") or {}
                    key = range_cfg.get("key", "MATNR")
                    prefixes = range_cfg.get("prefixes")
                    sentinel = range_cfg.get("sentinel")

                    def on_start(chunks_total, _source=source, _target=target):
                        if run_id is not None:
                            upsert_execution_table(
                                engine, sink, run_id, _target,
                                chunks_total=chunks_total, chunks_ok=0, status="running",
                            )
                        update_live(
                            running=True, run_id=run_id, table=_source, phase="extrayendo",
                            chunk_index=0, chunk_total=chunks_total, rows_so_far=0,
                            elapsed_s=round(time.time() - table_start, 1),
                        )

                    def on_chunk(index, total, rows_chunk, rows_so_far, _target=target):
                        if run_id is not None:
                            upsert_execution_table(
                                engine, sink, run_id, _target,
                                chunks_ok=index, rows_extracted=rows_so_far, status="running",
                            )
                        update_live(
                            running=True, run_id=run_id, table=source, phase="extrayendo",
                            chunk_index=index, chunk_total=total, rows_so_far=rows_so_far,
                            elapsed_s=round(time.time() - table_start, 1),
                        )

                    df = extract_in_ranges(
                        connector, source, fields, filters=filters,
                        key=key, prefixes=prefixes, sentinel=sentinel,
                        on_start=on_start, on_chunk=on_chunk,
                    )
                else:
                    update_live(
                        running=True, run_id=run_id, table=source, phase="extrayendo",
                        chunk_index=0, chunk_total=0, rows_so_far=0,
                        elapsed_s=round(time.time() - table_start, 1),
                    )
                    df = connector.extract(source, fields, filters=filters)

                n = len(df)

                logger.info(f"{n} registros")

                load_staging(df, target, engine, sink)

                new_last_delta = update_last_delta(df, table)

                mark_table_ok(engine, sink, target, n, new_last_delta)

                if run_id is not None:
                    upsert_execution_table(
                        engine, sink, run_id, target, status="ok",
                        duration_s=round(time.time() - table_start, 1),
                    )

                logger.info(f"{source} cargado")

                successful.append(table)

            except Exception as e:

                logger.exception(f"Error en tabla {source}: {e}")

                try:
                    mark_table_failed(engine, sink, target)
                except Exception:
                    logger.warning(f"No se pudo registrar el error de {source} en etl_progress")

                if run_id is not None:
                    try:
                        upsert_execution_table(
                            engine, sink, run_id, target, status="failed",
                            duration_s=round(time.time() - table_start, 1),
                        )
                    except Exception:
                        logger.warning(f"No se pudo registrar el detalle de {source} en etl_execution_tables")

                failures[source] = str(e)

            progress = int((i + 1) / total * 80)

            logger.info(f"Progreso {progress}%")

            update_state(
                running=True,
                progress=progress,
                status=f"Procesando {source}"
            )

        if successful:

            logger.info("Ejecutando MERGES")

            update_live(
                running=True, run_id=run_id, table=None, phase="merges",
                chunk_index=0, chunk_total=0, rows_so_far=0,
                elapsed_s=round(time.time() - start_run_time, 1),
            )

            update_state(
                running=True,
                progress=90,
                status="Ejecutando merges"
            )

            run_merges(engine=engine, sink=sink, tables=successful, config=config)

        if successful and config.get("derived"):

            from derived.materializer import run_deriveds

            logger.info("Materializando modelos derivados")

            update_live(
                running=True, run_id=run_id, table=None, phase="derived",
                chunk_index=0, chunk_total=0, rows_so_far=0,
                elapsed_s=round(time.time() - start_run_time, 1),
            )

            update_state(
                running=True,
                progress=95,
                status="Generando modelos derivados"
            )

            derived_start = time.time()

            try:
                for name, n_rows, excel_path in run_deriveds(engine=engine, sink=sink, config=config):
                    if run_id is not None:
                        upsert_execution_table(
                            engine, sink, run_id, name,
                            rows_extracted=n_rows, status="ok",
                            duration_s=round(time.time() - derived_start, 1),
                        )
                    logger.info(f"Modelo '{name}' materializado: {n_rows} filas -> {excel_path}")
            except Exception as e:
                logger.exception(f"Error en modelo derivado: {e}")
                if run_id is not None:
                    try:
                        upsert_execution_table(
                            engine, sink, run_id, "<derived>", status="failed",
                            duration_s=round(time.time() - derived_start, 1),
                        )
                    except Exception:
                        logger.warning("No se pudo registrar el fallo del modelo derivado")
                raise RuntimeError(f"Error en modelo derivado: {e}")

        if failures:

            logger.error(f"ETL finalizado con errores en tablas: {list(failures)}")

            update_live(
                running=False, run_id=run_id, table=None, phase="error",
                chunk_index=0, chunk_total=0, rows_so_far=0,
                elapsed_s=round(time.time() - start_run_time, 1),
            )

            update_state(
                running=False,
                status="Error en ETL"
            )

            raise RuntimeError(f"ETL con errores en tablas: {failures}")

        logger.info("ETL terminado")

        update_live(
            running=False, run_id=run_id, table=None, phase="idle",
            chunk_index=0, chunk_total=0, rows_so_far=0,
            elapsed_s=round(time.time() - start_run_time, 1),
        )

        update_state(
            running=False,
            progress=100,
            status="ETL finalizado",
            last_run=datetime.now(ZoneInfo("America/Santiago")).isoformat()
        )

        finish_run(engine, sink, run_id)

    except Exception as e:

        logger.exception(f"ERROR ETL: {e}")

        update_state(
            running=False,
            status="Error en ETL"
        )

        if run_id is not None and engine is not None:
            try:
                fail_run(engine, sink, run_id, e)
            except Exception:
                logger.warning("No se pudo registrar el fallo en la base de datos")

        raise

    finally:

        if connector:
            connector.close()

        update_live(running=False)

        update_state(running=False)

        release_lock()


if __name__ == "__main__":
    run_etl_job()
