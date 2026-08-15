import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sources.generic.http import HTTPConnector


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(self.server.pages.get(self.path, [])).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Server(HTTPServer):
    def __init__(self):
        self.pages = {}
        super().__init__(("127.0.0.1", 0), _Handler)


@pytest.fixture
def api():
    server = _Server()
    server.pages = {
        "/clientes?page=1&page_size=2": [{"id": 1, "nombre": "Ana"}, {"id": 2, "nombre": "Luis"}],
        "/clientes?page=2&page_size=2": [{"id": 3, "nombre": "Pedro"}],
        "/clientes?page=3&page_size=2": [],
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def _url(api):
    return f"http://127.0.0.1:{api.server_port}"


def test_http_extract_paginates(api):
    conn = HTTPConnector({"base_url": _url(api), "page_size": 2})
    df = conn.extract("clientes", ["id", "nombre"])
    assert list(df["id"]) == [1, 2, 3]


def test_http_selects_fields(api):
    conn = HTTPConnector({"base_url": _url(api), "page_size": 2})
    df = conn.extract("clientes", ["nombre"])
    assert list(df.columns) == ["nombre"]
    assert len(df) == 3


def test_http_without_pagination_single_page(api):
    api.pages = {"/clientes": [{"id": 1, "nombre": "Ana"}]}
    conn = HTTPConnector({"base_url": _url(api)})
    df = conn.extract("clientes", ["id", "nombre"])
    assert len(df) == 1


def test_http_data_key(api):
    api.pages = {"/clientes": {"data": [{"id": 5, "nombre": "Z"}]}}
    conn = HTTPConnector({"base_url": _url(api), "data_key": "data"})
    df = conn.extract("clientes", ["id"])
    assert list(df["id"]) == [5]


def test_http_missing_field_raises(api):
    api.pages = {"/clientes": [{"id": 1}]}
    conn = HTTPConnector({"base_url": _url(api)})
    with pytest.raises(ValueError):
        conn.extract("clientes", ["id", "no_existe"])
