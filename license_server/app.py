"""API HTTP del license server (FastAPI)."""

import os
import traceback
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine

from . import db as license_db
from .signing import sign_claims


class ActivateRequest(BaseModel):
    customer_id: str
    api_key: str


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": detail, "code": status_code})


def create_app(engine, private_key_pem: bytes) -> FastAPI:
    app = FastAPI(title="Novus License Server")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/activate")
    def activate(body: ActivateRequest):
        customer = license_db.get_customer(engine, body.customer_id)
        if customer is None or not license_db.verify_api_key(
                customer.api_key_hash, body.api_key):
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
    app = create_app(_engine, _default_private_key())
except Exception:
    traceback.print_exc()
    app = None  # sin claves/config el arranque directo fallará con mensaje claro
