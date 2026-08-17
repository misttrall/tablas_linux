import os

import pytest
from sqlalchemy import create_engine, text

from license_server import cli as server_cli
from license_server import db as license_db


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVUS_LICENSE_DB", str(tmp_path / "server.db"))
    engine = server_cli._engine()
    license_db.init_db(engine)
    return tmp_path


def test_keygen_writes_keys(env, tmp_path):
    server_cli._PRIVATE_KEY_PATH = str(tmp_path / "private_key.pem")
    server_cli._PUBLIC_KEY_PATH = str(tmp_path / "novus_public.pem")
    assert server_cli.cmd_keygen() == 0
    assert (tmp_path / "private_key.pem").exists()
    assert (tmp_path / "novus_public.pem").exists()


def test_customer_add_and_list(env, capsys):
    assert server_cli.cmd_customer_add(
        type("A", (), {"id": "empresa_001", "name": "Mi Empresa", "api_key": "clave-1"})) == 0
    assert server_cli.cmd_customer_list(None) == 0
    out = capsys.readouterr().out
    assert "empresa_001" in out


def test_customer_disable(env):
    server_cli.cmd_customer_add(
        type("A", (), {"id": "empresa_001", "name": "Mi Empresa", "api_key": "clave-1"}))
    server_cli.cmd_customer_disable(
        type("A", (), {"id": "empresa_001"}))
    assert license_db.get_customer(server_cli._engine(), "empresa_001").status == "disabled"


def test_license_issue_show_renew(env, capsys):
    server_cli.cmd_customer_add(
        type("A", (), {"id": "empresa_001", "name": "Mi Empresa", "api_key": "clave-1"}))
    args = type("A", (), {
        "customer": "empresa_001", "license_id": "NOVUS-001",
        "valid_from": "2026-08-01", "valid_until": "2026-08-31", "grace_days": 7,
        "modules": ["derived", "dashboard"], "limit": ["users=5"],
    })
    assert server_cli.cmd_license_issue(args) == 0
    assert server_cli.cmd_license_show(
        type("A", (), {"license_id": "NOVUS-001"})) == 0
    out = capsys.readouterr().out
    assert "NOVUS-001" in out
    assert "derived" in out
    assert "users" in out

    server_cli.cmd_license_renew(
        type("A", (), {"license_id": "NOVUS-001", "valid_from": None,
                       "valid_until": "2026-09-30", "grace_days": 7}))
    lic = license_db.get_license_by_id(server_cli._engine(), "NOVUS-001")
    assert lic["valid_until"] > 0


def test_license_suspend_and_revoke(env):
    server_cli.cmd_customer_add(
        type("A", (), {"id": "empresa_001", "name": "Mi Empresa", "api_key": "clave-1"}))
    server_cli.cmd_license_issue(
        type("A", (), {"customer": "empresa_001", "license_id": "NOVUS-001",
                       "valid_from": "2026-08-01", "valid_until": "2026-08-31",
                       "grace_days": 7, "modules": [], "limit": []}))
    server_cli.cmd_license_suspend(type("A", (), {"license_id": "NOVUS-001"}))
    assert license_db.get_license_by_id(server_cli._engine(), "NOVUS-001")["status"] == "suspended"
    server_cli.cmd_license_revoke(type("A", (), {"license_id": "NOVUS-001"}))
    assert license_db.get_license_by_id(server_cli._engine(), "NOVUS-001")["status"] == "revoked"


def test_main_dispatch(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NOVUS_LICENSE_DB", str(tmp_path / "server.db"))
    assert server_cli.main(["customer", "list"]) == 0
    assert server_cli.main(["license", "list"]) == 0
