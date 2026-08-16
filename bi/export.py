"""Export de las vistas derivadas a CSV (siempre) y Parquet (si pyarrow está disponible)."""

import os
import sys

from derived.db import read_table, table_exists
from derived.views import derived_views


def _out_dir(view, default_dir):
    excel_cfg = (view.get("excel") or {})
    path = excel_cfg.get("path")
    if path:
        return os.path.dirname(os.path.abspath(path)) or default_dir
    return default_dir


def export_views(config, engine, out_dir="output/bi", views=None):
    views = views if views is not None else derived_views(config)
    try:
        import pyarrow  # noqa: F401
        parquet_ok = True
    except ImportError:
        parquet_ok = False
        print("warn: pyarrow no instalado; export Parquet omitido", file=sys.stderr)

    os.makedirs(out_dir, exist_ok=True)
    results = []
    for view in views:
        name = view.get("name", "inv_bodega")
        if not table_exists(engine, name):
            print(f"warn: vista '{name}' no materializada; export omitido", file=sys.stderr)
            continue
        df = read_table(engine, name)
        csv_path = os.path.join(out_dir, f"{name}.csv")
        df.to_csv(csv_path, index=False)
        entry = {"name": name, "rows": int(len(df)), "csv_path": csv_path, "parquet_path": None}
        if parquet_ok:
            parquet_path = os.path.join(out_dir, f"{name}.parquet")
            df.to_parquet(parquet_path, index=False)
            entry["parquet_path"] = parquet_path
        results.append(entry)
    if not results:
        raise ValueError("ninguna vista derivada materializada (¿corrió el ETL?)")
    return results
