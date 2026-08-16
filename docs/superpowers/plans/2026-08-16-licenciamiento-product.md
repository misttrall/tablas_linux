# Licenciamiento / product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir control de licencias firmadas a Novus: un servidor (`license_server/`) que emite/valida JWT ed25519 y un cliente embebido (`licensing/`) que activa, cachea, da gracia offline y gatea los módulos opt-in (`derived`, `dashboard`, `bi`) más el límite de usuarios.

**Architecture:** El engine llama `POST /api/activate` con `customer_id` + `api_key` contra el servidor FastAPI (BD SQLite propia); el servidor firma un JWT ed25519 (clave privada solo en el servidor) con `modules`/`limits`/ventanas y el engine lo verifica con la clave pública embebida, lo cachea en disco y decide estados ACTIVE/GRACE/EXPIRED/SUSPENDED/REVOKED. Sin bloque `license` en config → modo no-licenciado (todo habilitado). Sin reescructurar el repo.

**Tech Stack:** FastAPI (existente), SQLAlchemy (existente), PyJWT (existente, EdDSA), `cryptography>=42` (nueva dependencia), sqlite, pytest, httpx (TestClient).

**Spec:** `docs/superpowers/specs/2026-08-16-licenciamiento-product.md`

## Global Constraints

- Sin bloque `license` en config → gating desactivado (modo `NO_LICENSE`: `License.no_license()`, `has()` siempre `True`, `limit()` `None`). La suite existente (246 tests) debe seguir en verde sin cambios.
- `etl` y `users` son core incluido (no se gatean); `derived`, `dashboard`, `bi` son opt-in.
- Claims del JWT: `customer_id`, `license_id`, `status`, `valid_from`, `valid_until`, `offline_until`, `modules` (dict str→bool), `limits` (dict str→int), `iat`, `exp` (= `offline_until`). Fechas como epoch int (UTC). `status` lowercase: `"active"`, `"suspended"`, `"revoked"`.
- `offline_until = valid_until + grace_days * 86400` (lo calcula el servidor; default `grace_days=7`).
- `api_key` se guarda como HMAC-SHA256 + pepper (`NOVUS_LICENSE_SERVER_SECRET`); comparación con `hmac.compare_digest`.
- Runtime importa desde `licensing.client` (no desde `licensing` raíz), para que los tests puedan `monkeypatch.setattr("licensing.client.get_manager", ...)`.
- Errores accionables en español; CLI exit≠0; datos ya extraídos nunca se borran.
- Nueva dependencia: `cryptography>=42` en `requirements-base.txt` y `pyproject.toml`.
- `.gitignore`: añadir `license_server/private_key.pem` (clave privada nunca se commitea).
- Nombres/formatos: mensajes con `[error]`/`[ok]` en CLI; detalles de error en inglés snake_case (p. ej. `credenciales_invalidas`, `modulo_no_contratado:derived`).

---

### Task 1: Dependencia `cryptography` + `licensing/models.py`

**Files:**
- Modify: `requirements-base.txt`
- Modify: `pyproject.toml`
- Create: `licensing/models.py`
- Create: `licensing/__init__.py`
- Test: `tests/test_licensing.py`

**Interfaces:**
- Produces: `licensing.models.LicenseState` (enum ACTIVE/GRACE/EXPIRED/SUSPENDED/REVOKED/NO_LICENSE), `licensing.models.License` (`has(module)`, `limit(name)`, `state(now)`, classmethod `no_license()`), excepciones `LicenseError`, `LicenseInvalid`, `LicenseBlocked`, `LicenseUnreachable`, `LicenseNotEntitled`.

- [ ] **Step 1: Añadir la dependencia y los paquetes**

En `requirements-base.txt`, añadir al final:

```
cryptography>=42
```

En `pyproject.toml`, en `[project].dependencies` añadir `"cryptography>=42",` y en `[tool.setuptools].packages` añadir `"licensing", "license_server",`.

- [ ] **Step 2: Instalar la dependencia**

Run: `.venv/bin/pip install -r requirements-base.txt`
Expected: `cryptography` instalado sin errores.

- [ ] **Step 3: Escribir el test que falla**

`tests/test_licensing.py`:

```python
import time

import pytest

from licensing import (
    License,
    LicenseBlocked,
    LicenseInvalid,
    LicenseNotEntitled,
    LicenseState,
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
    assert issubclass(LicenseNotEntitled, LicenseError)
```

- [ ] **Step 4: Ejecutar para verificar que falla**

Run: `.venv/bin/pytest tests/test_licensing.py -v`
Expected: `ModuleNotFoundError: No module named 'licensing'` (o `License` no definido).

- [ ] **Step 5: Implementar `licensing/models.py`**

```python
import enum


class LicenseState(enum.Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    NO_LICENSE = "NO_LICENSE"


class LicenseError(Exception):
    """Error de licencia genérico."""


class LicenseInvalid(LicenseError):
    """Firma corrupta o caché ilegible."""


class LicenseBlocked(LicenseError):
    """Activación rechazada / estado bloqueante."""


class LicenseUnreachable(LicenseError):
    """No se pudo contactar el servidor de licencias."""


class LicenseNotEntitled(LicenseError):
    """El módulo solicitado no está contratado."""


class License:
    def __init__(self, customer_id, license_id, status, valid_from, valid_until,
                 offline_until, modules, limits, issued_at):
        self.customer_id = customer_id
        self.license_id = license_id
        self.status = status
        self.valid_from = valid_from
        self.valid_until = valid_until
        self.offline_until = offline_until
        self.modules = modules      # dict[str, bool] | None (None = todos habilitados)
        self.limits = limits        # dict[str, int] | None
        self.issued_at = issued_at

    @classmethod
    def no_license(cls):
        return cls(customer_id=None, license_id=None, status="NO_LICENSE",
                   valid_from=None, valid_until=None, offline_until=None,
                   modules=None, limits=None, issued_at=None)

    def has(self, module):
        if self.modules is None:
            return True
        return bool(self.modules.get(module, False))

    def limit(self, name):
        if self.limits is None:
            return None
        return self.limits.get(name)

    def state(self, now):
        if self.status == "NO_LICENSE":
            return LicenseState.NO_LICENSE
        if self.status in ("suspended", "revoked"):
            return LicenseState[self.status.upper()]
        if now <= self.valid_until:
            return LicenseState.ACTIVE
        if now <= self.offline_until:
            return LicenseState.GRACE
        return LicenseState.EXPIRED
```

- [ ] **Step 6: Crear `licensing/__init__.py`**

```python
"""Cliente de licencias Novus embebido en el engine.

El runtime importa desde `licensing.client` (no desde este paquete) para
facilitar el mockeo en tests.
"""

from .client import LicenseManager, get_manager, require_license
from .models import (
    License,
    LicenseBlocked,
    LicenseError,
    LicenseInvalid,
    LicenseNotEntitled,
    LicenseState,
    LicenseUnreachable,
)

__all__ = [
    "LicenseManager",
    "get_manager",
    "require_license",
    "License",
    "LicenseBlocked",
    "LicenseError",
    "LicenseInvalid",
    "LicenseNotEntitled",
    "LicenseState",
    "LicenseUnreachable",
]
```

Nota: este `__init__.py` importa `.client`, que todavía no existe. Se creará en la Tarea 6; mientras tanto el test de la Tarea 1 importa `from licensing import ...`. Para que la Tarea 1 quede verde sin `client.py`, hacer que el `__init__.py` sea tolerante:

```python
try:
    from .client import LicenseManager, get_manager, require_license
except ImportError:  # pragma: no cover - cliente se completa en Tarea 6
    LicenseManager = None
    get_manager = None
    require_license = None
```

- [ ] **Step 7: Ejecutar para verificar que pasa**

Run: `.venv/bin/pytest tests/test_licensing.py -v`
Expected: 6 passed.

- [ ] **Step 8: Commit**

```bash
git add licensing/ tests/test_licensing.py requirements-base.txt pyproject.toml
git commit -m "feat(licensing): modelo de licencia y estados (ACTIVE/GRACE/EXPIRED/SUSPENDED/REVOKED/NO_LICENSE)"
```

---

### Task 2: Firma y verificación ed25519

**Files:**
- Create: `license_server/signing.py`
- Create: `licensing/validator.py`
- Test: `tests/test_licensing.py` (añadir casos)

**Interfaces:**
- Consumes: `LicenseInvalid` (de `licensing.models`).
- Produces: `license_server.signing.sign_claims(claims: dict, private_key_pem: bytes) -> str` (JWT EdDSA); `licensing.validator.verify_token(token: str, public_key_pem: bytes) -> dict` (levanta `LicenseInvalid` si la firma es inválida; `verify_exp=False` — las ventanas se evalúan en `License.state`).

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_licensing.py` (arriba del todo):

```python
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

import jwt

from licensing.validator import verify_token
from license_server.signing import sign_claims


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
```

- [ ] **Step 2: Ejecutar para verificar que falla**

Run: `.venv/bin/pytest tests/test_licensing.py -v`
Expected: FAIL con `ModuleNotFoundError` (`license_server` / `sign_claims` no existe).

- [ ] **Step 3: Implementar `license_server/signing.py`**

```python
"""Firma de licencias con ed25519 (JWT EdDSA). La clave privada vive solo en el servidor."""

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def sign_claims(claims: dict, private_key_pem: bytes) -> str:
    key = load_pem_private_key(private_key_pem, password=None)
    return jwt.encode(claims, key, algorithm="EdDSA")
```

- [ ] **Step 4: Implementar `licensing/validator.py`**

```python
"""Verificación de la firma de licencias con la clave pública de Novus."""

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .models import LicenseInvalid


def verify_token(token: str, public_key_pem: bytes) -> dict:
    key = load_pem_public_key(public_key_pem)
    try:
        return jwt.decode(token, key, algorithms=["EdDSA"], options={"verify_exp": False})
    except jwt.InvalidTokenError as exc:
        raise LicenseInvalid(f"firma de licencia inválida: {exc}") from exc
```

- [ ] **Step 5: Ejecutar para verificar que pasa**

Run: `.venv/bin/pytest tests/test_licensing.py -v`
Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
git add licensing/validator.py license_server/signing.py tests/test_licensing.py
git commit -m "feat(licensing): firma y verificación de licencias con JWT ed25519"
```

---

### Task 3: Base de datos del license server

**Files:**
- Create: `license_server/__init__.py`
- Create: `license_server/db.py`
- Test: `tests/test_license_server.py`

**Interfaces:**
- Consumes: nada (depende solo de SQLAlchemy).
- Produces: `license_server.db.init_db(engine)`, `hash_api_key(secret, api_key) -> str`, `verify_api_key(secret, api_key, expected_hash) -> bool`, `create_customer(engine, customer_id, name, api_key_hash)`, `get_customer(engine, customer_id) -> Row|None`, `list_customers(engine)`, `set_customer_status(engine, customer_id, status)`, `issue_license(engine, customer_id, license_id, valid_from, valid_until, grace_days, modules, limits)`, `renew_license(engine, license_id, valid_from, valid_until, grace_days)`, `set_license_status(engine, license_id, status, event)`, `get_active_license(engine, customer_id) -> dict|None` (con `modules`/`limits`), `get_license_by_id(engine, license_id) -> dict|None`, `list_licenses(engine, customer_id=None)`, `record_event(engine, license_id, event_type, detail)`.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_license_server.py`:

```python
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
    secret = "s3cr3t"
    h = license_db.hash_api_key(secret, "clave-cliente")
    assert license_db.verify_api_key(secret, "clave-cliente", h) is True
    assert license_db.verify_api_key(secret, "otra", h) is False


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
```

- [ ] **Step 2: Ejecutar para verificar que falla**

Run: `.venv/bin/pytest tests/test_license_server.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Crear `license_server/__init__.py`**

```python
"""Servidor de licencias Novus (emite y valida JWT firmados)."""
```

- [ ] **Step 4: Implementar `license_server/db.py`**

```python
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


def verify_api_key(secret: str, api_key: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(secret, api_key), expected_hash)


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
```

- [ ] **Step 5: Ejecutar para verificar que pasa**

Run: `.venv/bin/pytest tests/test_license_server.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add license_server/ tests/test_license_server.py
git commit -m "feat(license-server): esquema y DAO de clientes, licencias, módulos, límites y eventos"
```

---

### Task 4: API del license server (`/api/activate`, `/api/health`)

**Files:**
- Create: `license_server/app.py`
- Test: `tests/test_license_server.py` (añadir casos)

**Interfaces:**
- Consumes: `license_server.db.*`, `license_server.signing.sign_claims`, excepciones HTTP de FastAPI.
- Produces: `license_server.app.create_app(engine, private_key_pem, secret) -> FastAPI` con `GET /api/health` y `POST /api/activate` (`{customer_id, api_key}` → `{"token": str, "claims": dict}`; errores 401 credenciales/cliente inexistente, 403 cliente deshabilitado / sin licencia activa / suspendida / revocada).

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_license_server.py`:

```python
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
    eng = create_engine("sqlite://")
    license_db.init_db(eng)
    priv_pem, _ = keypair
    return TestClient(create_app(eng, priv_pem, "test-secret"))


@pytest.fixture
def customer_license(engine):
    license_db.create_customer(engine, "empresa_001", "Mi Empresa",
                               license_db.hash_api_key("test-secret", "clave-1"))
    license_db.issue_license(
        engine, "empresa_001", "NOVUS-001",
        valid_from=1_000_000, valid_until=9_000_000, grace_days=7,
        modules={"derived": True, "dashboard": True, "bi": False},
        limits={"users": 5})
    return engine


def test_health(api_client):
    res = api_client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_activate_ok(keypair, customer_license):
    priv_pem, pub_pem = keypair
    eng = customer_license
    client = TestClient(create_app(eng, priv_pem, "test-secret"))
    res = client.post("/api/activate", json={"customer_id": "empresa_001", "api_key": "clave-1"})
    assert res.status_code == 200
    body = res.json()
    claims = verify_token(body["token"], pub_pem)
    assert claims["customer_id"] == "empresa_001"
    assert claims["modules"]["derived"] is True
    assert claims["limits"]["users"] == 5
    assert body["claims"] == claims


def test_activate_bad_api_key(keypair, customer_license):
    eng = customer_license
    client = TestClient(create_app(eng, keypair[0], "test-secret"))
    res = client.post("/api/activate", json={"customer_id": "empresa_001", "api_key": "nope"})
    assert res.status_code == 401
    assert res.json()["detail"] == "credenciales_invalidas"


def test_activate_unknown_customer(keypair, customer_license):
    client = TestClient(create_app(customer_license, keypair[0], "test-secret"))
    res = client.post("/api/activate", json={"customer_id": "otra", "api_key": "x"})
    assert res.status_code == 401


def test_activate_disabled_customer(keypair, customer_license):
    license_db.set_customer_status(customer_license, "empresa_001", "disabled")
    client = TestClient(create_app(customer_license, keypair[0], "test-secret"))
    res = client.post("/api/activate", json={"customer_id": "empresa_001", "api_key": "clave-1"})
    assert res.status_code == 403
    assert res.json()["detail"] == "cliente_deshabilitado"


def test_activate_suspended_license(keypair, customer_license):
    license_db.set_license_status(customer_license, "NOVUS-001", "suspended", "suspended")
    client = TestClient(create_app(customer_license, keypair[0], "test-secret"))
    res = client.post("/api/activate", json={"customer_id": "empresa_001", "api_key": "clave-1"})
    assert res.status_code == 403
    assert res.json()["detail"] == "licencia_suspendida"


def test_activate_no_license(keypair):
    eng = create_engine("sqlite://")
    license_db.init_db(eng)
    license_db.create_customer(eng, "empresa_001", "Mi Empresa",
                               license_db.hash_api_key("test-secret", "clave-1"))
    client = TestClient(create_app(eng, keypair[0], "test-secret"))
    res = client.post("/api/activate", json={"customer_id": "empresa_001", "api_key": "clave-1"})
    assert res.status_code == 403
    assert res.json()["detail"] == "sin_licencia_activa"
```

- [ ] **Step 2: Ejecutar para verificar que falla**

Run: `.venv/bin/pytest tests/test_license_server.py -v`
Expected: FAIL con `ModuleNotFoundError: license_server.app`.

- [ ] **Step 3: Implementar `license_server/app.py`**

```python
"""API HTTP del license server (FastAPI)."""

import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine

from . import db as license_db
from .signing import sign_claims


class ActivateRequest(BaseModel):
    customer_id: str
    api_key: str


def create_app(engine, private_key_pem: bytes, secret: str) -> FastAPI:
    app = FastAPI(title="Novus License Server")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/activate")
    def activate(body: ActivateRequest):
        customer = license_db.get_customer(engine, body.customer_id)
        if customer is None or not license_db.verify_api_key(secret, body.api_key,
                                                             customer.api_key_hash):
            raise HTTPException(status_code=401, detail="credenciales_invalidas")
        if customer.status != "active":
            raise HTTPException(status_code=403, detail="cliente_deshabilitado")
        lic = license_db.get_active_license(engine, body.customer_id)
        if lic is None:
            raise HTTPException(status_code=403, detail="sin_licencia_activa")
        if lic["status"] == "suspended":
            raise HTTPException(status_code=403, detail="licencia_suspendida")
        if lic["status"] == "revoked":
            raise HTTPException(status_code=403, detail="licencia_revocada")
        now = int(datetime.now(timezone.utc).timestamp())
        claims = dict(lic)
        claims["iat"] = now
        claims["exp"] = lic["offline_until"]
        return {"token": sign_claims(claims, private_key_pem), "claims": claims}

    return app


def _default_engine():
    path = os.environ.get("NOVUS_LICENSE_DB", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "novus_license.db"))
    return create_engine(f"sqlite:///{path}")


def _default_private_key() -> bytes:
    path = os.environ.get("NOVUS_LICENSE_PRIVATE_KEY", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "private_key.pem"))
    with open(path, "rb") as fh:
        return fh.read()


def _default_secret() -> str:
    secret = os.environ.get("NOVUS_LICENSE_SERVER_SECRET")
    if not secret:
        raise RuntimeError("Define NOVUS_LICENSE_SERVER_SECRET (pepper del servidor de licencias)")
    return secret


try:  # app de arranque (uvicorn license_server.app:app); los tests usan create_app()
    _engine = _default_engine()
    license_db.init_db(_engine)
    app = create_app(_engine, _default_private_key(), _default_secret())
except Exception:
    app = None  # sin claves/config el arranque directo fallará con mensaje claro
```

- [ ] **Step 4: Ejecutar para verificar que pasa**

Run: `.venv/bin/pytest tests/test_license_server.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add license_server/app.py tests/test_license_server.py
git commit -m "feat(license-server): POST /api/activate y GET /api/health"
```

---

### Task 5: CLI de gestión del license server (`keygen`, `customer`, `license`)

**Files:**
- Create: `license_server/cli.py`
- Create: `scripts/run_license_server.sh`
- Test: `tests/test_license_server_cli.py`

**Interfaces:**
- Consumes: `license_server.db.*`.
- Produces: `python -m license_server.cli keygen|customer ...|license ...` con salida `[ok]`/`[error]` y código de salida.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_license_server_cli.py`:

```python
import os

import pytest
from sqlalchemy import create_engine, text

from license_server import cli as server_cli
from license_server import db as license_db


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVUS_LICENSE_DB", str(tmp_path / "server.db"))
    monkeypatch.setenv("NOVUS_LICENSE_SERVER_SECRET", "test-secret")
    engine = server_cli._engine()
    license_db.init_db(engine)
    return tmp_path


def test_keygen_writes_keys(env, tmp_path):
    key_path = tmp_path / "private_key.pem"
    monkeypatch_target = "license_server.cli._key_paths"
    # keygen escribe rutas fijas del repo; redirigimos con monkeypatch via atributo
    server_cli._PRIVATE_KEY_PATH = str(tmp_path / "private_key.pem")
    server_cli._PUBLIC_KEY_PATH = str(tmp_path / "novus_public.pem")
    assert server_cli.cmd_keygen() == 0
    assert (tmp_path / "private_key.pem").exists()
    assert (tmp_path / "novus_public.pem").exists()
    assert "PRIVATE KEY" in (tmp_path / "private_key.pem").read_text()
    assert "PUBLIC KEY" in (tmp_path / "novus_public.pem").read_text()


def test_customer_add_and_list(env, capsys):
    assert server_cli.cmd_customer_add(
        type("A", (), {"id": "empresa_001", "name": "Mi Empresa", "api_key": "clave-1"})) == 0
    assert server_cli.cmd_customer_list(None) == 0
    out = capsys.readouterr().out
    assert "empresa_001" in out


def test_customer_disable(env):
    server_cli.cmd_customer_add(
        type("A", (), {"id": "empresa_001", "name": "Mi Empresa", "api_key": "clave-1"}))
    server_cli.cmd_customer_disable(
        type("A", (), {"id": "empresa_001"}))
    assert license_db.get_customer(server_cli._engine(), "empresa_001").status == "disabled"


def test_license_issue_show_renew(env, capsys):
    server_cli.cmd_customer_add(
        type("A", (), {"id": "empresa_001", "name": "Mi Empresa", "api_key": "clave-1"}))
    args = type("A", (), {
        "customer": "empresa_001", "license_id": "NOVUS-001",
        "valid_from": "2026-08-01", "valid_until": "2026-08-31", "grace_days": 7,
        "modules": ["derived", "dashboard"], "limit": ["users=5"],
    })
    assert server_cli.cmd_license_issue(args) == 0
    assert server_cli.cmd_license_show(
        type("A", (), {"license_id": "NOVUS-001"})) == 0
    out = capsys.readouterr().out
    assert "NOVUS-001" in out
    assert "derived" in out
    assert "users" in out

    server_cli.cmd_license_renew(
        type("A", (), {"license_id": "NOVUS-001", "valid_from": None,
                       "valid_until": "2026-09-30", "grace_days": 7}))
    lic = license_db.get_license_by_id(server_cli._engine(), "NOVUS-001")
    assert lic["valid_until"] > 2_000_000_000


def test_license_suspend_and_revoke(env):
    server_cli.cmd_customer_add(
        type("A", (), {"id": "empresa_001", "name": "Mi Empresa", "api_key": "clave-1"}))
    server_cli.cmd_license_issue(
        type("A", (), {"customer": "empresa_001", "license_id": "NOVUS-001",
                       "valid_from": "2026-08-01", "valid_until": "2026-08-31",
                       "grace_days": 7, "modules": [], "limit": []}))
    server_cli.cmd_license_suspend(type("A", (), {"license_id": "NOVUS-001"}))
    assert license_db.get_license_by_id(server_cli._engine(), "NOVUS-001")["status"] == "suspended"
    server_cli.cmd_license_revoke(type("A", (), {"license_id": "NOVUS-001"}))
    assert license_db.get_license_by_id(server_cli._engine(), "NOVUS-001")["status"] == "revoked"


def test_main_dispatch(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NOVUS_LICENSE_DB", str(tmp_path / "server.db"))
    monkeypatch.setenv("NOVUS_LICENSE_SERVER_SECRET", "test-secret")
    assert server_cli.main(["customer", "list"]) == 0
    assert server_cli.main(["license", "list"]) == 0
```

- [ ] **Step 2: Ejecutar para verificar que falla**

Run: `.venv/bin/pytest tests/test_license_server_cli.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `license_server/cli.py`**

```python
"""CLI de gestión del license server: claves, clientes y licencias."""

import argparse
import datetime as _dt
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import create_engine

from . import db as license_db

_PRIVATE_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "private_key.pem")
_PUBLIC_KEY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "licensing", "novus_public.pem")


def _engine():
    path = os.environ.get("NOVUS_LICENSE_DB", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "novus_license.db"))
    return create_engine(f"sqlite:///{path}")


def _secret():
    secret = os.environ.get("NOVUS_LICENSE_SERVER_SECRET")
    if not secret:
        print("[error] define NOVUS_LICENSE_SERVER_SECRET (pepper para hash de api_key)")
        sys.exit(1)
    return secret


def _to_epoch(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    text_value = value.strip()
    if len(text_value) == 10:
        dt = _dt.datetime.strptime(text_value, "%Y-%m-%d")
    else:
        dt = _dt.datetime.fromisoformat(text_value)
    return int(dt.replace(tzinfo=_dt.timezone.utc).timestamp())


def _parse_modules(items):
    modules = {}
    for item in items or []:
        if "=" in item:
            name, _, raw = item.partition("=")
            modules[name.strip()] = raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            modules[item.strip()] = True
    return modules


def _parse_limits(items):
    limits = {}
    for item in items or []:
        name, _, value = item.partition("=")
        limits[name.strip()] = int(value)
    return limits


def cmd_keygen():
    if os.path.exists(_PRIVATE_KEY_PATH):
        print(f"[error] ya existe {_PRIVATE_KEY_PATH}; bórralo para regenerar")
        return 1
    private_key = ed25519.Ed25519PrivateKey.generate()
    priv_pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    pub_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    os.makedirs(os.path.dirname(_PRIVATE_KEY_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(_PUBLIC_KEY_PATH), exist_ok=True)
    with open(_PRIVATE_KEY_PATH, "wb") as fh:
        fh.write(priv_pem)
    with open(_PUBLIC_KEY_PATH, "wb") as fh:
        fh.write(pub_pem)
    print(f"[ok] clave privada -> {_PRIVATE_KEY_PATH}")
    print(f"[ok] clave pública  -> {_PUBLIC_KEY_PATH}")
    return 0


def cmd_customer_add(args):
    engine = _engine()
    license_db.init_db(engine)
    try:
        license_db.create_customer(engine, args.id, args.name,
                                   license_db.hash_api_key(_secret(), args.api_key))
    except Exception as exc:
        print(f"[error] no se pudo crear el cliente: {exc}")
        return 1
    print(f"[ok] cliente '{args.id}' creado")
    return 0


def cmd_customer_list(_args):
    engine = _engine()
    license_db.init_db(engine)
    for c in license_db.list_customers(engine):
        print(f"#{c.id} {c.customer_id}  {c.name}  [{c.status}]  {c.created_at}")
    return 0


def cmd_customer_disable(args):
    license_db.set_customer_status(_engine(), args.id, "disabled")
    print(f"[ok] cliente '{args.id}' deshabilitado")
    return 0


def cmd_license_issue(args):
    engine = _engine()
    license_db.init_db(engine)
    if license_db.get_customer(engine, args.customer) is None:
        print(f"[error] cliente '{args.customer}' no existe")
        return 1
    valid_from = _to_epoch(args.valid_from) if args.valid_from else int(
        _dt.datetime.now(_dt.timezone.utc).timestamp())
    try:
        license_db.issue_license(engine, args.customer, args.license_id,
                                 valid_from, _to_epoch(args.valid_until),
                                 args.grace_days, _parse_modules(args.modules),
                                 _parse_limits(args.limit))
    except Exception as exc:
        print(f"[error] no se pudo emitir la licencia: {exc}")
        return 1
    print(f"[ok] licencia '{args.license_id}' emitida para '{args.customer}'")
    return 0


def cmd_license_renew(args):
    engine = _engine()
    if license_db.get_license_by_id(engine, args.license_id) is None:
        print(f"[error] licencia '{args.license_id}' no existe")
        return 1
    valid_from = _to_epoch(args.valid_from) if args.valid_from else int(
        _dt.datetime.now(_dt.timezone.utc).timestamp())
    license_db.renew_license(engine, args.license_id, valid_from,
                             _to_epoch(args.valid_until), args.grace_days)
    print(f"[ok] licencia '{args.license_id}' renovada")
    return 0


def cmd_license_suspend(args):
    license_db.set_license_status(_engine(), args.license_id, "suspended", "suspended")
    print(f"[ok] licencia '{args.license_id}' suspendida")
    return 0


def cmd_license_revoke(args):
    license_db.set_license_status(_engine(), args.license_id, "revoked", "revoked")
    print(f"[ok] licencia '{args.license_id}' revocada")
    return 0


def cmd_license_show(args):
    lic = license_db.get_license_by_id(_engine(), args.license_id)
    if lic is None:
        print(f"[error] licencia '{args.license_id}' no existe")
        return 1
    import json
    print(json.dumps(lic, indent=2, sort_keys=True))
    return 0


def cmd_license_list(args):
    for lic in license_db.list_licenses(_engine(), getattr(args, "customer", None)):
        print(f"{lic['license_id']}  {lic['customer_id']}  [{lic['status']}]  "
              f"valida={lic['valid_until']}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="license-server")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("keygen", help="Genera el par de claves ed25519")

    c = sub.add_parser("customer", help="Gestiona clientes")
    csub = c.add_subparsers(dest="customer_action", required=True)
    ca = csub.add_parser("add")
    ca.add_argument("--id", required=True)
    ca.add_argument("--name", required=True)
    ca.add_argument("--api-key", required=True)
    csub.add_parser("list")
    cd = csub.add_parser("disable")
    cd.add_argument("--id", required=True)

    l = sub.add_parser("license", help="Gestiona licencias")
    lsub = l.add_subparsers(dest="license_action", required=True)
    li = lsub.add_parser("issue")
    li.add_argument("--customer", required=True)
    li.add_argument("--license-id", required=True)
    li.add_argument("--valid-until", required=True)
    li.add_argument("--valid-from", default=None)
    li.add_argument("--grace-days", type=int, default=7)
    li.add_argument("--modules", nargs="*", default=[])
    li.add_argument("--limit", nargs="*", default=[])
    lr = lsub.add_parser("renew")
    lr.add_argument("--license-id", required=True)
    lr.add_argument("--valid-until", required=True)
    lr.add_argument("--valid-from", default=None)
    lr.add_argument("--grace-days", type=int, default=7)
    for action_name in ("suspend", "revoke"):
        p = lsub.add_parser(action_name)
        p.add_argument("--license-id", required=True)
    ls = lsub.add_parser("show")
    ls.add_argument("--license-id", required=True)
    ll = lsub.add_parser("list")
    ll.add_argument("--customer", default=None)

    args = parser.parse_args(argv)
    if args.command == "keygen":
        return cmd_keygen()
    if args.command == "customer":
        if args.customer_action == "add":
            return cmd_customer_add(args)
        if args.customer_action == "list":
            return cmd_customer_list(args)
        if args.customer_action == "disable":
            return cmd_customer_disable(args)
    if args.command == "license":
        if args.license_action == "issue":
            return cmd_license_issue(args)
        if args.license_action == "renew":
            return cmd_license_renew(args)
        if args.license_action == "suspend":
            return cmd_license_suspend(args)
        if args.license_action == "revoke":
            return cmd_license_revoke(args)
        if args.license_action == "show":
            return cmd_license_show(args)
        if args.license_action == "list":
            return cmd_license_list(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Corregir el test de keygen**

El test referenciaba `_key_paths` que no existe; el Step 1 ya setea `server_cli._PRIVATE_KEY_PATH`/`_PUBLIC_KEY_PATH` y llama `cmd_keygen()`: la línea `monkeypatch_target = ...` es ruido, eliminarla en el archivo del test:

```python
def test_keygen_writes_keys(env, tmp_path):
    server_cli._PRIVATE_KEY_PATH = str(tmp_path / "private_key.pem")
    server_cli._PUBLIC_KEY_PATH = str(tmp_path / "novus_public.pem")
    assert server_cli.cmd_keygen() == 0
    assert (tmp_path / "private_key.pem").exists()
    assert (tmp_path / "novus_public.pem").exists()
```

- [ ] **Step 5: Ejecutar para verificar que pasa**

Run: `.venv/bin/pytest tests/test_license_server_cli.py -v`
Expected: 6 passed.

- [ ] **Step 6: Añadir `.gitignore` la clave privada**

Añadir a `.gitignore`:

```
# Claves del license server (nunca se commitean)
license_server/private_key.pem
```

- [ ] **Step 7: Crear `scripts/run_license_server.sh`**

```bash
#!/usr/bin/env bash
# Arranca el license server Novus.
# Requiere: NOVUS_LICENSE_SERVER_SECRET (pepper) y haber corrido `keygen`.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8002}"
export NOVUS_LICENSE_SERVER_SECRET="${NOVUS_LICENSE_SERVER_SECRET:-}"
if [ -z "$NOVUS_LICENSE_SERVER_SECRET" ]; then
  echo "Define NOVUS_LICENSE_SERVER_SECRET" >&2
  exit 1
fi

exec .venv/bin/uvicorn license_server.app:app --host "$HOST" --port "$PORT"
```

Hacerlo ejecutable: `chmod +x scripts/run_license_server.sh`.

- [ ] **Step 8: Commit**

```bash
git add license_server/cli.py tests/test_license_server_cli.py scripts/run_license_server.sh .gitignore
git commit -m "feat(license-server): CLI de gestión (keygen, customer, license) + script de arranque"
```

---

### Task 6: Cliente del engine — cache y manager

**Files:**
- Create: `licensing/cache.py`
- Create: `licensing/client.py`
- Test: `tests/test_licensing.py` (añadir casos)

**Interfaces:**
- Consumes: `licensing.models.*`, `licensing.validator.verify_token`.
- Produces: `licensing.cache.cache_path(config) -> str`, `licensing.cache.save_cache(path, data)`, `licensing.cache.load_cache(path) -> dict|None`; `licensing.client.LicenseManager(config)` con `get_license() -> License`, `require(module) -> License` (levanta `LicenseBlocked`/`LicenseNotEntitled`/`LicenseUnreachable`), `state() -> LicenseState`, `force_activate() -> License`, `validate() -> License`, `clear_cache()`, `users_limit() -> int|None`; `licensing.client.get_manager(config) -> LicenseManager` (singleton por servidor/cliente/cache) y `licensing.client.require_license(config, module) -> License`.

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_licensing.py`:

```python
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
    path = str(tmp_path / "cache.json")
    path.write_text("{not json")
    assert load_cache(path) is None
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
```

- [ ] **Step 2: Ejecutar para verificar que falla**

Run: `.venv/bin/pytest tests/test_licensing.py -v`
Expected: FAIL con `ModuleNotFoundError: licensing.client`.

- [ ] **Step 3: Implementar `licensing/cache.py`**

```python
"""Caché local firmada de la licencia (JSON atómico en disco)."""

import json
import os


def cache_path(config) -> str:
    lic = config.get("license") or {}
    if lic.get("cache_path"):
        return lic["cache_path"]
    customer = lic.get("customer_id", "default")
    return os.path.expanduser(os.path.join("~", ".novus", f"license-{customer}.json"))


def save_cache(path, data: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
```

- [ ] **Step 4: Implementar `licensing/client.py`**

```python
"""LicenseManager: activación, caché, estados y enforcement desde el engine."""

import json
import os
import time
import urllib.error
import urllib.request

from .cache import cache_path, load_cache, save_cache
from .models import (
    License,
    LicenseBlocked,
    LicenseError,
    LicenseInvalid,
    LicenseNotEntitled,
    LicenseState,
    LicenseUnreachable,
)
from .validator import verify_token


def _activate_http(server, payload: dict) -> str:
    """POST /api/activate. Devuelve el token JWT. Levanta LicenseBlocked o LicenseUnreachable."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        server + "/api/activate", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise LicenseBlocked(f"activación rechazada por el servidor ({exc.code})") from exc
        raise LicenseUnreachable(f"error de red al activar ({exc.code})") from exc
    except OSError as exc:
        raise LicenseUnreachable(f"no se pudo contactar el servidor de licencias: {exc}") from exc
    return body["token"]


class LicenseManager:
    def __init__(self, config):
        self.config = config
        lic = config.get("license") or {}
        self.enabled = bool(lic)
        self.server = (lic.get("server") or "").rstrip("/")
        self.customer_id = lic.get("customer_id")
        self.api_key = lic.get("api_key")
        self.refresh_minutes = lic.get("refresh_minutes", 720)
        self._cache_path = cache_path(config)
        self._public_key = self._load_public_key(lic)
        self._cached = None

    def _load_public_key(self, lic):
        path = lic.get("public_key")
        if path:
            with open(path, "rb") as fh:
                return fh.read()
        default = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "licensing", "novus_public.pem")
        with open(default, "rb") as fh:
            return fh.read()

    def _from_claims(self, claims) -> License:
        return License(
            customer_id=claims.get("customer_id"),
            license_id=claims.get("license_id"),
            status=claims.get("status", "active"),
            valid_from=claims.get("valid_from"),
            valid_until=claims.get("valid_until"),
            offline_until=claims.get("offline_until"),
            modules=claims.get("modules") or {},
            limits=claims.get("limits") or {},
            issued_at=claims.get("iat"),
        )

    def _is_fresh_enough(self, cached) -> bool:
        if time.time() - cached.get("fetched_at", 0) >= self.refresh_minutes * 60:
            return False
        offline_until = (cached.get("claims") or {}).get("offline_until")
        if offline_until is not None and time.time() > offline_until:
            return False
        return True

    def get_license(self) -> License:
        if not self.enabled:
            return License.no_license()
        cached = self._cached or load_cache(self._cache_path)
        if cached and self._is_fresh_enough(cached):
            try:
                claims = verify_token(cached["token"], self._public_key)
            except LicenseInvalid:
                cached = None
            else:
                self._cached = cached
                return self._from_claims(claims)
        return self._refresh(cached)

    def _refresh(self, cached) -> License:
        try:
            token = self._activate()
            claims = verify_token(token, self._public_key)
        except LicenseInvalid as exc:
            if cached:
                return self._cached_license(cached, exc)
            raise
        except (LicenseBlocked, LicenseUnreachable) as exc:
            if cached:
                return self._cached_license(cached, exc)
            raise
        data = {"claims": claims, "token": token, "fetched_at": int(time.time())}
        save_cache(self._cache_path, data)
        self._cached = data
        return self._from_claims(claims)

    def _cached_license(self, cached, cause: LicenseError) -> License:
        try:
            claims = verify_token(cached["token"], self._public_key)
        except LicenseInvalid:
            raise LicenseBlocked(
                "no se pudo validar la licencia y el caché local es inválido") from cause
        self._cached = cached
        return self._from_claims(claims)

    def _activate(self) -> str:
        return _activate_http(self.server, {"customer_id": self.customer_id,
                                            "api_key": self.api_key})

    def require(self, module: str) -> License:
        lic = self.get_license()
        state = lic.state(time.time())
        if state in (LicenseState.EXPIRED, LicenseState.SUSPENDED, LicenseState.REVOKED):
            raise LicenseBlocked(
                f"licencia {state.value}: el módulo '{module}' está bloqueado. "
                "Contacta a Novus para renovar.")
        if not lic.has(module):
            raise LicenseNotEntitled(
                f"módulo '{module}' no contratado. Contacta a Novus para contratarlo.")
        return lic

    def state(self) -> LicenseState:
        return self.get_license().state(time.time())

    def force_activate(self) -> License:
        token = self._activate()
        claims = verify_token(token, self._public_key)
        data = {"claims": claims, "token": token, "fetched_at": int(time.time())}
        save_cache(self._cache_path, data)
        self._cached = data
        return self._from_claims(claims)

    def validate(self) -> License:
        if not self.enabled:
            return License.no_license()
        cached = self._cached or load_cache(self._cache_path)
        if not cached:
            raise LicenseUnreachable("no hay caché de licencia local")
        claims = verify_token(cached["token"], self._public_key)
        return self._from_claims(claims)

    def clear_cache(self):
        self._cached = None
        if os.path.exists(self._cache_path):
            os.remove(self._cache_path)

    def users_limit(self):
        return self.get_license().limit("users")


_MANAGERS = {}
_NO_LICENSE_MANAGER = None


def get_manager(config) -> LicenseManager:
    global _NO_LICENSE_MANAGER
    lic = config.get("license")
    if not lic:
        if _NO_LICENSE_MANAGER is None:
            _NO_LICENSE_MANAGER = LicenseManager(config)
        return _NO_LICENSE_MANAGER
    key = (lic.get("server"), lic.get("customer_id"), lic.get("cache_path"))
    if key not in _MANAGERS:
        _MANAGERS[key] = LicenseManager(config)
    return _MANAGERS[key]


def require_license(config, module: str) -> License:
    return get_manager(config).require(module)
```

- [ ] **Step 5: Ajustar `licensing/__init__.py`**

Reemplazar el `try/except` por la versión final (sin `except`):

```python
from .client import LicenseManager, get_manager, require_license
from .models import (
    License,
    LicenseBlocked,
    LicenseError,
    LicenseInvalid,
    LicenseNotEntitled,
    LicenseState,
    LicenseUnreachable,
)

__all__ = [...igual que Tarea 1...]
```

- [ ] **Step 6: Ejecutar para verificar que pasa**

Run: `.venv/bin/pytest tests/test_licensing.py -v`
Expected: 19 passed.

- [ ] **Step 7: Commit**

```bash
git add licensing/cache.py licensing/client.py licensing/__init__.py tests/test_licensing.py
git commit -m "feat(licensing): LicenseManager con activación, caché firmada, estados y require()"
```

---

### Task 7: Integración CLI + config + límite de usuarios

**Files:**
- Modify: `cli.py`
- Modify: `schemas/config.schema.json`
- Modify: `config.example.json`
- Test: `tests/test_licensing_gating.py` (nuevo)

**Interfaces:**
- Consumes: `licensing.client.get_manager`, `licensing.client.require_license`, `licensing.models.LicenseError` (+ subclases), `auth_users.list_users`.
- Produces: subcomando `etl license {status|activate|validate|clear-cache}`; gates en `cmd_reporte` (derived), `cmd_bi` (bi), `cmd_bootstrap --with-derived` (derived), `_cmd_users_action add` (límite users). Campo `license` en schema y example.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_licensing_gating.py`:

```python
import json
import time

import pytest

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
    modules.update(overrides.pop("modules", {}))
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
    # sin tablas materializadas, derived_views() falla con ValueError antes del gate real:
    # el gate se evalúa primero, así que pasamos con una vista sin tabla
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
```

- [ ] **Step 2: Ejecutar para verificar que falla**

Run: `.venv/bin/pytest tests/test_licensing_gating.py -v`
Expected: FAIL (`cli.cmd_license` no existe, gates ausentes).

- [ ] **Step 3: Implementar gates en `cli.py`**

En `cmd_reporte`, justo después de `config = load_config(config_path)`:

```python
    from licensing.client import require_license, LicenseError
    try:
        require_license(config, "derived")
    except LicenseError as exc:
        print(f"[error] {exc}")
        return 1
```

En `cmd_bi`, justo después de `config = load_config(config_path)`:

```python
    from licensing.client import require_license, LicenseError
    try:
        require_license(config, "bi")
    except LicenseError as exc:
        print(f"[error] {exc}")
        return 1
```

En `cmd_bootstrap`, dentro del `if with_derived and config.get("derived"):` (antes de importar `run_deriveds`):

```python
        from licensing.client import require_license, LicenseError
        try:
            require_license(config, "derived")
        except LicenseError as exc:
            return fail(f"módulo derived no contratado: {exc}")
```

En `_cmd_users_action`, en la rama `if action == "add":` (al principio, antes de crear):

```python
        from licensing.client import get_manager, LicenseError
        try:
            limit = get_manager(config).users_limit()
        except LicenseError as exc:
            print(f"[error] {exc}")
            return 1
        if limit is not None and len(auth_users.list_users()) >= limit:
            print(f"[error] límite de usuarios alcanzado ({limit}); contacta a Novus")
            return 1
```

Ajustar la firma y el llamador de `_cmd_users_action` para pasar `config`:

```python
def cmd_users(args):
    from dashboard.auth import engine as auth_engine
    from dashboard.auth import users as auth_users

    config = load_config(args.config)
    previous = auth_engine.get_engine_provider()
    auth_engine.set_engine_provider(
        lambda: _engine_from_config(config, fast_executemany=False))
    try:
        return _cmd_users_action(auth_users, args, config)
    finally:
        auth_engine.set_engine_provider(previous)


def _cmd_users_action(auth_users, args, config):
```

- [ ] **Step 4: Implementar `cmd_license` y su parser en `cli.py`**

Añadir la función (junto a `cmd_bi`):

```python
def _fmt_epoch(epoch):
    import datetime
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d") if epoch else "-"


def cmd_license(config_path, action):
    config = load_config(config_path)
    from licensing.client import get_manager, LicenseError
    mgr = get_manager(config)
    if action == "status":
        try:
            lic = mgr.get_license()
        except LicenseError as exc:
            print(f"[error] {exc}")
            return 1
        print(f"estado: {lic.state(__import__('time').time()).value}")
        print(f"cliente: {lic.customer_id or '-'} · licencia: {lic.license_id or '-'}")
        print(f"válida hasta: {_fmt_epoch(lic.valid_until)} · gracia hasta: {_fmt_epoch(lic.offline_until)}")
        if lic.modules is None:
            print("módulos: todos (sin licenciar)")
        else:
            on = ", ".join(sorted(m for m, ok in lic.modules.items() if ok)) or "(ninguno)"
            print(f"módulos: {on}")
        if lic.limits:
            print("límites: " + ", ".join(f"{k}={v}" for k, v in sorted(lic.limits.items())))
        return 0
    if action == "activate":
        try:
            mgr.force_activate()
        except LicenseError as exc:
            print(f"[error] {exc}")
            return 1
        print("[ok] licencia activada")
        return 0
    if action == "validate":
        import time
        try:
            lic = mgr.validate()
        except LicenseError as exc:
            print(f"[error] {exc}")
            return 1
        print(f"[ok] firma válida · estado {lic.state(time.time()).value}")
        return 0
    if action == "clear-cache":
        mgr.clear_cache()
        print("[ok] caché de licencia eliminada")
        return 0
    print("Uso: etl license {status|activate|validate|clear-cache}")
    return 1
```

Nota: evitar el feo `__import__('time')`: añadir `import time` arriba de `cmd_license` y usar `time.time()`.

En `main()`, tras el parser de `users`:

```python
    license_parser = subparsers.add_parser(
        "license", help="Estado y gestión de la licencia de la empresa")
    license_sub = license_parser.add_subparsers(dest="license_action", required=True)
    for action_name in ("status", "activate", "validate", "clear-cache"):
        action_parser = license_sub.add_parser(action_name,
                                               help=f"{action_name} de la licencia")
        _add_config_arg(action_parser)
```

Y en el dispatch, antes del `if args.command == "users":`:

```python
    if args.command == "license":
        return cmd_license(args.config, args.license_action)
```

- [ ] **Step 5: Añadir `license` al schema y al example**

En `schemas/config.schema.json`, en `properties` (después de `"dashboard"`):

```json
    "license": {
      "description": "Activación online de la licencia Novus (opcional; sin ella todo queda habilitado).",
      "type": "object",
      "properties": {
        "server": { "type": "string" },
        "customer_id": { "type": "string" },
        "api_key": { "type": "string" },
        "public_key": { "type": "string" },
        "cache_path": { "type": "string" },
        "refresh_minutes": { "type": "integer", "minimum": 1 }
      },
      "additionalProperties": true
    }
```

En `config.example.json`, tras el bloque `"dashboard"` (con comas correctas):

```json
  "license": {
    "server": "https://lic.novusit.cl",
    "customer_id": "empresa_001",
    "api_key": "cambiar-por-api-key-del-cliente",
    "refresh_minutes": 720
  }
```

- [ ] **Step 6: Ejecutar para verificar que pasa**

Run: `.venv/bin/pytest tests/test_licensing_gating.py tests/test_cli.py tests/test_config_schema.py -v`
Expected: todos pasan.

- [ ] **Step 7: Ruff**

Run: `.venv/bin/ruff check cli.py licensing license_server tests/test_licensing_gating.py`
Expected: sin errores.

- [ ] **Step 8: Commit**

```bash
git add cli.py schemas/config.schema.json config.example.json tests/test_licensing_gating.py
git commit -m "feat(cli): subcomando license y gates de módulos derived/bi + límite de usuarios"
```

---

### Task 8: `etl_runner` omite materialización sin licencia `derived`

**Files:**
- Modify: `etl_runner.py:256-295`
- Test: `tests/test_licensing_gating.py` (añadir casos)

**Interfaces:**
- Consumes: `licensing.client.get_manager`.
- Produces: en `run_etl_job`, la materialización de `derived` solo corre si la licencia habilita `derived`; si no (o si la licencia no se puede verificar), se omite con `logger.warning` y el run core termina con éxito.

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_licensing_gating.py`:

```python
def test_etl_runner_skips_derived_when_not_entitled(harness_factory, monkeypatch, capsys):
    eng, sink, tmp_path, m = harness_factory
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(tmp_path / "db.sqlite")},
        "tables": [{"source": "OK", "target": "t_ok", "keys": ["id"]}],
        "fields": {"OK": ["id", "name"]},
        "derived": {"name": "inv_bodega"},
    }
    m.setattr(etl_runner, "load_config", lambda path=None: cfg)
    _patch_manager(m, _license(modules={"dashboard": True, "bi": True}))

    import derived.materializer as dm
    called = {}
    def fake_run_deriveds(**kwargs):
        called["ran"] = True
        return []
    m.setattr(dm, "run_deriveds", fake_run_deriveds)

    etl_runner.run_etl_job()
    assert "ran" not in called
```

Añadir también el helper de harness y el import (copiar el patrón de `tests/test_etl_runner.py`):

```python
import pandas as pd
import etl_runner
from db.sinks import get_sink

CONTROL_SQL = """
CREATE TABLE etl_execution (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_time TEXT NULL,
    status TEXT NOT NULL,
    message TEXT NULL
);
CREATE TABLE etl_progress (
    table_name TEXT PRIMARY KEY,
    rows_loaded INTEGER NULL,
    status TEXT NULL,
    updated_at TEXT NULL DEFAULT CURRENT_TIMESTAMP,
    last_delta_value VARCHAR(40) NULL
);
CREATE TABLE etl_execution_tables (
    run_id INTEGER NOT NULL,
    table_name TEXT NOT NULL,
    chunks_total INTEGER NULL,
    chunks_ok INTEGER NULL,
    rows_extracted INTEGER NULL,
    duration_s REAL NULL,
    status TEXT NULL,
    PRIMARY KEY (run_id, table_name)
);
"""

class FakeConnector:
    type = "csv"

    def connect(self):
        pass

    def close(self):
        pass

    def ping(self):
        return True

    def extract(self, table, fields, filters=None, batch_size=30000, max_wa_chars=None):
        return pd.DataFrame({f: [1, 2] for f in fields})


@pytest.fixture
def harness_factory(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with eng.begin() as conn:
        for stmt in CONTROL_SQL.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
        conn.execute(text("CREATE TABLE t_ok (id INTEGER PRIMARY KEY, name TEXT)"))
    sink = get_sink(eng)

    def no_lock():
        return None

    monkeypatch.setattr(etl_runner, "acquire_lock", no_lock)
    monkeypatch.setattr(etl_runner, "release_lock", no_lock)
    monkeypatch.setattr(etl_runner, "update_state", lambda **kw: None)
    monkeypatch.setattr(etl_runner, "get_engine", lambda config=None: eng)
    monkeypatch.setattr(etl_runner, "get_source", lambda sc: FakeConnector())
    monkeypatch.setenv("ETL_LIVE_FILE", str(tmp_path / "live.json"))
    return eng, sink, tmp_path, monkeypatch
```

Añadir los imports faltantes al archivo: `from sqlalchemy import create_engine, text`.

- [ ] **Step 2: Ejecutar para verificar que falla**

Run: `.venv/bin/pytest tests/test_licensing_gating.py::test_etl_runner_skips_derived_when_not_entitled -v`
Expected: FAIL (se materializa a pesar de no estar licenciado — `"ran" in called`).

- [ ] **Step 3: Modificar `etl_runner.py`**

Reemplazar el bloque actual (líneas 256-295):

```python
        if successful and config.get("derived"):

            from derived.materializer import run_deriveds

            logger.info("Materializando modelos derivados")

            update_live(
                running=True, run_id=run_id, table=None, phase="derived",
                chunk_index=0, chunk_total=0, rows_so_far=0,
                elapsed_s=round(time.time() - start_run_time, 1),
            )

            update_state(
                running=True,
                progress=95,
                status="Generando modelos derivados"
            )

            derived_start = time.time()

            try:
                for name, n_rows, excel_path in run_deriveds(engine=engine, sink=sink, config=config):
                    if run_id is not None:
                        upsert_execution_table(
                            engine, sink, run_id, name,
                            rows_extracted=n_rows, status="ok",
                            duration_s=round(time.time() - derived_start, 1),
                        )
                    logger.info(f"Modelo '{name}' materializado: {n_rows} filas -> {excel_path}")
            except Exception as e:
                logger.exception(f"Error en modelo derivado: {e}")
                if run_id is not None:
                    try:
                        upsert_execution_table(
                            engine, sink, run_id, "<derived>", status="failed",
                            duration_s=round(time.time() - derived_start, 1),
                        )
                    except Exception:
                        logger.warning("No se pudo registrar el fallo del modelo derivado")
                raise RuntimeError(f"Error en modelo derivado: {e}")
```

por:

```python
        if successful and config.get("derived"):

            from licensing.client import get_manager

            try:
                derived_entitled = get_manager(config).get_license().has("derived")
            except Exception:
                derived_entitled = False

            if not derived_entitled:
                logger.warning("módulo 'derived' no contratado; omitiendo materialización de modelos derivados")
            else:
                from derived.materializer import run_deriveds

                logger.info("Materializando modelos derivados")

                update_live(
                    running=True, run_id=run_id, table=None, phase="derived",
                    chunk_index=0, chunk_total=0, rows_so_far=0,
                    elapsed_s=round(time.time() - start_run_time, 1),
                )

                update_state(
                    running=True,
                    progress=95,
                    status="Generando modelos derivados"
                )

                derived_start = time.time()

                try:
                    for name, n_rows, excel_path in run_deriveds(engine=engine, sink=sink, config=config):
                        if run_id is not None:
                            upsert_execution_table(
                                engine, sink, run_id, name,
                                rows_extracted=n_rows, status="ok",
                                duration_s=round(time.time() - derived_start, 1),
                            )
                        logger.info(f"Modelo '{name}' materializado: {n_rows} filas -> {excel_path}")
                except Exception as e:
                    logger.exception(f"Error en modelo derivado: {e}")
                    if run_id is not None:
                        try:
                            upsert_execution_table(
                                engine, sink, run_id, "<derived>", status="failed",
                                duration_s=round(time.time() - derived_start, 1),
                            )
                        except Exception:
                            logger.warning("No se pudo registrar el fallo del modelo derivado")
                    raise RuntimeError(f"Error en modelo derivado: {e}")
```

- [ ] **Step 4: Ejecutar para verificar que pasa**

Run: `.venv/bin/pytest tests/test_licensing_gating.py tests/test_etl_runner.py -v`
Expected: todos pasan (incluida la suite existente del runner).

- [ ] **Step 5: Commit**

```bash
git add etl_runner.py tests/test_licensing_gating.py
git commit -m "feat(etl_runner): omite materialización derived sin licencia; el run core sigue intacto"
```

---

### Task 9: Dashboard — gating por módulo, `/api/license` y banner

**Files:**
- Modify: `dashboard/app.py`
- Modify: `dashboard/auth/router.py`
- Create: `dashboard/static/license.html`
- Modify: `dashboard/static/common.js`
- Test: `tests/test_licensing_gating.py` (añadir casos) y `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `licensing.client.get_manager`, `licensing.models.LicenseState`/`LicenseError`, `dashboard.auth.dependencies.require_user`.
- Produces: dependencia `dashboard.app.require_license_module(module) -> Depends` (403 con `licencia:ESTADO` / `modulo_no_contratado:modulo` / `licencia_no_verificable`); endpoint `GET /api/license`; `/derivadas` sirve `license.html` si `dashboard` no está contratado o la licencia está bloqueada; `admin_create_user` respeta `users_limit`.

- [ ] **Step 1: Escribir el test que falla**

Añadir a `tests/test_licensing_gating.py`:

```python
from fastapi.testclient import TestClient

import dashboard.app as dash_app
from dashboard.auth import users as auth_users


@pytest.fixture
def dash_client(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    db_path = tmp_path / "db.sqlite"
    cfg = {
        "environment": "qa",
        "source": {"type": "csv", "config": {"directory": str(tmp_path)}},
        "database": {"dialect": "sqlite", "database": str(db_path)},
        "tables": [], "fields": {},
        "license": {"server": "http://lic.test", "customer_id": "e", "api_key": "k"},
    }
    cfg_path.write_text(json.dumps(cfg))
    assert cli.cmd_migrate(str(cfg_path)) == 0
    auth_users.create_user("admin", "testpass123", role="admin", is_root=True,
                           must_change_password=False)
    monkeypatch.setenv("ETL_CONFIG", str(cfg_path))
    monkeypatch.setenv("ETL_SECRET", "test-secret")
    client = TestClient(dash_app.app)
    client.post("/api/auth/login", json={"username": "admin", "password": "testpass123"})
    return client


def test_dashboard_blocks_without_dashboard_module(tmp_path, monkeypatch):
    _patch_manager(monkeypatch, _license(modules={"derived": True, "bi": True}))
    client = dash_client_factory(tmp_path, monkeypatch)
    res = client.get("/api/derived-views")
    assert res.status_code == 403
    assert res.json()["detail"] == "modulo_no_contratado:dashboard"
    res = client.get("/derivadas")
    assert "licencia" in res.text.lower()


def test_dashboard_allows_with_module(tmp_path, monkeypatch):
    _patch_manager(monkeypatch, _license())
    client = dash_client_factory(tmp_path, monkeypatch)
    assert client.get("/api/derived-views").status_code == 200
    assert client.get("/api/license").status_code == 200


def test_dashboard_api_license_reports_state(tmp_path, monkeypatch):
    _patch_manager(monkeypatch, _license())
    client = dash_client_factory(tmp_path, monkeypatch)
    data = client.get("/api/license").json()
    assert data["state"] == "ACTIVE"
    assert data["modules"]["derived"] is True


def test_dashboard_blocks_blocked_license(tmp_path, monkeypatch):
    _patch_manager(monkeypatch, _license(status="revoked", modules={"derived": True,
                                                                    "dashboard": True,
                                                                    "bi": True}))
    client = dash_client_factory(tmp_path, monkeypatch)
    res = client.get("/api/derived-views")
    assert res.status_code == 403
    assert res.json()["detail"] == "licencia:REVOKED"


def test_admin_create_user_blocks_at_limit(tmp_path, monkeypatch):
    _patch_manager(monkeypatch, _license(limits={"users": 1}))
    client = dash_client_factory(tmp_path, monkeypatch)
    auth_users.create_user("admin2", "testpass123", role="admin", is_root=True,
                           must_change_password=False)
    res = client.post("/api/admin/users", json={"username": "usuario", "password": "testpass123",
                                                "role": "user"})
    assert res.status_code == 403
    assert res.json()["detail"] == "limite_usuarios"
```

Nota: convertir el fixture `dash_client` en una factory reutilizable:

```python
def dash_client_factory(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    db_path = tmp_path / "db.sqlite"
    cfg = {...igual que arriba...}
    cfg_path.write_text(json.dumps(cfg))
    assert cli.cmd_migrate(str(cfg_path)) == 0
    from dashboard.auth import engine as auth_engine
    auth_engine.set_engine_provider(
        lambda: create_engine(f"sqlite:///{db_path}"))
    auth_users.create_user("admin", "testpass123", role="admin", is_root=True,
                           must_change_password=False)
    monkeypatch.setenv("ETL_CONFIG", str(cfg_path))
    monkeypatch.setenv("ETL_SECRET", "test-secret")
    client = TestClient(dash_app.app)
    client.post("/api/auth/login", json={"username": "admin", "password": "testpass123"})
    return client
```

- [ ] **Step 2: Ejecutar para verificar que falla**

Run: `.venv/bin/pytest tests/test_licensing_gating.py -k dashboard -v`
Expected: FAIL (endpoints accesibles, `/api/license` 404).

- [ ] **Step 3: Implementar en `dashboard/app.py`**

Añadir imports:

```python
from licensing.client import get_manager, LicenseError
from licensing.models import LicenseState
```

Añadir la dependencia (tras `_SPAWNED_PID`/constantes):

```python
def require_license_module(module):
    def dependency(user=Depends(require_user)):
        config = load_config(os.environ.get("ETL_CONFIG"))
        try:
            lic = get_manager(config).get_license()
        except LicenseError as exc:
            raise HTTPException(status_code=403, detail="licencia_no_verificable") from exc
        state = lic.state(time.time())
        if state in (LicenseState.EXPIRED, LicenseState.SUSPENDED, LicenseState.REVOKED):
            raise HTTPException(status_code=403, detail=f"licencia:{state.value}")
        if not lic.has(module):
            raise HTTPException(status_code=403, detail=f"modulo_no_contratado:{module}")
        return user
    return dependency
```

Cambiar el guard en estos endpoints de `Depends(require_user)` a `Depends(require_license_module("dashboard"))`:
- `api_inventory` (/api/inventory)
- `api_inventory_filters` (/api/inventory/filters)
- `api_inventory_items` (/api/inventory/items)
- `api_inventory_alerts` (/api/inventory/alerts)
- `api_derived_summary`, `api_derived_filters`, `api_derived_items`, `api_derived_alerts`
- `api_derived_views` (/api/derived-views)

Añadir `/api/license`:

```python
_LICENSE_MESSAGES = {
    LicenseState.ACTIVE: "",
    LicenseState.GRACE: "Licencia en período de gracia: renueva para evitar la interrupción del servicio.",
    LicenseState.EXPIRED: "Licencia vencida. Los datos existentes se conservan; renueva para continuar.",
    LicenseState.SUSPENDED: "Licencia suspendida por Novus. Contacta a Novus para regularizar.",
    LicenseState.REVOKED: "Licencia revocada. Contacta a Novus.",
    LicenseState.NO_LICENSE: "",
}


@app.get("/api/license")
def api_license(user=Depends(require_user)):
    config = load_config(os.environ.get("ETL_CONFIG"))
    try:
        lic = get_manager(config).get_license()
    except LicenseError as exc:
        return {"state": "UNKNOWN", "message": str(exc), "modules": {}, "limits": {}}
    state = lic.state(time.time())
    return {
        "state": state.value,
        "customer": lic.customer_id,
        "license": lic.license_id,
        "valid_until": lic.valid_until,
        "offline_until": lic.offline_until,
        "modules": lic.modules,
        "limits": lic.limits,
        "message": _LICENSE_MESSAGES.get(state, ""),
    }
```

Cambiar `page_derivadas`:

```python
@app.get("/derivadas", response_class=HTMLResponse, include_in_schema=False)
def page_derivadas(user=Depends(current_user_or_none)):
    if user is None:
        return RedirectResponse(url="/login", status_code=307)
    config = load_config(os.environ.get("ETL_CONFIG"))
    try:
        lic = get_manager(config).get_license()
    except LicenseError:
        return _page("license.html")
    state = lic.state(time.time())
    if state in (LicenseState.EXPIRED, LicenseState.SUSPENDED, LicenseState.REVOKED):
        return _page("license.html")
    if not lic.has("dashboard"):
        return _page("license.html")
    return _page("derivadas.html")
```

- [ ] **Step 4: Implementar en `dashboard/auth/router.py`**

Añadir imports:

```python
from utils.config_loader import load_config
from licensing.client import get_manager, LicenseError
```

En `admin_create_user`, después de `_validate_password(body.password)`:

```python
    try:
        limit = get_manager(load_config(os.environ.get("ETL_CONFIG"))).users_limit()
    except LicenseError:
        raise HTTPException(status_code=403, detail="licencia_no_verificable") from None
    if limit is not None and len(list_users()) >= limit:
        raise HTTPException(status_code=403, detail="limite_usuarios")
```

- [ ] **Step 5: Crear `dashboard/static/license.html`**

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Licencia</title>
  <link rel="stylesheet" href="/static/common.css">
</head>
<body>
  <main class="notice">
    <img src="/static/novus-mark.png" alt="Novus">
    <h1>Módulo no disponible</h1>
    <p>El dashboard no está habilitado en la licencia de esta empresa, o la licencia requiere renovación.</p>
    <p>Los datos existentes se conservan. Contacta a <strong>Novus</strong> para contratar o renovar los módulos.</p>
  </main>
</body>
</html>
```

- [ ] **Step 6: Añadir el banner en `dashboard/static/common.js`**

Añadir al final:

```js
async function maybeLicenseBanner() {
  try {
    const res = await fetch('/api/license');
    if (!res.ok) return;
    const data = await res.json();
    const blocked = ['GRACE', 'EXPIRED', 'SUSPENDED', 'REVOKED'];
    if (!blocked.includes(data.state) || !data.message) return;
    const banner = document.createElement('div');
    banner.className = 'license-banner';
    banner.textContent = data.message;
    document.body.prepend(banner);
  } catch (e) { /* sin licencia local: no molestar */ }
}
document.addEventListener('DOMContentLoaded', maybeLicenseBanner);
```

Y en `dashboard/static/common.css`:

```css
.license-banner {
  background: #fdf0dc;
  color: #7a4e00;
  border-bottom: 1px solid #eac47e;
  padding: 10px 16px;
  text-align: center;
  font-size: 14px;
}
```

- [ ] **Step 7: Ejecutar para verificar que pasa**

Run: `.venv/bin/pytest tests/test_licensing_gating.py tests/test_dashboard.py tests/test_auth.py -v`
Expected: todos pasan.

- [ ] **Step 8: Ruff + node check**

Run: `.venv/bin/ruff check dashboard/`
Expected: sin errores.

- [ ] **Step 9: Commit**

```bash
git add dashboard/app.py dashboard/auth/router.py dashboard/static/license.html dashboard/static/common.js dashboard/static/common.css tests/test_licensing_gating.py
git commit -m "feat(dashboard): gating por módulo, endpoint /api/license y banner de renovación"
```

---

### Task 10: Docs y verificación final

**Files:**
- Modify: `README.md`
- Modify: `RUNBOOK.md`

**Interfaces:**
- Consumes: todo lo anterior.

- [ ] **Step 1: Documentar en `README.md`**

Añadir una sección "Licenciamiento (`licensing/` + `license_server/`)" después de la sección del dashboard, explicando:
- Qué hace `license_server` (emitir/validar JWT ed25519; `python -m license_server.cli keygen|customer|license`; `scripts/run_license_server.sh`).
- Qué hace el engine (`licensing/`): activación online, caché `~/.novus/license-<customer>.json`, gracia offline (`valid_until` + `offline_until`), estados.
- Módulos opt-in (`derived`, `dashboard`, `bi`) y dónde se gatean (`cli reporte`, `cli bi`, `etl run` materialización, dashboard).
- Config `license` (block ejemplo, `server`, `customer_id`, `api_key`, `public_key`, `cache_path`, `refresh_minutes`) y la regla de que sin el bloque todo queda habilitado (desarrollo).
- `cli license {status|activate|validate|clear-cache}`.

- [ ] **Step 2: Documentar en `RUNBOOK.md`**

Añadir un flujo operativo "Emitir una licencia para un cliente":
1. `NOVUS_LICENSE_SERVER_SECRET=... .venv/bin/python -m license_server.cli keygen` (una sola vez).
2. `NOVUS_LICENSE_SERVER_SECRET=... .venv/bin/python -m license_server.cli customer add --id empresa_001 --name "Mi Empresa" --api-key <secreto>`.
3. `NOVUS_LICENSE_SERVER_SECRET=... .venv/bin/python -m license_server.cli license issue --customer empresa_001 --license-id NOVUS-001 --valid-until 2026-09-01 --modules derived dashboard --limit users=5`.
4. Arrancar: `NOVUS_LICENSE_SERVER_SECRET=... ./scripts/run_license_server.sh` (puerto 8002).
5. En el config del cliente: bloque `license` con `server`, `customer_id`, `api_key`.
6. Verificar: `etl license status` y `etl license activate` en el cliente.

- [ ] **Step 3: Suite completa + lint**

Run: `.venv/bin/pytest -q`
Expected: todos los tests existentes (246) + nuevos en verde, 0 skipped fallando.

Run: `.venv/bin/ruff check .`
Expected: sin errores.

- [ ] **Step 4: Commit final**

```bash
git add README.md RUNBOOK.md
git commit -m "docs: licenciamiento (license_server + licensing) y flujo operativo de emisión"
```

---

## Self-Review

**Spec coverage:**
- `license_server/` (API, BD, CLI, firma) → Tasks 2-5.
- `licensing/` (activación, caché, estados, enforcement) → Tasks 1, 2, 6.
- Gating `derived` (reporte, bootstrap, etl_runner), `dashboard` (páginas/endpoints), `bi` (cli bi) → Tasks 7, 8, 9.
- Límite `users` en `cli users add` y `POST /api/admin/users` → Tasks 7, 9.
- `cli license status|activate|validate|clear-cache` → Task 7.
- Config `license` en schema + example → Task 7.
- Gracia offline (valid_until + offline_until), estados, mensajes, conservar datos → Tasks 1, 6, 8, 9.
- Sin bloque `license` → todo habilitado (NO_LICENSE) → Tasks 1, 6.
- Testing de firma/estados/cache/server/gating → Tasks 1-9.

**Placeholder scan:** sin "TBD"/"TODO"; cada paso de código tiene implementación literal.

**Type/name consistency:** `License.has/limit/state/no_license`, `verify_token`, `sign_claims`, `get_active_license`, `create_app`, `LicenseManager.get_license/require/state/force_activate/validate/clear_cache/users_limit`, `get_manager`, `require_license`, `cmd_license`, `require_license_module` se definen en su tarea y se usan con los mismos nombres y firmas en las siguientes.
