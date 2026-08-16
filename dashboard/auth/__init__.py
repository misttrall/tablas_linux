"""Autenticación y autorización del dashboard.

Modular a propósito: security (JWT+bcrypt) y el store de usuarios son
intercambiables sin tocar las rutas. El proveedor de motor se inyecta desde
dashboard.app via set_engine_provider para evitar dependencias circulares.
"""

from .dependencies import current_user, require_admin, require_user
from .engine import get_engine, set_engine_provider
from .router import router

__all__ = [
    "current_user",
    "get_engine",
    "require_admin",
    "require_user",
    "router",
    "set_engine_provider",
]
