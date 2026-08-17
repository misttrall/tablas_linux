"""Caché local firmada de la licencia (JSON atómico en disco)."""

import json
import os


def cache_path(config) -> str:
    lic = config.get("license") or {}
    if lic.get("cache_path"):
        return lic["cache_path"]
    customer = lic.get("customer_id", "default")
    return os.path.expanduser(os.path.join("~", ".novus", f"license-{customer}.json"))


def save_cache(path, data: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
