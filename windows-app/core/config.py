"""Persistent settings in ~/.routebuddy/config.json"""
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".routebuddy"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "city_bias": "",
    "geocoding_provider": "nominatim",
}


def load() -> dict:
    if CONFIG_FILE.exists():
        try:
            return {**DEFAULTS, **json.loads(CONFIG_FILE.read_text())}
        except Exception:
            pass
    return dict(DEFAULTS)


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
