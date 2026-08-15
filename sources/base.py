from abc import ABC, abstractmethod


class SourceConnector(ABC):
    """Contrato de un origen de datos (ERP/sistema) conectable al motor ETL."""

    type = ""

    def __init__(self, config):
        self.config = config

    def connect(self):
        """Establece la conexión con el origen. No-op en fuentes sin estado."""

    def close(self):
        """Libera la conexión. No-op en fuentes sin estado."""

    def ping(self):
        """Verifica que el origen es alcanzable."""
        return True

    @abstractmethod
    def extract(self, table, fields, filters=None):
        """Extrae `fields` de `table` y devuelve un DataFrame.
        `filters` es una lista opcional de condiciones/expresiones del origen.
        """
