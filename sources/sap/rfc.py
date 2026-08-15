import pandas as pd

MAX_WA_CHARS = 512


def parse_rfc_data(data, fields):
    """Convierte la respuesta cruda de RFC_READ_TABLE en una lista de filas."""
    rows = []
    for row in data:
        values = [v.strip() for v in row["WA"].split("|")]
        rows.append(values[: len(fields)])
    return rows


def _build_params(table, fields, filters, batch_size, offset):
    params = {
        "QUERY_TABLE": table,
        "DELIMITER": "|",
        "FIELDS": [{"FIELDNAME": f} for f in fields],
        "ROWCOUNT": batch_size,
        "ROWSKIPS": offset,
    }
    if filters:
        # RFC_READ_TABLE concatena las líneas OPTIONS con espacios, por lo que
        # los filtros AND-combinados deben ir en una única línea válida.
        params["OPTIONS"] = [{"TEXT": " AND ".join(filters)}]
    return params


def _read_chunk(connection, table, fields, filters, batch_size):
    """Lee un conjunto de campos con paginación. Devuelve (rows, wa_len)."""
    rows = []
    offset = 0
    wa_len = 0

    while True:
        result = connection.call(
            "RFC_READ_TABLE",
            **_build_params(table, fields, filters, batch_size, offset)
        )

        data = result.get("DATA") or []

        if not data:
            break

        if wa_len == 0:
            wa_len = len(data[0]["WA"])

        rows.extend(parse_rfc_data(data, fields))

        if len(data) < batch_size:
            break

        offset += batch_size

    return rows, wa_len


def _probe_fields(connection, table, fields, filters):
    """Verifica con una sola fila si un conjunto de campos es legible."""
    try:
        connection.call("RFC_READ_TABLE", **_build_params(table, fields, filters, 1, 0))
        return True
    except Exception:
        return False


def _partition_fields(connection, table, fields, filters):
    """Divide `fields` en particiones legibles, probando mitades de forma recursiva."""
    chunks = []
    pending = [fields]

    while pending:
        part = pending.pop()
        if _probe_fields(connection, table, part, filters):
            chunks.append(part)
            continue
        if len(part) <= 1:
            raise ValueError(f"No se pudo leer ningún campo de {table}: {part}")
        mid = len(part) // 2
        pending.append(part[:mid])
        pending.append(part[mid:])

    index = {f: i for i, f in enumerate(fields)}
    chunks.sort(key=lambda c: index[c[0]])
    return chunks


def _extract_partitioned(connection, table, fields, filters, batch_size):
    """Lee cada partición por separado y las une por posición de fila."""
    partitions = _partition_fields(connection, table, fields, filters)

    frames = []
    n = None

    for part in partitions:
        rows, _ = _read_chunk(connection, table, part, filters, batch_size)
        if n is None:
            n = len(rows)
        elif len(rows) != n:
            raise ValueError(
                f"Particiones de {table} con distinto número de filas "
                f"({len(rows)} vs {n}); no se pueden alinear por posición"
            )
        frames.append(pd.DataFrame(rows, columns=part))

    return frames[0] if len(frames) == 1 else pd.concat(frames, axis=1)


def extract_rfc_table(connection, table, fields, filters=None, batch_size=30000, max_wa_chars=MAX_WA_CHARS):
    """Pagina RFC_READ_TABLE y devuelve un DataFrame con las filas extraídas.

    Si el ancho del registro (WA) supera `max_wa_chars` (límite de RFC_READ_TABLE,
    512 chars), las columnas se particionan y se leen en bloques separados,
    uniéndose luego por posición de fila.
    """
    if batch_size < 100:
        raise ValueError("batch_size mínimo 100 (valores menores provocan lectura fila a fila)")

    if max_wa_chars is None:
        max_wa_chars = MAX_WA_CHARS

    try:
        rows, wa_len = _read_chunk(connection, table, fields, filters, batch_size)
    except Exception as first_error:
        try:
            return _extract_partitioned(connection, table, fields, filters, batch_size)
        except Exception:
            raise first_error

    if wa_len <= max_wa_chars:
        return pd.DataFrame(rows, columns=fields)

    return _extract_partitioned(connection, table, fields, filters, batch_size)
