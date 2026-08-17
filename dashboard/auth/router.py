"""Rutas de autenticacion y gestion de usuarios del dashboard."""

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from licensing.client import LicenseError, get_manager
from utils.config_loader import load_config

from . import security
from .dependencies import require_admin, require_user
from .rate_limit import InMemoryRateLimiter
from .users import (
    create_user,
    delete_user,
    get_user_with_hash,
    list_users,
    set_password,
    update_user,
)

router = APIRouter()

COOKIE_NAME = "etl_session"
MIN_PASSWORD_LENGTH = 8

# Limitador de intentos en login: 10 peticiones por minuto por IP
login_limiter = InMemoryRateLimiter(max_requests=10, window_seconds=60)


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"
    must_change_password: bool = True


class UserUpdate(BaseModel):
    role: str | None = None
    active: bool | None = None


class PasswordReset(BaseModel):
    new_password: str


def _cookie_secure():
    return os.environ.get("ETL_COOKIE_SECURE", "").lower() in ("1", "true", "yes")


def _validate_password(password):
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"password_muy_corto (minimo {MIN_PASSWORD_LENGTH})",
        )


@router.post("/api/auth/login")
def login(body: LoginRequest, response: Response, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    allowed, retry_after = login_limiter.check(client_ip)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="demasiados_intentos",
            headers={"Retry-After": str(retry_after)},
        )

    user = get_user_with_hash(body.username)
    if user is None or not security.verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="credenciales_invalidas")
    if not user["active"]:
        raise HTTPException(status_code=403, detail="usuario_inactivo")

    login_limiter.reset(client_ip)

    token = security.create_token(user["username"], user["role"], user["is_root"])
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        max_age=security.token_ttl_hours() * 3600,
        path="/",
    )
    return {
        "ok": True,
        "username": user["username"],
        "role": user["role"],
        "is_root": user["is_root"],
        "must_change_password": user["must_change_password"],
    }


@router.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/api/auth/me")
def me(user=Depends(require_user)):
    return {
        "username": user["username"],
        "role": user["role"],
        "is_root": user["is_root"],
        "must_change_password": user["must_change_password"],
    }


@router.post("/api/auth/password")
def change_password(body: PasswordChangeRequest, user=Depends(require_user)):
    full = get_user_with_hash(user["username"])
    if not security.verify_password(body.current_password, full.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="password_actual_incorrecta")
    _validate_password(body.new_password)
    if security.verify_password(body.new_password, full.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="password_igual_actual")
    set_password(user["id"], body.new_password)
    return {"ok": True}


def _require_admin_licensed(user=Depends(require_admin)):
    config = load_config(os.environ.get("ETL_CONFIG"))
    try:
        lic = get_manager(config).get_license()
    except LicenseError as exc:
        raise HTTPException(status_code=403, detail="licencia_no_verificable") from exc
    import time
    from licensing.models import LicenseState
    state = lic.state(time.time())
    if state in (LicenseState.EXPIRED, LicenseState.SUSPENDED, LicenseState.REVOKED):
        raise HTTPException(status_code=403, detail=f"licencia:{state.value}")
    if not lic.has("dashboard"):
        raise HTTPException(status_code=403, detail="modulo_no_contratado:dashboard")
    return user


@router.get("/api/admin/users")
def admin_list_users(user=Depends(_require_admin_licensed)):
    return list_users()


@router.post("/api/admin/users")
def admin_create_user(body: UserCreate, user=Depends(_require_admin_licensed)):
    if not body.username.strip() or len(body.username.strip()) < 3:
        raise HTTPException(status_code=400, detail="username_invalido")
    if body.role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="rol_invalido")
    _validate_password(body.password)
    try:
        limit = get_manager(load_config(os.environ.get("ETL_CONFIG"))).users_limit()
    except LicenseError:
        raise HTTPException(status_code=403, detail="licencia_no_verificable") from None
    if limit is not None and len(list_users()) >= limit:
        raise HTTPException(status_code=403, detail="limite_usuarios")
    try:
        user_id = create_user(
            username=body.username.strip(),
            password=body.password,
            role=body.role,
            must_change_password=body.must_change_password,
        )
    except Exception:
        raise HTTPException(status_code=409, detail="username_existe") from None
    return {"ok": True, "id": user_id}


@router.patch("/api/admin/users/{user_id}")
def admin_update_user(user_id: int, body: UserUpdate, user=Depends(_require_admin_licensed)):
    try:
        updated = update_user(user_id, role=body.role, active=body.active)
    except ValueError:
        raise HTTPException(status_code=404, detail="usuario_no_existe") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="root_protegido") from None
    return updated


@router.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, user=Depends(_require_admin_licensed)):
    try:
        delete_user(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="usuario_no_existe") from None
    except PermissionError:
        raise HTTPException(status_code=403, detail="root_protegido") from None
    return {"ok": True}


@router.post("/api/admin/users/{user_id}/password")
def admin_reset_password(user_id: int, body: PasswordReset, admin=Depends(_require_admin_licensed)):
    from .users import get_user_by_id

    target = get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="usuario_no_existe")
    if target["is_root"] and not admin["is_root"]:
        raise HTTPException(status_code=403, detail="root_protegido")
    _validate_password(body.new_password)
    set_password(user_id, body.new_password)
    return {"ok": True}
