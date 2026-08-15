"""Capa de modelo derivado: materializa visiones de negocio a partir de las
tablas crudas extraídas, sin depender de vistas SQL creadas por cliente.

La definición es declarativa (``config['derived']``): qué tabla base de stock,
cómo se arma el dominio (registro maestro en la BD destino o regla de filtros),
de dónde salen el área y el stock mínimo (tabla de referencia o fallback en
config), columnas de salida y exportación a Excel.
"""

import pandas as pd
from sqlalchemy import inspect, text

from db.db_connection import get_engine
from db.sinks import get_sink
from derived.db import read_table, table_exists
from derived.excel_export import export_inventory_excel
from derived.views import derived_views, resolve_view
from utils.config_loader import load_config

DEFAULT_DERIVED_COLUMNS = [
    {"as": "MATNR", "source": "MATNR"},
    {"as": "Descripcion", "source": "MAKTX"},
    {"as": "Centro", "source": "WERKS"},
    {"as": "Almacen", "source": "LGORT"},
    {"as": "StockLibre", "source": "LABST"},
    {"as": "Precio", "source": "STPRS"},
    {"as": "ValorTotal", "source": "SALK3"},
    {"as": "Area", "source": "AREA"},
    {"as": "stock_minimo", "source": "STOCK_MINIMO"},
]

DEFAULT_REGISTRY_COLUMNS = {
    "material": "material",
    "centro": "centro",
    "almacen": "almacen",
}

_BASE_SOURCE = "MARD"


def _target_map(config, derived):
    mapping = {t["source"]: t["target"] for t in config.get("tables", [])}
    mapping.update(derived.get("sources", {}))
    return mapping


def _require_cols(df, cols, ctx):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"derived.{ctx}: columnas inexistentes {missing}")


def _join_mara(wide, engine, mapping):
    table = mapping.get("MARA")
    if not table or not table_exists(engine, table):
        return wide
    mara = read_table(engine, table)
    mara = mara.drop_duplicates(subset=["MATNR"]) if "MATNR" in mara.columns else mara
    return wide.merge(mara, on="MATNR", how="left", suffixes=("", "_mara"))


def _join_makt(wide, engine, mapping, text_lang):
    table = mapping.get("MAKT")
    if not table or not table_exists(engine, table):
        return wide
    makt = read_table(engine, table)
    if "SPRAS" in makt.columns and text_lang:
        filtered = makt[makt["SPRAS"].astype(str) == str(text_lang)]
        if not filtered.empty:
            makt = filtered
    key = [c for c in ("MANDT", "MATNR") if c in makt.columns]
    makt = makt.drop_duplicates(subset=key)
    join_on = [c for c in key if c in wide.columns]
    return wide.merge(makt, on=join_on, how="left", suffixes=("", "_makt"))


def _join_mbew(wide, engine, mapping, precio_cfg, valor_cfg):
    table = mapping.get("MBEW")
    if not table or not table_exists(engine, table):
        return wide
    mbew = read_table(engine, table)
    precio_field = precio_cfg.get("field", "STPRS")
    valor_field = valor_cfg.get("field", "SALK3")
    for f in (precio_field, valor_field):
        if f not in mbew.columns:
            raise ValueError(f"derived: MBEW no extrae el campo '{f}' (config: precio/valor field)")

    if valor_cfg.get("by") == "aggregate":
        sums = mbew.groupby("MATNR")[valor_field].sum()
        firsts = mbew.groupby("MATNR")[precio_field].first()
        agg = pd.DataFrame({valor_field: sums, precio_field: firsts}).reset_index()
        return wide.merge(agg, on="MATNR", how="left", suffixes=("", "_mbew"))

    key = wide[["MATNR", "WERKS"]].drop_duplicates()
    fields = list(dict.fromkeys([precio_field, valor_field]))
    joined = key.merge(
        mbew[["MATNR", "BWKEY"] + fields],
        left_on=["MATNR", "WERKS"],
        right_on=["MATNR", "BWKEY"],
        how="left",
    ).drop(columns=["BWKEY"])
    return wide.merge(joined, on=["MATNR", "WERKS"], how="left", suffixes=("", "_mbew"))


def _join_t001l(wide, engine, mapping):
    table = mapping.get("T001L")
    if not table or not table_exists(engine, table):
        return wide
    t = read_table(engine, table)
    t = t.drop_duplicates(subset=[c for c in ("MANDT", "WERKS", "LGORT") if c in t.columns])
    keys = [c for c in ("MANDT", "WERKS", "LGORT") if c in t.columns and c in wide.columns]
    return wide.merge(t, on=keys, how="left", suffixes=("", "_t001l"))


def _build_dominio(derived, engine, wide):
    dom = derived.get("dominio") or {}
    registry = dom.get("registry_table")
    if not registry or not table_exists(engine, registry):
        return wide.copy()
    cols_cfg = dom.get("registry_columns", DEFAULT_REGISTRY_COLUMNS)
    needed = [cols_cfg["material"], cols_cfg["centro"], cols_cfg["almacen"]]
    _require_cols(read_table(engine, registry), needed, "dominio.registry")
    reg = read_table(engine, registry)[needed].rename(columns={
        cols_cfg["material"]: "MATNR",
        cols_cfg["centro"]: "WERKS",
        cols_cfg["almacen"]: "LGORT",
    }).drop_duplicates()
    join_on = [c for c in ("MATNR", "WERKS", "LGORT") if c in wide.columns]
    return reg.merge(wide, on=join_on, how="left")


def _apply_filters(df, filters):
    for f in filters or []:
        field = f.get("field")
        if field not in df.columns:
            raise ValueError(f"derived: filtro sobre campo '{field}' inexistente")
        op = f.get("op", "in")
        if op in ("in", "not_in"):
            values = f.get("values", f.get(op))
            if not isinstance(values, list):
                values = [values]
            df = df[df[field].isin(values)] if op == "in" else df[~df[field].isin(values)]
        elif op == "eq":
            df = df[df[field] == f["value"]]
        elif op == "neq":
            df = df[df[field] != f["value"]]
        else:
            raise ValueError(f"derived: operador de filtro no soportado '{op}'")
    return df


def _area_series(df, engine, area_cfg):
    if not area_cfg:
        return pd.Series("", index=df.index)
    mapping = None
    ref = area_cfg.get("reference_table")
    if ref and table_exists(engine, ref):
        lookup = read_table(engine, ref)
        join = area_cfg.get("join") or {}
        jt = join.get("table")
        if jt and table_exists(engine, jt):
            lookup = lookup.merge(
                read_table(engine, jt),
                left_on=join["on_local"],
                right_on=join["on_foreign"],
                how="left",
                suffixes=("", "_area"),
            )
        cols = area_cfg.get("columns", {"key": "material", "value": "area"})
        _require_cols(lookup, [cols["key"], cols["value"]], "area")
        series = pd.Series(
            lookup[cols["value"]].to_numpy(),
            index=lookup[cols["key"]].to_numpy(),
        )
        series = series[~series.index.duplicated(keep="last")]
        mapping = dict(series.items())
    if mapping is None:
        mapping = area_cfg.get("mapping")
    if not mapping:
        return pd.Series("", index=df.index)
    on = area_cfg.get("on", "MATNR")
    if on not in df.columns:
        return pd.Series("", index=df.index)
    return df[on].map(mapping).fillna("")


def _minimo_series(df, engine, minimo_cfg):
    empty = pd.Series(pd.NA, index=df.index)
    if not minimo_cfg:
        return empty
    ref = minimo_cfg.get("reference_table")
    if ref and table_exists(engine, ref):
        lookup = read_table(engine, ref)
        key_cols = minimo_cfg.get("key_columns", ["material"])
        value_col = minimo_cfg.get("value_column", "stock_minimo")
        _require_cols(lookup, key_cols + [value_col], "stock_minimo")
        on = minimo_cfg.get("on")
        if on is None:
            on = ["MATNR", "WERKS", "LGORT"] if len(key_cols) >= 3 else (
                ["MATNR", "WERKS"] if len(key_cols) == 2 else ["MATNR"])
        if len(on) != len(key_cols):
            raise ValueError("derived.stock_minimo: 'on' debe alinearse con 'key_columns'")
        if any(c not in df.columns for c in on):
            return empty
        series = pd.Series(
            lookup[value_col].to_numpy(),
            index=pd.MultiIndex.from_frame(lookup[key_cols]),
        )
        series = series[~series.index.duplicated(keep="last")]
        idx = pd.MultiIndex.from_frame(df[on])
        return idx.map(dict(series.items())).astype("Float64")
    mapping = minimo_cfg.get("mapping")
    if mapping:
        if "MATNR" not in df.columns:
            return empty
        return df["MATNR"].map(mapping).astype("Float64")
    source_field = minimo_cfg.get("source_field")
    if source_field:
        _require_cols(df, [source_field], "stock_minimo.source_field")
        return df[source_field].replace("", pd.NA).astype("Float64")
    return empty


def build_inventory(engine, config, derived=None):
    """Construye el DataFrame del inventario (dominio + stock + área + mínimo)."""
    derived = resolve_view(config, derived)
    mapping = _target_map(config, derived)

    base_table = mapping.get(_BASE_SOURCE)
    if not base_table:
        raise ValueError(f"derived: falta la tabla base '{_BASE_SOURCE}' en config.tables")
    if not table_exists(engine, base_table):
        raise ValueError(f"derived: la tabla base '{base_table}' no existe en la BD destino")

    wide = read_table(engine, base_table)
    wide = _join_mara(wide, engine, mapping)
    wide = _join_makt(wide, engine, mapping, derived.get("text_lang", "ES"))
    wide = _join_mbew(wide, engine, mapping, derived.get("precio", {}), derived.get("valor", {}))
    wide = _join_t001l(wide, engine, mapping)

    base = _build_dominio(derived, engine, wide)
    base = _apply_filters(base, derived.get("dominio", {}).get("filters", []))

    base["AREA"] = _area_series(base, engine, derived.get("area"))
    base["STOCK_MINIMO"] = _minimo_series(base, engine, derived.get("stock_minimo"))

    precio_field = derived.get("precio", {}).get("field", "STPRS")
    valor_field = derived.get("valor", {}).get("field", "SALK3")
    for c in ("LABST", precio_field, valor_field):
        if c in base.columns:
            base[c] = pd.to_numeric(base[c], errors="coerce").fillna(0)

    columns = derived.get("columns") or DEFAULT_DERIVED_COLUMNS
    _require_cols(base, [c["source"] for c in columns if "source" in c], "columns")
    out = {}
    for c in columns:
        name = c["as"]
        if c.get("compute"):
            out[name] = base.eval(c["compute"])
        else:
            out[name] = base[c["source"]]
    return pd.DataFrame(out)


def _sync_target(engine, sink, target, columns, keys):
    """Recrea la tabla derivada si existe pero cambió su esquema.

    La tabla derivada se regenera completa en cada corrida, así que si las
    columnas del config cambiaron (p. ej. se agregó AlmacenDesc/UMB) se
    elimina y se vuelve a crear con el esquema declarado.
    """
    with engine.connect() as conn:
        if not inspect(conn).has_table(target):
            sink.ensure_target(target, columns, keys)
            return
        existing = {c["name"] for c in inspect(conn).get_columns(target)}
    expected = set(columns)
    if existing != expected:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE {target}"))
    sink.ensure_target(target, columns, keys)


def _run_derived_view(engine, sink, config, derived):
    """Materializa una visión derivada (tabla + Excel). Devuelve (nombre, n_filas, ruta)."""
    df = build_inventory(engine, config, derived=derived)

    target = derived.get("name", "inv_bodega")
    columns_cfg = derived.get("columns") or DEFAULT_DERIVED_COLUMNS
    src_to_out = {c["source"]: c["as"] for c in columns_cfg if "source" in c}

    def _resolve(col):
        return src_to_out.get(col, col)

    keys = []
    for k in derived.get("keys", ["MATNR", "WERKS", "LGORT"]):
        out = _resolve(k)
        if out in df.columns and out not in keys:
            keys.append(out)
    if not keys:
        raise ValueError("derived: no se pudo determinar claves primarias para la tabla derivada")

    _sync_target(engine, sink, target, list(df.columns), keys)
    sink.load(df, target)

    path = export_inventory_excel(df, derived)
    return target, len(df), path


def _default_engine_sink_config(engine, sink, config):
    if config is None:
        config = load_config()
    if engine is None:
        engine = get_engine(config)
    if sink is None:
        sink = get_sink(engine)
    return engine, sink, config


def run_derived(engine=None, sink=None, config=None, derived=None):
    """Materializa la visión derivada (la pasada o la primera) y exporta su Excel.

    Devuelve (n_filas, ruta) — formato histórico.
    """
    engine, sink, config = _default_engine_sink_config(engine, sink, config)

    view = resolve_view(config, derived)
    _, n_rows, path = _run_derived_view(engine, sink, config, view)
    return n_rows, path


def run_deriveds(engine=None, sink=None, config=None):
    """Materializa todas las visiones derivadas declaradas en config.

    Devuelve una lista de (nombre, n_filas, ruta) por visión.
    """
    engine, sink, config = _default_engine_sink_config(engine, sink, config)

    return [_run_derived_view(engine, sink, config, view) for view in derived_views(config)]
