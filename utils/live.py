"""Estado en vivo de la extracción, compartido entre runner y dashboard.

Se escribe de forma atómica (tmp + rename) para que el dashboard pueda
leerlo de forma segura mientras el runner lo actualiza. La ruta se puede
sobrescribir con ETL_LIVE_FILE (necesario en Docker con volumen compartido).
"""

import json
import os

DEFAULT_LIVE_FILE = "/tmp/etl_live.json"


def _live_file():
    return os.environ.get("ETL_LIVE_FILE", DEFAULT_LIVE_FILE)


def idle_state():
    return {
        "running": False,
        "run_id": None,
        "table": None,
        "phase": "idle",
        "chunk_index": 0,
        "chunk_total": 0,
        "rows_so_far": 0,
        "elapsed_s": 0,
    }


def read_live():
    path = _live_file()
    if not os.path.exists(path):
        return idle_state()
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return idle_state()


def update_live(**kwargs):
    state = read_live()
    state.update(kwargs)

    path = _live_file()
    tmp = path + ".tmp"

    with open(tmp, "w") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp, path)
