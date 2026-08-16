"""Dependencias FastAPI de autenticacion/autorizacion.

El token viaja en la cookie 'etl_session'. El usuario se carga fresco desde el
store en cada request: si fue desactivado o cambiado de rol, se refleja al
instante (sin esperar la expiracion del token).
"""

from fastapi import Cookie, Depends, HTTPException

from . import security
from .users import get_user_by_username


def current_user(etl_session: str = Cookie(None)):
    if not etl_session:
        raise HTTPException(status_code=401, detail="no_authenticated")
    token = security.verify_token(etl_session)
    if not token:
        raise HTTPException(status_code=401, detail="no_authenticated")
    user = get_user_by_username(token.get("sub", ""))
    if not user or not user.get("active"):
        raise HTTPException(status_code=401, detail="no_authenticated")
    return user


def current_user_or_none(etl_session: str = Cookie(None)):
    """Devuelve el usuario activo o None (sin lanzar 401).

    Se usa en las rutas de página para redirigir a /login en vez de
    responder con un JSON 401 al navegar sin sesión.
    """
    if not etl_session:
        return None
    token = security.verify_token(etl_session)
    if not token:
        return None
    user = get_user_by_username(token.get("sub", ""))
    if not user or not user.get("active"):
        return None
    return user


def require_user(user=Depends(current_user)):
    return user


def require_admin(user=Depends(current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="forbidden")
    return user
