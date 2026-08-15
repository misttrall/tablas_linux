from .base import SourceConnector
from .config_resolver import resolve_source_config, validate_environment, validate_prd_limits
from .generic.csv import CSVConnector
from .generic.http import HTTPConnector
from .sap import SAPConnector

__all__ = [
    "SourceConnector",
    "resolve_source_config",
    "validate_environment",
    "validate_prd_limits",
    "CSVConnector",
    "HTTPConnector",
    "SAPConnector",
    "CONNECTORS",
    "get_source",
]

CONNECTORS = {
    "sap": SAPConnector,
    "http": HTTPConnector,
    "csv": CSVConnector,
}


def get_source(source_config):
    """Devuelve la instancia del conector según `type` en la configuración."""
    type_ = source_config.get("type")
    if not type_:
        raise ValueError("Configuración de fuente sin 'type'")
    try:
        return CONNECTORS[type_](source_config.get("config", {}))
    except KeyError:
        raise ValueError(f"Tipo de fuente no soportado: {type_}")
