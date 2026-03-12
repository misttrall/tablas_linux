from extractor.sap_extractor import extract_table
from db.staging_loader import load_staging
from db.merge_runner import run_merges
from db.db_connection import get_engine
from utils.config_loader import load_config
from utils.logger import get_logger
from pyrfc import Connection

logger = get_logger()


def run_bodega_job():

    config = load_config()

    engine = get_engine()

    sap_conn = Connection(**config["sap"])

    tables = config["tables"]

    total = len(tables)

    try:

        logger.info("ETL iniciado")

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

        logger.info("Ejecutando MERGES")

        run_merges()

        logger.info("ETL terminado")

    except Exception as e:

        logger.error(f"ERROR ETL: {e}")

        raise

    finally:

        sap_conn.close()


if __name__ == "__main__":
    run_bodega_job()