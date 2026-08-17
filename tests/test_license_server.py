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


from fastapi.testclient import TestClient

from license_server.app import create_app
from license_server.signing import sign_claims
from licensing.validator import verify_token


@pytest.fixture(scope="module")
def keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    private_key = ed25519.Ed25519PrivateKey.generate()
    priv_pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    pub_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv_pem, pub_pem


@pytest.fixture
def api_client(keypair):
    from sqlalchemy.pool import StaticPool
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    license_db.init_db(eng)
    priv_pem, _ = keypair
    return TestClient(create_app(eng, priv_pem))


@pytest.fixture
def customer_license():
    from sqlalchemy.pool import StaticPool
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    license_db.init_db(eng)
    license_db.create_customer(eng, "empresa_001", "Mi Empresa",
                               license_db.hash_api_key("clave-1"))
    license_db.issue_license(
        eng, "empresa_001", "NOVUS-001",
        valid_from=1_000_000, valid_until=9_000_000, grace_days=7,
        modules={"derived": True, "dashboard": True, "bi": False},
        limits={"users": 5})
    return eng


def test_health(api_client):
    res = api_client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_activate_ok(keypair, customer_license):
    priv_pem, pub_pem = keypair
    eng = customer_license
    client = TestClient(create_app(eng, priv_pem))
    res = client.post("/api/activate", json={"customer_id": "empresa_001", "api_key": "clave-1"})
    assert res.status_code == 200
    body = res.json()
    claims = verify_token(body["token"], pub_pem)
    assert claims["customer_id"] == "empresa_001"
    assert claims["modules"]["derived"] is True
    assert claims["limits"]["users"] == 5
    assert body["customer_id"] == "empresa_001"
    assert body["license_id"] == "NOVUS-001"
    assert body["valid_until"] == claims["valid_until"]
    assert body["offline_until"] == claims["offline_until"]
    assert body["modules"] == claims["modules"]
    assert body["limits"] == claims["limits"]


def test_activate_bad_api_key(keypair, customer_license):
    eng = customer_license
    client = TestClient(create_app(eng, keypair[0]))
    res = client.post("/api/activate", json={"customer_id": "empresa_001", "api_key": "nope"})
    assert res.status_code == 401
    assert res.json() == {"error": "credenciales_invalidas", "code": 401}


def test_activate_unknown_customer(keypair, customer_license):
    client = TestClient(create_app(customer_license, keypair[0]))
    res = client.post("/api/activate", json={"customer_id": "otra", "api_key": "x"})
    assert res.status_code == 401
    assert res.json() == {"error": "credenciales_invalidas", "code": 401}


def test_activate_disabled_customer(keypair, customer_license):
    license_db.set_customer_status(customer_license, "empresa_001", "disabled")
    client = TestClient(create_app(customer_license, keypair[0]))
    res = client.post("/api/activate", json={"customer_id": "empresa_001", "api_key": "clave-1"})
    assert res.status_code == 403
    assert res.json() == {"error": "cliente_deshabilitado", "code": 403}


def test_activate_suspended_license(keypair, customer_license):
    license_db.set_license_status(customer_license, "NOVUS-001", "suspended", "suspended")
    client = TestClient(create_app(customer_license, keypair[0]))
    res = client.post("/api/activate", json={"customer_id": "empresa_001", "api_key": "clave-1"})
    assert res.status_code == 403
    assert res.json() == {"error": "licencia_suspendida", "code": 403}


def test_activate_no_license(keypair):
    from sqlalchemy.pool import StaticPool
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    license_db.init_db(eng)
    license_db.create_customer(eng, "empresa_001", "Mi Empresa",
                               license_db.hash_api_key("clave-1"))
    client = TestClient(create_app(eng, keypair[0]))
    res = client.post("/api/activate", json={"customer_id": "empresa_001", "api_key": "clave-1"})
    assert res.status_code == 403
    assert res.json() == {"error": "sin_licencia_activa", "code": 403}
