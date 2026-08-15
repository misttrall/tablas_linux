import os

import pandas as pd

from sources.base import SourceConnector


class CSVConnector(SourceConnector):
    """Conector genérico para orígenes en archivos CSV.

    Config esperada:
    - directory: carpeta donde están los archivos (uno por tabla)
    - sep: separador de columnas (default ',')
    - encoding: codificación del archivo (default utf-8)
    """

    type = "csv"

    def __init__(self, config):
        super().__init__(config)
        self.directory = config["directory"]
        self.sep = config.get("sep", ",")
        self.encoding = config.get("encoding", "utf-8")

    def _path(self, table):
        filename = table if table.endswith(".csv") else f"{table}.csv"
        return os.path.join(self.directory, filename)

    def extract(self, table, fields, filters=None):
        path = self._path(table)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Archivo fuente no encontrado: {path}")

        df = pd.read_csv(path, sep=self.sep, encoding=self.encoding)

        missing = [f for f in fields if f not in df.columns]
        if missing:
            raise ValueError(f"Campos no encontrados en el CSV: {missing}")
        return df[fields]
