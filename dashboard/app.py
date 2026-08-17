"""Dashboard web del motor ETL: lee etl_execution/etl_progress de la BD destino.

No requiere el SDK de SAP; basta con acceso de lectura a la base de datos.
"""

import os
import signal
import subprocess
import sys
import time

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from dashboard import auth as auth_pkg
from dashboard.auth import require_admin, require_user
from dashboard.auth.dependencies import current_user_or_none
from db.db_connection import _connection_string
from derived.views import derived_views, view_tab_label
from licensing.client import LicenseError, get_manager
import functools
from licensing.models import LicenseState
from utils.config_loader import load_config
from utils.live import _live_file, read_live, update_live


@functools.lru_cache(maxsize=None)
def require_license_module(module: str, admin_only: bool = False):
    """FastAPI dependency factory: returns user if module is entitled, raises 403 otherwise."""
    def dependency(user=Depends(require_admin if admin_only else require_user)):
        config = load_config(os.environ.get("ETL_CONFIG"))
        try:
            lic = get_manager(config).get_license()
        except LicenseError as exc:
            raise HTTPException(status_code=403, detail="licencia_no_verificable") from exc
        state = lic.state(time.time())
        if state in (LicenseState.EXPIRED, LicenseState.SUSPENDED, LicenseState.REVOKED):
            raise HTTPException(status_code=403, detail=f"licencia:{state.value}")
        if not lic.has(module):
            raise HTTPException(status_code=403, detail=f"modulo_no_contratado:{module}")
        return user
    return dependency


def _docs_enabled() -> bool:
    env = os.environ.get("ENVIRONMENT", "dev").lower()
    return env == "dev" or os.environ.get("ETL_DOCS_ENABLED", "").lower() in ("1", "true", "yes")


docs_url = "/docs" if _docs_enabled() else None
redoc_url = "/redoc" if _docs_enabled() else None
openapi_url = "/openapi.json" if _docs_enabled() else None

app = FastAPI(title="ETL Dashboard", docs_url=docs_url, redoc_url=redoc_url, openapi_url=openapi_url)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response


app.include_router(auth_pkg.router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# PID del último ETL disparado por el botón Sincronizar (para vigilar/recolectar).
_SPAWNED_PID = {"pid": None}

# Si el ETL lleva más tiempo que esto sin tocar el archivo de estado, se
# considera colgado (una corrida normal dura ~20 s) y se fuerza su fin.
_STALE_SECONDS = 120

# Lock local de etl_runner.acquire_lock; se limpia solo si su dueño murió.
_ETL_LOCK_FILE = "/tmp/etl_sap.lock"


def get_engine():
    config = load_config(os.environ.get("ETL_CONFIG"))
    kwargs = {}
    if config["database"].get("dialect", "mssql") == "mssql":
        kwargs["fast_executemany"] = True
    return create_engine(_connection_string(config["database"]), **kwargs)


auth_pkg.set_engine_provider(get_engine)


def _child_status():
    """Estado del hijo disparado: 'running', 'exited' (código), 'signaled' (señal) o 'gone'.

    Usa waitpid(WNOHANG): reapa el zombie si el hijo ya murió.
    """
    pid = _SPAWNED_PID["pid"]
    if not pid:
        return None, None
    try:
        wpid, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        _SPAWNED_PID["pid"] = None
        return "gone", None
    if wpid == 0:
        return "running", None
    _SPAWNED_PID["pid"] = None
    if os.WIFEXITED(status):
        return "exited", os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return "signaled", os.WTERMSIG(status)
    return "exited", None


def _mark_run_failed(run_id):
    if not run_id:
        return
    try:
        engine = get_engine()
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE etl_execution SET status='failed', end_time=CURRENT_TIMESTAMP "
                "WHERE id=:rid AND status='running'"
            ), {"rid": run_id})
    except Exception:
        pass


def _clear_etl_lock(owner_pid):
    """Elimina el lock local de etl_runner solo si su dueño ya no existe.

    owner_pid puede ser None (proceso no rastreado): se limpia si el PID del
    lock tampoco está vivo.
    """
    if not os.path.exists(_ETL_LOCK_FILE):
        return
    try:
        with open(_ETL_LOCK_FILE) as f:
            lock_pid = int((f.read().strip() or "0"))
    except Exception:
        return

    def alive(pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        try:
            with open(f"/proc/{pid}/stat") as f:
                return f.read().split()[2] != "Z"
        except Exception:
            return True

    if lock_pid == owner_pid or (not alive(lock_pid)):
        try:
            os.remove(_ETL_LOCK_FILE)
        except OSError:
            pass


def _recover_stale():
    """Detecta un estado 'running' huérfano y lo limpia.

    Se llama en /api/live y /api/etl/trigger. Si el hijo murió (crash/senal) o
    lleva demasiado tiempo sin avanzar, marca la corrida como failed y deja el
    estado idle para que el dashboard se recupere solo.
    """
    live = read_live()
    if not live.get("running"):
        return

    pid = _SPAWNED_PID["pid"]
    state, code = _child_status()
    path = _live_file()
    live_age = time.time() - os.path.getmtime(path) if os.path.exists(path) else time.time()

    if state not in ("exited", "signaled", "gone") and live_age <= _STALE_SECONDS:
        return

    if state == "running":
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    _clear_etl_lock(pid)
    update_live(
        running=False, run_id=live.get("run_id"), table=None, phase="error",
        chunk_index=0, chunk_total=0, rows_so_far=0, elapsed_s=0,
    )
    _mark_run_failed(live.get("run_id"))
    _SPAWNED_PID["pid"] = None
    return {"run_id": live.get("run_id"), "state": state, "code": code}


class ProgressItem(BaseModel):
    table_name: str
    status: str
    rows_loaded: int
    last_delta_value: str
    updated_at: str


class ExecutionItem(BaseModel):
    id: int
    status: str
    start_time: str
    end_time: str


class DashboardData(BaseModel):
    executions: list
    progress: list
    last_execution: dict


def _last_execution():
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, status, start_time, end_time "
                 "FROM etl_execution ORDER BY id DESC LIMIT 1"),
        ).fetchone()
    if row is None:
        return None
    return {"id": row.id, "status": row.status,
            "start_time": str(row.start_time), "end_time": str(row.end_time or "")}


@app.get("/api/executions")
def api_executions(last: int = 10, user=Depends(require_license_module("dashboard", admin_only=True))):
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, status, start_time, end_time "
                 "FROM etl_execution ORDER BY id DESC LIMIT :n"),
            {"n": last},
        ).fetchall()
    return [ExecutionItem(id=r.id, status=r.status,
                          start_time=str(r.start_time),
                          end_time=str(r.end_time or "")).model_dump() for r in rows]


@app.get("/api/progress")
def api_progress(user=Depends(require_license_module("dashboard", admin_only=True))):
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name, status, rows_loaded, last_delta_value, updated_at "
                 "FROM etl_progress ORDER BY table_name"),
            {"n": 0},
        ).fetchall()
    return [ProgressItem(table_name=r.table_name, status=str(r.status or ""),
                         rows_loaded=r.rows_loaded or 0,
                         last_delta_value=str(r.last_delta_value or ""),
                         updated_at=str(r.updated_at or "")).model_dump() for r in rows]


@app.get("/api/dashboard")
def api_dashboard(user=Depends(require_license_module("dashboard", admin_only=True))):
    engine = get_engine()
    with engine.connect() as conn:
        runs = conn.execute(
            text("SELECT id, status, start_time, end_time "
                 "FROM etl_execution ORDER BY id DESC LIMIT 10"),
        ).fetchall()
        prog = conn.execute(
            text("SELECT table_name, status, rows_loaded, last_delta_value, updated_at "
                 "FROM etl_progress ORDER BY table_name"),
        ).fetchall()
    last = runs[0] if runs else None

    def row_dict(r):
        return dict(zip(r._mapping.keys(), r))

    return DashboardData(
        executions=[row_dict(r) for r in runs],
        progress=[row_dict(p) for p in prog],
        last_execution=row_dict(last) if last else {},
    ).model_dump()


@app.get("/api/health")
def api_health():
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}


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


@app.get("/api/live")
def api_live(user=Depends(require_license_module("dashboard"))):
    _recover_stale()
    return read_live()


@app.get("/api/last-sync")
def api_last_sync(user=Depends(require_license_module("dashboard"))):
    return _last_execution()


@app.get("/api/tables")
def api_tables(run_id: int, user=Depends(require_license_module("dashboard", admin_only=True))):
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name, chunks_total, chunks_ok, rows_extracted, duration_s, status "
                 "FROM etl_execution_tables WHERE run_id = :n ORDER BY table_name"),
            {"n": run_id},
        ).fetchall()
    return [dict(zip(r._mapping.keys(), r)) for r in rows]


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


def _inventory_alerts_config(view):
    alerts = view.get("alerts", {}) or {}
    return {
        "min_field": alerts.get("min_field", "stock_minimo"),
        "qty_field": alerts.get("qty_field", "StockLibre"),
        "total_field": alerts.get("total_field", "ValorTotal"),
    }


def _inventory_filter_columns(view):
    filters = (view.get("inventory", {}) or {}).get("filters", {}) or {}
    return {
        "centro": filters.get("centro", "Centro"),
        "almacen": filters.get("almacen", "Almacen"),
        "area": filters.get("area", "Area"),
    }


def _view_columns(view):
    """Columnas de presentación de una visión derivada (etiqueta, oculta, respaldo).

    Se derivan de `derived.columns` del config; sin columnas declaradas devuelve [].
    """
    out = []
    for c in view.get("columns", []):
        as_name = c.get("as")
        if not as_name:
            continue
        out.append({
            "as": as_name,
            "label": c.get("label") or as_name,
            "hidden": bool(c.get("hide")),
            "fallback": c.get("fallback"),
        })
    return out


def _coerce_numeric(df, fields):
    for f in fields:
        if f in df.columns:
            df[f] = pd.to_numeric(df[f], errors="coerce")


def _inventory_alert_mask(df, cfg):
    min_field, qty_field = cfg["min_field"], cfg["qty_field"]
    mask = pd.Series(False, index=df.index)
    if min_field in df.columns and qty_field in df.columns:
        mask = df[min_field].notna() & (df[qty_field] < df[min_field])
    return mask


def _filter_inventory(df, view, centro="", almacen="", area="", low_only=False, q=""):
    cols = _inventory_filter_columns(view)
    cfg = _inventory_alerts_config(view)
    _coerce_numeric(df, [cfg["min_field"], cfg["qty_field"], cfg["total_field"]])

    mask = pd.Series(True, index=df.index)
    for value, col in ((centro, cols["centro"]), (almacen, cols["almacen"]),
                       (area, cols["area"])):
        if value and col in df.columns:
            mask &= df[col].astype(str) == value
    if low_only:
        mask &= _inventory_alert_mask(df, cfg)
    if q:
        subset = df[mask]
        if len(subset):
            haystack = subset.astype(str).apply(lambda c: c.str.contains(q, case=False, regex=False))
            mask.iloc[subset.index] = haystack.any(axis=1)
    return df[mask], cfg, cols


def _inventory_summary(df, view):
    cfg = _inventory_alerts_config(view)
    total_field = cfg["total_field"]
    _coerce_numeric(df, [total_field, cfg["qty_field"], cfg["min_field"]])
    total_rows = int(len(df))
    row_label = view.get("row_label", "MATNR")
    materials = int(df[row_label].nunique()) if row_label in df.columns else total_rows
    total_value = float(df[total_field].fillna(0).sum()) if total_field in df.columns else 0.0
    alerts = df[_inventory_alert_mask(df, cfg)]
    risk = float(alerts[total_field].fillna(0).sum()) if total_field in alerts.columns else 0.0
    return {
        "available": True,
        "table": view.get("name", "inv_bodega"),
        "total_materials": materials,
        "total_rows": total_rows,
        "total_value": round(total_value, 2),
        "alerts_count": int(len(alerts)),
        "risk_value": round(risk, 2),
    }


@app.get("/api/inventory")
def api_inventory(user=Depends(require_license_module("dashboard"))):
    df, view = _inventory_frame()
    if view is None:
        return {"available": False, "reason": "no_derived"}
    if df is None:
        return {"available": False, "reason": "table_missing",
                "table": view.get("name", "inv_bodega")}
    return _inventory_summary(df, view)


@app.get("/api/inventory/filters")
def api_inventory_filters(user=Depends(require_license_module("dashboard"))):
    df, view = _inventory_frame()
    if view is None or df is None:
        return {"available": False}
    cols = _inventory_filter_columns(view)
    out = {}
    for key, col in cols.items():
        if col in df.columns:
            values = df[col].dropna().astype(str).unique().tolist()
            out[key] = sorted(values)
        else:
            out[key] = []
    out["available"] = True
    out["columns"] = cols
    return out


@app.get("/api/inventory/items")
def api_inventory_items(centro: str = "", almacen: str = "", area: str = "",
                        low_only: bool = False, q: str = "",
                        limit: int = 100, offset: int = 0,
                        user=Depends(require_license_module("dashboard"))):
    df, view = _inventory_frame()
    if view is None:
        return {"available": False, "reason": "no_derived"}
    if df is None:
        return {"available": False, "reason": "table_missing",
                "table": view.get("name", "inv_bodega")}

    rows, cfg, cols = _filter_inventory(df, view, centro, almacen, area, low_only, q)
    total = int(len(rows))
    low_only_count = int(len(rows[_inventory_alert_mask(rows, cfg)]))
    page = rows.iloc[offset:offset + limit].fillna("")
    return {
        "available": True,
        "table": view.get("name", "inv_bodega"),
        "total": total,
        "offset": offset,
        "limit": limit,
        "low_only_count": low_only_count,
        "rows": page.to_dict(orient="records"),
    }


@app.get("/api/inventory/alerts")
def api_inventory_alerts(limit: int = 500, q: str = "", user=Depends(require_license_module("dashboard"))):
    data = api_inventory_items(low_only=True, q=q, limit=limit, offset=0)
    return {"alerts": data.get("rows", [])}


@app.get("/api/derived/{name}/summary")
def api_derived_summary(name: str, user=Depends(require_license_module("dashboard"))):
    df, view = _inventory_frame_for(name)
    if view is None:
        raise HTTPException(status_code=404, detail="vista_inexistente")
    if df is None:
        return {"available": False, "reason": "table_missing", "table": name}
    return _inventory_summary(df, view)


@app.get("/api/derived/{name}/filters")
def api_derived_filters(name: str, user=Depends(require_license_module("dashboard"))):
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
                      user=Depends(require_license_module("dashboard"))):
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
def api_derived_alerts(name: str, limit: int = 500, q: str = "", user=Depends(require_license_module("dashboard"))):
    data = api_derived_items(name=name, low_only=True, q=q, limit=limit, offset=0)
    if isinstance(data, dict) and data.get("available") is False:
        return {"alerts": []}
    return {"alerts": data.get("rows", [])}


@app.get("/api/derived/{name}/export/excel")
def api_derived_export_excel(name: str, user=Depends(require_license_module("dashboard"))):
    df, view = _inventory_frame_for(name)
    if view is None:
        raise HTTPException(status_code=404, detail="vista_inexistente")
    if df is None:
        raise HTTPException(status_code=404, detail="tabla_no_materializada")
    from derived.excel_export import export_inventory_excel
    path = export_inventory_excel(df, view)
    filename = f"{name}.xlsx"
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


@app.get("/api/derived/{name}/export/csv")
def api_derived_export_csv(name: str, user=Depends(require_license_module("dashboard"))):
    df, view = _inventory_frame_for(name)
    if view is None:
        raise HTTPException(status_code=404, detail="vista_inexistente")
    if df is None:
        raise HTTPException(status_code=404, detail="tabla_no_materializada")

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )


@app.get("/api/bi/manifest")
def api_bi_manifest(user=Depends(require_license_module("bi"))):
    config = load_config(os.environ.get("ETL_CONFIG"))
    engine = get_engine()
    from bi.manifest import build_manifest
    return build_manifest(config, engine)


@app.get("/api/bi/guide")
def api_bi_guide(user=Depends(require_license_module("bi"))):
    config = load_config(os.environ.get("ETL_CONFIG"))
    from bi.guide import render_guide
    guide_md = render_guide(config)
    return {"guide_markdown": guide_md}


@app.post("/api/bi/export")
def api_bi_export(user=Depends(require_license_module("bi"))):
    config = load_config(os.environ.get("ETL_CONFIG"))
    engine = get_engine()
    from bi.export import export_views
    from bi.manifest import build_manifest, manifest_to_json
    from bi.guide import render_guide

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "bi")
    os.makedirs(out_dir, exist_ok=True)

    try:
        results = export_views(config, engine, out_dir=out_dir)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    manifest = build_manifest(config, engine)
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        fh.write(manifest_to_json(manifest))

    guide_path = os.path.join(out_dir, "GUIA_CONEXION_POWER_BI.md")
    with open(guide_path, "w", encoding="utf-8") as fh:
        fh.write(render_guide(config))

    return {
        "ok": True,
        "out_dir": out_dir,
        "files": results,
        "manifest": manifest,
    }


@app.get("/api/bi/download/{view_name}/parquet")
def api_bi_download_parquet(view_name: str, user=Depends(require_license_module("bi"))):
    config = load_config(os.environ.get("ETL_CONFIG"))
    engine = get_engine()
    from derived.db import read_table, table_exists
    if not table_exists(engine, view_name):
        raise HTTPException(status_code=404, detail="vista_no_materializada")
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        raise HTTPException(status_code=501, detail="pyarrow_no_disponible")
    df = read_table(engine, view_name)
    import io
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.apache.parquet",
        headers={"Content-Disposition": f'attachment; filename="{view_name}.parquet"'},
    )


@app.get("/api/bi/download/{view_name}/csv")
def api_bi_download_csv(view_name: str, user=Depends(require_license_module("bi"))):
    config = load_config(os.environ.get("ETL_CONFIG"))
    engine = get_engine()
    from derived.db import read_table, table_exists
    if not table_exists(engine, view_name):
        raise HTTPException(status_code=404, detail="vista_no_materializada")
    df = read_table(engine, view_name)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{view_name}.csv"'},
    )


@app.get("/api/bi/download/manifest")
def api_bi_download_manifest(user=Depends(require_license_module("bi"))):
    config = load_config(os.environ.get("ETL_CONFIG"))
    engine = get_engine()
    from bi.manifest import build_manifest, manifest_to_json
    manifest = build_manifest(config, engine)
    return Response(
        content=manifest_to_json(manifest).encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="manifest.json"'},
    )


@app.get("/api/bi/download/guide")
def api_bi_download_guide(user=Depends(require_license_module("bi"))):
    config = load_config(os.environ.get("ETL_CONFIG"))
    from bi.guide import render_guide
    guide_md = render_guide(config)
    return Response(
        content=guide_md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="GUIA_CONEXION_POWER_BI.md"'},
    )


@app.get("/api/bi/download-zip")
def api_bi_download_zip(user=Depends(require_license_module("bi"))):
    import io
    import zipfile
    config = load_config(os.environ.get("ETL_CONFIG"))
    engine = get_engine()
    from bi.export import export_views
    from bi.manifest import build_manifest, manifest_to_json
    from bi.guide import render_guide

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "bi")
    os.makedirs(out_dir, exist_ok=True)

    try:
        results = export_views(config, engine, out_dir=out_dir)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    manifest = build_manifest(config, engine)
    guide_text = render_guide(config)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for res in results:
            if res.get("csv_path") and os.path.exists(res["csv_path"]):
                zip_file.write(res["csv_path"], arcname=os.path.basename(res["csv_path"]))
            if res.get("parquet_path") and os.path.exists(res["parquet_path"]):
                zip_file.write(res["parquet_path"], arcname=os.path.basename(res["parquet_path"]))
        zip_file.writestr("manifest.json", manifest_to_json(manifest))
        zip_file.writestr("GUIA_CONEXION_POWER_BI.md", guide_text)

    zip_buffer.seek(0)
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="novus_power_bi_dataset.zip"'},
    )


@app.post("/api/etl/trigger")
def api_etl_trigger(user=Depends(require_license_module("dashboard", admin_only=True))):
    _recover_stale()

    live = read_live()
    if live.get("running"):
        return JSONResponse(
            {"ok": False, "reason": "already_running", "run_id": live.get("run_id")},
            status_code=409,
        )

    try:
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT id FROM etl_execution WHERE status='running' "
                "ORDER BY id DESC LIMIT 1"
            )).fetchone()
    except Exception:
        row = None
    if row is not None:
        return JSONResponse(
            {"ok": False, "reason": "already_running", "run_id": row[0]},
            status_code=409,
        )

    config_path = os.environ.get("ETL_CONFIG") or "config.json"
    env = dict(os.environ)
    env["ETL_CONFIG"] = config_path

    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "etl_sync.log")
    try:
        with open(log_path, "a") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "cli", "run", "--config", config_path],
                env=env, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as e:
        return JSONResponse(
            {"ok": False, "reason": "spawn_error", "error": str(e)}, status_code=500
        )

    _SPAWNED_PID["pid"] = proc.pid
    return {"ok": True, "pid": proc.pid}


class SapConfigRequest(BaseModel):
    ashost: str
    sysnr: str = "00"
    client: str = "100"
    user: str
    passwd: str
    lang: str = "ES"


@app.get("/api/onboarding/status")
def api_onboarding_status(user=Depends(require_license_module("dashboard", admin_only=True))):
    config = load_config(os.environ.get("ETL_CONFIG"))
    source = config.get("source", {})
    src_type = source.get("type", "csv")
    src_cfg = source.get("config", {})
    configured = bool(src_cfg.get("ashost") and src_cfg.get("user")) if src_type == "sap" else True
    return {
        "source_type": src_type,
        "configured": configured,
        "ashost": src_cfg.get("ashost", ""),
        "sysnr": src_cfg.get("sysnr", "00"),
        "client": src_cfg.get("client", "100"),
        "user": src_cfg.get("user", ""),
        "lang": src_cfg.get("lang", "ES"),
        "has_password": bool(src_cfg.get("passwd")),
    }


@app.post("/api/onboarding/test-sap")
def api_onboarding_test_sap(body: SapConfigRequest, user=Depends(require_license_module("dashboard", admin_only=True))):
    start = time.perf_counter()
    sap_cfg = {
        "ashost": body.ashost.strip(),
        "sysnr": body.sysnr.strip() or "00",
        "client": body.client.strip() or "100",
        "user": body.user.strip(),
        "passwd": body.passwd,
        "lang": body.lang.strip().upper() or "ES",
    }
    if not sap_cfg["ashost"] or not sap_cfg["user"]:
        raise HTTPException(status_code=400, detail="faltan_parametros_obligatorios")

    try:
        from sources.sap.connector import SAPConnector
        conn = SAPConnector(sap_cfg)
        conn.connect()
        conn.ping()
        conn.close()
        latency = round((time.perf_counter() - start) * 1000, 2)
        return {"ok": True, "latency_ms": latency, "message": f"Conexión exitosa con SAP ({latency} ms)"}
    except ImportError:
        return JSONResponse(
            status_code=501,
            content={"ok": False, "error": "pyrfc_not_installed", "message": "El SDK de SAP NW RFC no está instalado en este entorno."},
        )
    except Exception as exc:
        latency = round((time.perf_counter() - start) * 1000, 2)
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "sap_connection_error", "message": str(exc), "latency_ms": latency},
        )


@app.post("/api/onboarding/save-sap")
def api_onboarding_save_sap(body: SapConfigRequest, user=Depends(require_license_module("dashboard", admin_only=True))):
    import json
    config_path = os.environ.get("ETL_CONFIG") or "config.json"
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="config_no_encontrado")

    with open(config_path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    if not isinstance(cfg.get("source"), dict):
        cfg["source"] = {"type": "sap", "config": {}}
    cfg["source"]["type"] = "sap"
    src_cfg = cfg["source"].setdefault("config", {})
    src_cfg["ashost"] = body.ashost.strip()
    src_cfg["sysnr"] = body.sysnr.strip() or "00"
    src_cfg["client"] = body.client.strip() or "100"
    src_cfg["user"] = body.user.strip()
    if body.passwd:
        src_cfg["passwd"] = body.passwd
    src_cfg["lang"] = body.lang.strip().upper() or "ES"

    with open(config_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)

    return {"ok": True, "message": "Configuración SAP guardada correctamente"}


def _page(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", name)
    return FileResponse(path)


def _check_page_license():
    config = load_config(os.environ.get("ETL_CONFIG"))
    try:
        lic = get_manager(config).get_license()
    except LicenseError:
        return False
    state = lic.state(time.time())
    if state in (LicenseState.EXPIRED, LicenseState.SUSPENDED, LicenseState.REVOKED):
        return False
    if not lic.has("dashboard"):
        return False
    return True


def _check_page_license():
    config = load_config(os.environ.get("ETL_CONFIG"))
    try:
        lic = get_manager(config).get_license()
    except LicenseError:
        return False
    state = lic.state(time.time())
    if state in (LicenseState.EXPIRED, LicenseState.SUSPENDED, LicenseState.REVOKED):
        return False
    if not lic.has("dashboard"):
        return False
    return True


_LICENSE_MESSAGES = {
    LicenseState.ACTIVE: "",
    LicenseState.GRACE: "Licencia en período de gracia: renueva para evitar la interrupción del servicio.",
    LicenseState.EXPIRED: "Licencia vencida. Los datos existentes se conservan; renueva para continuar.",
    LicenseState.SUSPENDED: "Licencia suspendida por Novus. Contacta a Novus para regularizar.",
    LicenseState.REVOKED: "Licencia revocada. Contacta a Novus.",
    LicenseState.NO_LICENSE: "",
}


@app.get("/api/license")
def api_license(user=Depends(require_user)):
    config = load_config(os.environ.get("ETL_CONFIG"))
    try:
        lic = get_manager(config).get_license()
    except LicenseError as exc:
        return {"state": "UNKNOWN", "message": str(exc), "modules": {}, "limits": {}}
    state = lic.state(time.time())
    return {
        "state": state.value,
        "customer": lic.customer_id,
        "license": lic.license_id,
        "valid_until": lic.valid_until,
        "offline_until": lic.offline_until,
        "modules": lic.modules,
        "limits": lic.limits,
        "message": _LICENSE_MESSAGES.get(state, ""),
    }


@app.get("/", include_in_schema=False)
def root(user=Depends(current_user_or_none)):
    if user is None:
        return RedirectResponse(url="/login", status_code=307)
    if not _check_page_license():
        return RedirectResponse(url="/derivadas", status_code=307)
    return RedirectResponse(
        url="/panel" if user["role"] == "admin" else "/derivadas",
        status_code=307,
    )


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def page_login():
    return _page("login.html")


@app.get("/inventario", include_in_schema=False)
def page_inventario(user=Depends(current_user_or_none)):
    if user is None:
        return RedirectResponse(url="/login", status_code=307)
    return RedirectResponse(url="/derivadas", status_code=307)


@app.get("/etl", response_class=HTMLResponse, include_in_schema=False)
def page_etl(user=Depends(current_user_or_none)):
    if user is None:
        return RedirectResponse(url="/login", status_code=307)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    if not _check_page_license():
        return _page("license.html")
    return _page("etl.html")


@app.get("/panel", response_class=HTMLResponse, include_in_schema=False)
def page_panel(user=Depends(current_user_or_none)):
    if user is None:
        return RedirectResponse(url="/login", status_code=307)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    if not _check_page_license():
        return _page("license.html")
    return _page("panel.html")


@app.get("/api/derived-views")
def api_derived_views(user=Depends(require_license_module("dashboard"))):
    config = load_config(os.environ.get("ETL_CONFIG"))
    views = [{"name": v.get("name", "inv_bodega"), "tab": view_tab_label(v),
              "table": v.get("name", "inv_bodega"), "columns": _view_columns(v)}
             for v in derived_views(config)]
    return {"views": views}


@app.get("/derivadas", response_class=HTMLResponse, include_in_schema=False)
def page_derivadas(user=Depends(current_user_or_none)):
    if user is None:
        return RedirectResponse(url="/login", status_code=307)
    if not _check_page_license():
        return _page("license.html")
    return _page("derivadas.html")
