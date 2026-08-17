import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

import jwt

from licensing.validator import verify_token
from license_server.signing import sign_claims

from licensing import (
    License,
    LicenseBlocked,
    LicenseError,
    LicenseInvalid,
    LicenseNotEntitled,
    LicenseState,
    LicenseUnreachable,
)

NOW = int(time.time())
DAY = 86400


def test_license_state_windows():
    lic = License(
        customer_id="empresa_001", license_id="NOVUS-001", status="active",
        valid_from=NOW - DAY, valid_until=NOW + DAY,
        offline_until=NOW + 8 * DAY, modules={"derived": True, "bi": False},
        limits={"users": 5}, issued_at=NOW,
    )
    assert lic.state(NOW) is LicenseState.ACTIVE
    assert lic.state(NOW + 2 * DAY) is LicenseState.GRACE
    assert lic.state(NOW + 9 * DAY) is LicenseState.EXPIRED


def test_license_suspended_and_revoked():
    lic = License("e", "l", "suspended", NOW, NOW + DAY, NOW + DAY,
                  {"derived": True}, {}, NOW)
    assert lic.state(NOW) is LicenseState.SUSPENDED
    lic.status = "revoked"
    assert lic.state(NOW) is LicenseState.REVOKED


def test_license_has_and_limit():
    lic = License("e", "l", "active", NOW, NOW + DAY, NOW + DAY,
                  {"derived": True}, {"users": 5}, NOW)
    assert lic.has("derived") is True
    assert lic.has("bi") is False
    assert lic.limit("users") == 5
    assert lic.limit("sources") is None


def test_no_license_allows_everything():
    lic = License.no_license()
    assert lic.state(NOW) is LicenseState.NO_LICENSE
    assert lic.has("derived") is True
    assert lic.has("cualquier_cosa") is True
    assert lic.limit("users") is None


def test_exceptions_hierarchy():
    assert issubclass(LicenseInvalid, LicenseError)
    assert issubclass(LicenseBlocked, LicenseError)
    assert issubclass(LicenseUnreachable, LicenseError)
    assert issubclass(LicenseNotEntitled, LicenseError)


@pytest.fixture(scope="module")
def keypair():
    private_key = ed25519.Ed25519PrivateKey.generate()
    priv_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    pub_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def _claims(**overrides):
    base = {
        "customer_id": "empresa_001", "license_id": "NOVUS-001", "status": "active",
        "valid_from": NOW - DAY, "valid_until": NOW + DAY, "offline_until": NOW + 8 * DAY,
        "modules": {"derived": True}, "limits": {"users": 5},
        "iat": NOW, "exp": NOW + 8 * DAY,
    }
    base.update(overrides)
    return base


def test_sign_and_verify_roundtrip(keypair):
    priv_pem, pub_pem = keypair
    token = sign_claims(_claims(), priv_pem)
    claims = verify_token(token, pub_pem)
    assert claims["customer_id"] == "empresa_001"
    assert claims["modules"] == {"derived": True}


def test_verify_rejects_tampered_token(keypair):
    priv_pem, pub_pem = keypair
    token = sign_claims(_claims(), priv_pem)
    header, payload, sig = token.split(".")
    import base64, json
    padded = payload + "=" * (-len(payload) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(padded))
    decoded["valid_until"] = NOW + 3650 * DAY
    raw = json.dumps(decoded).encode().rstrip(b"=")
    tampered = header + "." + base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + sig
    with pytest.raises(LicenseInvalid):
        verify_token(tampered, pub_pem)


def test_verify_rejects_wrong_key(keypair):
    priv_pem, pub_pem = keypair
    token = sign_claims(_claims(), priv_pem)
    other = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with pytest.raises(LicenseInvalid):
        verify_token(token, other)


import json
import os

from licensing.cache import cache_path, load_cache, save_cache
from licensing.client import LicenseManager, get_manager, require_license


def _config(**license_overrides):
    lic = {"server": "http://lic.test", "customer_id": "empresa_001",
           "api_key": "clave-1", "refresh_minutes": 720}
    lic.update(license_overrides)
    return {"database": {}, "license": lic}


def test_cache_path_uses_customer(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert cache_path(_config()) == str(tmp_path / ".novus" / "license-empresa_001.json")


def test_cache_roundtrip(tmp_path):
    data = {"claims": {"customer_id": "e"}, "token": "tok", "fetched_at": 123}
    path = str(tmp_path / "cache.json")
    save_cache(path, data)
    assert load_cache(path) == data


def test_cache_corrupt_returns_none(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json")
    assert load_cache(str(path)) is None
    assert load_cache(str(tmp_path / "missing.json")) is None


class _OfflineTransport:
    def __init__(self):
        self.calls = 0

    def __call__(self, server, payload):
        self.calls += 1
        raise OSError("sin internet")


def test_manager_uses_cache_when_offline(keypair, tmp_path, monkeypatch):
    priv_pem, pub_pem = keypair
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(pub_pem)
    cache_file = tmp_path / "cache.json"
    token = sign_claims(_claims(valid_until=NOW + DAY, offline_until=NOW + 8 * DAY), priv_pem)
    save_cache(str(cache_file), {"claims": {}, "token": token, "fetched_at": NOW})

    transport = _OfflineTransport()
    monkeypatch.setattr("licensing.client._activate_http", transport)

    mgr = LicenseManager(_config(
        public_key=str(pub_path), cache_path=str(cache_file), refresh_minutes=0))
    lic = mgr.get_license()
    assert lic.state(time.time()) in (LicenseState.ACTIVE, LicenseState.GRACE)
    assert lic.has("derived") is True
    assert transport.calls >= 1


def test_manager_activates_online(keypair, tmp_path, monkeypatch):
    priv_pem, pub_pem = keypair
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(pub_pem)
    cache_file = tmp_path / "cache.json"
    token = sign_claims(_claims(), priv_pem)

    monkeypatch.setattr("licensing.client._activate_http",
                        lambda server, payload: token)
    mgr = LicenseManager(_config(public_key=str(pub_path), cache_path=str(cache_file)))
    lic = mgr.get_license()
    assert lic.customer_id == "empresa_001"
    assert lic.state(time.time()) is LicenseState.ACTIVE
    cached = load_cache(str(cache_file))
    assert cached and cached["token"] == token


def test_manager_require_blocks_module_not_contracted(keypair, tmp_path, monkeypatch):
    priv_pem, pub_pem = keypair
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(pub_pem)
    cache_file = tmp_path / "cache.json"
    token = sign_claims(_claims(modules={"dashboard": True}), priv_pem)
    save_cache(str(cache_file), {"claims": {}, "token": token, "fetched_at": NOW})
    monkeypatch.setattr("licensing.client._activate_http", lambda server, payload: token)
    mgr = LicenseManager(_config(public_key=str(pub_path), cache_path=str(cache_file)))
    with pytest.raises(LicenseNotEntitled):
        mgr.require("derived")
    assert mgr.require("dashboard") is not None


def test_manager_require_blocks_expired(keypair, tmp_path, monkeypatch):
    priv_pem, pub_pem = keypair
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(pub_pem)
    cache_file = tmp_path / "cache.json"
    token = sign_claims(_claims(valid_until=NOW - 2 * DAY, offline_until=NOW - DAY), priv_pem)
    save_cache(str(cache_file), {"claims": {}, "token": token, "fetched_at": NOW})
    monkeypatch.setattr("licensing.client._activate_http",
                        lambda server, payload: (_ for _ in ()).throw(OSError("offline")))
    mgr = LicenseManager(_config(public_key=str(pub_path), cache_path=str(cache_file)))
    with pytest.raises(LicenseBlocked):
        mgr.require("derived")


def test_manager_no_license_config_passes(tmp_path):
    mgr = LicenseManager({"database": {}})
    assert mgr.get_license().state(time.time()) is LicenseState.NO_LICENSE
    assert mgr.require("derived") is not None
    assert mgr.users_limit() is None


def test_get_manager_singleton_and_require_license(tmp_path):
    cfg = _config()
    assert get_manager(cfg) is get_manager(cfg)
    lic = require_license({"database": {}}, "bi")
    assert lic.state(time.time()) is LicenseState.NO_LICENSE
