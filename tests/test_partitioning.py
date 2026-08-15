import re

import pandas as pd
import pytest

from sources.config_resolver import validate_prd_limits
from sources.partitioning import build_chunks, extract_in_ranges

COND_RE = re.compile(r"(\w+) (<=|>=|<|>) '([^']*)'")

SENTINEL = "~" * 18


def key_in_chunk(condition, key):
    for _col, op, val in COND_RE.findall(condition):
        if op == "<" and not (key < val):
            return False
        if op == "<=" and not (key <= val):
            return False
        if op == ">" and not (key > val):
            return False
        if op == ">=" and not (key >= val):
            return False
    return True


def matching_chunks(key, chunks):
    return [c for c in chunks if key_in_chunk(c, key)]


def test_chunks_cover_all_keys_exactly_once():
    chunks = build_chunks()
    assert len(chunks) == 63

    samples = [
        "  123",
        "0", "1", "5", "9",
        "A", "B", "D95300030", "IN24000044", "J81400105", "Z",
        "a", "z", "z" * 18,
        "~", "A1B2", "0123456789",
    ]
    for key in samples:
        matches = matching_chunks(key, chunks)
        assert len(matches) == 1, f"key={key!r} -> {len(matches)} chunks"


def test_chunks_disjoint_consecutive():
    chunks = build_chunks()
    assert chunks[0] == "MATNR < '0'"
    assert chunks[1] == "MATNR >= '0' AND MATNR < '1'"
    assert chunks[-1] == f"MATNR >= 'z' AND MATNR < '{SENTINEL}'"


def test_chunks_custom_prefixes():
    chunks = build_chunks(prefixes=["J", "D"])
    assert chunks == [
        "MATNR < 'D'",
        "MATNR >= 'D' AND MATNR < 'J'",
        f"MATNR >= 'J' AND MATNR < '{SENTINEL}'",
    ]


def test_chunks_custom_sentinel():
    chunks = build_chunks(prefixes=["A"], sentinel="ZZZZ")
    assert chunks[-1] == "MATNR >= 'A' AND MATNR < 'ZZZZ'"


def test_chunks_custom_key():
    assert build_chunks(key="WERKS", prefixes=["A"])[1].startswith("WERKS >= 'A'")


class FakeRangeConnector:
    def __init__(self):
        self.calls = []

    def extract(self, table, fields, filters=None, batch_size=30000, max_wa_chars=None):
        self.calls.append((table, list(fields), list(filters or [])))
        return pd.DataFrame({f: [1] for f in fields})


def test_extract_in_ranges_with_filters_does_not_partition():
    conn = FakeRangeConnector()
    out = extract_in_ranges(
        conn, "MARA", ["MATNR", "MEINS"],
        filters=["X = '1'"],
    )
    assert len(out) == 1
    assert list(out.columns) == ["MATNR", "MEINS"]
    assert len(conn.calls) == 1
    assert conn.calls[0][2] == ["X = '1'"]


def test_extract_in_ranges_no_filters_partitions():
    conn = FakeRangeConnector()
    out = extract_in_ranges(conn, "MAKT", ["MATNR"], prefixes=["A", "B"])
    assert len(out) == 3
    assert len(conn.calls) == 3
    assert conn.calls[0][2] == ["MATNR < 'A'"]
    assert conn.calls[1][2] == ["MATNR >= 'A' AND MATNR < 'B'"]
    assert conn.calls[2][2] == [f"MATNR >= 'B' AND MATNR < '{SENTINEL}'"]


def test_extract_in_ranges_all_empty_chunks_returns_empty():
    class EmptyConnector:
        def extract(self, table, fields, filters=None, batch_size=30000, max_wa_chars=None):
            return pd.DataFrame(columns=fields)

    out = extract_in_ranges(EmptyConnector(), "MARA", ["MATNR"], prefixes=["A"])
    assert out.empty
    assert list(out.columns) == ["MATNR"]


def test_validate_prd_limits_allows_range_load():
    validate_prd_limits({
        "environment": "prd",
        "tables": [{"source": "MARA", "load_mode": "range"}],
    })


def test_validate_prd_limits_allows_filters():
    validate_prd_limits({
        "environment": "prd",
        "tables": [{"source": "MARA", "filters": ["MATNR = 'X'"]}],
    })


def test_validate_prd_limits_blocks_bare_fullscan():
    with pytest.raises(ValueError):
        validate_prd_limits({
            "environment": "prd",
            "tables": [{"source": "MARA"}],
        })


def test_validate_prd_limits_ignores_non_prd():
    validate_prd_limits({
        "environment": "qa",
        "tables": [{"source": "MARA"}],
    })
