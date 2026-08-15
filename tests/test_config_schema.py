import json
import os

import pytest

from utils.config_loader import load_config
from utils.config_validation import ensure_valid_config, validate_config

MINIMAL = {
    "environment": "qa",
    "source": {"type": "csv", "config": {"directory": "/tmp"}},
    "database": {"dialect": "sqlite", "database": "/tmp/db.sqlite"},
    "tables": [
        {"source": "T001L", "target": "T001L_Data", "keys": ["WERKS", "LGORT"]},
    ],
    "fields": {"T001L": ["WERKS", "LGORT", "LGOBE"]},
}


def test_minimal_config_is_valid():
    assert validate_config(MINIMAL) == []


def test_missing_required_section_fails():
    cfg = dict(MINIMAL)
    del cfg["database"]
    errors = validate_config(cfg)
    assert any("database" in e and "required" in e for e in errors)


def test_invalid_environment_fails():
    cfg = dict(MINIMAL)
    cfg["environment"] = "staging"
    errors = validate_config(cfg)
    assert any("environment" in e for e in errors)


def test_invalid_source_type_fails():
    cfg = dict(MINIMAL)
    cfg["source"] = {"type": "oracle", "config": {}}
    errors = validate_config(cfg)
    assert any("source" in e for e in errors)


def test_invalid_dialect_fails():
    cfg = dict(MINIMAL)
    cfg["database"] = {"dialect": "oracle", "database": "x"}
    errors = validate_config(cfg)
    assert any("dialect" in e for e in errors)


def test_table_requires_target():
    cfg = dict(MINIMAL)
    cfg["tables"] = [{"source": "MARD", "keys": ["MATNR"]}]
    errors = validate_config(cfg)
    assert any("target" in e for e in errors)


def test_derived_single_object_accepted():
    cfg = dict(MINIMAL)
    cfg["derived"] = {"name": "inv_bodega", "columns": [{"as": "MATNR", "source": "MATNR"}]}
    assert validate_config(cfg) == []


def test_derived_list_accepted():
    cfg = dict(MINIMAL)
    cfg["derived"] = [
        {"name": "inv_bodega", "columns": [{"as": "MATNR", "source": "MATNR"}]},
        {"name": "stock_mov", "columns": [{"as": "Total", "compute": "A * B"}]},
    ]
    assert validate_config(cfg) == []


def test_derived_column_requires_as():
    cfg = dict(MINIMAL)
    cfg["derived"] = {"name": "inv_bodega", "columns": [{"source": "MATNR"}]}
    errors = validate_config(cfg)
    assert any("as" in e for e in errors)


def test_ensure_valid_config_raises_clear_error():
    cfg = dict(MINIMAL)
    del cfg["fields"]
    with pytest.raises(ValueError, match="config.schema.json"):
        ensure_valid_config(cfg)


def test_real_and_example_configs_pass():
    from utils.config_loader import BASE_DIR
    for name in ("config.json", "config.example.json"):
        with open(os.path.join(BASE_DIR, name)) as fh:
            cfg = json.load(fh)
        assert validate_config(cfg) == []


def test_load_config_validates_real_config():
    cfg = load_config()
    assert cfg["environment"] in ("qa", "prd")
