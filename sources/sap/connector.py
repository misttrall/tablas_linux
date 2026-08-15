from sources.base import SourceConnector

from .rfc import extract_rfc_table


class SAPConnector(SourceConnector):

    type = "sap"

    def __init__(self, config):
        super().__init__(config)
        self._connection = None

    def _get_connection(self):
        if self._connection is None:
            from pyrfc import Connection
            self._connection = Connection(**self.config)
        return self._connection

    def connect(self):
        self._get_connection()

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def ping(self):
        self._get_connection().ping()
        return True

    def extract(self, table, fields, filters=None, batch_size=30000, max_wa_chars=None):
        connection = self._get_connection()
        return extract_rfc_table(
            connection, table, fields, filters=filters, batch_size=batch_size,
            max_wa_chars=max_wa_chars,
        )
