"""Firma de licencias con ed25519 (JWT EdDSA). La clave privada vive solo en el servidor."""

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def sign_claims(claims: dict, private_key_pem: bytes) -> str:
    key = load_pem_private_key(private_key_pem, password=None)
    return jwt.encode(claims, key, algorithm="EdDSA")
