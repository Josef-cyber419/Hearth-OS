"""In Desktop Mode, hold the controller's Guide button to go back to Hearth.

Also: if the desktop was reached through Steam's "Switch to Desktop" while
Steam ran inside Hearth, go straight back (see hearth-steam's marker). And
the first time, put the "Hearth" and "Steam Gaming Mode" shortcuts on the
desktop (desktop_icons).

Started by the desktop's autostart (/etc/xdg/autostart/hearth-desktop-guide.desktop).
Inside Game Mode Hearth handles Guide itself, so this exits there. Holding
(not tapping) Guide, for as long as Hearth's own hold-to-go-home, means a
stray press doesn't end the desktop session. Controllers connected later are
picked up too.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from . import events, homebutton, logs

log = logging.getLogger("hearth")

GAME_MODE = "/usr/libexec/hearth/hearth-gamemode"
RESCAN_SECONDS = 3.0
# hearth-steam keeps this fresh while Steam runs inside Hearth. Found fresh
# when the desktop starts, it means Steam's "Switch to Desktop" logged out
# from inside Hearth: go straight back.
STEAM_MARKER_SECONDS = 60.0


def steam_marker() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local/state")
    return Path(base) / "hearth" / "steam-in-hearth"


def came_from_steam(now: float | None = None) -> bool:
    """Whether this desktop session came from Steam's "Switch to Desktop" in
    Hearth. The marker is used up either way, so it can't loop."""
    path = steam_marker()
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    path.unlink(missing_ok=True)
    return 0 <= age <= STEAM_MARKER_SECONDS


def in_game_mode() -> bool:
    return bool(os.environ.get("GAMESCOPE_WAYLAND_DISPLAY"))


# The two shortcuts on the desktop: back to Hearth, and Game Mode with
# Steam's own interface for one session. New users get them from /etc/skel;
# this puts them on an existing user's desktop once (a stamp remembers, so
# one that's been deleted on purpose stays deleted).
DESKTOP_ICONS = ("hearth-gamemode.desktop", "hearth-steam-gamemode.desktop")
APPLICATIONS = Path("/usr/share/applications")


def desktop_folder(home: Path | None = None) -> Path:
    """~/Desktop, or wherever the desktop keeps its files (user-dirs.dirs)."""
    home = home or Path(os.environ.get("HOME") or Path.home())
    folder = home / "Desktop"
    try:
        for line in (home / ".config/user-dirs.dirs").read_text().splitlines():
            if line.startswith("XDG_DESKTOP_DIR="):
                value = line.split("=", 1)[1].strip().strip('"')
                folder = Path(value.replace("$HOME", str(home)))
    except OSError:
        pass
    return folder


def desktop_icons(home: Path | None = None, source: Path = APPLICATIONS, stamp: Path | None = None) -> list[Path]:
    """Copy the shortcuts to the desktop if they aren't there, once per
    user. Returns what was added."""
    home = home or Path(os.environ.get("HOME") or Path.home())
    stamp = stamp or Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "hearth" / "desktop-icons"
    if stamp.exists():
        return []
    folder = desktop_folder(home)
    added = []
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for name in DESKTOP_ICONS:
            target = folder / name
            if target.exists() or not (source / name).exists():
                continue
            target.write_bytes((source / name).read_bytes())
            target.chmod(0o755)  # a launcher the desktop trusts (KDE); GNOME also wants its mark
            subprocess.call(["gio", "set", str(target), "metadata::trusted", "true"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            added.append(target)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text("\n".join(p.name for p in added) + "\n")
    except OSError as e:
        log.info("desktop icons: %s", e)
    return added


def hold_seconds() -> float:
    from . import config as cfg

    try:
        return cfg.load(None).guide_hold
    except Exception:  # a broken config must not stop the way back
        return homebutton.HOLD_SECONDS


def wait_for_hold(list_devices: Callable[[], list[str]], watcher=homebutton.Watcher,
                  hold: float = homebutton.HOLD_SECONDS, stop: threading.Event | None = None) -> bool:
    """Block until Guide is held on any controller. Restarts the watcher
    when controllers come or go. Returns False if `stop` was set."""
    fired = threading.Event()
    stop = stop or threading.Event()
    while not stop.is_set():
        devices = set(list_devices())
        w = watcher(fired.set, homebutton.HomeButton, hold_seconds=hold)
        w.start()
        while not fired.wait(RESCAN_SECONDS) and not stop.is_set():
            if set(list_devices()) != devices:
                break
        w.stop()
        w.join(timeout=1)
        if fired.is_set():
            return True
    return False


def main() -> int:
    logs.setup("desktop-guide")
    if in_game_mode():
        return 0
    for path in desktop_icons():
        log.info("desktop guide: put %s on the desktop", path.name)
    if came_from_steam():
        events.record("desktop_from_steam")
        log.info("desktop guide: came from Steam's Switch to Desktop in Hearth; going back")
        return subprocess.call([GAME_MODE])
    if homebutton.evdev is None:
        log.info("desktop guide: python-evdev missing; Guide won't return to Hearth")
        return 0
    if wait_for_hold(homebutton.evdev.list_devices, hold=hold_seconds()):
        events.record("desktop_guide")
        log.info("desktop guide: Guide held, going back to Hearth")
        return subprocess.call([GAME_MODE])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
