from __future__ import annotations

import os
import tomllib
from pathlib import Path

_KEYS = frozenset({"model", "language", "directory"})

_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _escape_toml_basic_string(value: str) -> str:
    return "".join(_ESCAPES.get(c, c) for c in value)


def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    return base / "add-subs-to-videos" / "config.toml"


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    return {k: v for k, v in data.items() if k in _KEYS}


def save_config(updates: dict) -> None:
    current = load_config()
    current.update({k: v for k, v in updates.items() if k in _KEYS})
    current = {k: v for k, v in current.items() if v}  # drop empty/None
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f'{k} = "{_escape_toml_basic_string(current[k])}"\n' for k in sorted(current)),
        encoding="utf-8",
    )
