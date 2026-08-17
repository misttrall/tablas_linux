import os
import traceback
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine

from dashboard.auth.rate_limit import InMemoryRateLimiter

from . import db as license_db
from .signing import sign_claims


class ActivateRequest(BaseModel):
    customer_id: str
    api_key: str


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": detail, "code": status_code})


def _docs_enabled() -> bool:
    env = os.environ.get("ENVIRONMENT", "dev").lower()
    return env == "dev" or os.environ.get("ETL_DOCS_ENABLED", "").lower() in ("1", "true", "yes")


def create_app(engine, private_key_pem: bytes, secret: str = "") -> FastAPI:
    docs_url = "/docs" if _docs_enabled() else None
    redoc_url = "/redoc" if _docs_enabled() else None
    openapi_url = "/openapi.json" if _docs_enabled() else None

    app = FastAPI(
        title="Novus License Server",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    # Limitador de activación: 30 peticiones por minuto por IP
    activate_limiter = InMemoryRateLimiter(max_requests=30, window_seconds=60)

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.get("/")
    def root():
        endpoints = ["/api/health", "/api/activate"]
        if _docs_enabled():
            endpoints.append("/docs")
        return {
            "service": "Novus License Server",
            "status": "online",
            "endpoints": endpoints,
            "dashboard_url": "http://127.0.0.1:8083",
        }

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/activate")
    def activate(body: ActivateRequest, request: Request):
        client_ip = request.client.host if request.client else "unknown"
        allowed, retry_after = activate_limiter.check(client_ip)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "demasiados_intentos", "code": 429},
                headers={"Retry-After": str(retry_after)},
            )

        customer = license_db.get_customer(engine, body.customer_id)
        if customer is None or not license_db.verify_api_key(
                secret, body.api_key, customer.api_key_hash):
            return _error(401, "credenciales_invalidas")
        if customer.status != "active":
            return _error(403, "cliente_deshabilitado")
        lic = license_db.get_active_license(engine, body.customer_id)
        if lic is None:
            return _error(403, "sin_licencia_activa")
        if lic["status"] == "suspended":
            return _error(403, "licencia_suspendida")
        if lic["status"] == "revoked":
            return _error(403, "licencia_revocada")
        now = int(datetime.now(timezone.utc).timestamp())
        claims = {
            "customer_id": lic["customer_id"],
            "license_id": lic["license_id"],
            "status": lic["status"],
            "valid_from": lic["valid_from"],
            "valid_until": lic["valid_until"],
            "offline_until": lic["offline_until"],
            "modules": lic["modules"],
            "limits": lic["limits"],
            "iat": now,
            "exp": lic["offline_until"],
        }
        token = sign_claims(claims, private_key_pem)
        return {
            "token": token,
            "valid_until": claims["valid_until"],
            "offline_until": claims["offline_until"],
            "modules": claims["modules"],
            "limits": claims["limits"],
            "customer_id": claims["customer_id"],
            "license_id": claims["license_id"],
        }

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


try:  # app de arranque (uvicorn license_server.app:app); los tests usan create_app()
    _engine = _default_engine()
    license_db.init_db(_engine)
    _secret = os.environ.get("NOVUS_LICENSE_SERVER_SECRET", "")
    app = create_app(_engine, _default_private_key(), _secret)
except Exception:
    traceback.print_exc()
    app = None  # sin claves/config el arranque directo fallará con mensaje claro
