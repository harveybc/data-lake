"""Host configuration: JSON in, defaults merged, nothing about the data itself.

Everything data-specific (roots, globs, resource contracts, time columns) belongs to the
provider and travels in `backend.settings`, which the host hashes but never interprets.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "store_id": "lake",
    "title": "data-lake",
    "description": "Reusable lake host",
    "kind": "lake",
    "engine": None,
    "transport": "http",
    "web_host": "127.0.0.1",
    "web_port": 5060,
    "secret_key": "change-me",
    "max_downloads": 2,
    "max_read_rows": 8000,
    "max_span_days": 366,
    "service_token": None,
    "service_token_file": None,
    "backend": {"entry_point": None, "distribution": None, "settings": {}},
}


def load(path: str | Path | None = None, overrides: dict | None = None) -> dict:
    config = json.loads(json.dumps(DEFAULTS))
    if path:
        file_config = json.loads(Path(path).read_text(encoding="utf-8"))
        backend = dict(config["backend"], **(file_config.get("backend") or {}))
        config.update(file_config)
        config["backend"] = backend
    if overrides:
        backend = dict(config["backend"], **(overrides.get("backend") or {}))
        config.update(overrides)
        config["backend"] = backend
    return config
