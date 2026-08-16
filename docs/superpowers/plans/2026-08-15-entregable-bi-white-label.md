# Entregable BI (bi/) + Dashboard multi-pestañas + White-label Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir la capa de entregable BI (módulo `bi/`, CLI `etl bi`, dashboard multi-pestañas por vista derivada y branding por config) sobre v0.4.0.

**Architecture:** Un solo `config.json` por empresa alimenta ETL, DWH, dashboard y `bi/`. `derived[]` es el contrato: cada vista = tabla materializada + pestaña de dashboard + entrada de manifiesto BI + export. Backend FastAPI se generaliza por vista (rutas `/api/derived/<name>/*`, alias `/api/inventory*` retrocompatibles). `bi/manifest.py` lee `config['derived']` y `bi/export.py` escribe CSV/Parquet.

**Tech Stack:** Python 3.10+, FastAPI, pandas, SQLAlchemy, argparse (CLI existente), jsonschema, pytest + ruff (E/F/W/I, line-length 120).

**Spec:** `docs/superpowers/specs/2026-08-15-entregable-bi-white-label-design.md`

## Global Constraints

- Repo: `/home/mist/ETL/tablas_linux`, rama `dev`. Suite base: 207 passed, 19 skipped, 0 failed.
- Ejecutar la suite con `python -m pytest` (el proyecto no configura `pythonpath`).
- Ruff: `ruff check .` — reglas E/F/W/I, line-length 120, cero errores antes de cada commit.
- TDD estricto: escribir test → verificar fallo → implementación mínima → verificar pase → commit.
- Commits frecuentes, mensajes concisos en estilo del repo (`git log --oneline`).
- `config.json`/`inv_bodega` son EJEMPLO: nada se hardcodea a nombres SAP. Todo lee de `config['derived']`.
- `derived[]` puede ser objeto único o lista (ya normalizado por `derived.views.derived_views`).
- Campo `tab` en cada vista: OPCIONAL. Si falta, derivar etiqueta legible de `name`.
- Bloque `config["dashboard"]` (branding): `{ "title", "logo", "color", "footer" }` — todos opcionales, defaults neutros.
- `modules` en config: SOLO documental (no valida ni bloquea).
- Parquet: dependencia opcional. Si `import pyarrow` falla, el export Parquet se omite con warning; CSV siempre disponible.
- No crear `product/`, no licenciamiento, no telemetría, no adaptadores Oracle/Mongo (Fase 2/3 fuera de alcance).

---
---

## Task 1: Helpers de vista derivada en `derived/views.py`

**Files:**
- Modify: `derived/views.py`
- Test: `tests/test_views.py` (crear)

**Interfaces:**
- Consumes: `derived_views(config)` (existe), `DEFAULT_VIEW_NAME = "inv_bodega"` (existe).
- Produces:
  - `derived_view_by_name(config, name) -> dict | None` — busca en `derived_views(config)` por `view["name"]` (default `inv_bodega`). None si no existe.
  - `view_tab_label(view) -> str` — devuelve `view.get("tab")` si no es vacío; si no, deriva de `view["name"]` (default `inv_bodega`): snake_case → Title Case ("inv_bodega" → "Inv Bodega", "ventas_mensuales" → "Ventas Mensuales").

- [ ] **Step 1: Write the failing test** — crear `tests/test_views.py`:

```python
from derived.views import derived_view_by_name, view_tab_label, derived_views


def test_derived_view_by_name_single():
    config = {"derived": {"name": "inv_bodega"}}
    view = derived_view_by_name(config, "inv_bodega")
    assert view == {"name": "inv_bodega"}
    assert derived_view_by_name(config, "otra") is None


def test_derived_view_by_name_list():
    config = {"derived": [
        {"name": "inv_bodega"},
        {"name": "ventas", "tab": "Ventas"},
    ]}
    assert derived_view_by_name(config, "ventas")["tab"] == "Ventas"
    assert derived_view_by_name(config, "nope") is None


def test_view_tab_label_explicit():
    assert view_tab_label({"name": "ventas", "tab": "Ventas"}) == "Ventas"
    assert view_tab_label({"name": "ventas", "tab": ""}) == "Ventas"


def test_view_tab_label_derived_from_name():
    assert view_tab_label({"name": "inv_bodega"}) == "Inv Bodega"
    assert view_tab_label({"name": "ventas_mensuales"}) == "Ventas Mensuales"
    assert view_tab_label({"name": "STOCK_BAJO"}) == "Stock Bajo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_views.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'derived.views'` no; más bien `ImportError` porque las funciones no existen.

- [ ] **Step 3: Write minimal implementation** — añadir a `derived/views.py`:

```python
DEFAULT_VIEW_NAME = "inv_bodega"  # ya existe


def derived_view_by_name(config, name=None):
    target = name or DEFAULT_VIEW_NAME
    for view in derived_views(config):
        if view.get("name", DEFAULT_VIEW_NAME) == target:
            return view
    return None


def view_tab_label(view):
    tab = (view.get("tab") or "").strip()
    if tab:
        return tab
    name = view.get("name", DEFAULT_VIEW_NAME)
    return " ".join(part.capitalize() for part in name.split("_"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_views.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add derived/views.py tests/test_views.py
git commit -m "feat: helpers de vista derivada (by_name, tab_label)"
```

---
---

## Task 2: Backend del dashboard generalizado por vista

**Files:**
- Modify: `dashboard/app.py`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `derived.views.derived_views`, `derived.views.derived_view_by_name`, `derived.views.view_tab_label` (Task 1).
- Produces (todas en `dashboard/app.py`):
  - `_view_frame(view=None) -> tuple[pd.DataFrame|None, dict|None]` — lee la tabla de la vista pasada; si `view is None`, usa la primera de `derived_views(config)`. Devuelve `(None, view)` si la tabla no existe, `(None, None)` si no hay vistas. Reemplaza a `_inventory_frame` (que pasa a envolverla).
  - `_inventory_frame() -> tuple` — wrapper: `return _view_frame()` (retrocompat para endpoints `/api/inventory*`).
  - `_inventory_summary(df, view) -> dict` — MISMA firma (ya parametrizada por view), pero usa `view.get("row_label", "MATNR")` en vez de hardcodear `"MATNR"` para `total_materials`; `materials = df[row_label].nunique()` si `row_label` existe.
  - `_inventory_frame_for(name) -> tuple` — `view = derived_view_by_name(config, name)`; si None → `(None, None)`.

- [ ] **Step 1: Write the failing test** — añadir a `tests/test_dashboard.py` (tras el fixture `inventory_client` existente):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard.py::test_inventory_summary_uses_row_label tests/test_dashboard.py::test_derived_endpoints_unknown_view tests/test_dashboard.py::test_derived_endpoints_table_missing -v`
Expected: FAIL — rutas `/api/derived/*` no existen (404) y `_inventory_summary` hardcodea `MATNR`.

- [ ] **Step 3: Write minimal implementation** — en `dashboard/app.py`:

```python
def _view_frame(view=None):
    config = load_config(os.environ.get("ETL_CONFIG"))
    if view is None:
        views = derived_views(config)
        if not views:
            return None, None
        view = views[0]
    from derived.db import read_table, table_exists
    name = view.get("name", "inv_bodega")
    if not table_exists(get_engine(), name):
        return None, view
    return read_table(get_engine(), name), view


def _inventory_frame():
    return _view_frame()


def _inventory_frame_for(name):
    from derived.views import derived_view_by_name
    config = load_config(os.environ.get("ETL_CONFIG"))
    view = derived_view_by_name(config, name)
    if view is None:
        return None, None
    return _view_frame(view)
```

  Y en `_inventory_summary`, reemplazar la línea del conteo de materiales:

```python
    row_label = view.get("row_label", "MATNR")
    materials = int(df[row_label].nunique()) if row_label in df.columns else total_rows
```

  Y añadir los endpoints (después de `api_inventory_alerts`):

```python
@app.get("/api/derived/{name}/summary")
def api_derived_summary(name: str, user=Depends(require_user)):
    df, view = _inventory_frame_for(name)
    if view is None:
        raise HTTPException(status_code=404, detail="vista_inexistente")
    if df is None:
        return {"available": False, "reason": "table_missing", "table": name}
    return _inventory_summary(df, view)


@app.get("/api/derived/{name}/filters")
def api_derived_filters(name: str, user=Depends(require_user)):
    df, view = _inventory_frame_for(name)
    if view is None:
        raise HTTPException(status_code=404, detail="vista_inexistente")
    if df is None:
        return {"available": False}
    cols = _inventory_filter_columns(view)
    out = {}
    for key, col in cols.items():
        out[key] = sorted(df[col].dropna().astype(str).unique().tolist()) if col in df.columns else []
    out["available"] = True
    out["columns"] = cols
    return out


@app.get("/api/derived/{name}/items")
def api_derived_items(name: str, centro: str = "", almacen: str = "", area: str = "",
                      low_only: bool = False, q: str = "", limit: int = 100, offset: int = 0,
                      user=Depends(require_user)):
    df, view = _inventory_frame_for(name)
    if view is None:
        raise HTTPException(status_code=404, detail="vista_inexistente")
    if df is None:
        return {"available": False, "reason": "table_missing", "table": name}
    rows, cfg, cols = _filter_inventory(df, view, centro, almacen, area, low_only, q)
    total = int(len(rows))
    low_only_count = int(len(rows[_inventory_alert_mask(rows, cfg)]))
    page = rows.iloc[offset:offset + limit].fillna("")
    return {
        "available": True, "table": name, "total": total,
        "offset": offset, "limit": limit, "low_only_count": low_only_count,
        "rows": page.to_dict(orient="records"),
    }


@app.get("/api/derived/{name}/alerts")
def api_derived_alerts(name: str, limit: int = 500, q: str = "", user=Depends(require_user)):
    data = api_derived_items(name=name, low_only=True, q=q, limit=limit, offset=0)
    if isinstance(data, dict) and data.get("available") is False:
        return {"alerts": []}
    return {"alerts": data.get("rows", [])}
```

  Nota: `api_inventory_alerts` llama a `api_inventory_items(low_only=True, ...)` (posiciónal `low_only`); sigue funcionando por retrocompat. El nuevo `api_derived_alerts` usa la firma con keyword.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: todos los tests existentes + 3 nuevos pasan (el alias `/api/inventory*` intacto).

- [ ] **Step 5: Commit**

```bash
git add dashboard/app.py tests/test_dashboard.py
git commit -m "feat: endpoints /api/derived/<name>/* generalizados por vista"
```

---
---

## Task 3: Módulo `bi/manifest.py`

**Files:**
- Create: `bi/__init__.py`
- Create: `bi/manifest.py`
- Test: `tests/test_bi.py` (crear)

**Interfaces:**
- Consumes: `derived.views.derived_views`, `derived.views.view_tab_label` (Task 1), `derived.db.table_exists`, `derived.db.read_table`, `dashboard.app._inventory_alerts_config` NO — no importar del dashboard; duplicar defaults mínimos en el manifiesto.
- Produces:
  - `build_manifest(config, engine, views=None) -> dict` — views default `derived_views(config)`. Devuelve:
    ```json
    {
      "dialect": "mssql" | ... ,
      "generated_at": "2026-08-15T...",
      "views": [
        {"name": "inv_bodega", "tab": "Inv Bodega", "table": "inv_bodega",
         "materialized": true, "row_count": 123,
         "columns": [{"name": "MATNR", "dtype": "object"}, ...],
         "keys": ["MATNR", "WERKS", "LGORT"],
         "measures": [{"name": "ValorTotal", "kind": "sum"}]}
      ]
    }
    ```
  - `column_types(df) -> list[dict]` — `[{"name": c, "dtype": str(df[c].dtype)} for c in df.columns]`.
  - `suggested_measures(view) -> list[dict]` — suma sobre `view["alerts"]["total_field"]` y `view["alerts"]["qty_field"]` (defaults `ValorTotal`/`StockLibre`) si dichas columnas existen en la vista.
  - `manifest_to_json(manifest) -> str` — JSON indentado con `ensure_ascii=False`.

- [ ] **Step 1: Write the failing test** — crear `tests/test_bi.py`:

```python
import json

import pandas as pd
from sqlalchemy import create_engine, text

from bi.manifest import build_manifest, manifest_to_json, suggested_measures
from derived.views import view_tab_label


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
    assert {"name": "MATNR", "dtype": "object"} in v["columns"]
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bi.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bi'`.

- [ ] **Step 3: Write minimal implementation**

`bi/__init__.py`:
```python
"""Entregable BI: manifiesto, export y guía de conectividad para Power BI."""
```

`bi/manifest.py`:
```python
"""Manifiesto del dataset BI: lee config['derived'] y describe cada vista para Power BI."""

from datetime import datetime

from derived.db import read_table, table_exists
from derived.views import derived_views, view_tab_label

_DEFAULT_TOTAL_FIELD = "ValorTotal"
_DEFAULT_QTY_FIELD = "StockLibre"


def column_types(df):
    return [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns]


def suggested_measures(view):
    alerts = view.get("alerts") or {}
    total_field = alerts.get("total_field", _DEFAULT_TOTAL_FIELD)
    qty_field = alerts.get("qty_field", _DEFAULT_QTY_FIELD)
    columns = {c["as"] for c in view.get("columns", []) if "as" in c}
    measures = []
    for field in (total_field, qty_field):
        if field in columns:
            measures.append({"name": field, "kind": "sum"})
    return measures


def _view_entry(config, view, engine):
    name = view.get("name", "inv_bodega")
    if not table_exists(engine, name):
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
        "measures": suggested_measures(view),
    }


def build_manifest(config, engine, views=None):
    views = views if views is not None else derived_views(config)
    return {
        "dialect": config["database"].get("dialect", "mssql"),
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "views": [_view_entry(config, view, engine) for view in views],
    }


def manifest_to_json(manifest):
    import json
    return json.dumps(manifest, indent=2, ensure_ascii=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bi.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add bi/__init__.py bi/manifest.py tests/test_bi.py
git commit -m "feat: manifiesto BI (bi/manifest.py)"
```

---
---

## Task 4: Módulo `bi/export.py`

**Files:**
- Create: `bi/export.py`
- Test: `tests/test_bi.py` (ampliar)

**Interfaces:**
- Consumes: `derived.db.table_exists`, `derived.db.read_table`, `derived.views.derived_views` (Task 1).
- Produces:
  - `export_views(config, engine, out_dir="output/bi", views=None) -> list[dict]` — por cada vista materializada escribe `<out_dir>/<name>.csv` (UTF-8, index=False) y, si `import pyarrow` funciona, también `<out_dir>/<name>.parquet`. Devuelve lista de `{"name", "rows", "csv_path", "parquet_path"|None}`. Vistas no materializadas se saltan con warning en stderr. Si NINGUNA existe → `ValueError("ninguna vista derivada materializada")`.
  - `_out_dir(view, default_dir) -> str` — respeta `view.get("excel", {}).get("path")` como directorio de salida si `default_dir` no se pasa (default: "output/bi").

- [ ] **Step 1: Write the failing test** — ampliar `tests/test_bi.py`:

```python
import os

from bi.export import export_views


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bi.py::test_export_views_csv tests/test_bi.py::test_export_views_none_materialized_raises -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bi.export'`.

- [ ] **Step 3: Write minimal implementation**

`bi/export.py`:
```python
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
```

  Nota: `_out_dir` no se usa por defecto porque `cli bi export` pasa `out_dir`; se mantiene como helper para el CLI si el config lo declara. (Si el lint F401 de pyarrow molesta, usar `import pyarrow as _pyarrow` — verificado con `import pyarrow; pyarrow.__version__`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bi.py -v`
Expected: 7 passed (5 previos + 2 nuevos). El test Parquet se valida implícitamente: si pyarrow NO está, `parquet_path` es None y el test CSV no lo exige.

- [ ] **Step 5: Commit**

```bash
git add bi/export.py tests/test_bi.py
git commit -m "feat: export de vistas a CSV/Parquet (bi/export.py)"
```

---
---

## Task 5: Guía de conectividad `bi/guide.py`

**Files:**
- Create: `bi/guide.py`
- Test: `tests/test_bi.py` (ampliar)

**Interfaces:**
- Consumes: `derived.views.derived_views`, `derived.views.view_tab_label` (Task 1).
- Produces:
  - `render_guide(config, views=None) -> str` — texto Markdown con secciones por dialecto (mssql nativo recomendado, postgresql/mysql → ODBC, sqlite → no-soportado + recomendación), tabla de vistas con `name`, `tab`, `table`, `keys`, y bloque de publicación en el servicio de Power BI. Los valores salen del config (dialect, tabla, claves).
  - `guide_text(dialect) -> str` — texto fijo por dialecto con instrucciones del conector.

- [ ] **Step 1: Write the failing test** — ampliar `tests/test_bi.py`:

```python
from bi.guide import render_guide


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bi.py::test_guide_render_mssql tests/test_bi.py::test_guide_render_sqlite_advises_migration tests/test_bi.py::test_guide_render_defaults_views -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bi.guide'`.

- [ ] **Step 3: Write minimal implementation**

`bi/guide.py`:
```python
"""Guía de conectividad de Power BI por dialecto, parametrizada por empresa."""

from derived.views import derived_views, view_tab_label


def guide_text(dialect):
    if dialect == "mssql":
        return (
            "- Conector nativo 'SQL Server' de Power BI (sin costo).\n"
            "- Recomendado: modo Importación para el DWH; DirectQuery si el volumen lo exige.\n"
            "- Publica el modelo en el Power BI Service y configura una puerta de enlace (gateway) si la BD es on-premise."
        )
    if dialect in ("postgresql", "mysql"):
        return (
            f"- Conector '{'PostgreSQL' if dialect == 'postgresql' else 'MySQL'}' de Power BI.\n"
            "- Requiere el driver ODBC del motor instalado en la máquina del gateway.\n"
            "- Recomendado: modo Importación."
        )
    if dialect == "sqlite":
        return (
            "- SQLite no está soportado de forma nativa por Power BI.\n"
            "- No recomendado para clientes BI: migra el DWH a SQL Server (conector nativo)."
        )
    return f"- Dialecto '{dialect}': revisa el conector disponible en Power BI."


def render_guide(config, views=None):
    views = views if views is not None else derived_views(config)
    db = config["database"]
    dialect = db.get("dialect", "mssql")
    lines = [
        "# Guía de conectividad · Power BI",
        "",
        f"Empresa: {config.get('environment', '?')} · BD destino: {dialect}",
        "",
        "## Conexión",
        *guide_text(dialect).splitlines(),
        "",
        "## Vistas disponibles (dataset)",
        "",
        "| Vista | Pestaña | Tabla | Claves |",
        "|-------|---------|-------|--------|",
    ]
    for view in views:
        name = view.get("name", "inv_bodega")
        lines.append(
            f"| {name} | {view_tab_label(view)} | {name} | "
            f"{', '.join(view.get('keys', [])) or '-'} |"
        )
    lines += [
        "",
        "## Publicación",
        "- Abre el archivo .pbix, obtén datos desde la vista que necesites.",
        "- Agrega medidas a medida (servicio Novus) y publica en el Power BI Service.",
        "- El manifiesto (etl bi manifest) lista columnas y medidas sugeridas.",
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bi.py -v`
Expected: 10 passed (7 previos + 3 nuevos).

- [ ] **Step 5: Commit**

```bash
git add bi/guide.py tests/test_bi.py
git commit -m "feat: guía de conectividad BI por dialecto (bi/guide.py)"
```

---
---

## Task 6: CLI subcomando `etl bi`

**Files:**
- Modify: `cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `bi.manifest.build_manifest`, `bi.manifest.manifest_to_json`, `bi.export.export_views`, `bi.guide.render_guide` (Tasks 3-5), `cli._engine_from_config` (existe), `cli._add_config_arg` (existe).
- Produces:
  - `cmd_bi(config_path, action, out_dir) -> int` — action ∈ {manifest, export, guide}. Retorna 0 si OK, 1 si error.
    - `manifest`: imprime el JSON en stdout.
    - `export`: escribe archivos en `out_dir` (default `output/bi`) y lista resultados.
    - `guide`: escribe el markdown en stdout.
  - `bi_parser` en `main()`: subcomando `bi` con sub-subcomandos `manifest|export|guide` y `--out-dir` (solo export).

- [ ] **Step 1: Write the failing test** — ampliar `tests/test_cli.py`:

```python
def _cli_bi_env(tmp_path):
    cfg_path = tmp_path / "config.json"
    db_path = tmp_path / "db.sqlite"
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(db_path)},
        "tables": [], "fields": {},
        "derived": [{"name": "inv_bodega", "keys": ["MATNR"]}],
    }
    cfg_path.write_text(json.dumps(cfg))
    engine = create_engine(f"sqlite:///{db_path}")
    import pandas as pd
    pd.DataFrame([{"MATNR": "M1", "ValorTotal": 1.0}]).to_sql("inv_bodega", engine, index=False)
    return str(cfg_path)


def test_cli_bi_manifest(tmp_path, capsys):
    cfg_path = _cli_bi_env(tmp_path)
    assert cli.cmd_bi(cfg_path, "manifest") == 0
    out = capsys.readouterr().out
    assert '"inv_bodega"' in out
    assert '"materialized": true' in out


def test_cli_bi_export(tmp_path, capsys):
    cfg_path = _cli_bi_env(tmp_path)
    out_dir = str(tmp_path / "bi_out")
    assert cli.cmd_bi(cfg_path, "export", out_dir=out_dir) == 0
    out = capsys.readouterr().out
    assert "inv_bodega" in out
    assert os.path.exists(os.path.join(out_dir, "inv_bodega.csv"))


def test_cli_bi_guide(tmp_path, capsys):
    cfg_path = _cli_bi_env(tmp_path)
    assert cli.cmd_bi(cfg_path, "guide") == 0
    out = capsys.readouterr().out
    assert "Guía de conectividad" in out
    assert "inv_bodega" in out


def test_cli_main_bi(tmp_path, monkeypatch):
    cfg_path = _cli_bi_env(tmp_path)
    captured = {}

    def fake_bi(config_path, action, out_dir="output/bi"):
        captured["config_path"] = config_path
        captured["action"] = action
        captured["out_dir"] = out_dir
        return 0

    monkeypatch.setattr(cli, "cmd_bi", fake_bi)
    assert cli.main(["bi", "manifest", "--config", cfg_path]) == 0
    assert captured == {"config_path": cfg_path, "action": "manifest", "out_dir": "output/bi"}
```

  Nota: añadir `import os` arriba de `tests/test_cli.py` (ya importa `json` y `pytest`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py::test_cli_bi_manifest tests/test_cli.py::test_cli_bi_export tests/test_cli.py::test_cli_bi_guide tests/test_cli.py::test_cli_main_bi -v`
Expected: FAIL — `AttributeError: module 'cli' has no attribute 'cmd_bi'`.

- [ ] **Step 3: Write minimal implementation** — en `cli.py`, añadir tras `cmd_importar_minimos`:

```python
def cmd_bi(config_path, action, out_dir="output/bi"):
    from bi.export import export_views
    from bi.guide import render_guide
    from bi.manifest import build_manifest, manifest_to_json

    config = load_config(config_path)
    engine = _engine_from_config(config)

    if action == "manifest":
        print(manifest_to_json(build_manifest(config, engine)))
        return 0
    if action == "export":
        try:
            results = export_views(config, engine, out_dir=out_dir)
        except ValueError as e:
            print(f"[error] {e}")
            return 1
        for r in results:
            extra = f", parquet={r['parquet_path']}" if r["parquet_path"] else ""
            print(f"[ok] '{r['name']}': {r['rows']} filas -> {r['csv_path']}{extra}")
        return 0
    if action == "guide":
        print(render_guide(config))
        return 0
    print("Uso: etl bi {manifest|export|guide}")
    return 1
```

  Y en `main()`, tras el parser de `importar-minimos`:

```python
    bi_parser = subparsers.add_parser(
        "bi", help="Entregable BI: manifiesto, export y guía de conectividad para Power BI")
    bi_sub = bi_parser.add_subparsers(dest="bi_action", required=True)

    bi_manifest = bi_sub.add_parser("manifest", help="Genera el manifiesto del dataset")
    _add_config_arg(bi_manifest)
    bi_manifest.add_argument("--out", default=None, help=argparse.SUPPRESS)

    bi_export = bi_sub.add_parser("export", help="Exporta las vistas a CSV/Parquet")
    bi_export.add_argument("--out-dir", default="output/bi",
                           help="Directorio de salida (por defecto: output/bi)")
    _add_config_arg(bi_export)

    bi_guide = bi_sub.add_parser("guide", help="Emite la guía de conectividad de Power BI")
    _add_config_arg(bi_guide)
```

  Y en el dispatch de `main()`, tras el bloque de `importar-minimos`:

```python
    if args.command == "bi":
        if args.bi_action == "manifest":
            return cmd_bi(args.config, "manifest")
        if args.bi_action == "export":
            return cmd_bi(args.config, "export", out_dir=args.out_dir)
        if args.bi_action == "guide":
            return cmd_bi(args.config, "guide")
        return 1
```

  (Nota: `required=True` en `add_subparsers` requiere argparse ≥3.7 — OK con Python ≥3.10. El `--out` en manifest queda oculto/SUPPRESS para futura ruta de salida, sin romper la firma actual.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: todos los tests del CLI pasan (previos + 4 nuevos).

- [ ] **Step 5: Commit**

```bash
git add cli.py tests/test_cli.py
git commit -m "feat: CLI etl bi (manifest, export, guide)"
```

---
---

## Task 7: Frontend multi-pestañas del dashboard

**Files:**
- Modify: `dashboard/app.py`
- Create: `dashboard/static/derivadas.html`
- Modify: `dashboard/static/common.css`
- Modify: `dashboard/static/common.js`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `derived.views.derived_views`, `derived.views.view_tab_label` (Task 1).
- Produces:
  - `app.get("/derivadas")` — página HTML de pestañas derivadas (requiere `current_user_or_none`; redirect a `/login` si no autenticado). Rol `user` y `admin` permitidos.
  - `app.get("/api/derived-views")` — `user=Depends(require_user)`; devuelve `{"views": [{"name", "tab", "table"}...]}` desde `derived_views(config)`.
  - En `common.js`: `renderBranding(meta)` — pinta título/color/footer desde un objeto `{title, color, footer}`.

- [ ] **Step 1: Write the failing test** — ampliar `tests/test_dashboard.py`:

```python
def test_derived_views_endpoint(inventory_client):
    res = inventory_client.get("/api/derived-views")
    assert res.status_code == 200
    data = res.json()
    assert data["views"][0]["name"] == "inv_bodega"
    assert data["views"][0]["tab"] == "Inv Bodega"
    assert data["views"][0]["table"] == "inv_bodega"


def test_derivadas_page_served(client):
    res = client.get("/derivadas", follow_redirects=False)
    assert res.status_code == 200
    assert "Pestañas" in res.text or "derivada" in res.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard.py::test_derived_views_endpoint tests/test_dashboard.py::test_derivadas_page_served -v`
Expected: FAIL — endpoint y página no existen.

- [ ] **Step 3: Write minimal implementation**

  En `dashboard/app.py`, tras `page_panel`:

```python
@app.get("/api/derived-views")
def api_derived_views(user=Depends(require_user)):
    config = load_config(os.environ.get("ETL_CONFIG"))
    views = [{"name": v.get("name", "inv_bodega"), "tab": view_tab_label(v),
              "table": v.get("name", "inv_bodega")} for v in derived_views(config)]
    return {"views": views}


@app.get("/derivadas", response_class=HTMLResponse, include_in_schema=False)
def page_derivadas(user=Depends(current_user_or_none)):
    if user is None:
        return RedirectResponse(url="/login", status_code=307)
    return _page("derivadas.html")
```

  (Añadir `from derived.views import derived_views, view_tab_label` en el import de `_first_derived_view` — el módulo ya importa `from derived.views import derived_views` dentro de `_first_derived_view`; subir al top-level y reutilizar.)

  Crear `dashboard/static/derivadas.html` (página genérica de pestañas; reutiliza el patrón de inventario.html pero con pestañas dinámicas y columnas genéricas):

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vistas · ETL Dashboard</title>
  <link rel="stylesheet" href="/static/common.css">
</head>
<body>
  <header>
    <h1 id="appTitle">ETL Dashboard</h1>
    <div class="userbar" id="userbar"></div>
  </header>
  <nav id="tabs" class="tabs"></nav>
  <main>
    <div id="kpis" class="cards"></div>
    <div id="viewBody">
      <div id="viewMessage">Cargando…</div>
    </div>
  </main>
  <footer id="appFooter"></footer>
  <script src="/static/common.js"></script>
  <script src="/static/derivadas.js"></script>
</body>
</html>
```

  Crear `dashboard/static/derivadas.js`:

```javascript
let views = [];
let activeView = null;

function tabLabel(name) {
  return name.split('_').map(function (w) {
    return w.charAt(0).toUpperCase() + w.slice(1);
  }).join(' ');
}

async function loadViews() {
  const res = await api('/api/derived-views');
  const data = await res.json();
  views = data.views || [];
  const nav = document.getElementById('tabs');
  nav.innerHTML = views.map(function (v) {
    const label = v.tab || tabLabel(v.name);
    return '<button class="tab' + (v.name === activeView ? ' active' : '') +
      '" onclick="selectView(\'' + v.name + '\')">' + label + '</button>';
  }).join('');
  if (!activeView && views.length) selectView(views[0].name);
}

async function selectView(name) {
  activeView = name;
  document.getElementById('viewBody').innerHTML =
    '<div id="viewMessage">Cargando…</div>';
  const res = await api('/api/derived/' + name + '/summary');
  const sum = await res.json();
  const body = document.getElementById('viewBody');
  if (!sum.available) {
    body.innerHTML = '<div id="viewMessage">Datos no disponibles (' + name + ')</div>';
    loadViews();
    return;
  }
  const kpis = document.getElementById('kpis');
  kpis.innerHTML =
    '<div class="card"><div class="label">Filas</div><div class="value">' + sum.total_rows + '</div></div>' +
    '<div class="card"><div class="label">Total</div><div class="value">' + formatMoney(sum.total_value) + '</div></div>' +
    '<div class="card"><div class="label">Alertas</div><div class="value">' + sum.alerts_count + '</div></div>';
  body.innerHTML = '<div id="viewMessage">Filtros y detalle por vista disponibles vía /api/derived/' + name + '/items</div>';
  loadViews();
}

function initDerivadas() {
  renderBranding();
  loadViews();
}

document.addEventListener('DOMContentLoaded', initDerivadas);
```

  En `common.js`:

```javascript
function renderBranding() {
  fetch('/api/branding').then(function (r) { return r.json(); }).then(function (b) {
    if (b.title) document.title = b.title;
    const t = document.getElementById('appTitle');
    if (t && b.title) t.textContent = b.title;
    const f = document.getElementById('appFooter');
    if (f && b.footer) f.textContent = b.footer;
  }).catch(function () {});
}
```

  (El endpoint `/api/branding` se implementa en Task 8. `renderBranding` tolera su ausencia.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: todos pasan (previos + 2 nuevos). Los tests JS no se ejecutan en pytest (validación manual en navegador o Playwright en Task 10).

- [ ] **Step 5: Commit**

```bash
git add dashboard/app.py dashboard/static/derivadas.html dashboard/static/derivadas.js dashboard/static/common.js tests/test_dashboard.py
git commit -m "feat: dashboard multi-pestañas por vista derivada"
```

---
---

## Task 8: Branding por config (`/api/branding` + pestaña `#etl` solo admin)

**Files:**
- Modify: `dashboard/app.py`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `load_config` (existe).
- Produces:
  - `app.get("/api/branding")` — sin auth (público, solo metadata de marca); devuelve `{"title", "logo", "color", "footer"}` desde `config.get("dashboard", {})`, con defaults neutros `title="ETL Dashboard"`, `color=""`, `footer=""`, `logo=""`.
  - La página `/etl` mantiene `require admin` (ya está). Confirmar que `page_etl` no cambia.

- [ ] **Step 1: Write the failing test** — ampliar `tests/test_dashboard.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard.py::test_branding_defaults tests/test_dashboard.py::test_branding_from_config -v`
Expected: FAIL — `/api/branding` devuelve 404.

- [ ] **Step 3: Write minimal implementation** — en `dashboard/app.py`, junto a `/api/health`:

```python
@app.get("/api/branding")
def api_branding():
    config = load_config(os.environ.get("ETL_CONFIG"))
    dash = config.get("dashboard") or {}
    return {
        "title": dash.get("title", "ETL Dashboard"),
        "logo": dash.get("logo", ""),
        "color": dash.get("color", ""),
        "footer": dash.get("footer", ""),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: todos pasan (previos + 2 nuevos).

- [ ] **Step 5: Commit**

```bash
git add dashboard/app.py tests/test_dashboard.py
git commit -m "feat: branding por config (/api/branding)"
```

---
---

## Task 9: Schema, config de ejemplo y docs

**Files:**
- Modify: `schemas/config.schema.json`
- Modify: `config.example.json`
- Modify: `README.md`
- Test: `tests/test_config_schema.py`

**Interfaces:**
- Consumes: schema actual (`derived_view` definition), `jsonschema` (ya dependencia).
- Produces: schema extendido con `tab` (string opcional), `row_label` (string opcional) en `derived_view`, y `dashboard` (objeto con `title`/`logo`/`color`/`footer` opcionales) en la raíz.

- [ ] **Step 1: Write the failing test** — ampliar `tests/test_config_schema.py`. Primero revisar cómo se estructura hoy:

```bash
grep -n "def test" tests/test_config_schema.py
```

  Añadir (asumiendo helpers existentes `validate_config` importada de `utils.config_validation`):

```python
def test_schema_accepts_tab_and_row_label():
    from utils.config_validation import validate_config
    config = {
        "source": {"type": "csv", "config": {}},
        "database": {"dialect": "sqlite", "database": "x.db"},
        "tables": [], "fields": {},
        "derived": {"name": "inv_bodega", "tab": "Inventario", "row_label": "MATNR",
                    "columns": [{"as": "MATNR", "source": "MATNR"}]},
        "dashboard": {"title": "ACME", "logo": "/l.png", "color": "#fff", "footer": "©"},
    }
    assert validate_config(config) == []


def test_schema_accepts_derived_list():
    from utils.config_validation import validate_config
    config = {
        "source": {"type": "csv", "config": {}},
        "database": {"dialect": "sqlite", "database": "x.db"},
        "tables": [], "fields": {},
        "derived": [{"name": "a"}, {"name": "b", "tab": "B"}],
    }
    assert validate_config(config) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_schema.py -v`
Expected: FAIL — `validate_config(config) != []` (schema rechaza `tab`/`row_label`/`dashboard`).

- [ ] **Step 3: Write minimal implementation**

  En `schemas/config.schema.json`:
  - En la raíz `properties`, añadir:
    ```json
    "dashboard": {
      "type": "object",
      "properties": {
        "title": { "type": "string" },
        "logo": { "type": "string" },
        "color": { "type": "string" },
        "footer": { "type": "string" }
      },
      "additionalProperties": true
    }
    ```
  - En `definitions.derived_view.properties`, añadir:
    ```json
    "tab": { "type": "string" },
    "row_label": { "type": "string" }
    ```

  En `config.example.json`, añadir tras `"derived"` (y antes del cierre):
  - Un bloque `"dashboard"` de ejemplo:
    ```json
    "dashboard": {
      "title": "Mi Empresa · Novus BI",
      "logo": "",
      "color": "#0f4c81",
      "footer": "Novus IT · Datos e Inteligencia de Negocios"
    }
    ```
  - En la vista derivada de ejemplo, añadir `"tab": "Inventario"` y `"row_label": "MATNR"`.

  En `README.md`: sección breve "Entregable BI" documentando `etl bi manifest|export|guide`, la guía de conectividad por dialecto, y el onboarding por empresa (config → migrate → bootstrap → reporte/bi). Referenciar el spec en `docs/superpowers/specs/`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config_schema.py -v` y luego `python -m pytest tests/test_config_schema.py tests/test_bi.py tests/test_cli.py tests/test_dashboard.py -v`
Expected: todos pasan.

- [ ] **Step 5: Commit**

```bash
git add schemas/config.schema.json config.example.json README.md tests/test_config_schema.py
git commit -m "docs: schema (tab/row_label/dashboard), config de ejemplo y README BI"
```

---
---

## Task 10: Verificación final de la suite y lint

**Files:**
- Ninguno (solo ejecución).

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest`
Expected: 207 + nuevos tests pasan, 0 failed. Reportar el conteo exacto.

- [ ] **Step 2: Run ruff**

Run: `ruff check .`
Expected: `All checks passed!` (0 errores).

- [ ] **Step 3: Smoke test CLI en vivo**

Run:
```bash
python -m cli bi manifest --config config.example.json 2>&1 | head -30
python -m cli bi guide --config config.example.json 2>&1 | head -20
python -m cli bi export --out-dir /tmp/bi_smoke --config config.example.json 2>&1
```
Expected: sin excepciones; manifiesto y guía imprimen contenido; export advierte (vistas no materializadas contra config.example no conectado) o exporta si hay BD local.

- [ ] **Step 4: Smoke test dashboard multi-pestañas (opcional, si hay navegador/Playwright)**

Run: `python -m uvicorn dashboard.app:app` con `ETL_CONFIG` apuntando a una BD con 2+ vistas, abrir `/derivadas`. Validar pestañas, KPIs y `/api/branding`.

- [ ] **Step 5: Commit final**

```bash
git add -A
git status
git commit -m "chore: verificación final entregable BI"
```
  Solo si hay cambios pendientes tras el smoke test (p. ej. fixes). Si el árbol está limpio, no se commitea nada.

---
---

## Self-Review (ejecutado por el autor del plan)

**Spec coverage:**
- Sección 1 (`bi/`): Tasks 3 (manifest), 4 (export), 5 (guide) ✓
- Sección 2 (dashboard pestañas + branding): Tasks 1-2 (backend por vista), 7 (frontend multi-pestaña), 8 (branding), `#etl` admin solo ya existente ✓
- Sección 3 (config por empresa, schema, onboarding): Task 9 ✓
- Sección 4 (CLI `etl bi`): Task 6 ✓
- Sección 5 (errores + testing): integrado en cada task (vista faltante → warning no aborta en export; 404 en endpoints; validación schema) + Task 10 ✓
- `modules` documental: no se valida — fuera de alcance explícito ✓
- Retrocompatibilidad `/api/inventory*`: Task 2 mantiene `_inventory_frame` wrapper ✓

**Placeholder scan:** sin TBD/TODO; todo paso tiene código real. La nota "revisar cómo se estructura test_config_schema" usa un `grep` concreto (instrucción ejecutable, no placeholder). ✓

**Type consistency:**
- `view_tab_label(view) -> str`, `derived_view_by_name(config, name)` definidos en Task 1, usados en Tasks 2, 3, 5, 7 — firmas idénticas. ✓
- `export_views(config, engine, out_dir, views=None)` — Task 4 define, Task 6 consume con `out_dir=`. ✓
- `cmd_bi(config_path, action, out_dir="output/bi")` — Task 6 define, test lo llama igual. ✓
- `build_manifest(config, engine, views=None)` / `manifest_to_json(manifest)` — consistentes Task 3→6. ✓
- `render_guide(config, views=None)` — Task 5 define, Task 6 consume. ✓
- `api_derived_items` devuelve dict con `available`/`rows`; `api_derived_alerts` maneja el caso `available: False`. ✓
