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
