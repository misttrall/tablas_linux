import json
import os
import re

from utils.config_validation import ensure_valid_config

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

ENV_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")


def _expand_env_vars(data):
    """Expande recursivamente variables ${VAR} o ${VAR:-default} en el archivo de configuración."""
    if isinstance(data, str):
        def _repl(match):
            var_name = match.group(1)
            default_val = match.group(2)
            return os.environ.get(var_name, default_val if default_val is not None else "")
        return ENV_PATTERN.sub(_repl, data)
    elif isinstance(data, dict):
        return {k: _expand_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_expand_env_vars(item) for item in data]
    return data


def load_config(path=None):
    if path and os.path.exists(path):
        cfg_path = os.path.abspath(path)
    elif os.path.exists(CONFIG_PATH):
        cfg_path = CONFIG_PATH
    else:
        fallback = os.path.join(BASE_DIR, "config.example.json")
        cfg_path = fallback if os.path.exists(fallback) else CONFIG_PATH
    with open(cfg_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    config = _expand_env_vars(config)
    return ensure_valid_config(config)
