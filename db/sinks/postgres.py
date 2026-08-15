from sqlalchemy import text

from .base import Sink


class PostgreSQLSink(Sink):

    dialect = "postgresql"
    now_sql = "NOW()"

    def _truncate_sql(self, table):
        return f"TRUNCATE TABLE {table}"

    def _create_table(self, conn, table, fields, keys):
        columns = list(fields)
        for k in keys:
            if k not in columns:
                columns.append(k)
        cols = ",\n    ".join(f'"{c}" TEXT' for c in columns)
        pk = ", ".join(f'"{k}"' for k in keys)
        conn.execute(text(f"CREATE TABLE {table} (\n    {cols},\n    PRIMARY KEY ({pk})\n)"))

    def merge(self, target, staging, keys, fields):
        keys_sql = ", ".join(keys)
        insert_fields = ", ".join(fields)
        select_fields = ", ".join(f"src.{f}" for f in fields)
        update_fields = [f for f in fields if f not in keys]

        conflict = "DO NOTHING"
        if update_fields:
            update_clause = ",\n            ".join(f"{f} = EXCLUDED.{f}" for f in update_fields)
            conflict = "DO UPDATE SET\n            " + update_clause

        sql = f"""
        INSERT INTO {target} ({insert_fields})
        SELECT {select_fields}
        FROM (
            SELECT DISTINCT ON ({keys_sql}) {insert_fields}
            FROM {staging}
        ) AS src
        ON CONFLICT ({keys_sql}) {conflict};
        """

        with self.engine.begin() as conn:
            conn.execute(text(sql))
            self._clear(conn, staging)

    def insert_execution(self, conn, source):
        return conn.execute(
            text("INSERT INTO etl_execution (start_time, status) VALUES (NOW(), 'running') RETURNING id")
        ).scalar()

    def get_active_run(self, conn, stale_seconds):
        row = conn.execute(
            text(
                "SELECT id, start_time, status FROM etl_execution "
                "WHERE status='running' AND EXTRACT(EPOCH FROM (NOW() - start_time)) < :s "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"s": stale_seconds},
        ).first()
        return dict(row._mapping) if row is not None else None

    def orphaned_runs(self, conn, stale_seconds):
        rows = conn.execute(
            text(
                "SELECT id, start_time, status FROM etl_execution "
                "WHERE status='running' AND EXTRACT(EPOCH FROM (NOW() - start_time)) >= :s "
                "ORDER BY id DESC"
            ),
            {"s": stale_seconds},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    def upsert_progress(self, conn, table_name, rows_loaded, status, last_delta_value=None):
        conn.execute(
            text(
                f"""
                INSERT INTO etl_progress (table_name, rows_loaded, status, updated_at, last_delta_value)
                VALUES (:t, :rows, :status, {self.now_expr()}, :delta)
                ON CONFLICT (table_name) DO UPDATE SET
                    rows_loaded = EXCLUDED.rows_loaded,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at,
                    last_delta_value = EXCLUDED.last_delta_value
                """
            ),
            {"t": table_name, "rows": rows_loaded, "status": status, "delta": last_delta_value},
        )

    def upsert_execution_table(self, conn, run_id, table_name, chunks_total=None,
                               chunks_ok=None, rows_extracted=None, duration_s=None,
                               status=None):
        conn.execute(
            text(
                """
                INSERT INTO etl_execution_tables
                    (run_id, table_name, chunks_total, chunks_ok, rows_extracted, duration_s, status)
                VALUES (:run, :t, :total, :ok, :rows, :dur, :status)
                ON CONFLICT (run_id, table_name) DO UPDATE SET
                    chunks_total = COALESCE(EXCLUDED.chunks_total, etl_execution_tables.chunks_total),
                    chunks_ok = COALESCE(EXCLUDED.chunks_ok, etl_execution_tables.chunks_ok),
                    rows_extracted = COALESCE(EXCLUDED.rows_extracted, etl_execution_tables.rows_extracted),
                    duration_s = COALESCE(EXCLUDED.duration_s, etl_execution_tables.duration_s),
                    status = EXCLUDED.status
                """
            ),
            {"run": run_id, "t": table_name, "total": chunks_total, "ok": chunks_ok,
             "rows": rows_extracted, "dur": duration_s, "status": status},
        )
