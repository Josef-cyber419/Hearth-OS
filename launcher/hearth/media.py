"""What's playing, and play/pause/skip, for the Quick Menu.

Media apps announce themselves on the session bus (MPRIS): VacuumTube and
other Electron/Chromium apps, Spotify, Kodi, browsers, most music players.
Read and driven with busctl (systemd's own D-Bus tool, always there).
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("hearth")

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
ACTIONS = ("PlayPause", "Next", "Previous")
EVERY_SECONDS = 2.0  # how often the Quick Menu asks what's playing, while it's open

Runner = Callable[[list[str]], str | None]


def _busctl(args: list[str]) -> str | None:
    try:
        p = subprocess.run(["busctl", "--user", "--json=short", *args], capture_output=True, text=True, timeout=1.5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


@dataclass(frozen=True)
class Player:
    bus: str  # org.mpris.MediaPlayer2.<name>
    name: str  # what to call it: "Spotify", "VacuumTube"
    playing: bool
    title: str
    artist: str

    @property
    def summary(self) -> str:
        return f"{self.title} · {self.artist}" if self.artist and self.title else self.title or self.name


def _value(data) -> object:
    """busctl's JSON wraps values as {"type": ..., "data": ...}."""
    while isinstance(data, dict) and "data" in data:
        data = data["data"]
    return data


def _get(run: Runner, bus: str, interface: str, prop: str) -> object:
    """One property of a player, or None if it didn't answer sensibly."""
    try:
        return _value(json.loads(run(["get-property", bus, PATH, interface, prop]) or "null"))
    except ValueError:
        return None


def players(run: Runner = _busctl) -> list[Player]:
    """Media players on the session bus, playing ones first."""
    out = run(["list"])
    try:
        names = [row["name"] for row in json.loads(out or "[]") if str(row.get("name", "")).startswith(PREFIX)]
    except (ValueError, TypeError, KeyError):
        return []
    found = []
    for bus in names:
        status = _get(run, bus, PLAYER, "PlaybackStatus")
        meta = _get(run, bus, PLAYER, "Metadata") or {}
        identity = _get(run, bus, "org.mpris.MediaPlayer2", "Identity")
        if not isinstance(meta, dict):
            meta = {}
        title = _value(meta.get("xesam:title")) or ""
        artist = _value(meta.get("xesam:artist")) or ""
        if isinstance(artist, list):
            artist = ", ".join(str(a) for a in artist)
        name = identity if isinstance(identity, str) and identity else bus[len(PREFIX):].split(".")[0]
        found.append(Player(bus, name, status == "Playing", str(title), str(artist)))
    found.sort(key=lambda p: not p.playing)
    return found


def control(bus: str, action: str, run: Runner = _busctl) -> bool:
    if action not in ACTIONS:
        return False
    return run(["call", bus, PATH, PLAYER, action]) is not None


class Watcher:
    """Asks what's playing, and passes on play/pause/skip, on a thread of its
    own: a media app that's slow to answer (Electron ones can be) never holds
    up the Quick Menu."""

    def __init__(self, run: Runner = _busctl, every: float = EVERY_SECONDS) -> None:
        self.run = run
        self.every = every
        self.players: list[Player] = []
        self.fresh = False  # set when players changed: the menu shows it
        self._asked = -1e9
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    def poll(self, now: float | None = None) -> list[Player]:
        """The players as last seen; asks again every so often."""
        now = time.monotonic() if now is None else now
        if now - self._asked >= self.every and self._jobs.empty():
            self._asked = now
            self._put(None)
        return self.players

    def control(self, bus: str, action: str) -> None:
        self._put((bus, action))

    def wait(self) -> None:
        """Until everything asked so far is done (for tests)."""
        self._jobs.join()

    def _put(self, job) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, name="media", daemon=True)
            self._thread.start()
        self._jobs.put(job)

    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                if job:
                    control(*job, run=self.run)
                found = players(self.run)
                if found != self.players:
                    self.players = found
                    self.fresh = True
            except Exception:  # never let one bad answer stop the watching
                log.exception("media")
            finally:
                self._jobs.task_done()
