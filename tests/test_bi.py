import json

import pandas as pd
from sqlalchemy import create_engine

from bi.manifest import build_manifest, manifest_to_json, suggested_measures


def _engine_with_views(tmp_path, views_cfg, tables):
    db_path = tmp_path / "db.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    for table, rows in tables.items():
        pd.DataFrame(rows).to_sql(table, engine, index=False)
    config = {"environment": "qa",
              "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
              "database": {"dialect": "sqlite", "database": str(db_path)},
              "tables": [], "fields": {}, "derived": views_cfg}
    return config, engine


def test_manifest_single_view(tmp_path):
    views = {"inv_bodega": [
        {"MATNR": "M1", "StockLibre": 5, "ValorTotal": 50.0},
    ]}
    config, engine = _engine_with_views(tmp_path, {"name": "inv_bodega"}, views)
    m = build_manifest(config, engine)
    assert m["dialect"] == "sqlite"
    assert len(m["views"]) == 1
    v = m["views"][0]
    assert v["name"] == "inv_bodega"
    assert v["materialized"] is True
    assert v["row_count"] == 1
    matnr = next(c for c in v["columns"] if c["name"] == "MATNR")
    assert matnr["dtype"] in {"str", "object"}
    assert v["keys"] == []
    assert v["measures"] == []


def test_manifest_multiple_views(tmp_path):
    views = {
        "inv_bodega": [{"MATNR": "M1", "StockLibre": 5, "ValorTotal": 50.0}],
        "ventas": [{"ID": 1, "Monto": 10.0}],
    }
    cfg_cfg = [
        {"name": "inv_bodega", "tab": "Inventario", "keys": ["MATNR"],
         "alerts": {"total_field": "ValorTotal", "qty_field": "StockLibre"}},
        {"name": "ventas", "tab": "Ventas", "keys": ["ID"]},
    ]
    config, engine = _engine_with_views(tmp_path, cfg_cfg, views)
    m = build_manifest(config, engine)
    assert [v["name"] for v in m["views"]] == ["inv_bodega", "ventas"]
    inv = m["views"][0]
    assert inv["tab"] == "Inventario"
    assert inv["keys"] == ["MATNR"]
    assert inv["measures"] == [
        {"name": "ValorTotal", "kind": "sum"},
        {"name": "StockLibre", "kind": "sum"},
    ]
    assert m["views"][1]["measures"] == []


def test_manifest_view_not_materialized(tmp_path):
    config, engine = _engine_with_views(tmp_path, {"name": "no_existe"}, {})
    m = build_manifest(config, engine)
    v = m["views"][0]
    assert v["materialized"] is False
    assert v["row_count"] == 0
    assert v["columns"] == []


def test_suggested_measures_skips_missing_columns(tmp_path):
    config, engine = _engine_with_views(tmp_path, {"name": "vista_sin_alertas"}, {})
    view = {"name": "vista_sin_alertas"}
    assert suggested_measures(view) == []


def test_manifest_to_json_roundtrip(tmp_path):
    views = {"inv_bodega": [{"MATNR": "M1", "ValorTotal": 1.0}]}
    config, engine = _engine_with_views(tmp_path, {"name": "inv_bodega"}, views)
    m = build_manifest(config, engine)
    data = json.loads(manifest_to_json(m))
    assert data["dialect"] == "sqlite"
    assert data["views"][0]["name"] == "inv_bodega"
