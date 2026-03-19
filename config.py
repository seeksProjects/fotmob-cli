"""Centralized configuration — loads API keys from environment, .env file, or config.json.

Lookup order:
1. Environment variables
2. .env file in project directory
3. config.json file in project directory

NEVER hardcode keys in source code.
"""

import os
import json

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv():
    """Load key=value pairs from a .env file if it exists."""
    env_path = os.path.join(_PROJECT_DIR, ".env")
    vals = {}
    if os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        vals[key.strip()] = value.strip().strip("\"'")
        except OSError:
            pass  # .env file unreadable — skip silently
    return vals


def _load_config_json():
    """Load keys from config.json if it exists."""
    cfg_path = os.path.join(_PROJECT_DIR, "config.json")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass  # config.json missing or malformed — skip silently
    return {}


def get_key(name):
    """Return an API key by name using the fallback chain: env -> .env -> config.json.

    Returns an empty string if the key is not found anywhere.
    """
    # 1. Environment variable
    val = os.environ.get(name)
    if val:
        return val

    # 2. .env file
    dotenv = _load_dotenv()
    if name in dotenv and dotenv[name]:
        return dotenv[name]

    # 3. config.json
    cfg = _load_config_json()
    if name in cfg and cfg[name]:
        return cfg[name]

    return ""


# Convenience accessors
GEMINI_API_KEY = get_key("GEMINI_API_KEY")
GROQ_API_KEY = get_key("GROQ_API_KEY")
