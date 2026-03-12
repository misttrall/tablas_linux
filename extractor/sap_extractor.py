from pyrfc import Connection
import pandas as pd


def extract_table(connection, table, fields, batch_size=30000):

    rows = []
    offset = 0

    while True:

        result = connection.call(
            "RFC_READ_TABLE",
            QUERY_TABLE=table,
            DELIMITER="|",
            FIELDS=[{"FIELDNAME": f} for f in fields],
            ROWCOUNT=batch_size,
            ROWSKIPS=offset
        )

        data = result["DATA"]

        if not data:
            break

        for row in data:
            values = [v.strip() for v in row["WA"].split("|")]
            rows.append(values[:len(fields)])

        print(f"{table}: {len(rows)} registros")

        offset += batch_size

    df = pd.DataFrame(rows, columns=fields)

    return df