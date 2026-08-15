"""Dashboard web del motor ETL: lee etl_execution/etl_progress de la BD destino.

No requiere el SDK de SAP; basta con acceso de lectura a la base de datos.
"""

import os
import signal
import subprocess
import sys
import time

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, text

from db.db_connection import _connection_string
from utils.config_loader import load_config
from utils.live import _live_file, read_live, update_live

app = FastAPI(title="ETL Dashboard")

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


@app.get("/api/executions")
def api_executions(last: int = 10):
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
def api_progress():
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name, status, rows_loaded, last_delta_value, updated_at "
                 "FROM etl_progress ORDER BY table_name"),
        ).fetchall()
    return [ProgressItem(table_name=r.table_name, status=str(r.status or ""),
                         rows_loaded=r.rows_loaded or 0,
                         last_delta_value=str(r.last_delta_value or ""),
                         updated_at=str(r.updated_at or "")).model_dump() for r in rows]


@app.get("/api/dashboard")
def api_dashboard():
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


@app.get("/api/live")
def api_live():
    _recover_stale()
    return read_live()


@app.get("/api/tables")
def api_tables(run_id: int):
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT table_name, chunks_total, chunks_ok, rows_extracted, duration_s, status "
                 "FROM etl_execution_tables WHERE run_id = :n ORDER BY table_name"),
            {"n": run_id},
        ).fetchall()
    return [dict(zip(r._mapping.keys(), r)) for r in rows]


def _first_derived_view(config):
    from derived.views import derived_views
    views = derived_views(config)
    return views[0] if views else None


def _inventory_frame():
    config = load_config(os.environ.get("ETL_CONFIG"))
    view = _first_derived_view(config)
    if view is None:
        return None, None
    from derived.db import read_table, table_exists
    name = view.get("name", "inv_bodega")
    if not table_exists(get_engine(), name):
        return None, name
    return read_table(get_engine(), name), view


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
    _coerce_numeric(df, [total_field])
    total_rows = int(len(df))
    materials = int(df["MATNR"].nunique()) if "MATNR" in df.columns else total_rows
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
def api_inventory():
    df, view = _inventory_frame()
    if view is None:
        return {"available": False, "reason": "no_derived"}
    if df is None:
        return {"available": False, "reason": "table_missing",
                "table": view.get("name", "inv_bodega")}
    return _inventory_summary(df, view)


@app.get("/api/inventory/filters")
def api_inventory_filters():
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
                        limit: int = 100, offset: int = 0):
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
def api_inventory_alerts(limit: int = 500, q: str = ""):
    data = api_inventory_items(low_only=True, q=q, limit=limit, offset=0)
    return {"alerts": data.get("rows", [])}


@app.post("/api/etl/trigger")
def api_etl_trigger():
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


@app.get("/", response_class=HTMLResponse)
def index():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "index.html")
    return FileResponse(path)
