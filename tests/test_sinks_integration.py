import os

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from db.sinks import get_sink

FIELDS = ["id", "name", "qty"]

DIALECTS = ["postgresql", "mysql", "sqlite"]


def _url(dialect, tmp_path):
    if dialect == "postgresql":
        return os.environ.get("ETL_TEST_PG_URL")
    if dialect == "mysql":
        return os.environ.get("ETL_TEST_MYSQL_URL")
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture(params=DIALECTS)
def env(request, tmp_path):
    dialect = request.param
    url = _url(dialect, tmp_path)
    if url is None:
        pytest.skip(f"URL de prueba no configurada para {dialect}")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS target"))
        conn.execute(text("DROP TABLE IF EXISTS stg_target"))
        if dialect == "mysql":
            conn.execute(text("CREATE TABLE target (id INT PRIMARY KEY, name VARCHAR(255), qty INT) ENGINE=InnoDB"))
        else:
            conn.execute(text("CREATE TABLE target (id INTEGER PRIMARY KEY, name TEXT, qty INTEGER)"))
    return engine


@pytest.fixture
def sink(env):
    return get_sink(env)


def test_integration_load_creates_staging(sink, env):
    df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"], "qty": [10, 20]})
    assert sink.load(df, "stg_target") == 2
    with env.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM stg_target")).scalar() == 2


def test_integration_load_replaces_content(sink, env):
    sink.load(pd.DataFrame({"id": [1, 2], "name": ["a", "b"], "qty": [10, 20]}), "stg_target")
    sink.load(pd.DataFrame({"id": [3], "name": ["c"], "qty": [30]}), "stg_target")
    with env.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM stg_target")).scalar() == 1


def test_integration_load_converts_empty_strings_to_null(sink, env):
    sink.load(pd.DataFrame({"id": [1], "name": [""], "qty": [5]}), "stg_target")
    with env.connect() as conn:
        assert conn.execute(text("SELECT name FROM stg_target")).scalar() is None


def test_integration_merge_inserts_and_updates(sink, env):
    sink.load(pd.DataFrame({"id": [1, 2], "name": ["a", "b"], "qty": [10, 20]}), "stg_target")
    sink.merge("target", "stg_target", ["id"], FIELDS)

    sink.load(pd.DataFrame({"id": [1, 3], "name": ["a2", "c"], "qty": [99, 30]}), "stg_target")
    sink.merge("target", "stg_target", ["id"], FIELDS)

    with env.connect() as conn:
        rows = conn.execute(text("SELECT id, name, qty FROM target ORDER BY id")).fetchall()
    assert rows == [(1, "a2", 99), (2, "b", 20), (3, "c", 30)]


def test_integration_merge_dedupes_staging(sink, env):
    df = pd.DataFrame({"id": [1, 1], "name": ["first", "second"], "qty": [1, 2]})
    sink.load(df, "stg_target")
    sink.merge("target", "stg_target", ["id"], FIELDS)
    with env.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM target")).scalar() == 1


def test_integration_merge_cleans_staging(sink, env):
    sink.load(pd.DataFrame({"id": [1], "name": ["a"], "qty": [1]}), "stg_target")
    sink.merge("target", "stg_target", ["id"], FIELDS)
    with env.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM stg_target")).scalar() == 0
