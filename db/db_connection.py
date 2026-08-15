from sqlalchemy import create_engine

from utils.config_loader import load_config

_DIALECT_PORTS = {
    "mssql": 1433,
    "postgresql": 5432,
    "mysql": 3306,
}


def _connection_string(db):
    dialect = db.get("dialect", "mssql")
    if dialect not in _DIALECT_PORTS and dialect != "sqlite":
        raise ValueError(f"Dialecto de base de datos no soportado: {dialect}")
    if dialect == "sqlite":
        return f"sqlite:///{db['database']}"
    if dialect == "mssql":
        driver = db.get("driver", "ODBC+Driver+18+for+SQL+Server")
        return (
            f"mssql+pyodbc://{db['user']}:{db['password']}@{db['server']}/{db['database']}"
            f"?driver={driver}&TrustServerCertificate=yes"
        )
    port = db.get("port", _DIALECT_PORTS[dialect])
    if dialect == "postgresql":
        return f"postgresql+psycopg2://{db['user']}:{db['password']}@{db['server']}:{port}/{db['database']}"
    if dialect == "mysql":
        return f"mysql+pymysql://{db['user']}:{db['password']}@{db['server']}:{port}/{db['database']}"
    raise ValueError(f"Dialecto de base de datos no soportado: {dialect}")


def get_engine(config=None):
    config = config or load_config()
    db = config["database"]
    kwargs = {}
    if db.get("dialect", "mssql") == "mssql":
        kwargs["fast_executemany"] = True
    return create_engine(_connection_string(db), **kwargs)
