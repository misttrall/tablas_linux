"""Resolución de las visiones derivadas declaradas en config['derived'].

Se acepta un único objeto (formato simple) o una lista (múltiples visiones).
Siempre se normaliza a lista y se valida que los nombres de tabla sean únicos
(la tabla derivada se recrea completa en cada corrida).
"""

DEFAULT_VIEW_NAME = "inv_bodega"


def derived_views(config):
    """Devuelve la lista de visiones derivadas (vacía si no hay sección 'derived')."""
    d = config.get("derived")
    if not d:
        return []
    views = d if isinstance(d, list) else [d]
    seen = set()
    for v in views:
        name = v.get("name", DEFAULT_VIEW_NAME)
        if name in seen:
            raise ValueError(f"derived: nombre de visión derivada duplicado '{name}'")
        seen.add(name)
    return views


def resolve_view(config, derived=None):
    """Resuelve la visión a usar: la pasada explícita o la primera declarada."""
    if derived is not None:
        return derived
    views = derived_views(config)
    if not views:
        raise ValueError("No hay sección 'derived' en config.json")
    return views[0]
