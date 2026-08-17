"""Pruebas automatizadas para el asistente de onboarding y configuración SAP."""

import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
import pytest

import cli
from dashboard import app as dash_app
from dashboard.auth import engine as auth_engine, users as auth_users


@pytest.fixture
def onboarding_env(tmp_path, monkeypatch):
    db_path = tmp_path / "control.db"
    cfg_path = tmp_path / "config.json"
    cfg = {
        "environment": "qa",
        "source": {
            "type": "sap",
            "config": {
                "ashost": "192.168.1.50",
                "sysnr": "00",
                "client": "100",
                "user": "RFC_TEST",
                "passwd": "secretpassword",
                "lang": "ES",
            },
        },
        "database": {"dialect": "sqlite", "database": str(db_path)},
        "tables": [{"source": "MARA", "target": "Mara_Data", "keys": ["MATNR"]}],
        "fields": {},
    }
    cfg_path.write_text(json.dumps(cfg))
    assert cli.cmd_migrate(str(cfg_path)) == 0
    monkeypatch.setenv("ETL_CONFIG", str(cfg_path))
    monkeypatch.setenv("ETL_SECRET", "super-secret-onboarding-key-32-chars-long!")
    monkeypatch.setattr(auth_engine, "_ENGINE_PROVIDER", dash_app.get_engine)

    auth_users.create_user("admin", "adminpass", role="admin", is_root=True, must_change_password=False)
    auth_users.create_user("operator", "userpass", role="user", is_root=False, must_change_password=False)
    return str(cfg_path)


def test_onboarding_status_rejects_regular_user(onboarding_env):
    client = TestClient(dash_app.app)
    login_res = client.post("/api/auth/login", json={"username": "operator", "password": "userpass"})
    assert login_res.status_code == 200

    res = client.get("/api/onboarding/status")
    assert res.status_code == 403


def test_onboarding_status_success(onboarding_env):
    client = TestClient(dash_app.app)
    client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})

    res = client.get("/api/onboarding/status")
    assert res.status_code == 200
    data = res.json()
    assert data["source_type"] == "sap"
    assert data["configured"] is True
    assert data["ashost"] == "192.168.1.50"
    assert data["user"] == "RFC_TEST"
    assert data["has_password"] is True
    # La contraseña NO debe venir en texto plano en la respuesta de status
    assert "passwd" not in data
    assert "password" not in data


def test_onboarding_test_sap_missing_fields(onboarding_env):
    client = TestClient(dash_app.app)
    client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})

    res = client.post("/api/onboarding/test-sap", json={"ashost": "", "user": "", "passwd": ""})
    assert res.status_code == 400


def test_onboarding_test_sap_mocked_success(onboarding_env):
    client = TestClient(dash_app.app)
    client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})

    mock_conn = MagicMock()
    mock_conn.ping.return_value = True

    with patch("sources.sap.connector.SAPConnector.connect", return_value=None), \
         patch("sources.sap.connector.SAPConnector.ping", return_value=True), \
         patch("sources.sap.connector.SAPConnector.close", return_value=None):
        res = client.post("/api/onboarding/test-sap", json={
            "ashost": "192.168.1.50",
            "sysnr": "00",
            "client": "100",
            "user": "RFC_TEST",
            "passwd": "secretpassword",
            "lang": "ES",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert "latency_ms" in data
        assert "Conexión exitosa" in data["message"]


def test_onboarding_save_sap_preserves_config(onboarding_env):
    client = TestClient(dash_app.app)
    client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})

    res = client.post("/api/onboarding/save-sap", json={
        "ashost": "sap.empresa.corp",
        "sysnr": "01",
        "client": "200",
        "user": "RFC_NEW",
        "passwd": "newpassword123",
        "lang": "EN",
    })
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # Verificar que config.json se actualizó pero preservó tables y license intactos
    with open(onboarding_env, "r", encoding="utf-8") as fh:
        saved_cfg = json.load(fh)

    assert saved_cfg["source"]["config"]["ashost"] == "sap.empresa.corp"
    assert saved_cfg["source"]["config"]["sysnr"] == "01"
    assert saved_cfg["source"]["config"]["client"] == "200"
    assert saved_cfg["source"]["config"]["user"] == "RFC_NEW"
    assert saved_cfg["source"]["config"]["passwd"] == "newpassword123"
    assert saved_cfg["source"]["config"]["lang"] == "EN"

    # Tablas preservadas
    assert len(saved_cfg["tables"]) == 1
    assert saved_cfg["tables"][0]["source"] == "MARA"
