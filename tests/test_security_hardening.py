"""Pruebas automatizadas de hardening de seguridad y mitigación de brechas."""

import json
import warnings
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine

import cli
from dashboard import app as dash_app
from dashboard.auth import engine as auth_engine, security as auth_security, users as auth_users
from dashboard.auth.router import login_limiter
from license_server import app as license_server_app, db as license_server_db


@pytest.fixture
def sec_env(tmp_path, monkeypatch):
    db_path = tmp_path / "control.db"
    cfg_path = tmp_path / "config.json"
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(db_path)},
        "tables": [],
        "fields": {},
    }
    cfg_path.write_text(json.dumps(cfg))
    assert cli.cmd_migrate(str(cfg_path)) == 0
    monkeypatch.setenv("ETL_CONFIG", str(cfg_path))
    monkeypatch.setenv("ETL_SECRET", "super-secret-security-hardening-key-32-chars!")
    monkeypatch.setattr(auth_engine, "_ENGINE_PROVIDER", dash_app.get_engine)
    login_limiter.reset()
    return str(cfg_path)


def test_security_headers_dashboard(sec_env):
    client = TestClient(dash_app.app)
    res = client.get("/login")
    assert res.status_code == 200
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in res.headers
    assert "frame-ancestors 'none'" in res.headers["Content-Security-Policy"]


def test_security_headers_license_server(tmp_path):
    priv = ed25519.Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'lic.db'}")
    license_server_db.init_db(engine)
    app = license_server_app.create_app(engine, pem, "pepper")
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("X-Content-Type-Options") == "nosniff"


def test_etl_trigger_rejects_regular_user(sec_env):
    auth_users.create_user("operator", "pass12345", role="user", is_root=False, must_change_password=False)
    client = TestClient(dash_app.app)
    login_res = client.post("/api/auth/login", json={"username": "operator", "password": "pass12345"})
    assert login_res.status_code == 200

    # Usuario con rol "user" intenta disparar sincronización ETL
    res = client.post("/api/etl/trigger")
    assert res.status_code == 403
    assert res.json()["detail"] == "forbidden"


def test_login_rate_limiting(sec_env):
    client = TestClient(dash_app.app)
    login_limiter.reset()

    # Ejecutar 10 intentos fallidos
    for i in range(10):
        res = client.post("/api/auth/login", json={"username": "fake_user", "password": "wrong_password"})
        assert res.status_code == 401

    # El intento 11 debe ser bloqueado por Rate Limiting con 429
    res = client.post("/api/auth/login", json={"username": "fake_user", "password": "wrong_password"})
    assert res.status_code == 429
    assert res.json()["detail"] == "demasiados_intentos"
    assert "Retry-After" in res.headers

    # Reset desbloquea nuevamente
    login_limiter.reset()
    res = client.post("/api/auth/login", json={"username": "fake_user", "password": "wrong_password"})
    assert res.status_code == 401


def test_license_server_activate_rate_limiting(tmp_path):
    priv = ed25519.Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'lic2.db'}")
    license_server_db.init_db(engine)
    app = license_server_app.create_app(engine, pem, "pepper")
    client = TestClient(app)

    for i in range(30):
        res = client.post("/api/activate", json={"customer_id": "cust", "api_key": "bad"})
        assert res.status_code == 401

    res = client.post("/api/activate", json={"customer_id": "cust", "api_key": "bad"})
    assert res.status_code == 429
    assert res.json()["error"] == "demasiados_intentos"


def test_etl_secret_warning_on_short_key(monkeypatch):
    monkeypatch.setenv("ETL_SECRET", "short-key")
    with pytest.warns(UserWarning, match="tiene menos de 32 caracteres"):
        secret = auth_security.get_secret()
        assert secret == "short-key"


def test_docs_enabled_behavior(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "prd")
    monkeypatch.delenv("ETL_DOCS_ENABLED", raising=False)
    assert dash_app._docs_enabled() is False

    monkeypatch.setenv("ENVIRONMENT", "dev")
    assert dash_app._docs_enabled() is True

    monkeypatch.setenv("ENVIRONMENT", "prd")
    monkeypatch.setenv("ETL_DOCS_ENABLED", "1")
    assert dash_app._docs_enabled() is True
