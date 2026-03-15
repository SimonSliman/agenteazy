"""AgentEazy Config — read/write ~/.agenteazy/config.json."""

DEFAULT_REGISTRY_URL = "https://simondusable--agenteazy-registry-serve.modal.run"
DEFAULT_GATEWAY_URL = "https://simondusable--agenteazy-gateway-serve.modal.run"

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".agenteazy"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _ensure_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load the full config dict, returning {} if the file doesn't exist."""
    if not CONFIG_FILE.is_file():
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(cfg: dict) -> None:
    """Write the config dict to disk."""
    _ensure_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")


def get_registry_url() -> str | None:
    """Return the stored registry URL, or None."""
    return load_config().get("registry_url")


def set_registry_url(url: str) -> None:
    """Store the registry URL."""
    cfg = load_config()
    cfg["registry_url"] = url
    save_config(cfg)


def get_gateway_url() -> str | None:
    """Return the stored gateway URL, or None."""
    return load_config().get("gateway_url")


def set_gateway_url(url: str) -> None:
    """Store the gateway URL."""
    cfg = load_config()
    cfg["gateway_url"] = url
    save_config(cfg)


def get_api_key() -> str | None:
    """Return the stored API key, or None."""
    return load_config().get("api_key")


def set_api_key(key: str) -> None:
    """Store the API key."""
    cfg = load_config()
    cfg["api_key"] = key
    save_config(cfg)


def get_config() -> dict:
    """Return the full config dict."""
    return load_config()
