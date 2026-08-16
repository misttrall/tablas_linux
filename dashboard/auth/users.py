"""Store de usuarios en la tabla app_users de la BD destino.

El admin raiz (is_root) es protegido: no puede ser borrado ni degradado ni
tener su password reseteado por otro usuario.
"""

from sqlalchemy import text

from .engine import get_engine
from .security import hash_password

_PUBLIC_FIELDS = (
    "id",
    "username",
    "role",
    "is_root",
    "must_change_password",
    "active",
    "created_at",
)


def _row_to_public(row):
    d = dict(zip(row._mapping.keys(), row))
    out = {}
    for key in _PUBLIC_FIELDS:
        if key in d:
            out[key] = d[key]
    if "is_root" in out:
        out["is_root"] = bool(out["is_root"])
    if "active" in out:
        out["active"] = bool(out["active"])
    if "must_change_password" in out:
        out["must_change_password"] = bool(out["must_change_password"])
    return out


def create_user(username, password, role="user", is_root=False,
                must_change_password=False, active=True):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app_users "
                "(username, password_hash, role, is_root, must_change_password, active) "
                "VALUES (:u, :h, :r, :is_root, :mcp, :active)"
            ),
            {
                "u": username,
                "h": hash_password(password),
                "r": role,
                "is_root": bool(is_root),
                "mcp": bool(must_change_password),
                "active": bool(active),
            },
        )
        return conn.execute(
            text("SELECT id FROM app_users WHERE username = :u"),
            {"u": username},
        ).scalar_one()


def _get_row(username):
    engine = get_engine()
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT * FROM app_users WHERE username = :u"),
            {"u": username},
        ).fetchone()


def get_user_with_hash(username):
    row = _get_row(username)
    if row is None:
        return None
    d = _row_to_public(row)
    d["password_hash"] = dict(zip(row._mapping.keys(), row)).get("password_hash")
    return d


def get_user_by_username(username):
    row = _get_row(username)
    if row is None:
        return None
    return _row_to_public(row)


def get_user_by_id(user_id):
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM app_users WHERE id = :id"),
            {"id": user_id},
        ).fetchone()
    if row is None:
        return None
    return _row_to_public(row)


def list_users():
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, username, role, is_root, must_change_password, active, created_at "
                "FROM app_users ORDER BY id"
            )
        ).fetchall()
    return [_row_to_public(r) for r in rows]


def _require_not_root(user_id):
    target = get_user_by_id(user_id)
    if target is None:
        raise ValueError("usuario_no_existe")
    if target["is_root"]:
        raise PermissionError("root_protegido")
    return target


def set_password(user_id, new_password):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE app_users SET password_hash = :h, must_change_password = 0, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = :id"
            ),
            {"h": hash_password(new_password), "id": user_id},
        )


def update_user(user_id, role=None, active=None):
    target = get_user_by_id(user_id)
    if target is None:
        raise ValueError("usuario_no_existe")
    if target["is_root"] and (role is not None or active is not None):
        raise PermissionError("root_protegido")

    sets, params = [], {"id": user_id}
    if role is not None:
        sets.append("role = :role")
        params["role"] = role
    if active is not None:
        sets.append("active = :active")
        params["active"] = bool(active)
    if not sets:
        return target
    sets.append("updated_at = CURRENT_TIMESTAMP")
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE app_users SET {', '.join(sets)} WHERE id = :id"), params)
    return get_user_by_id(user_id)


def delete_user(user_id):
    _require_not_root(user_id)
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM app_users WHERE id = :id"), {"id": user_id})
