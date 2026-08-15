"""Acceso a las tablas de la BD destino para la capa derivada."""

import pandas as pd
from sqlalchemy import inspect


def dialect(engine):
    return engine.dialect.name


def table_exists(engine, table):
    with engine.connect() as conn:
        return inspect(conn).has_table(table)


def read_table(engine, table):
    """Lee una tabla destino respetando el esquema por dialecto (dbo en mssql)."""
    kwargs = {}
    if dialect(engine) == "mssql":
        kwargs["schema"] = "dbo"
    return pd.read_sql_table(table, engine, **kwargs)
