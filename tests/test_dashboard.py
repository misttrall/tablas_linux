import json
import os
import subprocess
import sys
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import cli
from dashboard import app as dashboard_app
from dashboard.auth import users as auth_users


def _login_admin(client):
    auth_users.create_user("admin", "testpass123", role="admin", is_root=True,
                           must_change_password=False)
    res = client.post("/api/auth/login",
                      json={"username": "admin", "password": "testpass123"})
    assert res.status_code == 200
    return client


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    db_path = tmp_path / "db.sqlite"
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(db_path)},
        "tables": [],
        "fields": {},
    }
    cfg_path.write_text(json.dumps(cfg))

    assert cli.cmd_migrate(str(cfg_path)) == 0

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO etl_execution (status, start_time, end_time) "
            "VALUES ('finished', '2026-01-01 00:00:00', '2026-01-01 00:01:00')"))
        conn.execute(text(
            "INSERT INTO etl_execution (status, start_time, end_time) "
            "VALUES ('failed', '2026-01-01 01:00:00', NULL)"))
        conn.execute(text(
            "INSERT INTO etl_progress (table_name, status, rows_loaded, last_delta_value) "
            "VALUES ('T001L_Data', 'ok', 450, '20260101')"))
        conn.execute(text(
            "INSERT INTO etl_execution_tables (run_id, table_name, chunks_total, chunks_ok, "
            "rows_extracted, duration_s, status) "
            "VALUES (1, 'Mara_Data', 63, 63, 15687, 3.2, 'ok')"))

    monkeypatch.setenv("ETL_CONFIG", str(cfg_path))
    monkeypatch.setenv("ETL_SECRET", "test-secret-at-least-32-chars-long!")
    return _login_admin(TestClient(dashboard_app.app))


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_progress(client):
    res = client.get("/api/progress")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["table_name"] == "T001L_Data"
    assert data[0]["status"] == "ok"
    assert data[0]["rows_loaded"] == 450
    assert data[0]["last_delta_value"] == "20260101"


def test_executions(client):
    res = client.get("/api/executions")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    assert data[0]["id"] > data[1]["id"]
    assert data[0]["status"] == "failed"


def test_dashboard_aggregate(client):
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    data = res.json()
    assert data["last_execution"]["status"] == "failed"
    assert data["progress"][0]["rows_loaded"] == 450
    assert len(data["executions"]) == 2


def test_index_served(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/panel"
    res2 = client.get("/derivadas")
    assert res2.status_code == 200
    assert "Novus" in res2.text


def test_inventario_redirects_to_derivadas(client):
    res = client.get("/inventario", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/derivadas"


def test_all_pages_have_branding_elements(client):
    for path in ("/login", "/panel", "/etl", "/derivadas"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert 'id="appTitle"' in res.text, path
        assert 'id="appLogo"' in res.text, path


def test_etl_page_has_sync_controls(client):
    res = client.get("/etl")
    assert res.status_code == 200
    assert "Sincroniz" in res.text
    assert 'id="btnSync"' in res.text


def test_common_js_auto_applies_branding():
    src = os.path.join(dashboard_app.STATIC_DIR, "common.js")
    with open(src) as f:
        js = f.read()
    assert "renderBranding" in js
    assert "DOMContentLoaded" in js or "readyState" in js
    assert "/inventario" not in js


def test_tables_detail(client):
    res = client.get("/api/tables?run_id=1")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["table_name"] == "Mara_Data"
    assert data[0]["chunks_total"] == 63
    assert data[0]["chunks_ok"] == 63
    assert data[0]["rows_extracted"] == 15687
    assert data[0]["status"] == "ok"


@pytest.fixture
def inventory_client(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    db_path = tmp_path / "db.sqlite"
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(db_path)},
        "tables": [],
        "fields": {},
        "derived": {
            "name": "inv_bodega",
            "alerts": {
                "enabled": True,
                "min_field": "stock_minimo",
                "qty_field": "StockLibre",
                "total_field": "ValorTotal",
            },
        },
    }
    cfg_path.write_text(json.dumps(cfg))

    assert cli.cmd_migrate(str(cfg_path)) == 0

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        pd.DataFrame([
            {"MATNR": "M1", "Descripcion": "Esparrago", "Centro": "IN01", "Almacen": "1014",
             "StockLibre": 8, "stock_minimo": 10, "ValorTotal": 53.04, "Area": "MANTENCION"},
            {"MATNR": "M2", "Descripcion": "Tornillo", "Centro": "IN01", "Almacen": "1014",
             "StockLibre": 20, "stock_minimo": 5, "ValorTotal": 10.0, "Area": "Taller"},
            {"MATNR": "M3", "Descripcion": "Pintura", "Centro": "IN01", "Almacen": "1014",
             "StockLibre": 3, "stock_minimo": 7, "ValorTotal": 25.0, "Area": "Taller"},
        ]).to_sql("inv_bodega", conn, index=False)

    monkeypatch.setenv("ETL_CONFIG", str(cfg_path))
    monkeypatch.setenv("ETL_SECRET", "test-secret-at-least-32-chars-long!")
    return _login_admin(TestClient(dashboard_app.app))


def test_inventory_summary_uses_row_label(inventory_client):
    engine = dashboard_app.get_engine()
    with engine.begin() as conn:
        pd.DataFrame([
            {"ID": "X1", "Descripcion": "A", "Centro": "IN01", "StockLibre": 3,
             "stock_minimo": 5, "ValorTotal": 30.0, "Area": "Taller"},
        ]).to_sql("otra_vista", conn, index=False)
    cfg_path = os.environ["ETL_CONFIG"]
    cfg = json.load(open(cfg_path))
    cfg["derived"] = [
        {"name": "inv_bodega", "alerts": {
            "enabled": True, "min_field": "stock_minimo",
            "qty_field": "StockLibre", "total_field": "ValorTotal"}},
        {"name": "otra_vista", "row_label": "ID", "alerts": {
            "enabled": True, "min_field": "stock_minimo",
            "qty_field": "StockLibre", "total_field": "ValorTotal"}},
    ]
    json.dump(cfg, open(cfg_path, "w"))

    res = inventory_client.get("/api/derived/otra_vista/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["available"] is True
    assert data["table"] == "otra_vista"
    assert data["total_materials"] == 1


def test_derived_endpoints_unknown_view(client):
    res = client.get("/api/derived/inexistente/summary")
    assert res.status_code == 404


def test_derived_endpoints_table_missing(inventory_client):
    cfg_path = os.environ["ETL_CONFIG"]
    cfg = json.load(open(cfg_path))
    cfg["derived"] = [{"name": "no_materializada"}]
    json.dump(cfg, open(cfg_path, "w"))
    res = inventory_client.get("/api/derived/no_materializada/summary")
    assert res.status_code == 200
    assert res.json()["available"] is False


def test_inventory_summary(inventory_client):
    res = inventory_client.get("/api/inventory")
    assert res.status_code == 200
    data = res.json()
    assert data["available"] is True
    assert data["table"] == "inv_bodega"
    assert data["total_materials"] == 3
    assert data["total_value"] == 88.04
    assert data["alerts_count"] == 2
    assert data["risk_value"] == 78.04


def test_inventory_summary_coerces_qty_fields(inventory_client):
    """Las columnas TEXT (cómo llegan del manifest) deben compararse numéricamente."""
    engine = dashboard_app.get_engine()
    with engine.begin() as conn:
        pd.DataFrame([
            {"MATNR": "M-A", "Descripcion": "A", "Centro": "IN01", "Almacen": "1014",
             "StockLibre": "45", "stock_minimo": "9", "ValorTotal": "10.0", "Area": "Taller"},
            {"MATNR": "M-B", "Descripcion": "B", "Centro": "IN01", "Almacen": "1014",
             "StockLibre": "3", "stock_minimo": "7", "ValorTotal": "25.0", "Area": "Taller"},
        ]).to_sql("inv_texto", conn, index=False)
    cfg_path = os.environ["ETL_CONFIG"]
    cfg = json.load(open(cfg_path))
    cfg["derived"] = [
        cfg["derived"],
        {"name": "inv_texto", "alerts": {
            "enabled": True, "min_field": "stock_minimo",
            "qty_field": "StockLibre", "total_field": "ValorTotal"}},
    ]
    json.dump(cfg, open(cfg_path, "w"))

    res = inventory_client.get("/api/derived/inv_texto/summary")
    assert res.status_code == 200
    data = res.json()
    assert data["available"] is True
    # "45" < "9" en string sería True; numéricamente 45 < 9 es False → solo M-B es alerta.
    assert data["alerts_count"] == 1
    assert data["risk_value"] == 25.0


def test_inventory_alerts(inventory_client):
    res = inventory_client.get("/api/inventory/alerts")
    assert res.status_code == 200
    data = res.json()
    assert len(data["alerts"]) == 2
    mats = {a["MATNR"] for a in data["alerts"]}
    assert mats == {"M1", "M3"}


def test_inventory_alerts_filter(inventory_client):
    res = inventory_client.get("/api/inventory/alerts?q=Taller")
    assert res.status_code == 200
    data = res.json()
    assert len(data["alerts"]) == 1
    assert data["alerts"][0]["MATNR"] == "M3"


def test_inventory_filters_endpoint(inventory_client):
    res = inventory_client.get("/api/inventory/filters")
    assert res.status_code == 200
    data = res.json()
    assert data["available"] is True
    assert data["centro"] == ["IN01"]
    assert data["almacen"] == ["1014"]
    assert data["area"] == ["MANTENCION", "Taller"]
    assert data["columns"] == {"centro": "Centro", "almacen": "Almacen", "area": "Area"}


def test_inventory_items_all(inventory_client):
    res = inventory_client.get("/api/inventory/items")
    assert res.status_code == 200
    data = res.json()
    assert data["available"] is True
    assert data["total"] == 3
    assert data["low_only_count"] == 2
    assert len(data["rows"]) == 3


def test_inventory_items_filter_low_only(inventory_client):
    res = inventory_client.get("/api/inventory/items?low_only=true")
    data = res.json()
    assert data["total"] == 2
    assert {r["MATNR"] for r in data["rows"]} == {"M1", "M3"}


def test_inventory_items_filter_by_area(inventory_client):
    res = inventory_client.get("/api/inventory/items?area=Taller")
    data = res.json()
    assert data["total"] == 2
    assert {r["MATNR"] for r in data["rows"]} == {"M2", "M3"}


def test_inventory_items_filter_by_centro_and_q(inventory_client):
    res = inventory_client.get("/api/inventory/items?centro=IN01&q=Esparrago")
    data = res.json()
    assert data["total"] == 1
    assert data["rows"][0]["MATNR"] == "M1"


def test_inventory_items_pagination(inventory_client):
    res = inventory_client.get("/api/inventory/items?limit=2&offset=2")
    data = res.json()
    assert data["total"] == 3
    assert len(data["rows"]) == 1
    assert data["rows"][0]["MATNR"] == "M3"


def test_inventory_items_no_match(inventory_client):
    res = inventory_client.get("/api/inventory/items?centro=XX")
    data = res.json()
    assert data["total"] == 0
    assert data["rows"] == []


def test_etl_trigger(inventory_client, monkeypatch, tmp_path):
    monkeypatch.setenv("ETL_LIVE_FILE", str(tmp_path / "live.json"))
    calls = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, env, stdout, stderr, start_new_session):
        calls["cmd"] = cmd
        calls["env"] = env
        calls["start_new_session"] = start_new_session
        return FakeProc()

    monkeypatch.setattr(dashboard_app.subprocess, "Popen", fake_popen)
    res = inventory_client.post("/api/etl/trigger")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["pid"] == 4242
    assert calls["cmd"][-2:] == ["--config", str(tmp_path / "config.json")]
    assert calls["env"]["ETL_CONFIG"] == str(tmp_path / "config.json")
    assert calls["start_new_session"] is True


def test_etl_trigger_rejects_running(inventory_client, monkeypatch, tmp_path):
    monkeypatch.setenv("ETL_LIVE_FILE", str(tmp_path / "live.json"))
    monkeypatch.setattr(
        dashboard_app, "read_live",
        lambda: {"running": True, "run_id": 7},
    )
    res = inventory_client.post("/api/etl/trigger")
    assert res.status_code == 409
    data = res.json()
    assert data["ok"] is False
    assert data["reason"] == "already_running"
    assert data["run_id"] == 7


def test_etl_trigger_rejects_active_db_run(inventory_client, monkeypatch, tmp_path):
    monkeypatch.setenv("ETL_LIVE_FILE", str(tmp_path / "live.json"))

    engine = dashboard_app.get_engine()
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO etl_execution (status, start_time) "
            "VALUES ('running', '2026-01-01 00:00:00')"))

    res = inventory_client.post("/api/etl/trigger")
    assert res.status_code == 409
    data = res.json()
    assert data["reason"] == "already_running"
    assert data["run_id"] == 1


def _write_stale_live(tmp_path, run_id=99):
    live = tmp_path / "live.json"
    live.write_text(json.dumps({
        "running": True, "run_id": run_id, "table": None, "phase": "derived",
        "chunk_index": 0, "chunk_total": 0, "rows_so_far": 0, "elapsed_s": 14.6,
    }))
    old = time.time() - 3600
    os.utime(live, (old, old))


def test_recover_stale_reaps_dead_child(inventory_client, monkeypatch, tmp_path):
    monkeypatch.setenv("ETL_LIVE_FILE", str(tmp_path / "live.json"))
    lock_path = tmp_path / "etl_sap.lock"
    monkeypatch.setattr(dashboard_app, "_ETL_LOCK_FILE", str(lock_path))
    engine = dashboard_app.get_engine()
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO etl_execution (id, status, start_time) "
            "VALUES (99, 'running', '2026-01-01 00:00:00')"))

    child = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(7)"])
    child.wait()
    monkeypatch.setattr(dashboard_app, "_SPAWNED_PID", {"pid": child.pid})
    _write_stale_live(tmp_path, run_id=99)
    lock_path.write_text(str(child.pid))

    res = inventory_client.get("/api/live")
    assert res.status_code == 200
    assert res.json()["running"] is False
    assert res.json()["phase"] == "error"

    with engine.connect() as conn:
        row = conn.execute(text("SELECT status FROM etl_execution WHERE id=99")).fetchone()
    assert row[0] == "failed"
    assert dashboard_app._SPAWNED_PID["pid"] is None
    assert not lock_path.exists()


def test_recover_stale_without_tracked_pid(inventory_client, monkeypatch, tmp_path):
    monkeypatch.setenv("ETL_LIVE_FILE", str(tmp_path / "live.json"))
    _write_stale_live(tmp_path, run_id=99)
    monkeypatch.setattr(dashboard_app, "_SPAWNED_PID", {"pid": None})

    res = inventory_client.get("/api/live")
    assert res.status_code == 200
    assert res.json()["running"] is False


def test_recover_keeps_fresh_running(inventory_client, monkeypatch, tmp_path):
    monkeypatch.setenv("ETL_LIVE_FILE", str(tmp_path / "live.json"))
    live = tmp_path / "live.json"
    live.write_text(json.dumps({
        "running": True, "run_id": 99, "phase": "extrayendo",
    }))
    monkeypatch.setattr(dashboard_app, "_SPAWNED_PID", {"pid": None})

    res = inventory_client.get("/api/live")
    assert res.status_code == 200
    assert res.json()["running"] is True


def test_inventory_not_available_without_derived(client):
    res = client.get("/api/inventory")
    assert res.status_code == 200
    assert res.json()["available"] is False


def test_derived_views_endpoint(inventory_client):
    res = inventory_client.get("/api/derived-views")
    assert res.status_code == 200
    data = res.json()
    assert data["views"][0]["name"] == "inv_bodega"
    assert data["views"][0]["tab"] == "Inv Bodega"
    assert data["views"][0]["table"] == "inv_bodega"
    assert data["views"][0]["columns"] == []


def test_derived_views_columns_metadata(inventory_client):
    cfg_path = os.environ["ETL_CONFIG"]
    cfg = json.load(open(cfg_path))
    cfg["derived"]["columns"] = [
        {"as": "MATNR", "source": "MATNR", "label": "Material"},
        {"as": "Almacen", "source": "LGORT", "hide": True},
        {"as": "AlmacenDesc", "source": "LGOBE", "fallback": "Almacen"},
        {"as": "ValorTotal", "compute": "LABST * VERPR", "label": "Valor"},
    ]
    json.dump(cfg, open(cfg_path, "w"))

    res = inventory_client.get("/api/derived-views")
    assert res.status_code == 200
    cols = res.json()["views"][0]["columns"]
    assert {"as": "MATNR", "label": "Material", "hidden": False, "fallback": None} in cols
    assert {"as": "Almacen", "label": "Almacen", "hidden": True, "fallback": None} in cols
    assert {"as": "AlmacenDesc", "label": "AlmacenDesc", "hidden": False, "fallback": "Almacen"} in cols
    assert {"as": "ValorTotal", "label": "Valor", "hidden": False, "fallback": None} in cols


def test_derivadas_page_served(client):
    res = client.get("/derivadas", follow_redirects=False)
    assert res.status_code == 200
    assert "Pestañas" in res.text or "derivada" in res.text


def test_branding_defaults(client):
    res = client.get("/api/branding")
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "ETL Dashboard"
    assert data["color"] == ""
    assert data["footer"] == ""


def test_branding_from_config(client):
    cfg_path = os.environ["ETL_CONFIG"]
    cfg = json.load(open(cfg_path))
    cfg["dashboard"] = {"title": "Bodegas ACME", "color": "#123456",
                        "footer": "© ACME 2026", "logo": "/static/logo.png"}
    json.dump(cfg, open(cfg_path, "w"))
    res = client.get("/api/branding")
    data = res.json()
    assert data["title"] == "Bodegas ACME"
    assert data["color"] == "#123456"
    assert data["footer"] == "© ACME 2026"
    assert data["logo"] == "/static/logo.png"
