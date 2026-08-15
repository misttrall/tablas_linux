import pandas as pd
import pytest
from sqlalchemy import create_engine, text

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
)
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
"""


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'control.db'}")
    with eng.begin() as conn:
        for stmt in CONTROL_SQL.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    return eng


@pytest.fixture
def sink(engine):
    return get_sink(engine)


def test_start_run_returns_id_and_inserts(engine, sink):
    run_id = start_run(engine, sink, "sap")
    assert run_id == 1
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status FROM etl_execution WHERE id=:id"), {"id": run_id}
        ).first()
        assert row.status == "running"


def test_start_run_blocks_second_active(engine, sink):
    start_run(engine, sink, "sap")
    with pytest.raises(EtlAlreadyRunning):
        start_run(engine, sink, "sap")


def test_finish_run(engine, sink):
    run_id = start_run(engine, sink, "sap")
    finish_run(engine, sink, run_id)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, end_time FROM etl_execution WHERE id=:id"), {"id": run_id}
        ).first()
        assert row.status == "finished"
        assert row.end_time is not None


def test_fail_run(engine, sink):
    run_id = start_run(engine, sink, "sap")
    fail_run(engine, sink, run_id, "boom")
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, message FROM etl_execution WHERE id=:id"), {"id": run_id}
        ).first()
        assert row.status == "failed"
        assert row.message == "boom"


def test_stale_run_is_replaced_as_orphan(engine, sink):
    run_id = start_run(engine, sink, "sap")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE etl_execution SET start_time = datetime('now', '-120 minutes') WHERE id=:id"),
            {"id": run_id},
        )
    new_id = start_run(engine, sink, "sap")
    assert new_id == run_id + 1
    with engine.connect() as conn:
        old = conn.execute(
            text("SELECT status, message FROM etl_execution WHERE id=:id"), {"id": run_id}
        ).first()
        new = conn.execute(
            text("SELECT status FROM etl_execution WHERE id=:id"), {"id": new_id}
        ).first()
        assert old.status == "failed"
        assert "huérfano" in old.message
        assert new.status == "running"


def test_upsert_progress_insert_and_update(engine, sink):
    mark_table_ok(engine, sink, "Mara_Data", 10, "20240101")
    mark_table_ok(engine, sink, "Mara_Data", 5, "20240102")
    p = get_table_progress(engine, sink, "Mara_Data")
    assert p["rows_loaded"] == 5
    assert p["last_delta_value"] == "20240102"
    assert p["status"] == "ok"
    assert get_table_progress(engine, sink, "Otro") is None


def test_mark_table_failed(engine, sink):
    mark_table_ok(engine, sink, "T001L_Data", 450, None)
    mark_table_failed(engine, sink, "T001L_Data")
    p = get_table_progress(engine, sink, "T001L_Data")
    assert p["status"] == "failed"
    assert p["rows_loaded"] is None


def test_build_delta_filters():
    t = {"source": "MARA", "filters": ["MATNR = 'X'"], "incremental": {"field": "LAEDA"}}
    assert build_delta_filters(t, "20240101") == ["MATNR = 'X'", "LAEDA >= '20240101'"]
    assert build_delta_filters(t, None) == ["MATNR = 'X'"]
    assert build_delta_filters({"source": "MARA"}, "20240101") is None
    assert build_delta_filters({"source": "MARA", "incremental": {"field": "LAEDA"}}, None) is None


def test_update_last_delta():
    df = pd.DataFrame({"MATNR": ["1", "2"], "LAEDA": ["20240101", "20240103"]})
    assert update_last_delta(df, {"incremental": {"field": "LAEDA"}}) == "20240103"
    assert update_last_delta(df, {}) is None
    assert update_last_delta(pd.DataFrame({"MATNR": []}), {"incremental": {"field": "LAEDA"}}) is None
    assert update_last_delta(df, {"incremental": {"field": "NOPE"}}) is None
