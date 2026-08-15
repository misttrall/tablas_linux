import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from sources.base import SourceConnector


class HTTPConnector(SourceConnector):
    """Conector genérico para cualquier sistema que exponga una API REST.

    Config esperada:
    - base_url: URL base de la API (ej. https://erp.example.com/api)
    - headers: dict de cabeceras opcionales (ej. autorización)
    - timeout: segundos de espera por request (default 30)
    - data_key: clave del JSON donde está la lista de registros (opcional)
    - page_size, page_param, size_param: paginación opcional
    """

    type = "http"

    def __init__(self, config):
        super().__init__(config)
        self.base_url = config["base_url"].rstrip("/")
        self.headers = config.get("headers", {})
        self.timeout = config.get("timeout", 30)
        self.data_key = config.get("data_key")
        self.page_size = config.get("page_size")
        self.page_param = config.get("page_param", "page")
        self.size_param = config.get("size_param", "page_size")

    def _request(self, url):
        req = Request(url, headers=self.headers)
        with urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _endpoint(self, table, page=None):
        path = f"{self.base_url}/{table}"
        if self.page_size:
            path = f"{path}?{urlencode({self.page_param: page, self.size_param: self.page_size})}"
        return path

    def _records(self, payload):
        if self.data_key:
            return payload[self.data_key]
        return payload

    def extract(self, table, fields, filters=None):
        records = []
        page = 1
        while True:
            data = self._records(self._request(self._endpoint(table, page)))
            if not data:
                break
            records.extend(data)
            if not self.page_size or len(data) < self.page_size:
                break
            page += 1

        df = pd.DataFrame(records)
        if fields:
            missing = [f for f in fields if f not in df.columns]
            if missing:
                raise ValueError(f"Campos no encontrados en la respuesta: {missing}")
            df = df[fields]
        return df
