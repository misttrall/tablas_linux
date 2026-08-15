import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from db.sinks import get_sink

FIELDS = ["id", "name", "qty"]


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE target (id INTEGER PRIMARY KEY, name TEXT, qty INTEGER)"))
    return eng


@pytest.fixture
def sink(engine):
    return get_sink(engine)


def test_load_creates_staging_when_missing(sink, engine):
    df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"], "qty": [10, 20]})
    assert sink.load(df, "stg_x") == 2
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM stg_x")).scalar() == 2


def test_load_replaces_content(sink, engine):
    sink.load(pd.DataFrame({"id": [1, 2], "name": ["a", "b"], "qty": [10, 20]}), "stg_x")
    sink.load(pd.DataFrame({"id": [3], "name": ["c"], "qty": [30]}), "stg_x")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM stg_x")).scalar() == 1


def test_load_converts_empty_strings_to_null(sink, engine):
    sink.load(pd.DataFrame({"id": [1], "name": [""], "qty": [5]}), "stg_x")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM stg_x")).scalar() is None


def test_merge_inserts_and_updates(sink, engine):
    sink.load(pd.DataFrame({"id": [1, 2], "name": ["a", "b"], "qty": [10, 20]}), "stg_x")
    sink.merge("target", "stg_x", ["id"], FIELDS)

    sink.load(pd.DataFrame({"id": [1, 3], "name": ["a2", "c"], "qty": [99, 30]}), "stg_x")
    sink.merge("target", "stg_x", ["id"], FIELDS)

    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, name, qty FROM target ORDER BY id")).fetchall()
    assert rows == [(1, "a2", 99), (2, "b", 20), (3, "c", 30)]


def test_merge_dedupes_staging(sink, engine):
    df = pd.DataFrame({"id": [1, 1], "name": ["first", "second"], "qty": [1, 2]})
    sink.load(df, "stg_x")
    sink.merge("target", "stg_x", ["id"], FIELDS)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM target")).scalar() == 1


def test_merge_cleans_staging(sink, engine):
    sink.load(pd.DataFrame({"id": [1], "name": ["a"], "qty": [1]}), "stg_x")
    sink.merge("target", "stg_x", ["id"], FIELDS)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM stg_x")).scalar() == 0
