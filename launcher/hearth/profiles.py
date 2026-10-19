"""People: everyone in the household with their own home screen.

With one person (how every PC starts) nothing changes and nobody is asked
who they are. Adding a second person (Settings → People) makes the first one
the admin, who needs a PIN; from then on Hearth starts on "Who's playing?".

What's each person's own:
- favorites, tile order, hidden tiles, the Continue row and play times;
- their Steam account (Steam signs in to it; installed games are shared);
- their Discord (its data is swapped in when they're picked);
- limits the admin sets: game time a day, bedtime, locked tiles.
Everything else is shared: ROMs and emulators, apps, Wi-Fi, the look.

These are Hearth's profiles on one account on the PC, not separate Linux
accounts: they keep the household's things apart on the TV, and only an admin
can open Settings or Desktop Mode. The first person keeps the files Hearth
used before there were people ("owner"), so nothing moves.

Kept in ~/.config/hearth/people.json (PINs only as salted hashes).
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("hearth")

OWNER = "owner"  # the first person: keeps the files from before there were people
PIN_LENGTH = 4
COLORS = ("#e8702a", "#3d8fd1", "#4caf6a", "#c9453b", "#8e5cc4", "#d4a72c", "#2aa198", "#d15a9b")
# Settings keys that are each person's own (settings.py keeps them apart).
PERSONAL = ("favorites", "pins", "order", "hide_recent", "hide", "accessibility")
# Tiles only an admin can open (others are asked for an admin's PIN).
ADMIN_TILES = frozenset({"settings", "desktop"})
# Apps whose data (their ~/.var/app folder) is each person's own.
PER_PERSON_APPS = ("com.discordapp.Discord",)
PER_PERSON_TILES = ("discord",)  # their tiles in the shipped apps.toml (closed before a switch)


@dataclass
class Person:
    id: str
    name: str
    color: str = COLORS[0]
    pin: str | None = None  # "salt$hash"
    admin: bool = False
    steam: str | None = None  # the Steam account name they sign in with
    rules: dict = field(default_factory=dict)  # family limits: daily_minutes, bedtime, when_up, locked
    livery: str | None = None  # their own colour scheme (style.LIVERIES), or the household's

    @property
    def initial(self) -> str:
        return (self.name.strip()[:1] or "?").upper()


# -- the file ------------------------------------------------------------------


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hearth" / "people.json"


_cache: tuple[Path, int, dict] | None = None  # (path, mtime_ns, data): it's read on hot paths


def _read() -> dict:
    global _cache
    p = path()
    try:
        stamp = p.stat().st_mtime_ns
    except OSError:
        return {}
    if _cache and _cache[0] == p and _cache[1] == stamp:
        return copy.deepcopy(_cache[2])
    try:
        data = json.loads(p.read_text())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}
    _cache = (p, stamp, copy.deepcopy(data))
    return data


def _write(data: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".people-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def people() -> list[Person]:
    out = []
    for raw in _read().get("people") or []:
        if isinstance(raw, dict) and raw.get("id") and raw.get("name"):
            known = {k: raw[k] for k in Person.__dataclass_fields__ if k in raw}
            known["rules"] = known.get("rules") if isinstance(known.get("rules"), dict) else {}
            out.append(Person(**known))
    return out


def _save_people(ps: list[Person], current: str | None = None) -> None:
    data = _read()
    data["people"] = [asdict(p) for p in ps]
    if current is not None:
        data["current"] = current
    ids = {p.id for p in ps}
    if data.get("current") not in ids:
        data["current"] = OWNER if OWNER in ids else (ps[0].id if ps else OWNER)
    _write(data)


def active() -> bool:
    """More than one person: Hearth asks who's playing."""
    return len(people()) > 1


def get(pid: str) -> Person | None:
    return next((p for p in people() if p.id == pid), None)


def current_id() -> str:
    if not active():
        return OWNER
    cur = _read().get("current")
    return cur if isinstance(cur, str) and get(cur) else OWNER


def current() -> Person | None:
    """Who's using Hearth, or None with only one person (no people yet)."""
    return get(current_id()) if active() else None


def is_admin() -> bool:
    """May open Settings and Desktop Mode: the only person, or an admin."""
    p = current()
    return p is None or p.admin


# -- PINs ------------------------------------------------------------------------


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 200_000).hex()


def valid_pin(pin: str) -> bool:
    return pin.isdigit() and len(pin) == PIN_LENGTH


def hash_pin(pin: str) -> str:
    if not valid_pin(pin):
        raise ValueError(f"a PIN is {PIN_LENGTH} digits")
    salt = secrets.token_hex(8)
    return f"{salt}${_hash(pin, salt)}"


def pin_matches(stored: str | None, pin: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, want = stored.split("$", 1)
    return hmac.compare_digest(_hash(pin, salt), want)


def check_pin(pid: str, pin: str) -> bool:
    p = get(pid)
    return p is not None and pin_matches(p.pin, pin)


def check_admin_pin(pin: str) -> bool:
    """Any admin's PIN: lets a child past a limit, or into Settings."""
    return any(p.admin and pin_matches(p.pin, pin) for p in people())


# -- adding and changing people --------------------------------------------------------


def _new_id(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20] or "person"
    pid, n = base, 2
    while pid in taken or pid == OWNER:
        pid, n = f"{base}-{n}", n + 1
    return pid


def start(owner_name: str, owner_pin: str, family_rules: dict | None = None) -> Person:
    """Turn people on: the one person so far becomes the admin (with a PIN).
    Household limits set before become the starting limits for new people."""
    if people():
        raise ValueError("there are people already")
    owner = Person(OWNER, owner_name.strip() or "Me", COLORS[0], hash_pin(owner_pin), admin=True)
    data = _read()
    data["new_rules"] = {k: v for k, v in (family_rules or {}).items() if k != "pin"}
    _write(data)
    _save_people([owner], current=OWNER)
    return owner


def add(name: str, admin: bool = False) -> Person:
    """A new person, with the household's starting limits (unless admin)."""
    ps = people()
    if not ps:
        raise ValueError("turn people on first (start)")
    name = name.strip()
    if not name:
        raise ValueError("a person needs a name")
    person = Person(_new_id(name, {p.id for p in ps}), name, COLORS[len(ps) % len(COLORS)], admin=admin,
                    rules={} if admin else dict(_read().get("new_rules") or {}))
    _save_people([*ps, person])
    return person


def update(pid: str, **changes) -> Person:
    ps = people()
    for p in ps:
        if p.id == pid:
            for k, v in changes.items():
                if k not in Person.__dataclass_fields__ or k == "id":
                    raise ValueError(f"can't change {k}")
                setattr(p, k, v)
            if not any(q.admin for q in ps):
                raise ValueError("someone has to be an admin")
            if p.admin and not p.pin:
                raise ValueError("an admin needs a PIN")
            _save_people(ps)
            return p
    raise KeyError(pid)


def set_pin(pid: str, pin: str | None) -> None:
    """A new PIN, or None for none (not for an admin)."""
    update(pid, pin=hash_pin(pin) if pin else None)


def set_rule(pid: str, key: str, value) -> None:
    p = get(pid)
    if p is None:
        raise KeyError(pid)
    rules = dict(p.rules)
    if value is None:
        rules.pop(key, None)
    else:
        rules[key] = value
    update(pid, rules=rules)


def remove(pid: str) -> None:
    """Remove a person (their favorites and play times go; games stay). The
    first person can't be removed; with one left, Hearth goes back to not
    asking who's playing."""
    if pid == OWNER:
        raise ValueError("the first person can't be removed")
    ps = [p for p in people() if p.id != pid]
    if not any(p.admin for p in ps):
        raise ValueError("someone has to be an admin")
    if current_id() == pid:
        switch(OWNER)  # the Settings app closes their apps first (hub.switch_person)
    _save_people(ps)
    forget(pid)
    if len(ps) == 1:  # back to one person: no picker, no PINs
        data = _read()
        data.update(people=[], current=OWNER)
        _write(data)


def forget(pid: str, home: Path | None = None) -> None:
    """A removed person's own files: their app data, favorites and play
    times, so a person added later with the same name starts fresh."""
    from . import library, settings

    home = home or Path.home()
    shutil.rmtree(_app_data("", home)[1] / pid, ignore_errors=True)
    if pid != OWNER:
        shutil.rmtree(state_dir(library.state_dir(), pid), ignore_errors=True)
    raw = settings._raw()
    if isinstance(raw.get("people"), dict) and pid in raw["people"]:
        del raw["people"][pid]
        settings.save_raw(raw)


# -- whose files ---------------------------------------------------------------------


def state_dir(base: Path, pid: str | None = None) -> Path:
    """Where a person's own state goes under `base`: base itself for the
    first person (as before there were people), else base/people/<id>."""
    pid = current_id() if pid is None else pid
    return base if pid == OWNER else base / "people" / pid


def _app_data(app_id: str, home: Path) -> tuple[Path, Path]:
    """(where the app keeps its data, where people's copies wait)."""
    return home / ".var/app" / app_id, home / ".var/app-people"


def swap_app_data(old: str, new: str, home: Path | None = None) -> list[str]:
    """Put `old`'s data for each per-person app away and bring `new`'s in
    (renames on one drive: instant). The apps must be closed. Returns
    problems (empty: done)."""
    home = home or Path.home()
    problems = []
    for app_id in PER_PERSON_APPS:
        live, keep = _app_data(app_id, home)
        mine, theirs = keep / old / app_id, keep / new / app_id
        try:
            if mine.exists():  # left by a switch that didn't finish: keep it, out of the way
                aside = mine.with_name(f"{mine.name}.old-{int(time.time())}")
                mine.rename(aside)
                problems.append(f"{app_id}: an older copy for {old} was in the way; kept as {aside.name}")
            if live.exists():
                mine.parent.mkdir(parents=True, exist_ok=True)
                live.rename(mine)
            if theirs.exists():
                live.parent.mkdir(parents=True, exist_ok=True)
                theirs.rename(live)
        except OSError as e:
            problems.append(f"{app_id}: {e}")
    return problems


def switch(pid: str, home: Path | None = None) -> list[str]:
    """Make `pid` the person using Hearth: their apps' data and Steam sign-in.
    Per-person apps (Steam, Discord) must be closed first (the hub does it)."""
    from . import steamlogin

    target = get(pid)
    if target is None:
        raise KeyError(pid)
    old = _read().get("current") or OWNER
    problems = []
    if old != pid:
        problems += swap_app_data(old, pid, home)
    try:
        steamlogin.set_auto_login(target.steam or "", home)
    except OSError as e:
        problems.append(f"Steam: {e}")
    data = _read()
    data["current"] = pid
    _write(data)
    for problem in problems:
        log.warning("switching to %s: %s", pid, problem)
    return problems


def note_steam_account(home: Path | None = None) -> None:
    """Remember which Steam account the current person signed in to (Steam
    marks it most recent), so Steam goes straight to it next time."""
    from . import steamlogin

    p = current()
    if p is None:
        return
    name = steamlogin.most_recent(home)
    if name and name != p.steam:
        update(p.id, steam=name)


def steam_account_id(home: Path | None = None) -> str | None:
    """The current person's Steam account folder under userdata/, if known
    (None: everyone's, as with one person)."""
    from . import steamlogin

    p = current()
    if p is None or not p.steam:
        return None
    return steamlogin.account_id(p.steam, home)
