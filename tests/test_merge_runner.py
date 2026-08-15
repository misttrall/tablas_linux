import pandas as pd
from sqlalchemy import create_engine, text

from db.merge_runner import run_merges
from db.sinks import get_sink
from db.staging_loader import load_staging


def test_run_merges_only_merges_selected_tables(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'merge.db'}")
    sink = get_sink(eng)
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE t1 (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("CREATE TABLE t2 (id INTEGER PRIMARY KEY, name TEXT)"))

    load_staging(pd.DataFrame({"id": [1], "name": ["a"]}), "t1", eng, sink)
    load_staging(pd.DataFrame({"id": [2], "name": ["b"]}), "t2", eng, sink)

    config = {
        "tables": [
            {"source": "S1", "target": "t1", "keys": ["id"]},
            {"source": "S2", "target": "t2", "keys": ["id"]},
        ],
        "fields": {"S1": ["id", "name"], "S2": ["id", "name"]},
    }

    run_merges(engine=eng, sink=sink, tables=[config["tables"][0]], config=config)

    with eng.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM t1")).scalar() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM t2")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM stg_t2")).scalar() == 1
