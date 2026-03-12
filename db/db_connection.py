from sqlalchemy import create_engine
from utils.config_loader import load_config


def get_engine():

    config = load_config()

    db = config["database"]

    connection_string = (
        f"mssql+pyodbc://{db['user']}:{db['password']}@{db['server']}/{db['database']}"
        "?driver=ODBC+Driver+18+for+SQL+Server"
        "&TrustServerCertificate=yes"
    )

    return create_engine(connection_string, fast_executemany=True)