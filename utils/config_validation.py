"""Validación del config contra el contrato JSON Schema (schemas/config.schema.json)."""

import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCHEMA_PATH = os.path.join(BASE_DIR, "schemas", "config.schema.json")


def load_schema(path=None):
    with open(path or SCHEMA_PATH) as f:
        return json.load(f)


def validate_config(config, schema_path=None):
    """Valida un dict de config contra el contrato. Devuelve la lista de errores (vacía si es válido)."""
    from jsonschema import Draft7Validator

    schema = load_schema(schema_path)
    errors = []
    for err in sorted(Draft7Validator(schema).iter_errors(config), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "$"
        errors.append(f"{loc}: {err.message}")
    return errors


def ensure_valid_config(config, schema_path=None):
    """Falla rápido con un mensaje claro si el config no cumple el contrato."""
    errors = validate_config(config, schema_path)
    if errors:
        raise ValueError(
            "Config inválido según schemas/config.schema.json:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
    return config
