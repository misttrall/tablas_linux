"""Manifiesto del dataset BI: lee config['derived'] y describe cada vista para Power BI."""

import sys
from datetime import datetime, timezone

from derived.db import read_table, table_exists
from derived.views import derived_views, view_tab_label

_DEFAULT_TOTAL_FIELD = "ValorTotal"
_DEFAULT_QTY_FIELD = "StockLibre"


def column_types(df):
    return [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns]


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
    df = read_table(engine, name)
    return {
        "name": name, "tab": view_tab_label(view), "table": name,
        "materialized": True, "row_count": int(len(df)),
        "columns": column_types(df),
        "keys": list(view.get("keys", [])),
        "measures": suggested_measures(view, df.columns),
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
