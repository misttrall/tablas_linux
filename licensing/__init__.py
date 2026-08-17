"""Cliente de licencias Novus embebido en el engine.

El runtime importa desde `licensing.client` (no desde este paquete) para
facilitar el mockeo en tests.
"""

try:
    from .client import LicenseManager, get_manager, require_license
except ImportError:  # pragma: no cover - cliente se completa en Tarea 6
    LicenseManager = None
    get_manager = None
    require_license = None

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
