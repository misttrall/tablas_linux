import pytest

from sources.generic.csv import CSVConnector


def test_csv_extract_selects_fields(tmp_path):
    (tmp_path / "clientes.csv").write_text("id,nombre,ciudad\n1,Ana,Santiago\n2,Luis,Valpo\n")
    conn = CSVConnector({"directory": str(tmp_path)})
    df = conn.extract("clientes", ["id", "nombre"])
    assert list(df.columns) == ["id", "nombre"]
    assert len(df) == 2


def test_csv_extract_with_extension(tmp_path):
    (tmp_path / "t.csv").write_text("id,nombre\n1,Ana\n")
    conn = CSVConnector({"directory": str(tmp_path)})
    assert len(conn.extract("t.csv", ["id"])) == 1


def test_csv_missing_field_raises(tmp_path):
    (tmp_path / "t.csv").write_text("id,nombre\n1,Ana\n")
    conn = CSVConnector({"directory": str(tmp_path)})
    with pytest.raises(ValueError):
        conn.extract("t", ["id", "no_existe"])


def test_csv_missing_file_raises(tmp_path):
    conn = CSVConnector({"directory": str(tmp_path)})
    with pytest.raises(FileNotFoundError):
        conn.extract("no_existe", ["id"])
