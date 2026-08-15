from abc import ABC, abstractmethod

from sqlalchemy import inspect, text


class Sink(ABC):
    """Estrategia por dialecto de base de datos para las operaciones no portables del ETL."""

    dialect = ""
    now_sql = ""

    def __init__(self, engine):
        self.engine = engine

    def now_expr(self):
        """Expresión SQL de 'timestamp actual' compatible con el dialecto."""
        return self.now_sql

    @abstractmethod
    def _truncate_sql(self, table):
        """Devuelve el SQL para vaciar una tabla según el dialecto."""

    def _create_table(self, conn, table, fields, keys):
        """Crea la tabla destino con PRIMARY KEY sobre keys."""
        raise NotImplementedError

    def ensure_target(self, table, fields, keys):
        """Crea la tabla destino (con PK sobre keys) si no existe aún."""
        with self.engine.begin() as conn:
            if self._table_exists(conn, table):
                return
            self._create_table(conn, table, fields, keys)

    def _table_exists(self, conn, table):
        return inspect(conn).has_table(table)

    def _clear(self, conn, table):
        conn.execute(text(self._truncate_sql(table)))

    def load(self, df, table):
        """Reemplaza el contenido de la tabla con el DataFrame de forma atómica."""
        data = df.replace("", None)
        with self.engine.begin() as conn:
            if self._table_exists(conn, table):
                conn.execute(text(self._truncate_sql(table)))
            data.to_sql(table, conn, if_exists="append", index=False, chunksize=10000)
        return len(data)

    @abstractmethod
    def merge(self, target, staging, keys, fields):
        """Upsert desde staging hacia target y limpia la tabla staging."""

    def insert_execution(self, conn, source):
        """Crea una ejecución 'running' en etl_execution y devuelve su id."""
        raise NotImplementedError

    def get_active_run(self, conn, stale_seconds):
        """Devuelve la ejecución 'running' activa (no huérfana) o None."""
        raise NotImplementedError

    def orphaned_runs(self, conn, stale_seconds):
        """Devuelve las ejecuciones 'running' huérfanas (lock vencido)."""
        raise NotImplementedError

    def upsert_progress(self, conn, table_name, rows_loaded, status, last_delta_value=None):
        """Inserta o actualiza la fila de etl_progress de una tabla."""
        raise NotImplementedError

    def upsert_execution_table(self, conn, run_id, table_name, chunks_total=None,
                               chunks_ok=None, rows_extracted=None, duration_s=None,
                               status=None):
        """Inserta o actualiza las estadísticas de extracción de una tabla en una corrida."""
        raise NotImplementedError

    def finish_execution(self, conn, run_id):
        conn.execute(
            text(
                f"UPDATE etl_execution SET status='finished', end_time={self.now_expr()} "
                "WHERE id=:id"
            ),
            {"id": run_id},
        )

    def fail_execution(self, conn, run_id, message):
        conn.execute(
            text(
                f"UPDATE etl_execution SET status='failed', end_time={self.now_expr()}, "
                "message=:msg WHERE id=:id"
            ),
            {"id": run_id, "msg": str(message)},
        )

    def get_progress(self, conn, table_name):
        row = conn.execute(
            text(
                "SELECT table_name, rows_loaded, status, last_delta_value, updated_at "
                "FROM etl_progress WHERE table_name=:t"
            ),
            {"t": table_name},
        ).first()
        return dict(row._mapping) if row is not None else None
