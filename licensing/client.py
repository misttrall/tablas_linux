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
        try:
            with open(default, "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            return None

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
        try:
            return _activate_http(self.server, {"customer_id": self.customer_id,
                                                 "api_key": self.api_key})
        except (LicenseBlocked, LicenseUnreachable):
            raise
        except OSError as exc:
            raise LicenseUnreachable(str(exc)) from exc

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
