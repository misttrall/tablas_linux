import pytest

from sources import get_source, resolve_source_config, validate_environment, validate_prd_limits
from sources.generic.csv import CSVConnector
from sources.generic.http import HTTPConnector
from sources.sap import SAPConnector


def test_resolve_source_new_schema():
    cfg = {"source": {"type": "csv", "config": {"directory": "/tmp"}}}
    assert resolve_source_config(cfg) == {"type": "csv", "config": {"directory": "/tmp"}}


def test_resolve_source_backward_compat_with_sap():
    cfg = {"sap": {"user": "u"}}
    assert resolve_source_config(cfg) == {"type": "sap", "config": {"user": "u"}}


def test_resolve_source_missing_raises():
    with pytest.raises(ValueError):
        resolve_source_config({"database": {}})


def test_get_source_types():
    assert isinstance(get_source({"type": "sap", "config": {}}), SAPConnector)
    assert isinstance(get_source({"type": "http", "config": {"base_url": "x"}}), HTTPConnector)
    assert isinstance(get_source({"type": "csv", "config": {"directory": "/tmp"}}), CSVConnector)


def test_get_source_unknown_type_raises():
    with pytest.raises(ValueError):
        get_source({"type": "odoo"})


def test_get_source_missing_type_raises():
    with pytest.raises(ValueError):
        get_source({"config": {}})


def test_validate_environment_ok():
    assert validate_environment({"environment": "qa"}) == "qa"
    assert validate_environment({"environment": "prd"}) == "prd"


def test_validate_environment_missing_raises():
    with pytest.raises(ValueError):
        validate_environment({"source": {"type": "sap"}})


def test_validate_environment_invalid_raises():
    with pytest.raises(ValueError):
        validate_environment({"environment": "dev"})


def test_validate_prd_limits_allows_filtered_large_tables():
    cfg = {
        "environment": "prd",
        "tables": [
            {"source": "MARA", "target": "Mara_Data", "filters": ["MATNR = 'X'"]},
            {"source": "T001L", "target": "T001L_Data"},
        ],
    }
    validate_prd_limits(cfg)


def test_validate_prd_limits_blocks_full_scan_large_table():
    cfg = {
        "environment": "prd",
        "tables": [{"source": "MARD", "target": "Mard_Data"}],
    }
    with pytest.raises(ValueError):
        validate_prd_limits(cfg)


def test_validate_prd_limits_ignores_qa():
    cfg = {
        "environment": "qa",
        "tables": [{"source": "MARD", "target": "Mard_Data"}],
    }
    validate_prd_limits(cfg)
