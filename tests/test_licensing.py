import time

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
