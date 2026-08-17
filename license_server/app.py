"""API HTTP del license server (FastAPI)."""

import os
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine

from . import db as license_db
from .signing import sign_claims


class ActivateRequest(BaseModel):
    customer_id: str
    api_key: str


def create_app(engine, private_key_pem: bytes, secret: str) -> FastAPI:
    app = FastAPI(title="Novus License Server")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/activate")
    def activate(body: ActivateRequest):
        customer = license_db.get_customer(engine, body.customer_id)
        if customer is None or not license_db.verify_api_key(
                customer.api_key_hash, body.api_key):
            raise HTTPException(status_code=401, detail="credenciales_invalidas")
        if customer.status != "active":
            raise HTTPException(status_code=403, detail="cliente_deshabilitado")
        lic = license_db.get_active_license(engine, body.customer_id)
        if lic is None:
            raise HTTPException(status_code=403, detail="sin_licencia_activa")
        if lic["status"] == "suspended":
            raise HTTPException(status_code=403, detail="licencia_suspendida")
        if lic["status"] == "revoked":
            raise HTTPException(status_code=403, detail="licencia_revocada")
        now = int(datetime.now(timezone.utc).timestamp())
        claims = dict(lic)
        claims["iat"] = now
        claims["exp"] = lic["offline_until"]
        return {"token": sign_claims(claims, private_key_pem), "claims": claims}

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


def _default_secret() -> str:
    secret = os.environ.get("NOVUS_LICENSE_SERVER_SECRET")
    if not secret:
        raise RuntimeError("Define NOVUS_LICENSE_SERVER_SECRET (pepper del servidor de licencias)")
    return secret


try:  # app de arranque (uvicorn license_server.app:app); los tests usan create_app()
    _engine = _default_engine()
    license_db.init_db(_engine)
    app = create_app(_engine, _default_private_key(), _default_secret())
except Exception:
    app = None  # sin claves/config el arranque directo fallará con mensaje claro
