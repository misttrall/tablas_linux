from .base import Sink
from .mysql import MySQLSink
from .postgres import PostgreSQLSink
from .sqlite import SQLiteSink
from .sqlserver import SQLServerSink

__all__ = [
    "Sink",
    "MySQLSink",
    "PostgreSQLSink",
    "SQLiteSink",
    "SQLServerSink",
    "SINKS",
    "get_sink",
]

SINKS = {
    "mssql": SQLServerSink,
    "postgresql": PostgreSQLSink,
    "mysql": MySQLSink,
    "sqlite": SQLiteSink,
}


def get_sink(engine, dialect=None):
    """Devuelve la implementación de Sink según el dialecto del engine."""
    if dialect is None:
        dialect = engine.dialect.name
    try:
        return SINKS[dialect](engine)
    except KeyError:
        raise ValueError(f"Dialecto de base de datos no soportado: {dialect}")
