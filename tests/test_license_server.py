import pytest
from sqlalchemy import create_engine, text

from license_server import db as license_db


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    license_db.init_db(eng)
    return eng


def test_init_db_creates_tables(engine):
    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert {"customers", "licenses", "license_modules", "license_limits",
            "license_events"} <= tables


def test_hash_and_verify_api_key():
    h = license_db.hash_api_key("clave-cliente")
    assert license_db.verify_api_key(h, "clave-cliente") is True
    assert license_db.verify_api_key(h, "otra") is False


def test_create_and_get_customer(engine):
    license_db.create_customer(engine, "empresa_001", "Mi Empresa", "hash1")
    row = license_db.get_customer(engine, "empresa_001")
    assert row is not None
    assert row.customer_id == "empresa_001"
    assert row.status == "active"
    assert license_db.get_customer(engine, "no_existe") is None


def test_set_customer_status(engine):
    license_db.create_customer(engine, "empresa_001", "Mi Empresa", "hash1")
    license_db.set_customer_status(engine, "empresa_001", "disabled")
    assert license_db.get_customer(engine, "empresa_001").status == "disabled"


def test_issue_and_get_active_license(engine):
    license_db.create_customer(engine, "empresa_001", "Mi Empresa", "hash1")
    license_db.issue_license(
        engine, "empresa_001", "NOVUS-001",
        valid_from=1_000_000, valid_until=2_000_000, grace_days=7,
        modules={"derived": True, "bi": False}, limits={"users": 5},
    )
    lic = license_db.get_active_license(engine, "empresa_001")
    assert lic["license_id"] == "NOVUS-001"
    assert lic["status"] == "active"
    assert lic["offline_until"] == 2_000_000 + 7 * 86400
    assert lic["modules"] == {"derived": True, "bi": False}
    assert lic["limits"] == {"users": 5}


def test_renew_and_status_changes(engine):
    license_db.create_customer(engine, "empresa_001", "Mi Empresa", "hash1")
    license_db.issue_license(
        engine, "empresa_001", "NOVUS-001",
        valid_from=1_000_000, valid_until=2_000_000, grace_days=7,
        modules={"derived": True}, limits={},
    )
    license_db.renew_license(engine, "NOVUS-001", 1_000_000, 9_000_000, 7)
    lic = license_db.get_active_license(engine, "empresa_001")
    assert lic["valid_until"] == 9_000_000

    license_db.set_license_status(engine, "NOVUS-001", "suspended", "suspended")
    assert license_db.get_license_by_id(engine, "NOVUS-001")["status"] == "suspended"


def test_list_licenses_and_events(engine):
    license_db.create_customer(engine, "empresa_001", "Mi Empresa", "hash1")
    license_db.issue_license(
        engine, "empresa_001", "NOVUS-001",
        valid_from=1_000_000, valid_until=2_000_000, grace_days=7,
        modules={"derived": True}, limits={},
    )
    rows = license_db.list_licenses(engine, "empresa_001")
    assert len(rows) == 1
    assert rows[0]["license_id"] == "NOVUS-001"
    with engine.connect() as conn:
        events = conn.execute(text("SELECT event_type FROM license_events")).fetchall()
    assert events and events[0][0] == "issued"


def test_record_event(engine):
    license_db.create_customer(engine, "empresa_001", "Mi Empresa", "hash1")
    license_db.issue_license(
        engine, "empresa_001", "NOVUS-001",
        valid_from=1_000_000, valid_until=2_000_000, grace_days=7,
        modules={"derived": True}, limits={},
    )
    license_db.record_event(engine, "NOVUS-001", "activated", "by admin")
    with engine.connect() as conn:
        events = conn.execute(
            text("SELECT event_type, detail FROM license_events "
                 "WHERE event_type = 'activated'")).fetchall()
    assert len(events) == 1
    assert events[0][0] == "activated"
    assert events[0][1] == "by admin"


def test_list_customers(engine):
    license_db.create_customer(engine, "emp_001", "Empresa Uno", "hash1")
    license_db.create_customer(engine, "emp_002", "Empresa Dos", "hash2")
    rows = license_db.list_customers(engine)
    assert len(rows) == 2
    ids = {r.customer_id for r in rows}
    assert ids == {"emp_001", "emp_002"}


def test_get_license_by_id_not_found(engine):
    assert license_db.get_license_by_id(engine, "NO-EXISTE") is None
