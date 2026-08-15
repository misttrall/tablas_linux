from db.db_connection import _connection_string

MSSQL = {"dialect": "mssql", "server": "srv", "database": "db", "user": "u", "password": "p"}
POSTGRES = {"dialect": "postgresql", "server": "srv", "database": "db", "user": "u", "password": "p"}
MYSQL = {"dialect": "mysql", "server": "srv", "database": "db", "user": "u", "password": "p"}


def test_mssql_is_default_dialect():
    url = _connection_string({"server": "srv", "database": "db", "user": "u", "password": "p"})
    assert url.startswith("mssql+pyodbc://u:p@srv/db")
    assert "driver=ODBC+Driver+18+for+SQL+Server" in url
    assert "TrustServerCertificate=yes" in url


def test_mssql_custom_driver():
    url = _connection_string({**MSSQL, "driver": "ODBC+Driver+17+for+SQL+Server"})
    assert "driver=ODBC+Driver+17+for+SQL+Server" in url


def test_postgres_url():
    assert _connection_string(POSTGRES) == "postgresql+psycopg2://u:p@srv:5432/db"


def test_postgres_custom_port():
    assert _connection_string({**POSTGRES, "port": 5433}) == "postgresql+psycopg2://u:p@srv:5433/db"


def test_mysql_url():
    assert _connection_string(MYSQL) == "mysql+pymysql://u:p@srv:3306/db"


def test_sqlite_relative_path():
    assert _connection_string({"dialect": "sqlite", "database": "test.db"}) == "sqlite:///test.db"


def test_sqlite_absolute_path():
    assert _connection_string({"dialect": "sqlite", "database": "/tmp/x.db"}) == "sqlite:////tmp/x.db"


def test_unknown_dialect_raises():
    import pytest
    with pytest.raises(ValueError):
        _connection_string({"dialect": "oracle", "server": "s", "database": "d", "user": "u", "password": "p"})
