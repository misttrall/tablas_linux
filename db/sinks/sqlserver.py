from sqlalchemy import text

from .base import Sink


class SQLServerSink(Sink):

    dialect = "mssql"
    now_sql = "GETDATE()"

    def _truncate_sql(self, table):
        return f"TRUNCATE TABLE {table}"

    def _create_table(self, conn, table, fields, keys):
        columns = list(fields)
        for k in keys:
            if k not in columns:
                columns.append(k)
        defn = []
        for c in columns:
            nullable = "NULL" if c not in keys else "NOT NULL"
            defn.append(f"[{c}] NVARCHAR(255) {nullable}")
        cols = ",\n    ".join(defn)
        pk = ", ".join(f"[{k}]" for k in keys)
        conn.execute(text(f"CREATE TABLE dbo.{table} (\n    {cols},\n    PRIMARY KEY ({pk})\n)"))

    def merge(self, target, staging, keys, fields):
        keys_sql = ", ".join(keys)
        on_clause = " AND ".join(f"target.{k} = src.{k}" for k in keys)
        update_fields = [f for f in fields if f not in keys]
        insert_fields = ", ".join(fields)
        insert_values = ", ".join(f"src.{f}" for f in fields)

        matched = ""
        if update_fields:
            update_clause = ",\n            ".join(f"{f} = src.{f}" for f in update_fields)
            matched = f"""
        WHEN MATCHED THEN
            UPDATE SET
            {update_clause}"""

        sql = f"""
        MERGE {target} AS target
        USING (
            SELECT *
            FROM (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY {keys_sql}
                        ORDER BY {keys_sql}
                    ) AS rn
                FROM {staging}
            ) t
            WHERE rn = 1
        ) AS src
        ON {on_clause}{matched}
        WHEN NOT MATCHED THEN
            INSERT ({insert_fields})
            VALUES ({insert_values});
        """

        with self.engine.begin() as conn:
            conn.execute(text(sql))
            self._clear(conn, staging)

    def insert_execution(self, conn, source):
        return conn.execute(
            text(
                "INSERT INTO dbo.etl_execution (start_time, status) "
                "OUTPUT inserted.id VALUES (GETDATE(), 'running')"
            )
        ).scalar()

    def get_active_run(self, conn, stale_seconds):
        row = conn.execute(
            text(
                "SELECT TOP 1 id, start_time, status FROM dbo.etl_execution "
                "WHERE status='running' AND DATEDIFF(SECOND, start_time, GETDATE()) < :s "
                "ORDER BY id DESC"
            ),
            {"s": stale_seconds},
        ).first()
        return dict(row._mapping) if row is not None else None

    def orphaned_runs(self, conn, stale_seconds):
        rows = conn.execute(
            text(
                "SELECT id, start_time, status FROM dbo.etl_execution "
                "WHERE status='running' AND DATEDIFF(SECOND, start_time, GETDATE()) >= :s "
                "ORDER BY id DESC"
            ),
            {"s": stale_seconds},
        ).fetchall()
        return [dict(r._mapping) for r in rows]

    def upsert_progress(self, conn, table_name, rows_loaded, status, last_delta_value=None):
        conn.execute(
            text(
                f"""
                MERGE dbo.etl_progress AS tgt
                USING (VALUES (:t, :rows, :status, {self.now_expr()}, :delta))
                    AS src(table_name, rows_loaded, status, updated_at, last_delta_value)
                ON tgt.table_name = src.table_name
                WHEN MATCHED THEN UPDATE SET
                    rows_loaded = src.rows_loaded,
                    status = src.status,
                    updated_at = src.updated_at,
                    last_delta_value = src.last_delta_value
                WHEN NOT MATCHED THEN
                    INSERT (table_name, rows_loaded, status, updated_at, last_delta_value)
                    VALUES (src.table_name, src.rows_loaded, src.status, src.updated_at, src.last_delta_value);
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
                MERGE dbo.etl_execution_tables AS tgt
                USING (VALUES (:run, :t, :total, :ok, :rows, :dur, :status))
                    AS src(run_id, table_name, chunks_total, chunks_ok, rows_extracted, duration_s, status)
                ON tgt.run_id = src.run_id AND tgt.table_name = src.table_name
                WHEN MATCHED THEN UPDATE SET
                    chunks_total = COALESCE(src.chunks_total, tgt.chunks_total),
                    chunks_ok = COALESCE(src.chunks_ok, tgt.chunks_ok),
                    rows_extracted = COALESCE(src.rows_extracted, tgt.rows_extracted),
                    duration_s = COALESCE(src.duration_s, tgt.duration_s),
                    status = src.status
                WHEN NOT MATCHED THEN
                    INSERT (run_id, table_name, chunks_total, chunks_ok, rows_extracted, duration_s, status)
                    VALUES (src.run_id, src.table_name, src.chunks_total, src.chunks_ok,
                            src.rows_extracted, src.duration_s, src.status);
                """
            ),
            {"run": run_id, "t": table_name, "total": chunks_total, "ok": chunks_ok,
             "rows": rows_extracted, "dur": duration_s, "status": status},
        )
