"""Settings changed in the Settings app, kept in ~/.config/hearth/settings.json.

They use the same tables as apps.toml ([theme], [wii_remote], ...) and are
layered on top of it, so the most recent choice wins wherever it was made.
Your hand-written apps.toml is never rewritten. `hide` lists tiles hidden
from the Settings app.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

TABLES = ("theme", "quick_menu", "controllers", "wii_remote", "home", "emulation")


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hearth" / "settings.json"


def load() -> dict:
    try:
        data = json.loads(path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".settings-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, p)


def put(table: str, key: str, value: Any) -> dict:
    """Change one setting (None removes it, going back to the default)."""
    data = load()
    section = data.setdefault(table, {})
    if value is None:
        section.pop(key, None)
    else:
        section[key] = value
    save(data)
    return data


def set_hidden(app_id: str, hidden: bool) -> dict:
    data = load()
    hide = [a for a in data.get("hide", []) if a != app_id]
    if hidden:
        hide.append(app_id)
    data["hide"] = hide
    save(data)
    return data


def toggle_in(name: str, key: str, on: bool) -> dict:
    """Add or remove `key` in a list setting (e.g. pins), keeping its order."""
    data = load()
    items = [k for k in data.get(name, []) if k != key]
    if on:
        items.append(key)
    data[name] = items
    save(data)
    return data


def mtime() -> float:
    try:
        return path().stat().st_mtime
    except OSError:
        return 0.0


def apply(config_data: dict, settings: dict, hide: bool = True) -> dict:
    """apps.toml contents (already merged) with the Settings app's choices on top."""
    out = copy.deepcopy(config_data)
    for table in TABLES:
        if isinstance(settings.get(table), dict):
            out[table] = {**out.get(table, {}), **settings[table]}
    hidden = set(settings.get("hide", [])) if hide else set()
    if hidden:
        for row in out.get("rows", []):
            row["apps"] = [a for a in row.get("apps", []) if a.get("id") not in hidden]
        out["rows"] = [r for r in out.get("rows", []) if r.get("apps")]
    return out
