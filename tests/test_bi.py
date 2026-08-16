import json
import os

import pandas as pd
from sqlalchemy import create_engine

from bi.export import export_views
from bi.guide import render_guide
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
    assert matnr["dtype"].startswith("VARCHAR") or matnr["dtype"] in {"TEXT", "VARCHAR"}
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


def _unreachable_engine():
    class _Unreachable:
        class _Dialect:
            name = "mssql"

        dialect = _Dialect()

        def connect(self):
            raise RuntimeError("no conectado")

    return _Unreachable()


def test_manifest_unreachable_db_reports_not_materialized(tmp_path, capsys):
    config, _ = _engine_with_views(tmp_path, {"name": "inv_bodega"}, {})
    m = build_manifest(config, _unreachable_engine())
    v = m["views"][0]
    assert v["name"] == "inv_bodega"
    assert v["materialized"] is False
    assert v["row_count"] == 0
    assert v["columns"] == []
    assert "no accesible" in capsys.readouterr().err


def test_manifest_metadata_read_failure_degrades(tmp_path, capsys, monkeypatch):
    views = {"inv_bodega": [{"MATNR": "M1", "ValorTotal": 1.0}]}
    config, engine = _engine_with_views(tmp_path, {"name": "inv_bodega"}, views)

    def boom(*a, **k):
        raise RuntimeError("lectura falló")

    monkeypatch.setattr("bi.manifest.inspect", boom)
    m = build_manifest(config, engine)
    v = m["views"][0]
    assert v["materialized"] is False
    assert v["row_count"] == 0
    assert v["columns"] == []
    assert "no accesible" in capsys.readouterr().err


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


def _views_for_export(tmp_path):
    db_path = tmp_path / "db.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    pd.DataFrame([{"MATNR": "M1", "ValorTotal": 1.0},
                  {"MATNR": "M2", "ValorTotal": 2.0}]).to_sql("inv_bodega", engine, index=False)
    config = {"environment": "qa",
              "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
              "database": {"dialect": "sqlite", "database": str(db_path)},
              "tables": [], "fields": {},
              "derived": [{"name": "inv_bodega"}, {"name": "no_materializada"}]}
    return config, engine


def test_export_views_csv(tmp_path):
    config, engine = _views_for_export(tmp_path)
    out_dir = str(tmp_path / "bi_out")
    results = export_views(config, engine, out_dir=out_dir)
    assert len(results) == 1
    assert results[0]["name"] == "inv_bodega"
    assert results[0]["rows"] == 2
    assert os.path.exists(results[0]["csv_path"])
    with open(results[0]["csv_path"]) as f:
        content = f.read()
    assert "MATNR" in content
    assert "M2" in content
    assert not os.path.exists(os.path.join(out_dir, "no_materializada.csv"))


def test_export_views_excel_dir_per_view(tmp_path):
    config, engine = _views_for_export(tmp_path)
    pd.DataFrame([{"ID": 1, "Monto": 10.0}]).to_sql("ventas", engine, index=False)
    excel_dir = tmp_path / "excel_out"
    config["derived"] = [
        {"name": "inv_bodega", "excel": {"path": str(excel_dir / "inventario.xlsx")}},
        {"name": "ventas"},
        {"name": "no_materializada"},
    ]
    out_dir = str(tmp_path / "bi_out")
    results = export_views(config, engine, out_dir=out_dir)
    assert [r["name"] for r in results] == ["inv_bodega", "ventas"]
    inv = next(r for r in results if r["name"] == "inv_bodega")
    ventas = next(r for r in results if r["name"] == "ventas")
    assert inv["csv_path"] == str(excel_dir / "inv_bodega.csv")
    assert os.path.exists(str(excel_dir / "inv_bodega.csv"))
    assert not os.path.exists(os.path.join(out_dir, "inv_bodega.csv"))
    assert ventas["csv_path"] == os.path.join(out_dir, "ventas.csv")
    assert os.path.exists(os.path.join(out_dir, "ventas.csv"))


def test_export_views_none_materialized_raises(tmp_path):
    db_path = tmp_path / "db2.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    config = {"environment": "qa",
              "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
              "database": {"dialect": "sqlite", "database": str(db_path)},
              "tables": [], "fields": {}, "derived": [{"name": "no_existe"}]}
    import pytest
    with pytest.raises(ValueError):
        export_views(config, engine, out_dir=str(tmp_path / "out"))


def test_export_views_unreachable_db_warns(tmp_path, capsys):
    config, _ = _views_for_export(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        export_views(config, _unreachable_engine(), out_dir=str(tmp_path / "out"))
    err = capsys.readouterr().err
    assert "no accesible" in err
    assert "inv_bodega" in err


def _guide_config(tmp_path):
    return {"environment": "qa",
            "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
            "database": {"dialect": "mssql", "server": "192.168.1.10",
                         "database": "dw_cliente", "user": "bi_user"},
            "tables": [], "fields": {},
            "derived": [{"name": "inv_bodega", "tab": "Inventario", "keys": ["MATNR"]},
                        {"name": "ventas", "tab": "Ventas", "keys": ["ID"]}]}


def test_guide_render_mssql(tmp_path):
    guide = render_guide(_guide_config(tmp_path))
    assert "mssql" in guide
    assert "192.168.1.10" in guide
    assert "dw_cliente" in guide
    assert "inv_bodega" in guide
    assert "Inventario" in guide
    assert "ventas" in guide
    assert "Power BI Service" in guide


def test_guide_render_sqlite_advises_migration(tmp_path):
    config = _guide_config(tmp_path)
    config["database"]["dialect"] = "sqlite"
    guide = render_guide(config)
    assert "sqlite" in guide
    assert "no recomendado" in guide
    assert "mssql" in guide.lower() or "SQL Server" in guide


def test_guide_render_defaults_views(tmp_path):
    config = _guide_config(tmp_path)
    guide = render_guide(config)
    assert "MATNR" in guide
