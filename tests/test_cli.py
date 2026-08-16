import json
import os

import pytest
from sqlalchemy import create_engine, text

import cli


@pytest.fixture
def cli_env(tmp_path):
    db_path = tmp_path / "db.sqlite"
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(db_path)},
        "tables": [{"source": "A", "target": "t_a", "keys": ["id"]}],
        "fields": {"A": ["id", "name"]},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    return str(cfg_path), str(db_path)


def test_migrate_applies_and_is_idempotent(cli_env, capsys):
    cfg_path, db_path = cli_env

    assert cli.cmd_migrate(cfg_path) == 0
    out1 = capsys.readouterr().out
    assert "[ok]" in out1
    assert "Migraciones aplicadas: 4" in out1

    eng = create_engine(f"sqlite:///{db_path}")
    with eng.connect() as conn:
        tables = {r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert {"etl_execution", "etl_progress", "etl_execution_tables",
                "app_users", "schema_migrations"} <= tables
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(etl_progress)"))]
        assert "last_delta_value" in cols
        versions = [r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))]
        assert len(versions) == 4

    capsys.readouterr()
    assert cli.cmd_migrate(cfg_path) == 0
    out2 = capsys.readouterr().out
    assert "[skip]" in out2
    assert "Migraciones aplicadas: 0" in out2


def test_status_prints_runs_and_progress(cli_env, capsys):
    cfg_path, db_path = cli_env
    cli.cmd_migrate(cfg_path)
    capsys.readouterr()

    eng = create_engine(f"sqlite:///{db_path}")
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO etl_execution (status, start_time) VALUES ('finished', '2026-01-01 00:00:00')"))
        conn.execute(text(
            "INSERT INTO etl_progress (table_name, status, rows_loaded) "
            "VALUES ('t_a', 'ok', 5)"))

    assert cli.cmd_status(cfg_path) == 0
    out = capsys.readouterr().out
    assert "finished" in out
    assert "t_a" in out
    assert "ok" in out


def test_status_reports_missing_tables(cli_env, capsys):
    cfg_path, db_path = cli_env
    # sin migraciones aplicadas
    assert cli.cmd_status(cfg_path) == 1
    out = capsys.readouterr().out
    assert "etl_execution" in out


def test_main_run_with_tables_passthrough(cli_env, monkeypatch, capsys):
    cfg_path, db_path = cli_env
    captured = {}

    def fake_run(config_path=None, tables=None):
        captured["config_path"] = config_path
        captured["tables"] = tables
        return 0

    monkeypatch.setattr(cli, "cmd_run", fake_run)

    assert cli.main(["run", "--tables", "A,t_a", "--config", cfg_path]) == 0
    assert captured == {"config_path": cfg_path, "tables": ["A", "t_a"]}


def test_main_no_command_prints_help(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "usage:" in out


def _cli_bi_env(tmp_path):
    cfg_path = tmp_path / "config.json"
    db_path = tmp_path / "db.sqlite"
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(db_path)},
        "tables": [], "fields": {},
        "derived": [{"name": "inv_bodega", "keys": ["MATNR"]}],
    }
    cfg_path.write_text(json.dumps(cfg))
    engine = create_engine(f"sqlite:///{db_path}")
    import pandas as pd
    pd.DataFrame([{"MATNR": "M1", "ValorTotal": 1.0}]).to_sql("inv_bodega", engine, index=False)
    return str(cfg_path)


def test_cli_bi_manifest(tmp_path, capsys):
    cfg_path = _cli_bi_env(tmp_path)
    assert cli.cmd_bi(cfg_path, "manifest") == 0
    out = capsys.readouterr().out
    assert '"inv_bodega"' in out
    assert '"materialized": true' in out


def test_cli_bi_export(tmp_path, capsys):
    cfg_path = _cli_bi_env(tmp_path)
    out_dir = str(tmp_path / "bi_out")
    assert cli.cmd_bi(cfg_path, "export", out_dir=out_dir) == 0
    out = capsys.readouterr().out
    assert "inv_bodega" in out
    assert os.path.exists(os.path.join(out_dir, "inv_bodega.csv"))


def test_cli_bi_guide(tmp_path, capsys):
    cfg_path = _cli_bi_env(tmp_path)
    assert cli.cmd_bi(cfg_path, "guide") == 0
    out = capsys.readouterr().out
    assert "Guía de conectividad" in out
    assert "inv_bodega" in out


def test_cli_main_bi(tmp_path, monkeypatch):
    cfg_path = _cli_bi_env(tmp_path)
    captured = {}

    def fake_bi(config_path, action, out_dir="output/bi"):
        captured["config_path"] = config_path
        captured["action"] = action
        captured["out_dir"] = out_dir
        return 0

    monkeypatch.setattr(cli, "cmd_bi", fake_bi)
    assert cli.main(["bi", "manifest", "--config", cfg_path]) == 0
    assert captured == {"config_path": cfg_path, "action": "manifest", "out_dir": "output/bi"}
