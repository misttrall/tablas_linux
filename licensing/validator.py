"""Verificación de la firma de licencias con la clave pública de Novus."""

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .models import LicenseInvalid


def verify_token(token: str, public_key_pem: bytes) -> dict:
    if public_key_pem is None:
        raise LicenseInvalid("no se encontró la clave pública de verificación")
    key = load_pem_public_key(public_key_pem)
    try:
        return jwt.decode(token, key, algorithms=["EdDSA"], options={"verify_exp": False})
    except jwt.InvalidTokenError as exc:
        raise LicenseInvalid(f"firma de licencia inválida: {exc}") from exc
