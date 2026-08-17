"""Suite de pruebas E2E del Simulador y Entorno de Licenciamiento Novus.

Valida de punta a punta:
- Los 12 escenarios de licenciamiento (E01 a E12).
- Gating de endpoints FastAPI (Dashboard, Inventario, Panel de Usuarios, Licencia).
- Gating de comandos CLI (status, validate, reporte, bi, users add).
- Tolerancia a desconexión, períodos de gracia y rechazo de adulteración criptográfica.
"""

import json
import os
import sys
import time
from pathlib import Path

# Garantizar resolución del paquete raíz y scripts
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

import cli
import dashboard.app as dash_app
from dashboard.auth import engine as auth_engine
from dashboard.auth import users as auth_users
from licensing.cache import cache_path, save_cache
from licensing.client import (
    LicenseError,
    LicenseBlocked,
    LicenseInvalid,
    LicenseNotEntitled,
    LicenseUnreachable,
    get_manager,
    LicenseManager,
)
from licensing.models import LicenseState
from licensing.validator import verify_token
from license_server.signing import sign_claims
from scripts.simulate_licensing import (
    SCENARIOS,
    build_scenario_token,
    evaluate_scenario,
    inject_scenario_cache,
    generate_ephemeral_keypair,
)
from utils.config_loader import load_config

DAY = 86400


@pytest.fixture(scope="module")
def keypair():
    """Genera par de claves Ed25519 para las pruebas E2E."""
    return generate_ephemeral_keypair()


@pytest.fixture
def sandbox_env(tmp_path, keypair):
    """Crea un entorno sandbox completo con BD SQLite, CSVs y config.json."""
    priv_pem, pub_pem = keypair
    priv_file = tmp_path / "private_key.pem"
    pub_file = tmp_path / "novus_public.pem"
    cache_file = tmp_path / "license_cache.json"
    db_file = tmp_path / "sandbox.db"
    csv_dir = tmp_path / "csv"
    out_dir = tmp_path / "output"
    csv_dir.mkdir()
    out_dir.mkdir()

    priv_file.write_bytes(priv_pem)
    pub_file.write_bytes(pub_pem)

    # Crear tablas sintéticas CSV
    (csv_dir / "MARA.csv").write_text("MATNR,MTART,MATKL,XCHPF,MEINS\nMAT-1,ROH,RAW,X,UN\n")
    (csv_dir / "MARD.csv").write_text("MANDT,MATNR,WERKS,LGORT,LABST,LMINB\n100,MAT-1,P100,A001,10.0,2.0\n")
    (csv_dir / "MBEW.csv").write_text("MATNR,BWKEY,LBKUM,SALK3,VPRSV,STPRS,VERPR\nMAT-1,P100,10.0,1000.0,V,0.0,100.0\n")
    (csv_dir / "MAKT.csv").write_text("MANDT,MATNR,SPRAS,MAKTX,MAKTG\n100,MAT-1,ES,Material Test,MAT TEST\n")
    (csv_dir / "T001L.csv").write_text("WERKS,LGORT,LGOBE\nP100,A001,Bodega Central\n")

    cfg_dict = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(csv_dir)}},
        "database": {"dialect": "sqlite", "database": str(db_file)},
        "tables": [
            {"source": "MARA", "target": "Mara_Data", "keys": ["MATNR"]},
            {"source": "MARD", "target": "Mard_Data", "keys": ["MANDT", "MATNR", "WERKS", "LGORT"]},
            {"source": "MBEW", "target": "Mbew_Data", "keys": ["MATNR", "BWKEY"]},
            {"source": "MAKT", "target": "Makt_Data", "keys": ["MANDT", "MATNR", "SPRAS"]},
            {"source": "T001L", "target": "T001L_Data", "keys": ["WERKS", "LGORT"]},
        ],
        "fields": {
            "MARA": ["MATNR", "MTART", "MATKL", "XCHPF", "MEINS"],
            "MARD": ["MANDT", "MATNR", "WERKS", "LGORT", "LABST", "LMINB"],
            "MBEW": ["MATNR", "BWKEY", "LBKUM", "SALK3", "VPRSV", "STPRS", "VERPR"],
            "MAKT": ["MANDT", "MATNR", "SPRAS", "MAKTX", "MAKTG"],
            "T001L": ["WERKS", "LGORT", "LGOBE"],
        },
        "derived": {
            "name": "inv_bodega",
            "text_lang": "ES",
            "tab": "Inventario",
            "row_label": "MATNR",
            "dominio": {"filters": [{"field": "WERKS", "op": "eq", "value": "P100"}]},
            "precio": {"field": "VERPR"},
            "valor": {"field": "VERPR"},
            "keys": ["MATNR", "WERKS", "LGORT"],
            "inventory": {"filters": {"centro": "Centro", "almacen": "Almacen"}},
            "columns": [
                {"as": "MATNR", "source": "MATNR", "label": "Material"},
                {"as": "Descripcion", "source": "MAKTX", "label": "Descripción"},
                {"as": "Centro", "source": "WERKS", "label": "Centro"},
                {"as": "Almacen", "source": "LGORT", "label": "Almacén"},
                {"as": "StockLibre", "source": "LABST", "label": "Stock"},
                {"as": "ValorTotal", "compute": "LABST * VERPR", "label": "Valor"},
            ],
            "excel": {"path": str(out_dir / "inv.xlsx"), "sheet": "Stock", "alerts_sheet": "StockBajo"},
        },
        "license": {
            "server": "http://127.0.0.1:59999",  # Mock / offline
            "customer_id": "cust_sandbox",
            "api_key": "sandbox-key",
            "public_key": str(pub_file),
            "cache_path": str(cache_file),
            "refresh_minutes": 1440,
        },
    }

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg_dict, indent=2))

    # Inicializar BD y tablas de control + ETL
    cli.cmd_migrate(str(cfg_file))
    cli.cmd_run(str(cfg_file), tables=None)

    return {
        "tmp_path": tmp_path,
        "config_path": str(cfg_file),
        "priv_pem": priv_pem,
        "pub_pem": pub_pem,
        "cache_file": str(cache_file),
        "db_file": str(db_file),
    }


def _make_authed_client(sandbox_env, monkeypatch, username="admin_test", role="admin", is_root=True):
    """Crea usuario y loguea un TestClient de FastAPI."""
    cfg_path = sandbox_env["config_path"]
    monkeypatch.setenv("ETL_CONFIG", cfg_path)
    monkeypatch.setenv("ETL_SECRET", "test-secret-32-chars-long-e2e-ok!")
    monkeypatch.setattr(auth_engine, "_ENGINE_PROVIDER", dash_app.get_engine)

    # Crear usuario si no existe
    if auth_users.get_user_by_username(username) is None:
        auth_users.create_user(username, "testpass1234", role=role, is_root=is_root, must_change_password=False)

    client = TestClient(dash_app.app)
    res = client.post("/api/auth/login", json={"username": username, "password": "testpass1234"})
    assert res.status_code == 200, f"Login falló: {res.text}"
    return client


def test_scenario_matrix_all_12_scenarios(sandbox_env):
    """Ejecuta y verifica la matriz completa de los 12 escenarios de simulación."""
    tmp_path = sandbox_env["tmp_path"]
    priv_pem = sandbox_env["priv_pem"]
    pub_pem = sandbox_env["pub_pem"]

    for sc_id in sorted(SCENARIOS.keys()):
        res = evaluate_scenario(sc_id, priv_pem, pub_pem, tmp_path)
        assert res["passed"] is True, f"Fallo en escenario {sc_id}: {res['error']}"


def test_e01_active_full_fastapi_and_cli(sandbox_env, monkeypatch):
    """E01: Licencia completa activa habilita todos los endpoints y comandos."""
    cfg_path = sandbox_env["config_path"]
    priv_pem = sandbox_env["priv_pem"]
    inject_scenario_cache(cfg_path, "E01", priv_pem)

    client = _make_authed_client(sandbox_env, monkeypatch)

    res_lic = client.get("/api/license")
    assert res_lic.status_code == 200
    body = res_lic.json()
    assert body["state"] == "ACTIVE"
    assert body["modules"]["derived"] is True
    assert body["modules"]["dashboard"] is True
    assert body["limits"]["users"] == 10

    # Endpoints protegidos
    res_inv = client.get("/api/inventory")
    assert res_inv.status_code == 200

    # CLI
    assert cli.cmd_license(cfg_path, "status") == 0
    assert cli.cmd_license(cfg_path, "validate") == 0
    assert cli.cmd_bi(cfg_path, "manifest") == 0


def test_e02_modular_dashboard_only(sandbox_env, monkeypatch, capsys):
    """E02: Dashboard activo pero derived y bi restringidos."""
    cfg_path = sandbox_env["config_path"]
    priv_pem = sandbox_env["priv_pem"]
    inject_scenario_cache(cfg_path, "E02", priv_pem)

    client = _make_authed_client(sandbox_env, monkeypatch)

    res_lic = client.get("/api/license")
    assert res_lic.status_code == 200
    assert res_lic.json()["modules"]["derived"] is False
    assert res_lic.json()["modules"]["dashboard"] is True

    # CLI BI y Reporte deben fallar por falta de módulo
    assert cli.cmd_bi(cfg_path, "manifest") == 1
    out_bi = capsys.readouterr().out
    assert "bi" in out_bi

    assert cli.cmd_reporte(cfg_path) == 1
    out_rep = capsys.readouterr().out
    assert "derived" in out_rep


def test_e03_modular_no_dashboard(sandbox_env, monkeypatch):
    """E03: Sin módulo dashboard, las rutas web protegidas se bloquean."""
    cfg_path = sandbox_env["config_path"]
    priv_pem = sandbox_env["priv_pem"]
    inject_scenario_cache(cfg_path, "E03", priv_pem)

    client = _make_authed_client(sandbox_env, monkeypatch)

    res_inv = client.get("/api/inventory")
    assert res_inv.status_code == 403
    assert "modulo_no_contratado:dashboard" in res_inv.json()["detail"]

    # Vista HTML redirige a license.html
    res_page = client.get("/inventario")
    assert res_page.status_code == 200
    assert "licencia" in res_page.text.lower()


def test_e04_user_limits_enforced(sandbox_env, monkeypatch):
    """E04: Bloquea creación de usuarios por encima de limits.users."""
    cfg_path = sandbox_env["config_path"]
    priv_pem = sandbox_env["priv_pem"]
    inject_scenario_cache(cfg_path, "E04", priv_pem)  # users limit = 2

    client = _make_authed_client(sandbox_env, monkeypatch, username="admin_root", is_root=True)

    # Crear 2do usuario (ya hay admin_root + 1 = 2)
    auth_users.create_user("operador1", "pass1234", "user")

    # Intentar crear 3er usuario vía API debe fallar con 403
    res_add = client.post("/api/admin/users", json={"username": "extra_user", "password": "pass1234", "role": "user"})
    assert res_add.status_code == 403
    assert res_add.json()["detail"] == "limite_usuarios"

    # Intentar crear 3er usuario vía CLI debe fallar
    args = type("Args", (), {
        "config": cfg_path,
        "users_action": "add",
        "username": "extra_cli_user",
        "password": "password123",
        "role": "user",
        "root": False,
        "no_force_password_change": True,
    })()
    assert cli.cmd_users(args) == 1


def test_e05_grace_period_banner_and_continuity(sandbox_env, monkeypatch):
    """E05: Período de gracia permite operación pero muestra mensaje de advertencia."""
    cfg_path = sandbox_env["config_path"]
    priv_pem = sandbox_env["priv_pem"]
    inject_scenario_cache(cfg_path, "E05", priv_pem)

    client = _make_authed_client(sandbox_env, monkeypatch)

    res_lic = client.get("/api/license")
    assert res_lic.status_code == 200
    body = res_lic.json()
    assert body["state"] == "GRACE"
    assert "gracia" in body["message"].lower()

    # Rutas siguen funcionando durante el período de gracia
    res_inv = client.get("/api/inventory")
    assert res_inv.status_code == 200


def test_e06_e07_e08_blocked_states(sandbox_env, monkeypatch):
    """E06 (Expired), E07 (Suspended), E08 (Revoked): Bloquean acceso a módulos protegidos."""
    cfg_path = sandbox_env["config_path"]
    priv_pem = sandbox_env["priv_pem"]

    client = _make_authed_client(sandbox_env, monkeypatch)

    for sc_id, expected_st in [("E06", "EXPIRED"), ("E07", "SUSPENDED"), ("E08", "REVOKED")]:
        inject_scenario_cache(cfg_path, sc_id, priv_pem)
        monkeypatch.setenv("ETL_CONFIG", cfg_path)

        res_lic = client.get("/api/license")
        assert res_lic.status_code == 200
        assert res_lic.json()["state"] == expected_st

        # API inventory retorna 403 con estado bloqueante
        res_inv = client.get("/api/inventory")
        assert res_inv.status_code == 403
        assert f"licencia:{expected_st}" in res_inv.json()["detail"]


def test_e11_tampered_token_rejection(sandbox_env):
    """E11: Token adulterado o firmado con clave ajena es rechazado inmediatamente."""
    cfg_path = sandbox_env["config_path"]
    priv_pem = sandbox_env["priv_pem"]
    inject_scenario_cache(cfg_path, "E11", priv_pem)

    cfg = load_config(cfg_path)
    mgr = LicenseManager(cfg)

    # validate() debe levantar LicenseInvalid
    with pytest.raises(LicenseInvalid):
        mgr.validate()

    assert cli.cmd_license(cfg_path, "validate") == 1


def test_e12_no_license_open_mode(tmp_path):
    """E12: Modo sin licencia en config permite todas las funciones."""
    cfg_dict = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(tmp_path / "db.sqlite")},
        "tables": [],
        "fields": {},
    }
    cfg_file = tmp_path / "open_config.json"
    cfg_file.write_text(json.dumps(cfg_dict))

    cfg = load_config(str(cfg_file))
    mgr = LicenseManager(cfg)
    lic = mgr.get_license()

    assert lic.state(time.time()) is LicenseState.NO_LICENSE
    assert lic.has("derived") is True
    assert lic.has("dashboard") is True
    assert lic.has("bi") is True
    assert mgr.users_limit() is None


def test_cli_license_inspect(sandbox_env, capsys):
    """Verifica el comando etl license inspect con caché presente y usuarios."""
    cfg_path = sandbox_env["config_path"]
    priv_pem = sandbox_env["priv_pem"]
    inject_scenario_cache(cfg_path, "E01", priv_pem)

    assert cli.cmd_license(cfg_path, "inspect") == 0
    out = capsys.readouterr().out
    assert "Inspección Detallada" in out
    assert "ACTIVE" in out
    assert "cust_sandbox" in out
    assert "Módulos habilitados" in out
    assert "Límite de usuarios" in out

