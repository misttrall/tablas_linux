import json
import time

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

import cli
import etl_runner
from db.sinks import get_sink
from licensing import (
    License,
    LicenseBlocked,
    LicenseNotEntitled,
    LicenseState,
)

NOW = int(time.time())
DAY = 86400


class StubManager:
    def __init__(self, lic):
        self._lic = lic

    def get_license(self):
        return self._lic

    def require(self, module):
        st = self._lic.state(time.time())
        if st in (LicenseState.EXPIRED, LicenseState.SUSPENDED, LicenseState.REVOKED):
            raise LicenseBlocked(f"licencia {st.value}")
        if not self._lic.has(module):
            raise LicenseNotEntitled(f"módulo '{module}' no contratado")
        return self._lic

    def state(self):
        return self._lic.state(time.time())

    def force_activate(self):
        return self._lic

    def validate(self):
        return self._lic

    def clear_cache(self):
        pass

    def users_limit(self):
        return self._lic.limit("users")


def _license(**overrides):
    modules = {"derived": True, "dashboard": True, "bi": True}
    if "modules" in overrides:
        modules = overrides.pop("modules")
    base = dict(customer_id="e", license_id="l", status="active",
                valid_from=NOW - DAY, valid_until=NOW + DAY, offline_until=NOW + 8 * DAY,
                modules=modules, limits={"users": 5}, issued_at=NOW)
    base.update(overrides)
    return License(**base)


def _make_config(tmp_path, **license_kwargs):
    cfg_path = tmp_path / "config.json"
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(tmp_path / "db.sqlite")},
        "tables": [], "fields": {},
        "license": {"server": "http://lic.test", "customer_id": "e", "api_key": "k"},
    }
    if license_kwargs.get("derived"):
        cfg["derived"] = {"name": "inv_bodega"}
    cfg_path.write_text(json.dumps(cfg))
    return str(cfg_path)


def _patch_manager(monkeypatch, lic):
    import licensing.client
    monkeypatch.setattr(licensing.client, "get_manager", lambda config: StubManager(lic))


def test_report_requires_derived(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path, derived=True)
    _patch_manager(monkeypatch, _license(modules={"dashboard": True, "bi": True}))
    assert cli.cmd_reporte(cfg) == 1
    out = capsys.readouterr().out
    assert "derived" in out


def test_report_ok_with_derived(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path, derived=True)
    _patch_manager(monkeypatch, _license())
    import derived.views as dv
    monkeypatch.setattr(dv, "derived_views", lambda config: [])
    assert cli.cmd_reporte(cfg) == 0


def test_bi_requires_bi(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path)
    _patch_manager(monkeypatch, _license(modules={"derived": True, "dashboard": True}))
    assert cli.cmd_bi(cfg, "manifest") == 1
    out = capsys.readouterr().out
    assert "bi" in out


def test_bootstrap_with_derived_requires_derived(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path, derived=True)
    _patch_manager(monkeypatch, _license(modules={"dashboard": True, "bi": True}))
    monkeypatch.setattr(cli, "cmd_migrate", lambda config_path: 0)
    assert cli.cmd_bootstrap(cfg, with_derived=True, skip_sap=True) == 1
    out = capsys.readouterr().out
    assert "derived" in out


def test_users_add_blocks_at_limit(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path)
    _patch_manager(monkeypatch, _license(limits={"users": 1}))
    from dashboard.auth import users as auth_users
    monkeypatch.setattr(auth_users, "list_users", lambda: [{"id": 1}])
    args = type("A", (), {"config": cfg, "users_action": "add",
                          "username": "nuevo", "password": "x", "role": "user",
                          "root": False, "no_force_password_change": True})
    assert cli.cmd_users(args) == 1
    out = capsys.readouterr().out
    assert "límite" in out


def test_license_status_and_clear_cache(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path)
    _patch_manager(monkeypatch, _license())
    assert cli.cmd_license(cfg, "status") == 0
    out = capsys.readouterr().out
    assert "ACTIVE" in out
    assert cli.cmd_license(cfg, "clear-cache") == 0
    assert "caché" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# etl_runner derived-gating harness
# ---------------------------------------------------------------------------

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

    def connect(self):
        pass

    def close(self):
        pass

    def ping(self):
        return True

    def extract(self, table, fields, filters=None, batch_size=30000, max_wa_chars=None):
        return pd.DataFrame({f: [1, 2] for f in fields})


@pytest.fixture
def harness_factory(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with eng.begin() as conn:
        for stmt in CONTROL_SQL.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
        conn.execute(text("CREATE TABLE t_ok (id INTEGER PRIMARY KEY, name TEXT)"))
    sink = get_sink(eng)

    def no_lock():
        return None

    monkeypatch.setattr(etl_runner, "acquire_lock", no_lock)
    monkeypatch.setattr(etl_runner, "release_lock", no_lock)
    monkeypatch.setattr(etl_runner, "update_state", lambda **kw: None)
    monkeypatch.setattr(etl_runner, "get_engine", lambda config=None: eng)
    monkeypatch.setattr(etl_runner, "get_source", lambda sc: FakeConnector())
    monkeypatch.setenv("ETL_LIVE_FILE", str(tmp_path / "live.json"))
    return eng, sink, tmp_path, monkeypatch


def test_etl_runner_skips_derived_when_not_entitled(harness_factory, monkeypatch, capsys):
    eng, sink, tmp_path, m = harness_factory
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(tmp_path / "db.sqlite")},
        "tables": [{"source": "OK", "target": "t_ok", "keys": ["id"]}],
        "fields": {"OK": ["id", "name"]},
        "derived": {"name": "inv_bodega"},
    }
    m.setattr(etl_runner, "load_config", lambda path=None: cfg)
    _patch_manager(m, _license(modules={"dashboard": True, "bi": True}))

    import derived.materializer as dm
    called = {}

    def fake_run_deriveds(**kwargs):
        called["ran"] = True
        return []

    m.setattr(dm, "run_deriveds", fake_run_deriveds)

    etl_runner.run_etl_job()
    assert "ran" not in called
