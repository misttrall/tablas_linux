"""Primitivas de seguridad: hash de password (bcrypt) y tokens JWT.

El secreto ETL_SECRET se genera durante la instalacion y se entrega por
variable de entorno. La expiracion se configura con ETL_TOKEN_TTL_HOURS.
"""

import os
import time

import bcrypt
import jwt

SECRET_ENV = "ETL_SECRET"
DEFAULT_TTL_HOURS = 12
MIN_SECRET_LENGTH = 32


def get_secret() -> str:
    secret = os.environ.get(SECRET_ENV)
    if not secret:
        # Si no se pasó por ENV, usar archivo secreto persistente con permisos 0600
        secret_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".etl_secret")
        if os.path.exists(secret_file):
            with open(secret_file, "r", encoding="utf-8") as f:
                secret = f.read().strip()
        else:
            import secrets
            secret = secrets.token_urlsafe(32)
            try:
                with open(secret_file, "w", encoding="utf-8") as f:
                    f.write(secret)
                os.chmod(secret_file, 0o600)
            except OSError:
                pass
    if len(secret.encode("utf-8")) < MIN_SECRET_LENGTH:
        import warnings
        warnings.warn(
            f"La variable {SECRET_ENV} tiene menos de {MIN_SECRET_LENGTH} caracteres. "
            "Se recomienda un secreto de al menos 32 caracteres para HMAC-SHA256 (RFC 7518).",
            UserWarning,
            stacklevel=2,
        )
    return secret


def hash_password(password):
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password, password_hash):
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def token_ttl_hours():
    try:
        return int(os.environ.get("ETL_TOKEN_TTL_HOURS", DEFAULT_TTL_HOURS))
    except ValueError:
        return DEFAULT_TTL_HOURS


def create_token(username, role, is_root):
    payload = {
        "sub": username,
        "role": role,
        "is_root": bool(is_root),
        "exp": int(time.time()) + token_ttl_hours() * 3600,
    }
    return jwt.encode(payload, get_secret(), algorithm="HS256")


def verify_token(token):
    try:
        return jwt.decode(token, get_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
