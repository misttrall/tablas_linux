import pandas as pd
import pytest
from sqlalchemy import create_engine, text

import etl_runner
from db.sinks import get_sink

CONTROL_SQL = """
CREATE TABLE etl_execution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_time TEXT NULL,
    status TEXT NOT NULL,
    message TEXT NULL
);
CREATE TABLE etl_progress (
    table_name TEXT PRIMARY KEY,
    rows_loaded INTEGER NULL,
    status TEXT NULL,
    updated_at TEXT NULL DEFAULT CURRENT_TIMESTAMP,
    last_delta_value VARCHAR(40) NULL
);
CREATE TABLE etl_execution_tables (
    run_id INTEGER NOT NULL,
    table_name TEXT NOT NULL,
    chunks_total INTEGER NULL,
    chunks_ok INTEGER NULL,
    rows_extracted INTEGER NULL,
    duration_s REAL NULL,
    status TEXT NULL,
    PRIMARY KEY (run_id, table_name)
);
"""


class FakeConnector:
    type = "csv"

    def __init__(self, config):
        self.config = config
        self.extract_filters = []

    def connect(self):
        pass

    def close(self):
        pass

    def ping(self):
        return True

    def extract(self, table, fields, filters=None, batch_size=30000, max_wa_chars=None):
        self.extract_filters.append(filters)
        if table == "BAD":
            raise RuntimeError(f"tabla {table} falla")
        df = pd.DataFrame({f: [1, 2] for f in fields})
        if "LAEDA" in fields:
            df["LAEDA"] = ["20240102", "20240103"]
        return df


def make_config(tmp_path, tables):
    return {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(tmp_path / "db.sqlite")},
        "tables": tables,
        "fields": {t["source"]: ["id", "name"] for t in tables},
    }


@pytest.fixture
def harness(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with eng.begin() as conn:
        for stmt in CONTROL_SQL.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
        conn.execute(text("CREATE TABLE t_ok (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("CREATE TABLE t_bad (id INTEGER PRIMARY KEY, name TEXT)"))

    sink = get_sink(eng)

    def no_lock():
        return None

    monkeypatch.setattr(etl_runner, "acquire_lock", no_lock)
    monkeypatch.setattr(etl_runner, "release_lock", no_lock)
    monkeypatch.setattr(etl_runner, "update_state", lambda **kw: None)
    monkeypatch.setattr(etl_runner, "get_engine", lambda config=None: eng)
    monkeypatch.setattr(etl_runner, "get_source", lambda sc: FakeConnector(sc["config"]))
    monkeypatch.setenv("ETL_LIVE_FILE", str(tmp_path / "live.json"))

    return eng, sink, tmp_path, monkeypatch


def test_runner_isolates_failing_table_and_marks_failed(harness):
    eng, sink, tmp_path, monkeypatch = harness
    cfg = make_config(tmp_path, [
        {"source": "OK", "target": "t_ok", "keys": ["id"]},
        {"source": "BAD", "target": "t_bad", "keys": ["id"]},
    ])
    monkeypatch.setattr(etl_runner, "load_config", lambda path=None: cfg)

    with pytest.raises(RuntimeError):
        etl_runner.run_etl_job()

    with eng.connect() as conn:
        run = conn.execute(text("SELECT status, message FROM etl_execution ORDER BY id DESC LIMIT 1")).first()
        assert run.status == "failed"
        assert "BAD" in run.message
        ok_prog = conn.execute(text("SELECT rows_loaded, status FROM etl_progress WHERE table_name='t_ok'")).first()
        bad_prog = conn.execute(text("SELECT rows_loaded, status FROM etl_progress WHERE table_name='t_bad'")).first()
        assert ok_prog == (2, "ok")
        assert bad_prog == (None, "failed")
        assert conn.execute(text("SELECT COUNT(*) FROM t_ok")).scalar() == 2
        assert conn.execute(text("SELECT COUNT(*) FROM t_bad")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM stg_t_ok")).scalar() == 0


def test_runner_success_marks_finished(harness):
    eng, sink, tmp_path, monkeypatch = harness
    cfg = make_config(tmp_path, [
        {"source": "OK", "target": "t_ok", "keys": ["id"]},
    ])
    monkeypatch.setattr(etl_runner, "load_config", lambda path=None: cfg)

    etl_runner.run_etl_job()

    with eng.connect() as conn:
        run = conn.execute(text("SELECT status FROM etl_execution ORDER BY id DESC LIMIT 1")).first()
        assert run.status == "finished"
        prog = conn.execute(text("SELECT rows_loaded, status FROM etl_progress WHERE table_name='t_ok'")).first()
        assert prog == (2, "ok")


def test_runner_skips_merge_for_failed_table_staging(harness):
    eng, sink, tmp_path, monkeypatch = harness
    cfg = make_config(tmp_path, [
        {"source": "OK", "target": "t_ok", "keys": ["id"]},
        {"source": "BAD", "target": "t_bad", "keys": ["id"]},
    ])
    monkeypatch.setattr(etl_runner, "load_config", lambda path=None: cfg)

    with pytest.raises(RuntimeError):
        etl_runner.run_etl_job()

    with eng.connect() as conn:
        stg = [r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'stg_%'")
        ).fetchall()]
        assert "stg_t_bad" not in stg
        assert conn.execute(text("SELECT COUNT(*) FROM stg_t_ok")).scalar() == 0


def test_runner_delta_incremental_applies_filter_on_second_run(harness):
    eng, sink, tmp_path, monkeypatch = harness

    with eng.begin() as conn:
        conn.execute(text("DROP TABLE t_ok"))
        conn.execute(text("CREATE TABLE t_ok (id INTEGER PRIMARY KEY, name TEXT, LAEDA VARCHAR(40))"))

    connectors = []

    def make_conn(sc):
        c = FakeConnector(sc["config"])
        connectors.append(c)
        return c

    monkeypatch.setattr(etl_runner, "get_source", make_conn)

    cfg = make_config(tmp_path, [
        {"source": "DELTA", "target": "t_ok", "keys": ["id"], "incremental": {"field": "LAEDA"}},
    ])
    cfg["fields"]["DELTA"] = ["id", "name", "LAEDA"]
    monkeypatch.setattr(etl_runner, "load_config", lambda path=None: cfg)

    etl_runner.run_etl_job()
    etl_runner.run_etl_job()

    assert connectors[0].extract_filters == [None]
    assert connectors[1].extract_filters == [["LAEDA >= '20240103'"]]

    with eng.connect() as conn:
        delta = conn.execute(
            text("SELECT last_delta_value FROM etl_progress WHERE table_name='t_ok'")
        ).scalar()
        assert delta == "20240103"
        assert conn.execute(text("SELECT COUNT(*) FROM t_ok")).scalar() == 2


def test_runner_range_load_extracts_by_chunks(harness):
    eng, sink, tmp_path, monkeypatch = harness
    connectors = []

    class RangeConnector:
        type = "csv"

        def __init__(self, config):
            self.config = config
            self.extract_filters = []
            self._call = 0

        def connect(self):
            pass

        def close(self):
            pass

        def extract(self, table, fields, filters=None, batch_size=30000, max_wa_chars=None):
            self.extract_filters.append(filters)
            base = self._call * 100
            self._call += 1
            return pd.DataFrame({f: [base + 1, base + 2] for f in fields})

    def make_conn(sc):
        c = RangeConnector(sc["config"])
        connectors.append(c)
        return c

    monkeypatch.setattr(etl_runner, "get_source", make_conn)

    cfg = make_config(tmp_path, [
        {"source": "RANGE", "target": "t_ok", "keys": ["id"],
         "load_mode": "range", "range": {"prefixes": ["A"]}},
    ])
    monkeypatch.setattr(etl_runner, "load_config", lambda path=None: cfg)

    etl_runner.run_etl_job()

    calls = connectors[0].extract_filters
    sentinel = "~" * 18
    assert len(calls) == 2
    assert calls[0] == ["MATNR < 'A'"]
    assert calls[1] == [f"MATNR >= 'A' AND MATNR < '{sentinel}'"]

    with eng.connect() as conn:
        prog = conn.execute(text("SELECT rows_loaded, status FROM etl_progress WHERE table_name='t_ok'")).first()
        assert prog == (4, "ok")
        assert conn.execute(text("SELECT COUNT(*) FROM t_ok")).scalar() == 4


def test_runner_tables_filter_processes_only_selected(harness):
    eng, sink, tmp_path, monkeypatch = harness
    connectors = []

    def make_conn(sc):
        c = FakeConnector(sc["config"])
        connectors.append(c)
        return c

    monkeypatch.setattr(etl_runner, "get_source", make_conn)

    cfg = make_config(tmp_path, [
        {"source": "A", "target": "t_ok", "keys": ["id"]},
        {"source": "B", "target": "t_bad", "keys": ["id"]},
    ])
    monkeypatch.setattr(etl_runner, "load_config", lambda path=None: cfg)

    etl_runner.run_etl_job(tables=["A"])

    processed = [c for c in connectors]
    assert len(processed) == 1
    with eng.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM t_ok")).scalar() == 2
        assert conn.execute(text("SELECT COUNT(*) FROM t_bad")).scalar() == 0
        prog = conn.execute(text("SELECT table_name FROM etl_progress")).fetchall()
        assert [p[0] for p in prog] == ["t_ok"]


def test_runner_tables_filter_unknown_raises(harness):
    eng, sink, tmp_path, monkeypatch = harness
    cfg = make_config(tmp_path, [
        {"source": "A", "target": "t_ok", "keys": ["id"]},
    ])
    monkeypatch.setattr(etl_runner, "load_config", lambda path=None: cfg)

    with pytest.raises(ValueError, match="Tablas no encontradas"):
        etl_runner.run_etl_job(tables=["NOSEXISTE"])
