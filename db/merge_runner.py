from db.db_connection import get_engine
from db.sinks import get_sink
from utils.config_loader import load_config


def resolve_keys(table_config, source):
    keys = table_config.get("keys")
    if not keys:
        raise ValueError(f"No se definieron claves primarias para la tabla {source} (campo 'keys' en config)")
    return keys


def run_merges(engine=None, sink=None, tables=None, config=None):
    """Ejecuta los MERGE por tabla. Por defecto usa config.json y todas sus tablas."""

    if config is None:
        config = load_config()
    if engine is None:
        engine = get_engine(config)
    if sink is None:
        sink = get_sink(engine)

    if tables is None:
        tables = config["tables"]
    fields = config["fields"]

    for t in tables:

        source = t["source"]
        target = t["target"]
        table_fields = fields[source]
        keys = resolve_keys(t, source)

        staging = f"stg_{target}"

        print(f"Ejecutando MERGE {source}...")

        sink.ensure_target(target, table_fields, keys)
        sink.merge(target, staging, keys, table_fields)

        print(f"Staging {staging} limpiada")
