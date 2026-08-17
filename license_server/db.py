"""Esquema y acceso a datos del license server (BD SQLite propia)."""

import datetime as _dt
import hashlib
import hmac

from sqlalchemy import create_engine, text


def init_db(engine):
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS customers ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "customer_id VARCHAR(128) NOT NULL UNIQUE, "
            "name VARCHAR(255) NOT NULL, "
            "api_key_hash VARCHAR(128) NOT NULL, "
            "status VARCHAR(32) NOT NULL DEFAULT 'active', "
            "created_at TEXT NOT NULL)"))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS licenses ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "license_id VARCHAR(128) NOT NULL UNIQUE, "
            "customer_id VARCHAR(128) NOT NULL, "
            "status VARCHAR(32) NOT NULL DEFAULT 'active', "
            "valid_from INTEGER NOT NULL, "
            "valid_until INTEGER NOT NULL, "
            "offline_until INTEGER NOT NULL, "
            "created_at TEXT NOT NULL, "
            "updated_at TEXT NOT NULL)"))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS license_modules ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "license_id INTEGER NOT NULL, "
            "module VARCHAR(64) NOT NULL, "
            "enabled INTEGER NOT NULL)"))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS license_limits ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "license_id INTEGER NOT NULL, "
            "name VARCHAR(64) NOT NULL, "
            "value INTEGER NOT NULL)"))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS license_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "license_id INTEGER, "
            "event_type VARCHAR(64) NOT NULL, "
            "detail TEXT, "
            "created_at TEXT NOT NULL)"))


def _now_iso():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def hash_api_key(secret: str, api_key: str) -> str:
    return hmac.new(secret.encode(), api_key.encode(), hashlib.sha256).hexdigest()


def verify_api_key(secret: str, provided: str, expected_hash: str) -> bool:
    computed = hash_api_key(secret, provided)
    return hmac.compare_digest(computed, expected_hash)


def create_customer(engine, customer_id, name, api_key_hash):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO customers (customer_id, name, api_key_hash, status, created_at) "
                 "VALUES (:cid, :name, :h, 'active', :ts)"),
            {"cid": customer_id, "name": name, "h": api_key_hash, "ts": _now_iso()})


def get_customer(engine, customer_id):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id, customer_id, name, api_key_hash, status FROM customers "
                 "WHERE customer_id = :cid"),
            {"cid": customer_id}).fetchone()


def list_customers(engine):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id, customer_id, name, status, created_at "
                 "FROM customers ORDER BY id")).fetchall()


def set_customer_status(engine, customer_id, status):
    with engine.begin() as conn:
        conn.execute(text("UPDATE customers SET status = :s WHERE customer_id = :cid"),
                     {"s": status, "cid": customer_id})


def issue_license(engine, customer_id, license_id, valid_from, valid_until,
                  grace_days, modules, limits):
    offline_until = valid_until + grace_days * 86400
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO licenses (license_id, customer_id, status, valid_from, "
                 "valid_until, offline_until, created_at, updated_at) "
                 "VALUES (:lid, :cid, 'active', :vf, :vu, :ou, :ts, :ts)"),
            {"lid": license_id, "cid": customer_id, "vf": valid_from,
             "vu": valid_until, "ou": offline_until, "ts": _now_iso()})
        lid = conn.execute(text("SELECT id FROM licenses WHERE license_id = :lid"),
                           {"lid": license_id}).scalar_one()
        for module, enabled in modules.items():
            conn.execute(
                text("INSERT INTO license_modules (license_id, module, enabled) "
                     "VALUES (:lid, :m, :e)"),
                {"lid": lid, "m": module, "e": 1 if enabled else 0})
        for name, value in limits.items():
            conn.execute(
                text("INSERT INTO license_limits (license_id, name, value) "
                     "VALUES (:lid, :n, :v)"),
                {"lid": lid, "n": name, "v": value})
        conn.execute(
            text("INSERT INTO license_events (license_id, event_type, detail, created_at) "
                 "VALUES (:lid, 'issued', :d, :ts)"),
            {"lid": lid, "d": f"license {license_id}", "ts": _now_iso()})
    return license_id


def renew_license(engine, license_id, valid_from, valid_until, grace_days):
    offline_until = valid_until + grace_days * 86400
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE licenses SET status='active', valid_from=:vf, valid_until=:vu, "
                 "offline_until=:ou, updated_at=:ts WHERE license_id=:lid"),
            {"vf": valid_from, "vu": valid_until, "ou": offline_until,
             "ts": _now_iso(), "lid": license_id})
        conn.execute(
            text("INSERT INTO license_events (license_id, event_type, detail, created_at) "
                 "VALUES ((SELECT id FROM licenses WHERE license_id=:lid), 'renewed', :d, :ts)"),
            {"lid": license_id, "d": f"license {license_id}", "ts": _now_iso()})


def set_license_status(engine, license_id, status, event):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE licenses SET status=:s, updated_at=:ts WHERE license_id=:lid"),
            {"s": status, "ts": _now_iso(), "lid": license_id})
        conn.execute(
            text("INSERT INTO license_events (license_id, event_type, detail, created_at) "
                 "VALUES ((SELECT id FROM licenses WHERE license_id=:lid), :e, :d, :ts)"),
            {"lid": license_id, "e": event, "d": f"license {license_id}", "ts": _now_iso()})


def _license_payload(engine, row):
    lid = row["id"]
    with engine.connect() as conn:
        modules = {m[0]: bool(m[1]) for m in conn.execute(
            text("SELECT module, enabled FROM license_modules WHERE license_id=:lid"),
            {"lid": lid})}
        limits = {n[0]: n[1] for n in conn.execute(
            text("SELECT name, value FROM license_limits WHERE license_id=:lid"),
            {"lid": lid})}
    return {
        "customer_id": row["customer_id"],
        "license_id": row["license_id"],
        "status": row["status"],
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "offline_until": row["offline_until"],
        "modules": modules,
        "limits": limits,
    }


def get_active_license(engine, customer_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, customer_id, license_id, status, valid_from, valid_until, "
                 "offline_until FROM licenses WHERE customer_id=:cid ORDER BY id DESC LIMIT 1"),
            {"cid": customer_id}).fetchone()
    if row is None:
        return None
    return _license_payload(engine, dict(row._mapping))


def get_license_by_id(engine, license_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, customer_id, license_id, status, valid_from, valid_until, "
                 "offline_until FROM licenses WHERE license_id=:lid"),
            {"lid": license_id}).fetchone()
    if row is None:
        return None
    return _license_payload(engine, dict(row._mapping))


def list_licenses(engine, customer_id=None):
    sql = ("SELECT id, customer_id, license_id, status, valid_from, valid_until, "
           "offline_until, created_at FROM licenses")
    params = {}
    if customer_id:
        sql += " WHERE customer_id=:cid"
        params["cid"] = customer_id
    sql += " ORDER BY id DESC"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return [dict(r._mapping) for r in rows]


def record_event(engine, license_id, event_type, detail):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO license_events (license_id, event_type, detail, created_at) "
                 "VALUES ((SELECT id FROM licenses WHERE license_id=:lid), :e, :d, :ts)"),
            {"lid": license_id, "e": event_type, "d": detail, "ts": _now_iso()})
