"""Importa la matriz de mínimos del cliente (Excel) a una tabla de referencia.

El libro de planificación del cliente trae el stock mínimo y (opcionalmente) el
área por material. Se importa a una tabla de la BD destino (por defecto
``stock_minimo``) para que el modelo derivado la use como tabla de referencia en
vez de ``MARD.LMINB``.

El nombre de la hoja y los nombres de columna son datos del cliente: se pasan
como argumentos (obligatorio ``sheet``).
"""

import pandas as pd

DEFAULT_COLUMNS = {
    "material": "material",
    "stock_minimo": "stock_minimo",
    "area": "area",
}


def import_stock_minimo(engine, sink, xlsx_path, sheet, columns=None, table="stock_minimo"):
    """Lee la hoja del Excel y reemplaza la tabla de referencia en la BD destino.

    ``sheet`` es obligatorio (nombre de la hoja del libro del cliente). Las
    columnas de origen se mapean con ``columns`` (p. ej. {"material": "CODIGO",
    "stock_minimo": "STOCK MÍNIMO", "area": "AREA"}).
    """
    if not sheet:
        raise ValueError("import_stock_minimo: falta el nombre de la hoja (dato del cliente)")
    cols = columns or DEFAULT_COLUMNS
    df = pd.read_excel(xlsx_path, sheet_name=sheet, header=0)

    missing = [c for c in cols.values() if c not in df.columns]
    if missing:
        raise ValueError(f"La hoja '{sheet}' no tiene columnas {missing}")

    df = df[list(cols.values())].rename(columns={v: k for k, v in cols.items()})
    df["material"] = df["material"].astype(str).str.strip().str.upper()
    df["stock_minimo"] = pd.to_numeric(df["stock_minimo"], errors="coerce")

    keep = ["material", "stock_minimo"]
    if "area" in df.columns:
        area = df["area"].astype(str).str.strip()
        df["area"] = area.mask(area.isin(["", "nan", "None"]), None)
        keep.append("area")

    df = df.drop_duplicates(subset=["material"])
    df = df[keep]

    sink.ensure_target(table, list(df.columns), ["material"])
    sink.load(df, table)
    return len(df)
