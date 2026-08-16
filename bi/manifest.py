"""Manifiesto del dataset BI: lee config['derived'] y describe cada vista para Power BI."""

import sys
from datetime import datetime, timezone

from sqlalchemy import inspect, text

from derived.db import table_exists
from derived.views import derived_views, view_tab_label

_DEFAULT_TOTAL_FIELD = "ValorTotal"
_DEFAULT_QTY_FIELD = "StockLibre"


def suggested_measures(view, columns=None):
    alerts = view.get("alerts")
    if not alerts:
        return []
    total_field = alerts.get("total_field", _DEFAULT_TOTAL_FIELD)
    qty_field = alerts.get("qty_field", _DEFAULT_QTY_FIELD)
    if columns is None:
        columns = {c["as"] for c in view.get("columns", []) if "as" in c}
    measures = []
    for field in (total_field, qty_field):
        if field in columns:
            measures.append({"name": field, "kind": "sum"})
    return measures


def _view_entry(config, view, engine):
    name = view.get("name", "inv_bodega")
    try:
        exists = table_exists(engine, name)
        if exists:
            cols = inspect(engine).get_columns(name)
            with engine.connect() as conn:
                row_count = conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()
    except Exception as e:
        print(f"warn: BD destino no accesible; vista '{name}' marcada como no materializada: {e}",
              file=sys.stderr)
        exists = False
    if not exists:
        return {
            "name": name, "tab": view_tab_label(view), "table": name,
            "materialized": False, "row_count": 0,
            "columns": [], "keys": list(view.get("keys", [])), "measures": [],
        }
    return {
        "name": name, "tab": view_tab_label(view), "table": name,
        "materialized": True, "row_count": int(row_count),
        "columns": [{"name": c["name"], "dtype": str(c["type"])} for c in cols],
        "keys": list(view.get("keys", [])),
        "measures": suggested_measures(view, [c["name"] for c in cols]),
    }


def build_manifest(config, engine, views=None):
    views = views if views is not None else derived_views(config)
    return {
        "dialect": config["database"].get("dialect", "mssql"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "views": [_view_entry(config, view, engine) for view in views],
    }


def manifest_to_json(manifest):
    import json
    return json.dumps(manifest, indent=2, ensure_ascii=False)
