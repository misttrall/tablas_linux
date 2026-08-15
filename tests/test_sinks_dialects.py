from types import SimpleNamespace

import pytest

from db.sinks import get_sink
from db.sinks.mysql import MySQLSink
from db.sinks.postgres import PostgreSQLSink
from db.sinks.sqlite import SQLiteSink
from db.sinks.sqlserver import SQLServerSink


class FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, stmt, *args, **kwargs):
        self.statements.append(str(stmt))
        return self

    def scalar(self):
        return None

    def first(self):
        return None

    def fetchall(self):
        return []


class FakeTransaction:
    def __init__(self):
        self.conn = FakeConnection()

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, name):
        self.dialect = SimpleNamespace(name=name)
        self.tx = FakeTransaction()

    def begin(self):
        return self.tx


def run_merge(sink, target="target", staging="stg_x", keys=("id",), fields=("id", "name", "qty")):
    sink.merge(target, staging, list(keys), list(fields))
    return " ".join(sink.engine.tx.conn.statements)


@pytest.mark.parametrize(
    "sink,expects",
    [
        (SQLServerSink(FakeEngine("mssql")), ["MERGE", "WHEN NOT MATCHED THEN", "ROW_NUMBER", "TRUNCATE"]),
        (PostgreSQLSink(FakeEngine("postgresql")), ["ON CONFLICT", "DISTINCT ON", "EXCLUDED", "TRUNCATE"]),
        (MySQLSink(FakeEngine("mysql")), ["ON DUPLICATE KEY", "ROW_NUMBER", "VALUES", "DELETE FROM"]),
        (SQLiteSink(FakeEngine("sqlite")), ["ON CONFLICT", "ROW_NUMBER", "excluded", "DELETE FROM"]),
    ],
)
def test_merge_generates_dialect_sql(sink, expects):
    sql = run_merge(sink)
    for expected in expects:
        assert expected in sql


def test_sqlserver_omits_update_when_all_fields_are_keys():
    sink = SQLServerSink(FakeEngine("mssql"))
    sql = run_merge(sink, keys=("id",), fields=("id",))
    assert "WHEN MATCHED THEN" not in sql
    assert "WHEN NOT MATCHED THEN" in sql


def test_get_sink_by_dialect():
    assert isinstance(get_sink(FakeEngine("mssql")), SQLServerSink)
    assert isinstance(get_sink(FakeEngine("postgresql")), PostgreSQLSink)
    assert isinstance(get_sink(FakeEngine("mysql")), MySQLSink)
    assert isinstance(get_sink(FakeEngine("sqlite")), SQLiteSink)


def test_get_sink_unknown_dialect_raises():
    with pytest.raises(ValueError):
        get_sink(FakeEngine("oracle"))


def test_now_expressions():
    assert SQLServerSink(FakeEngine("mssql")).now_expr() == "GETDATE()"
    assert PostgreSQLSink(FakeEngine("postgresql")).now_expr() == "NOW()"
    assert MySQLSink(FakeEngine("mysql")).now_expr() == "NOW()"
    assert SQLiteSink(FakeEngine("sqlite")).now_expr() == "CURRENT_TIMESTAMP"


@pytest.mark.parametrize(
    "sink,expects",
    [
        (SQLServerSink(FakeEngine("mssql")), ["CREATE TABLE dbo.", "PRIMARY KEY ([id])", "NOT NULL"]),
        (PostgreSQLSink(FakeEngine("postgresql")), ["CREATE TABLE", 'PRIMARY KEY ("id")']),
        (MySQLSink(FakeEngine("mysql")), ["CREATE TABLE", "VARCHAR(255)", "PRIMARY KEY (`id`)"]),
        (SQLiteSink(FakeEngine("sqlite")), ["CREATE TABLE", "PRIMARY KEY (id)"]),
    ],
)
def test_create_table_generates_dialect_sql(sink, expects):
    conn = sink.engine.tx.conn
    sink._create_table(conn, "target", ["id", "name"], ["id"])
    sql = " ".join(conn.statements)
    for expected in expects:
        assert expected in sql


def test_create_table_adds_missing_key_column():
    sink = SQLiteSink(FakeEngine("sqlite"))
    conn = sink.engine.tx.conn
    sink._create_table(conn, "target", ["name"], ["id", "name"])
    sql = " ".join(conn.statements)
    assert "id TEXT" in sql
    assert "PRIMARY KEY (id, name)" in sql


def test_ensure_target_creates_once_real_sqlite():
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine("sqlite://")
    sink = SQLiteSink(engine)
    sink.ensure_target("target", ["id", "name"], ["id"])
    with engine.connect() as conn:
        assert inspect(conn).has_table("target")
        cols = {r[1]: r[5] for r in conn.execute(text("PRAGMA table_info(target)"))}
        assert cols["id"] == 1
        assert cols["name"] == 0
    sink.ensure_target("target", ["id", "name"], ["id"])


@pytest.mark.parametrize(
    "sink,expects",
    [
        (SQLServerSink(FakeEngine("mssql")), ["INSERT INTO dbo.etl_execution", "OUTPUT inserted.id"]),
        (PostgreSQLSink(FakeEngine("postgresql")), ["INSERT INTO etl_execution", "RETURNING id"]),
        (MySQLSink(FakeEngine("mysql")), ["INSERT INTO etl_execution", "LAST_INSERT_ID"]),
        (SQLiteSink(FakeEngine("sqlite")), ["INSERT INTO etl_execution", "last_insert_rowid"]),
    ],
)
def test_insert_execution_generates_dialect_sql(sink, expects):
    conn = sink.engine.tx.conn
    sink.insert_execution(conn, "sap")
    sql = " ".join(conn.statements)
    for expected in expects:
        assert expected in sql


@pytest.mark.parametrize(
    "sink,expects",
    [
        (SQLServerSink(FakeEngine("mssql")), ["DATEDIFF", "TOP 1", "'running'"]),
        (PostgreSQLSink(FakeEngine("postgresql")), ["EXTRACT(EPOCH", "'running'"]),
        (MySQLSink(FakeEngine("mysql")), ["TIMESTAMPDIFF", "'running'"]),
        (SQLiteSink(FakeEngine("sqlite")), ["strftime", "'running'"]),
    ],
)
def test_get_active_run_generates_dialect_sql(sink, expects):
    conn = sink.engine.tx.conn
    sink.get_active_run(conn, 3600)
    sql = " ".join(conn.statements)
    for expected in expects:
        assert expected in sql


@pytest.mark.parametrize(
    "sink,expects",
    [
        (SQLServerSink(FakeEngine("mssql")), ["MERGE dbo.etl_progress", "WHEN MATCHED", "last_delta_value"]),
        (PostgreSQLSink(FakeEngine("postgresql")), ["ON CONFLICT", "last_delta_value"]),
        (MySQLSink(FakeEngine("mysql")), ["ON DUPLICATE KEY", "last_delta_value"]),
        (SQLiteSink(FakeEngine("sqlite")), ["ON CONFLICT", "last_delta_value"]),
    ],
)
def test_upsert_progress_generates_dialect_sql(sink, expects):
    conn = sink.engine.tx.conn
    sink.upsert_progress(conn, "Mara_Data", 10, "ok", "20240101")
    sql = " ".join(conn.statements)
    for expected in expects:
        assert expected in sql


@pytest.mark.parametrize(
    "sink",
    [
        SQLServerSink(FakeEngine("mssql")),
        PostgreSQLSink(FakeEngine("postgresql")),
        MySQLSink(FakeEngine("mysql")),
        SQLiteSink(FakeEngine("sqlite")),
    ],
)
def test_finish_and_fail_execution_are_portable(sink):
    conn = sink.engine.tx.conn
    sink.finish_execution(conn, 7)
    sink.fail_execution(conn, 7, "boom")
    sql = " ".join(conn.statements)
    assert "status='finished'" in sql
    assert "status='failed'" in sql
    assert "end_time=" in sql
    assert "message=:msg" in sql
