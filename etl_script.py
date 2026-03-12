from sqlalchemy import text
from db.db_connection import get_engine
from etl.etl_runner import run_bodega_job


def is_running(conn):

    result = conn.execute(text("""
        SELECT COUNT(*)
        FROM etl_execution
        WHERE status='running'
    """))

    return result.scalar() > 0


def start_execution(conn):

    result = conn.execute(text("""
        INSERT INTO etl_execution(start_time,status)
        VALUES(NOW(),'running')
        RETURNING id
    """))

    return result.scalar()


def finish_execution(conn, run_id):

    conn.execute(text("""
        UPDATE etl_execution
        SET status='finished',
            end_time=NOW()
        WHERE id=:id
    """), {"id": run_id})


def fail_execution(conn, run_id, error):

    conn.execute(text("""
        UPDATE etl_execution
        SET status='failed',
            end_time=NOW(),
            message=:msg
        WHERE id=:id
    """), {"id": run_id, "msg": str(error)})


def run():

    engine = get_engine()

    with engine.begin() as conn:

        if is_running(conn):
            print("ETL ya ejecutándose")
            return

        run_id = start_execution(conn)

    try:

        run_bodega_job()

        with engine.begin() as conn:
            finish_execution(conn, run_id)

    except Exception as e:

        with engine.begin() as conn:
            fail_execution(conn, run_id, e)

        raise


if __name__ == "__main__":
    run()