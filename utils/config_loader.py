import json
import os

from utils.config_validation import ensure_valid_config

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config(path=None):
    cfg_path = os.path.abspath(path) if path else CONFIG_PATH
    with open(cfg_path) as f:
        config = json.load(f)
    return ensure_valid_config(config)
