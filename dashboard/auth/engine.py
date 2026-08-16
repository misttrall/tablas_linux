"""Proveedor de motor SQLAlchemy para el store de usuarios.

Se inyecta desde dashboard.app (set_engine_provider) para no acoplar auth a la
carga de config. Permite sustituir la fuente de datos (p. ej. LDAP) sin tocar
las rutas.
"""

_ENGINE_PROVIDER = None


def set_engine_provider(fn):
    global _ENGINE_PROVIDER
    _ENGINE_PROVIDER = fn


def get_engine_provider():
    return _ENGINE_PROVIDER


def get_engine():
    if _ENGINE_PROVIDER is None:
        raise RuntimeError("auth engine provider no configurado (set_engine_provider)")
    return _ENGINE_PROVIDER()
