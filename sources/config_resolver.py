VALID_ENVIRONMENTS = {"qa", "prd"}

DEFAULT_PRD_LARGE_TABLES = {"MARA", "MARD", "MBEW", "MAKT"}


def _prd_large_tables(config):
    guard = config.get("guard", {}) or {}
    return set(guard.get("large_tables", DEFAULT_PRD_LARGE_TABLES))


def validate_environment(config):
    env = config.get("environment")
    if env not in VALID_ENVIRONMENTS:
        raise ValueError(
            "Falta o es inválido el campo 'environment' en config.json "
            f"(debe ser uno de: {sorted(VALID_ENVIRONMENTS)})"
        )
    return env


def validate_prd_limits(config):
    if config.get("environment") != "prd":
        return
    large_tables = _prd_large_tables(config)
    for table in config.get("tables", []):
        source = table.get("source")
        if source in large_tables and not table.get("filters") and table.get("load_mode") != "range":
            raise ValueError(
                f"environment=prd: la tabla {source} requiere 'filters' o "
                "'load_mode': 'range' (prohibido full-scan pelado en producción)"
            )


def resolve_source_config(config):
    if "source" in config:
        return config["source"]
    if "sap" in config:
        return {"type": "sap", "config": config["sap"]}
    raise ValueError("Falta la configuración de fuente ('source' o 'sap' en config.json)")
