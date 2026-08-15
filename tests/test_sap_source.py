import sys

import pytest

from sources.sap.rfc import extract_rfc_table, parse_rfc_data


class FakeRFCConnection:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def call(self, fn, **params):
        self.calls.append(params)
        if self.responses:
            return {"DATA": self.responses.pop(0)}
        return {"DATA": []}


def test_parse_rfc_data():
    data = [
        {"WA": "  100  |FERT|UN"},
        {"WA": " 200 |HALB|KG"},
    ]
    rows = parse_rfc_data(data, ["MATNR", "MTART", "MEINS"])
    assert rows == [["100", "FERT", "UN"], ["200", "HALB", "KG"]]


def test_extract_rfc_table_paginates():
    page1 = [{"WA": f"{i}|A|UN"} for i in range(100)]
    page2 = [{"WA": "2|B|UN"}]
    conn = FakeRFCConnection([page1, page2])

    df = extract_rfc_table(conn, "MARA", ["MATNR", "MTART", "MEINS"], batch_size=100)

    assert len(df) == 101
    assert conn.calls[0]["ROWSKIPS"] == 0
    assert conn.calls[1]["ROWSKIPS"] == 100
    assert len(conn.calls) == 2


def test_extract_rfc_table_stops_on_partial_page():
    conn = FakeRFCConnection([[{"WA": "1|A|UN"}]])
    df = extract_rfc_table(conn, "MARA", ["MATNR"], batch_size=100)
    assert len(df) == 1
    assert len(conn.calls) == 1


def test_extract_rfc_table_rejects_small_batch_size():
    import pytest
    conn = FakeRFCConnection([])
    with pytest.raises(ValueError):
        extract_rfc_table(conn, "MARA", ["MATNR"], batch_size=10)


def test_extract_rfc_table_sends_options_when_filters():
    conn = FakeRFCConnection([[{"WA": "1|A|UN"}]])
    extract_rfc_table(conn, "MARA", ["MATNR"], filters=["MTART = 'FERT'"])
    assert conn.calls[0]["OPTIONS"] == [{"TEXT": "MTART = 'FERT'"}]


def test_extract_rfc_table_joins_multiple_filters_in_one_line():
    conn = FakeRFCConnection([[{"WA": "1|A|UN"}]])
    extract_rfc_table(
        conn, "MARA", ["MATNR"],
        filters=["MATNR = 'X'", "MATNR < 'D'"],
    )
    assert conn.calls[0]["OPTIONS"] == [{"TEXT": "MATNR = 'X' AND MATNR < 'D'"}]


def test_extract_rfc_table_no_options_without_filters():
    conn = FakeRFCConnection([[{"WA": "1|A|UN"}]])
    extract_rfc_table(conn, "MARA", ["MATNR"])
    assert "OPTIONS" not in conn.calls[0]


def test_sap_connector_import_does_not_load_pyrfc():
    sys.modules.pop("pyrfc", None)
    from sources.sap import SAPConnector
    assert "pyrfc" not in sys.modules
    assert SAPConnector.type == "sap"


class WidthLimitedRFCConnection:
    """Simula RFC_READ_TABLE con límite de ancho y paginación real."""

    def __init__(self, lengths, n_rows=3, max_chars=512):
        self.lengths = lengths
        self.n_rows = n_rows
        self.max_chars = max_chars
        self.calls = []
        self.errors = 0

    def call(self, fn, **params):
        self.calls.append(params)
        fields = [f["FIELDNAME"] for f in params.get("FIELDS", [])]
        total = sum(self.lengths.get(f, 1) for f in fields)
        if total > self.max_chars:
            self.errors += 1
            raise RuntimeError("ancho del registro excede el limite")
        n = params.get("ROWCOUNT", 1)
        skip = params.get("ROWSKIPS", 0)
        stop = min(skip + n, self.n_rows)
        data = []
        for i in range(skip, stop):
            data.append({"WA": "|".join(f"{f}:{i}" for f in fields)})
        return {"DATA": data}


def test_extract_partitions_fields_over_wa_limit():
    conn = WidthLimitedRFCConnection({"A": 300, "B": 300, "C": 1}, n_rows=2, max_chars=512)
    df = extract_rfc_table(conn, "MARA", ["A", "B", "C"], batch_size=100)
    assert list(df.columns) == ["A", "B", "C"]
    assert len(df) == 2
    assert df.iloc[0]["A"] == "A:0"
    assert df.iloc[1]["C"] == "C:1"
    assert conn.errors > 0


def test_extract_partitions_paginated_alignment():
    conn = WidthLimitedRFCConnection({"A": 300, "B": 300, "C": 1, "D": 1}, n_rows=101, max_chars=512)
    df = extract_rfc_table(conn, "MARA", ["A", "B", "C", "D"], batch_size=100)
    assert list(df.columns) == ["A", "B", "C", "D"]
    assert len(df) == 101
    assert df.iloc[0]["A"] == "A:0"
    assert df.iloc[100]["A"] == "A:100"
    assert df.iloc[50]["C"] == "C:50"
    assert df.iloc[100]["D"] == "D:100"


def test_extract_no_partition_when_within_limit():
    conn = WidthLimitedRFCConnection({"A": 100, "B": 100}, n_rows=2, max_chars=512)
    df = extract_rfc_table(conn, "MARA", ["A", "B"], batch_size=100)
    assert list(df.columns) == ["A", "B"]
    assert len(df) == 2
    assert len(conn.calls) == 1
    assert conn.errors == 0


def test_extract_raises_original_when_partition_fails():
    conn = WidthLimitedRFCConnection({"A": 600, "B": 1}, n_rows=1, max_chars=512)
    with pytest.raises(RuntimeError, match="excede"):
        extract_rfc_table(conn, "MARA", ["A", "B"], batch_size=100)


def test_extract_max_wa_chars_custom_threshold():
    conn = WidthLimitedRFCConnection({"A": 200, "B": 200, "C": 200}, n_rows=1, max_chars=512)
    df = extract_rfc_table(conn, "MARA", ["A", "B", "C"], batch_size=100, max_wa_chars=300)
    assert list(df.columns) == ["A", "B", "C"]
    assert len(df) == 1
