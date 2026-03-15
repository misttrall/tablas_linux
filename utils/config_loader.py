import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config():

    with open(CONFIG_PATH) as f:
        return json.load(f)
