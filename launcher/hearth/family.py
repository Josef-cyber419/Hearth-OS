"""Household limits: a daily play-time allowance, a bedtime, and tiles locked
behind a PIN. With one person on this PC they apply to everyone, under the
household PIN; once there are people (profiles.py) each has their own,
set by an admin, and an admin's PIN lets them past (admins have none).

Only time in games counts (your library's games and the store and emulation
tiles), only while one is in front: a game paused for Quick Resume, films and
TV apps don't use the allowance. Entering the PIN lets a game start anyway
and gives EXTRA_MINUTES more.

Kept in settings.json under "family" (the PIN only as a salted hash); what's
been played today is in ~/.local/state/hearth/family.json.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import settings

EXTRA_MINUTES = 30  # what the PIN gives when time's up or it's bedtime
WARN_MINUTES = 5  # a heads-up this long before time's up
CLOSE_GRACE_SECONDS = 60  # "close the game": after this long a warning
DAILY_CHOICES = (0, 30, 60, 90, 120, 180, 240)  # minutes; 0: no limit
BEDTIMES = ("", "20:00-07:00", "21:00-07:00", "22:00-07:00", "23:00-07:00")
# Tiles whose time counts as play time (besides every game in the library).
GAME_TILES = frozenset({"steam", "emulation", "library", "epic", "battlenet", "ea", "ubisoft", "moonlight"})


@dataclass
class Rules:
    pin: str | None = None  # "salt$hash"
    daily_minutes: int = 0
    bedtime: str = ""  # "21:00-07:00"; "" for none
    when_up: str = "remind"  # or "close"
    locked: set[str] = field(default_factory=set)

    @property
    def active(self) -> bool:
        return bool(self.pin)


def rules(prefs: dict | None = None) -> Rules:
    from . import profiles

    if profiles.active():
        person = profiles.current()
        if person is None or person.admin:
            return Rules()
        return _rules({**person.rules, "pin": "admin"})  # an admin's PIN (check_pin)
    return _rules((settings.load() if prefs is None else prefs).get("family") or {})


def _rules(f: dict) -> Rules:
    try:
        daily = int(f.get("daily_minutes") or 0)
    except (TypeError, ValueError):
        daily = 0
    return Rules(pin=f.get("pin") or None, daily_minutes=max(0, daily),
                 bedtime=f.get("bedtime") if f.get("bedtime") in BEDTIMES else "",
                 when_up="close" if f.get("when_up") == "close" else "remind",
                 locked=set(f.get("locked") or []))


# -- the PIN ---------------------------------------------------------------------


def _hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 200_000).hex()


PIN_LENGTH = 4


def valid_pin(pin: str) -> bool:
    return pin.isdigit() and len(pin) == PIN_LENGTH


def set_pin(pin: str | None) -> None:
    """A new PIN (None turns household limits off altogether)."""
    if pin is None:
        data = settings.load()
        data.pop("family", None)
        settings.save(data)
        return
    if not valid_pin(pin):
        raise ValueError(f"a PIN is {PIN_LENGTH} digits")
    salt = secrets.token_hex(8)
    settings.put("family", "pin", f"{salt}${_hash(pin, salt)}")


def check_pin(pin: str, r: Rules | None = None) -> bool:
    from . import profiles

    if profiles.active():
        return profiles.check_admin_pin(pin)
    r = rules() if r is None else r
    if not r.pin or "$" not in r.pin:
        return False
    salt, want = r.pin.split("$", 1)
    return hmac.compare_digest(_hash(pin, salt), want)


# -- today's play time -----------------------------------------------------------


def _state_path(pid: str | None = None) -> Path:
    from . import profiles

    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return profiles.state_dir(Path(base) / "hearth", pid) / "family.json"  # each person's own


def _today(now: float) -> str:
    return datetime.fromtimestamp(now).strftime("%Y-%m-%d")


def _load(now: float, pid: str | None = None) -> dict:
    try:
        data = json.loads(_state_path(pid).read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or data.get("day") != _today(now):
        data = {"day": _today(now), "seconds": 0.0, "extra_until": data.get("extra_until", 0.0)
                if isinstance(data, dict) else 0.0}
    return data


def _save(data: dict) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def played_today(now: float | None = None, pid: str | None = None) -> float:
    """Seconds of games today (the person using Hearth's, or `pid`'s)."""
    return float(_load(time.time() if now is None else now, pid).get("seconds", 0.0))


def add_played(seconds: float, now: float | None = None) -> float:
    now = time.time() if now is None else now
    data = _load(now)
    data["seconds"] = float(data.get("seconds", 0.0)) + max(0.0, seconds)
    _save(data)
    return data["seconds"]


def grant_extra(now: float | None = None, minutes: int = EXTRA_MINUTES) -> None:
    """The PIN was entered: no limits for a while."""
    now = time.time() if now is None else now
    data = _load(now)
    data["extra_until"] = now + minutes * 60
    _save(data)


def extra(now: float) -> bool:
    return now < float(_load(now).get("extra_until", 0.0))


# -- the rules, applied ------------------------------------------------------------


def counts(app_id: str) -> bool:
    """Does time in this app count as play time?"""
    return app_id.startswith("game:") or app_id in GAME_TILES


def in_bedtime(r: Rules, now: float) -> bool:
    if not r.bedtime:
        return False
    start, end = (int(h) * 60 + int(m) for h, m in (part.split(":") for part in r.bedtime.split("-")))
    t = datetime.fromtimestamp(now)
    minute = t.hour * 60 + t.minute
    return minute >= start or minute < end if start > end else start <= minute < end


def left_today(r: Rules, now: float) -> float | None:
    """Seconds of play time left today (None: no daily limit)."""
    if not r.daily_minutes:
        return None
    return max(0.0, r.daily_minutes * 60 - played_today(now))


def needs_pin(app_id: str, now: float | None = None, r: Rules | None = None) -> str | None:
    """Why starting this tile asks for the PIN, or None if it can just start."""
    from . import profiles

    now = time.time() if now is None else now
    if app_id in profiles.ADMIN_TILES and not profiles.is_admin():
        return "Needs an admin's PIN"
    r = rules() if r is None else r
    if not r.active:
        return None
    if app_id in r.locked:
        return "This one is locked"
    if not counts(app_id) or extra(now):
        return None
    if in_bedtime(r, now):
        return BEDTIME
    left = left_today(r, now)
    if left is not None and left <= 0:
        return TIME_UP
    return None


BEDTIME = "It's bedtime"
TIME_UP = "That's all the play time for today"
TIME_REASONS = (BEDTIME, TIME_UP)  # the PIN then gives EXTRA_MINUTES more


def minutes_text(seconds: float) -> str:
    m = int(seconds // 60)
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h" if m % 60 == 0 else f"{m // 60} h {m % 60} min"


class Watcher:
    """Runs in the Quick Menu process: counts play time while a game is in
    front and says what to do: ("notice", title, detail) or ("close",)."""

    def __init__(self) -> None:
        self._at: float | None = None
        self._warned_day = ""
        self._up_since: float | None = None

    def tick(self, foreground_id: str | None, now: float | None = None) -> list[tuple]:
        now = time.time() if now is None else now
        r = rules()
        playing = bool(foreground_id) and counts(foreground_id or "")
        if not r.active or not playing:
            self._at, self._up_since = None, None
            return []
        if self._at is not None:
            add_played(min(now - self._at, 5.0), now)  # never more than a tick's worth at once
        self._at = now
        if extra(now):
            self._up_since = None
            return []
        out: list[tuple] = []
        left = left_today(r, now)
        up = in_bedtime(r, now) or (left is not None and left <= 0)
        if not up and left is not None and left <= WARN_MINUTES * 60 and self._warned_day != _today(now):
            self._warned_day = _today(now)
            out.append(("notice", f"{minutes_text(left) if left >= 60 else 'Under a minute'} of play time left",
                        "Time to find a place to save"))
        if up:
            if self._up_since is None:
                self._up_since = now
                why = "It's bedtime" if in_bedtime(r, now) else "That's all the play time for today"
                then = "Closing the game in a minute: save now" if r.when_up == "close" else "Time to stop"
                out.append(("notice", why, then))
            elif r.when_up == "close" and now - self._up_since >= CLOSE_GRACE_SECONDS:
                self._up_since = now + 1e9  # once
                out.append(("close",))
        else:
            self._up_since = None
        return out


# -- entering the PIN with a controller ------------------------------------------------


class PinEntry:
    """A combination lock: Up/Down change a digit, Left/Right move between
    them, A checks it, B cancels. Number keys (a keyboard, a TV remote) type."""

    def __init__(self, reason: str, target=None, length: int = PIN_LENGTH, checker=None) -> None:
        self.reason = reason
        self.target = target  # what to open once it's right
        self.checker = checker or check_pin  # the household's (or an admin's) PIN by default
        self.digits = [0] * length
        self.pos = 0
        self.message = ""
        self.tries = 0

    def handle(self, nav) -> str | None:
        """Returns "ok", "cancel" or None (still entering)."""
        from .model import Nav

        if nav is Nav.UP:
            self.digits[self.pos] = (self.digits[self.pos] + 1) % 10
        elif nav is Nav.DOWN:
            self.digits[self.pos] = (self.digits[self.pos] - 1) % 10
        elif nav is Nav.LEFT:
            self.pos = max(0, self.pos - 1)
        elif nav is Nav.RIGHT:
            self.pos = min(len(self.digits) - 1, self.pos + 1)
        elif nav is Nav.BACK:
            return "cancel"
        elif nav is Nav.SELECT:
            return self.check()
        return None

    def type(self, ch: str) -> str | None:
        if not ch.isdigit():
            return None
        self.digits[self.pos] = int(ch)
        if self.pos < len(self.digits) - 1:
            self.pos += 1
            return None
        return self.check()

    def check(self) -> str | None:
        if self.checker("".join(map(str, self.digits))):
            return "ok"
        self.message = "Not that one"
        self.digits = [0] * len(self.digits)
        self.pos = 0
        self.tries += 1
        return None
