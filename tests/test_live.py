
import pandas as pd

from sources.partitioning import extract_in_ranges
from utils.live import read_live, update_live


class CountingConnector:
    type = "csv"

    def extract(self, table, fields, filters=None, batch_size=30000, max_wa_chars=None):
        self.last_filters = filters
        return pd.DataFrame({f: [1, 2] for f in fields})


def test_live_default_idle(tmp_path, monkeypatch):
    monkeypatch.setenv("ETL_LIVE_FILE", str(tmp_path / "nuevo.json"))
    assert read_live()["running"] is False
    assert read_live()["phase"] == "idle"


def test_live_write_read(tmp_path, monkeypatch):
    path = tmp_path / "live.json"
    monkeypatch.setenv("ETL_LIVE_FILE", str(path))
    update_live(running=True, table="MARA", chunk_index=5, chunk_total=63,
                rows_so_far=100, phase="extrayendo")
    data = read_live()
    assert data["running"] is True
    assert data["table"] == "MARA"
    assert data["chunk_index"] == 5
    assert data["chunk_total"] == 63
    assert data["rows_so_far"] == 100
    assert data["phase"] == "extrayendo"
    update_live(running=False)
    assert read_live()["running"] is False


def test_extract_in_ranges_callbacks():
    calls = []
    conn = CountingConnector()

    def on_start(total):
        calls.append(("start", total))

    def on_chunk(index, total, rows_chunk, rows_so_far):
        calls.append((index, total, rows_chunk, rows_so_far))

    df = extract_in_ranges(conn, "T", ["A"], key="K", prefixes=["0", "1"],
                           on_start=on_start, on_chunk=on_chunk)

    assert calls[0] == ("start", 3)
    chunks = calls[1:]
    assert len(chunks) == 3
    assert [c[2] for c in chunks] == [2, 2, 2]
    assert [c[3] for c in chunks] == [2, 4, 6]
    assert [c[1] for c in chunks] == [3, 3, 3]
    assert len(df) == 6


def test_extract_in_ranges_callbacks_skipped_with_filters():
    calls = []
    conn = CountingConnector()
    df = extract_in_ranges(conn, "T", ["A"], filters=["A > 'x'"],
                           on_start=lambda t: calls.append("start"),
                           on_chunk=lambda *a: calls.append("chunk"))
    assert calls == []
    assert len(df) == 2


def test_live_dashboard_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from dashboard import app as dashboard_app

    path = tmp_path / "live.json"
    monkeypatch.setenv("ETL_LIVE_FILE", str(path))
    update_live(running=True, run_id=99, table="MBEW", phase="extrayendo",
                chunk_index=10, chunk_total=63, rows_so_far=5000, elapsed_s=3.2)

    client = TestClient(dashboard_app.app)
    res = client.get("/api/live")
    assert res.status_code == 200
    data = res.json()
    assert data["running"] is True
    assert data["table"] == "MBEW"
    assert data["chunk_index"] == 10
    assert data["chunk_total"] == 63
    assert data["rows_so_far"] == 5000
