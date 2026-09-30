"""Which Steam account Steam signs in to, for each person (profiles.py).

Steam remembers every account that ticked "Remember me" (config/
loginusers.vdf) and signs in to the one named AutoLoginUser in
~/.steam/registry.vdf. Setting that, and marking that account the most
recent, before Steam starts makes it go straight to the person's own
account; an empty name brings up Steam's account picker to sign in or add
one. Installed games are shared: they're in the same Steam folder.
"""

from __future__ import annotations

from pathlib import Path

from .library import parse_vdf
from .storage import dump_vdf

STEAMID64_BASE = 76561197960265728  # userdata/<id> is the SteamID64 minus this


def _home(home: Path | None) -> Path:
    return home or Path.home()


def registry_path(home: Path | None = None) -> Path:
    return _home(home) / ".steam/registry.vdf"


def loginusers_path(home: Path | None = None) -> Path | None:
    h = _home(home)
    for root in (h / ".local/share/Steam", h / ".steam/steam"):
        p = root / "config/loginusers.vdf"
        if p.is_file():
            return p
    return None


def _read(p: Path | None) -> dict:
    if p is None:
        return {}
    try:
        return parse_vdf(p.read_text(errors="replace"))
    except OSError:
        return {}


def _write(p: Path, data: dict) -> None:
    tmp = p.with_suffix(".hearth-tmp")
    tmp.write_text(dump_vdf(data))
    tmp.replace(p)


def _users(data: dict) -> dict:
    users = next((v for k, v in data.items() if k.lower() == "users" and isinstance(v, dict)), {})
    return {sid: u for sid, u in users.items() if isinstance(u, dict)}


def _field(user: dict, name: str) -> str:
    return next((str(v) for k, v in user.items() if k.lower() == name.lower()), "")


def accounts(home: Path | None = None) -> list[tuple[str, str]]:
    """(account name, display name) for every account Steam remembers."""
    return [(_field(u, "AccountName"), _field(u, "PersonaName") or _field(u, "AccountName"))
            for u in _users(_read(loginusers_path(home))).values() if _field(u, "AccountName")]


def most_recent(home: Path | None = None) -> str | None:
    for u in _users(_read(loginusers_path(home))).values():
        if _field(u, "MostRecent") == "1" and _field(u, "AccountName"):
            return _field(u, "AccountName")
    return None


def account_id(name: str, home: Path | None = None) -> str | None:
    """The account's folder under userdata/ (its play times and last played)."""
    for sid, u in _users(_read(loginusers_path(home))).items():
        if _field(u, "AccountName").lower() == name.lower():
            try:
                return str(int(sid) - STEAMID64_BASE)
            except ValueError:
                return None
    return None


def _path_in(data: dict, keys: tuple[str, ...]) -> dict:
    """The nested block at keys (matched without case), created if missing."""
    node = data
    for key in keys:
        found = next((k for k in node if k.lower() == key.lower() and isinstance(node[k], dict)), None)
        if found is None:
            node[key] = {}
            found = key
        node = node[found]
    return node


def _set(block: dict, name: str, value: str) -> None:
    key = next((k for k in block if k.lower() == name.lower()), name)
    block[key] = value


def set_auto_login(name: str, home: Path | None = None) -> None:
    """Make Steam sign in to `name` next time it starts ("" for its account
    picker). Only when Steam is set up here; Steam must be closed."""
    reg = registry_path(home)
    if reg.is_file():
        data = _read(reg)
        steam = _path_in(data, ("Registry", "HKCU", "Software", "Valve", "Steam"))
        _set(steam, "AutoLoginUser", name)
        _write(reg, data)
    users_path = loginusers_path(home)
    if users_path is not None:
        data = _read(users_path)
        users = _path_in(data, ("users",))
        for u in users.values():
            if isinstance(u, dict):
                mine = bool(name) and _field(u, "AccountName").lower() == name.lower()
                _set(u, "MostRecent", "1" if mine else "0")
                if mine:
                    _set(u, "AllowAutoLogin", "1")
        _write(users_path, data)
