"""Particionado por rangos de clave para extracción de tablas grandes.

La paginación ROWSKIPS de RFC_READ_TABLE no es determinista sin ORDER BY (SAP no
lo soporta), por lo que el full-load de tablas grandes se hace leyendo rangos
disjuntos de la clave: cada rango es una condición OPTIONS acotada e idempotente.

Restricción de RFC_READ_TABLE en este sistema: una línea OPTIONS admite a lo
sumo dos predicados (un solo `AND`) y no combina OR con AND. Por eso las
particiones se leen sin filtros base; cuando hay filtros (p. ej. delta
incremental) la lectura ya queda acotada en SAP y no se particiona.
"""

import string

import pandas as pd

# Cada valor de la clave se clasifica por su primer carácter. El alfabeto
# cubre digitos, mayúsculas y minúsculas; el tramo inicial captura valores con
# espacios iniciales y el centinela final cierra el rango superior.
DEFAULT_ALPHABET = string.digits + string.ascii_uppercase + string.ascii_lowercase

# Valor mayor que cualquier MATNR (CHAR 18). El parser de RFC_READ_TABLE
# rechaza literales de más de 18 caracteres, por lo que el centinela debe
# ajustarse a la longitud de la clave (configurable vía `sentinel`).
_SENTINEL = "~" * 18


def build_chunks(key="MATNR", prefixes=None, sentinel=_SENTINEL):
    """Genera condiciones OPTIONS que particionan el espacio de la clave.

    Cobertura completa, disjunta y sin solapamiento: cada valor de la clave
    satisface exactamente una condición. `prefixes` opcional restringe los
    límites a los primeros caracteres indicados (en cualquier orden).
    `sentinel` opcional reemplaza el límite superior (ajustar a la longitud
    de la clave si no es CHAR(18)).
    """
    boundaries = sorted(set(prefixes if prefixes else DEFAULT_ALPHABET))

    chunks = [f"{key} < '{boundaries[0]}'"]
    for i, lo in enumerate(boundaries):
        hi = boundaries[i + 1] if i + 1 < len(boundaries) else sentinel
        chunks.append(f"{key} >= '{lo}' AND {key} < '{hi}'")
    return chunks


def extract_in_ranges(
    connector, table, fields, filters=None, key="MATNR", prefixes=None,
    batch_size=30000, max_wa_chars=None, sentinel=_SENTINEL,
    on_start=None, on_chunk=None,
):
    """Extrae `table` completa leyendo por rangos disjuntos de `key`.

    Se particiona solo cuando no hay filtros base (full-load). Si hay filtros
    (p. ej. delta incremental o `filters` de config), la lectura ya está acotada
    en el origen y se hace en una sola llamada, sin particionar.

    `on_start(chunks_total)` y `on_chunk(index, total, rows_chunk, rows_so_far)`
    son callbacks opcionales de telemetría (no se invocan si hay filtros).

    Los resultados se concatenan en un único DataFrame. Un fallo en cualquier
    rango propaga la excepción (el runner la aísla por tabla).
    """
    if filters:
        return connector.extract(
            table, fields, filters=list(filters),
            batch_size=batch_size, max_wa_chars=max_wa_chars,
        )

    if sentinel is None:
        sentinel = _SENTINEL

    chunks = build_chunks(key=key, prefixes=prefixes, sentinel=sentinel)
    total = len(chunks)

    if on_start:
        on_start(total)

    frames = []
    rows_so_far = 0
    for index, chunk in enumerate(chunks, start=1):
        frame = connector.extract(
            table, fields, filters=[chunk],
            batch_size=batch_size, max_wa_chars=max_wa_chars,
        )
        frames.append(frame)
        rows_so_far += len(frame)
        if on_chunk:
            on_chunk(index, total, len(frame), rows_so_far)

    if not frames:
        return pd.DataFrame(columns=fields)
    return pd.concat(frames, ignore_index=True)
