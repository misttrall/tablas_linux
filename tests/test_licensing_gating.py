import json
import time

import cli
from licensing import (
    License,
    LicenseBlocked,
    LicenseNotEntitled,
    LicenseState,
)

NOW = int(time.time())
DAY = 86400


class StubManager:
    def __init__(self, lic):
        self._lic = lic

    def get_license(self):
        return self._lic

    def require(self, module):
        st = self._lic.state(time.time())
        if st in (LicenseState.EXPIRED, LicenseState.SUSPENDED, LicenseState.REVOKED):
            raise LicenseBlocked(f"licencia {st.value}")
        if not self._lic.has(module):
            raise LicenseNotEntitled(f"módulo '{module}' no contratado")
        return self._lic

    def state(self):
        return self._lic.state(time.time())

    def force_activate(self):
        return self._lic

    def validate(self):
        return self._lic

    def clear_cache(self):
        pass

    def users_limit(self):
        return self._lic.limit("users")


def _license(**overrides):
    modules = {"derived": True, "dashboard": True, "bi": True}
    if "modules" in overrides:
        modules = overrides.pop("modules")
    base = dict(customer_id="e", license_id="l", status="active",
                valid_from=NOW - DAY, valid_until=NOW + DAY, offline_until=NOW + 8 * DAY,
                modules=modules, limits={"users": 5}, issued_at=NOW)
    base.update(overrides)
    return License(**base)


def _make_config(tmp_path, **license_kwargs):
    cfg_path = tmp_path / "config.json"
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(tmp_path / "db.sqlite")},
        "tables": [], "fields": {},
        "license": {"server": "http://lic.test", "customer_id": "e", "api_key": "k"},
    }
    if license_kwargs.get("derived"):
        cfg["derived"] = {"name": "inv_bodega"}
    cfg_path.write_text(json.dumps(cfg))
    return str(cfg_path)


def _patch_manager(monkeypatch, lic):
    import licensing.client
    monkeypatch.setattr(licensing.client, "get_manager", lambda config: StubManager(lic))


def test_report_requires_derived(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path, derived=True)
    _patch_manager(monkeypatch, _license(modules={"dashboard": True, "bi": True}))
    assert cli.cmd_reporte(cfg) == 1
    out = capsys.readouterr().out
    assert "derived" in out


def test_report_ok_with_derived(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path, derived=True)
    _patch_manager(monkeypatch, _license())
    import derived.views as dv
    monkeypatch.setattr(dv, "derived_views", lambda config: [])
    assert cli.cmd_reporte(cfg) == 0


def test_bi_requires_bi(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path)
    _patch_manager(monkeypatch, _license(modules={"derived": True, "dashboard": True}))
    assert cli.cmd_bi(cfg, "manifest") == 1
    out = capsys.readouterr().out
    assert "bi" in out


def test_bootstrap_with_derived_requires_derived(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path, derived=True)
    _patch_manager(monkeypatch, _license(modules={"dashboard": True, "bi": True}))
    monkeypatch.setattr(cli, "cmd_migrate", lambda config_path: 0)
    assert cli.cmd_bootstrap(cfg, with_derived=True, skip_sap=True) == 1
    out = capsys.readouterr().out
    assert "derived" in out


def test_users_add_blocks_at_limit(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path)
    _patch_manager(monkeypatch, _license(limits={"users": 1}))
    from dashboard.auth import users as auth_users
    monkeypatch.setattr(auth_users, "list_users", lambda: [{"id": 1}])
    args = type("A", (), {"config": cfg, "users_action": "add",
                          "username": "nuevo", "password": "x", "role": "user",
                          "root": False, "no_force_password_change": True})
    assert cli.cmd_users(args) == 1
    out = capsys.readouterr().out
    assert "límite" in out


def test_license_status_and_clear_cache(tmp_path, monkeypatch, capsys):
    cfg = _make_config(tmp_path)
    _patch_manager(monkeypatch, _license())
    assert cli.cmd_license(cfg, "status") == 0
    out = capsys.readouterr().out
    assert "ACTIVE" in out
    assert cli.cmd_license(cfg, "clear-cache") == 0
    assert "caché" in capsys.readouterr().out
