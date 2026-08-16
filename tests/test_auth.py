import json

import pytest
from fastapi.testclient import TestClient

import cli
from dashboard import app as dashboard_app
from dashboard.auth import users as auth_users


@pytest.fixture
def auth_env(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    db_path = tmp_path / "db.sqlite"
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(db_path)},
        "tables": [],
        "fields": {},
    }
    cfg_path.write_text(json.dumps(cfg))
    assert cli.cmd_migrate(str(cfg_path)) == 0
    monkeypatch.setenv("ETL_CONFIG", str(cfg_path))
    monkeypatch.setenv("ETL_SECRET", "test-secret-for-auth-tests")
    return str(cfg_path)


@pytest.fixture
def client(auth_env):
    auth_users.create_user("root", "rootpass123", role="admin", is_root=True,
                           must_change_password=False)
    return TestClient(dashboard_app.app)


def _login(c, username, password):
    return c.post("/api/auth/login", json={"username": username, "password": password})


def test_login_success(client):
    res = _login(client, "root", "rootpass123")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["role"] == "admin"
    assert data["is_root"] is True
    assert "etl_session" in res.cookies


def test_login_wrong_password(client):
    res = _login(client, "root", "incorrecta")
    assert res.status_code == 401


def test_login_unknown_user(client):
    res = _login(client, "nadie", "nopass123")
    assert res.status_code == 401


def test_login_inactive_user(client, auth_env):
    uid = auth_users.create_user("inactivo", "inactivo123", role="user")
    auth_users.update_user(uid, active=False)
    res = _login(client, "inactivo", "inactivo123")
    assert res.status_code == 403


def test_me_requires_auth(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_me_returns_profile(client):
    _login(client, "root", "rootpass123")
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "root"
    assert data["role"] == "admin"
    assert data["is_root"] is True


def test_user_cannot_access_admin_endpoints(client):
    _login(client, "root", "rootpass123")
    client.post("/api/admin/users", json={
        "username": "operador", "password": "operador123",
        "role": "user", "must_change_password": False,
    })
    client.post("/api/auth/logout")
    _login(client, "operador", "operador123")

    assert client.get("/api/executions").status_code == 403
    assert client.get("/api/progress").status_code == 403
    assert client.get("/api/dashboard").status_code == 403
    assert client.get("/api/tables?run_id=1").status_code == 403
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/etl").status_code == 403
    assert client.get("/panel").status_code == 403


def test_user_can_access_user_endpoints(client):
    _login(client, "root", "rootpass123")
    client.post("/api/admin/users", json={
        "username": "operador", "password": "operador123",
        "role": "user", "must_change_password": False,
    })
    client.post("/api/auth/logout")
    _login(client, "operador", "operador123")

    assert client.get("/api/live").status_code == 200
    assert client.get("/api/last-sync").status_code == 200
    assert client.get("/api/inventory").status_code == 200
    assert client.get("/derivadas").status_code == 200


def test_change_password_flow(client):
    _login(client, "root", "rootpass123")
    client.post("/api/admin/users", json={
        "username": "operador", "password": "inicial123",
        "role": "user", "must_change_password": True,
    })
    client.post("/api/auth/logout")

    _login(client, "operador", "inicial123")
    me = client.get("/api/auth/me").json()
    assert me["must_change_password"] is True

    bad = client.post("/api/auth/password", json={
        "current_password": "mal", "new_password": "nuevapass123"})
    assert bad.status_code == 401

    ok = client.post("/api/auth/password", json={
        "current_password": "inicial123", "new_password": "nuevapass123"})
    assert ok.status_code == 200

    me2 = client.get("/api/auth/me").json()
    assert me2["must_change_password"] is False

    client.post("/api/auth/logout")
    assert _login(client, "operador", "nuevapass123").status_code == 200
    assert _login(client, "operador", "inicial123").status_code == 401


def test_change_password_min_length(client):
    _login(client, "root", "rootpass123")
    res = client.post("/api/auth/password", json={
        "current_password": "rootpass123", "new_password": "corto"})
    assert res.status_code == 400


def test_change_password_same_as_current(client):
    _login(client, "root", "rootpass123")
    res = client.post("/api/auth/password", json={
        "current_password": "rootpass123", "new_password": "rootpass123"})
    assert res.status_code == 400
    assert "password_igual_actual" in res.json()["detail"]


def test_index_redirects_to_login_without_session(client):
    client.post("/api/auth/logout")
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/login"


def test_index_redirects_by_role_with_session(client):
    _login(client, "root", "rootpass123")
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/panel"


def test_protected_pages_redirect_to_login_without_session(client):
    client.post("/api/auth/logout")
    for page in ("/inventario", "/etl", "/panel"):
        res = client.get(page, follow_redirects=False)
        assert res.status_code == 307
        assert res.headers["location"] == "/login"


def test_protected_pages_keep_role_checks(client):
    _login(client, "root", "rootpass123")
    client.post("/api/admin/users", json={
        "username": "solo_user", "password": "userpass123",
        "role": "user", "must_change_password": False})
    client.post("/api/auth/logout")
    _login(client, "solo_user", "userpass123")

    redir = client.get("/inventario", follow_redirects=False)
    assert redir.status_code == 307
    assert redir.headers["location"] == "/derivadas"
    assert client.get("/derivadas").status_code == 200
    assert client.get("/etl").status_code == 403
    assert client.get("/panel").status_code == 403


def test_admin_create_list_update_delete(client):
    _login(client, "root", "rootpass123")

    created = client.post("/api/admin/users", json={
        "username": "alice", "password": "alicepass123",
        "role": "user", "must_change_password": True})
    assert created.status_code == 200
    uid = created.json()["id"]

    listed = client.get("/api/admin/users").json()
    assert {u["username"] for u in listed} >= {"root", "alice"}

    up = client.patch(f"/api/admin/users/{uid}", json={"role": "admin"})
    assert up.status_code == 200
    assert up.json()["role"] == "admin"

    deact = client.patch(f"/api/admin/users/{uid}", json={"active": False})
    assert deact.json()["active"] is False

    assert client.delete(f"/api/admin/users/{uid}").status_code == 200
    assert not auth_users.get_user_by_id(uid)


def test_admin_create_duplicate_username(client):
    _login(client, "root", "rootpass123")
    body = {"username": "dup", "password": "duppass123", "role": "user"}
    assert client.post("/api/admin/users", json=body).status_code == 200
    assert client.post("/api/admin/users", json=body).status_code == 409


def test_admin_create_short_password(client):
    _login(client, "root", "rootpass123")
    res = client.post("/api/admin/users", json={
        "username": "short", "password": "123", "role": "user"})
    assert res.status_code == 400


def test_root_is_protected(client):
    _login(client, "root", "rootpass123")
    admin_id = client.post("/api/admin/users", json={
        "username": "admin2", "password": "admin2pass",
        "role": "admin", "must_change_password": False}).json()["id"]

    root_id = auth_users.get_user_by_username("root")["id"]

    patch = client.patch(f"/api/admin/users/{root_id}", json={"role": "user"})
    assert patch.status_code == 403
    assert client.delete(f"/api/admin/users/{root_id}").status_code == 403

    client.post("/api/auth/logout")
    _login(client, "admin2", "admin2pass")

    assert client.patch(f"/api/admin/users/{root_id}", json={"role": "user"}).status_code == 403
    assert client.delete(f"/api/admin/users/{root_id}").status_code == 403
    reset = client.post(f"/api/admin/users/{root_id}/password", json={"new_password": "x12345678"})
    assert reset.status_code == 403

    own = client.delete(f"/api/admin/users/{admin_id}")
    assert own.status_code == 200


def test_login_page_served(client):
    res = client.get("/login")
    assert res.status_code == 200
    assert "Invertec BI" in res.text


def test_static_assets_served(client):
    res = client.get("/static/common.css")
    assert res.status_code == 200
    assert "body" in res.text
    assert client.get("/static/common.js").status_code == 200


def test_cli_users_add_list_set_password(auth_env, capsys):
    assert cli.main(["users", "add", "--config", auth_env,
                     "--username", "cliuser", "--password", "clipass123",
                     "--role", "user", "--no-force-password-change"]) == 0
    capsys.readouterr()

    assert cli.main(["users", "list", "--config", auth_env]) == 0
    out = capsys.readouterr().out
    assert "cliuser" in out
    assert "[user]" in out

    assert cli.main(["users", "set-password", "--config", auth_env,
                     "--username", "cliuser", "--password", "nuevapass123"]) == 0
    capsys.readouterr()

    user = auth_users.get_user_by_username("cliuser")
    from dashboard.auth import security
    assert user is not None
    assert security.verify_password("nuevapass123", auth_users.get_user_with_hash("cliuser")["password_hash"])


def test_cli_users_set_password_missing_user(auth_env, capsys):
    assert cli.main(["users", "set-password", "--config", auth_env,
                     "--username", "fantasma", "--password", "nopass123"]) == 1
