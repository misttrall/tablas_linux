import json
import os

STATE_FILE = "/tmp/etl_state.json"


def get_state():

    if not os.path.exists(STATE_FILE):
        return {
            "running": False,
            "progress": 0,
            "status": "Idle",
            "last_run": None
        }

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "running": False,
            "progress": 0,
            "status": "Idle",
            "last_run": None
        }


def update_state(**kwargs):

    state = get_state()
    state.update(kwargs)

    tmp = STATE_FILE + ".tmp"

    with open(tmp, "w") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp, STATE_FILE)
