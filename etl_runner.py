from extractor.sap_extractor import extract_table
from db.staging_loader import load_staging
from db.merge_runner import run_merges
from db.db_connection import get_engine
from utils.config_loader import load_config
from utils.logger import get_logger
from pyrfc import Connection
from utils.etl_state import update_state

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

logger = get_logger()

LOCK_FILE = "/tmp/etl_sap.lock"


def acquire_lock():

    if os.path.exists(LOCK_FILE):
        logger.warning("ETL ya en ejecución")
        sys.exit(1)

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def release_lock():

    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


def run_bodega_job():

    acquire_lock()

    sap_conn = None

    try:

        config = load_config()

        engine = get_engine()

        logger.info("Conectando a SAP")

        sap_conn = Connection(**config["sap"])

        tables = config["tables"]
        total = len(tables)

        logger.info("ETL iniciado")

        update_state(
            running=True,
            progress=0,
            status="Iniciando ETL"
        )

        for i, table in enumerate(tables):

            source = table["source"]
            target = table["target"]

            fields = config["fields"][source]

            logger.info(f"Extrayendo {source}")

            df = extract_table(sap_conn, source, fields)

            logger.info(f"{len(df)} registros")

            load_staging(df, target, engine)

            logger.info(f"{source} cargado")

            progress = int((i + 1) / total * 80)

            logger.info(f"Progreso {progress}%")

            update_state(
                running=True,
                progress=progress,
                status=f"Procesando {source}"
            )

        logger.info("Ejecutando MERGES")

        update_state(
            running=True,
            progress=90,
            status="Ejecutando merges"
        )

        run_merges()

        logger.info("ETL terminado")

        update_state(
            running=False,
            progress=100,
            status="ETL finalizado",
            last_run=datetime.now(ZoneInfo("America/Santiago")).isoformat()
        )

    except Exception as e:

        logger.exception(f"ERROR ETL: {e}")

        update_state(
            running=False,
            status="Error en ETL"
        )

        raise

    finally:

        if sap_conn:
            sap_conn.close()

        update_state(running=False)

        release_lock()


if __name__ == "__main__":
    run_bodega_job()
