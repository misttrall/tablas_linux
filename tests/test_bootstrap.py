import json

import pandas as pd
from sqlalchemy import create_engine, text

import cli


def _write_csv(path, table, df):
    df.to_csv(path / f"{table}.csv", index=False)


def test_bootstrap_new_client_end_to_end(tmp_path):
    _write_csv(tmp_path, "T001L", pd.DataFrame([
        {"WERKS": "P1", "LGORT": "W1", "LGOBE": "Bodega Central"},
    ]))
    _write_csv(tmp_path, "MARA", pd.DataFrame([
        {"MATNR": "M1", "MTART": "ROH", "MATKL": "G1", "XCHPF": "", "MEINS": "UN"},
    ]))
    _write_csv(tmp_path, "MARD", pd.DataFrame([
        {"MANDT": 100, "MATNR": "M1", "WERKS": "P1", "LGORT": "W1", "LABST": 10.0, "LMINB": 5.0},
    ]))
    _write_csv(tmp_path, "MBEW", pd.DataFrame([
        {"MATNR": "M1", "BWKEY": "P1", "LBKUM": 10.0, "SALK3": 100.0, "STPRS": 10.0, "VERPR": 9.5},
    ]))
    _write_csv(tmp_path, "MAKT", pd.DataFrame([
        {"MANDT": 100, "MATNR": "M1", "SPRAS": "ES", "MAKTX": "Desc Uno", "MAKTG": "Desc Uno"},
    ]))

    config = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(tmp_path / "db.sqlite")},
        "tables": [
            {"source": "T001L", "target": "T001L_Data", "keys": ["WERKS", "LGORT"]},
            {"source": "MARA", "target": "Mara_Data", "keys": ["MATNR"]},
            {"source": "MARD", "target": "Mard_Data", "keys": ["MANDT", "MATNR", "WERKS", "LGORT"]},
            {"source": "MBEW", "target": "Mbew_Data", "keys": ["MATNR", "BWKEY"]},
            {"source": "MAKT", "target": "Makt_Data", "keys": ["MANDT", "MATNR", "SPRAS"]},
        ],
        "fields": {
            "T001L": ["WERKS", "LGORT", "LGOBE"],
            "MARA": ["MATNR", "MTART", "MATKL", "XCHPF", "MEINS"],
            "MARD": ["MANDT", "MATNR", "WERKS", "LGORT", "LABST", "LMINB"],
            "MBEW": ["MATNR", "BWKEY", "LBKUM", "SALK3", "STPRS", "VERPR"],
            "MAKT": ["MANDT", "MATNR", "SPRAS", "MAKTX", "MAKTG"],
        },
        "derived": {
            "name": "inv_bodega",
            "dominio": {"filters": [{"field": "MTART", "in": ["ROH"]}]},
            "stock_minimo": {"source_field": "LMINB"},
            "excel": {"path": str(tmp_path / "inventario.xlsx")},
        },
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config))

    assert cli.cmd_bootstrap(str(cfg_path), with_derived=True) == 0

    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' "
                                 "AND name='schema_migrations'")).scalar() == "schema_migrations"

    assert cli.cmd_run(str(cfg_path), None) == 0

    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM Mara_Data")).scalar() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM inv_bodega")).scalar() == 1
    assert (tmp_path / "inventario.xlsx").exists()

    assert cli.cmd_status(str(cfg_path)) == 0


def test_bootstrap_skip_sap_without_source_files(tmp_path):
    config = {
        "environment": "qa",
        "source": {"type": "sap", "config": {"user": "X", "passwd": "X"}},
        "database": {"dialect": "sqlite", "database": str(tmp_path / "db.sqlite")},
        "tables": [],
        "fields": {},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config))

    assert cli.cmd_bootstrap(str(cfg_path), skip_sap=True) == 0
