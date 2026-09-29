"""Screenshots, like a console's captures: taken from the Quick Menu (or
`hearthctl screenshot`), kept in ~/Pictures/Hearth, browsed with the Captures
tile, and shown in the screen saver.

Named "<what was playing> <date time>.png", so they sort by time and say
what they are in any file manager too.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

NAME = re.compile(r"^(?P<title>.*?) (?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}\.\d{2}\.\d{2})(?: \d+)?\.png$")


def folder(home: Path | None = None) -> Path:
    """~/Pictures/Hearth (the Pictures folder the desktop uses, if set)."""
    home = home or Path(os.environ.get("HOME") or Path.home())
    pictures = home / "Pictures"
    try:
        for line in (home / ".config/user-dirs.dirs").read_text().splitlines():
            if line.startswith("XDG_PICTURES_DIR="):
                pictures = Path(line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(home)))
    except OSError:
        pass
    return pictures / "Hearth"


@dataclass(frozen=True)
class Capture:
    path: Path
    title: str  # what was on screen: a game or app's name
    taken: float  # when (seconds since the epoch)

    @property
    def when(self) -> str:
        return time.strftime("%d %b %Y, %H:%M", time.localtime(self.taken))


def _safe(title: str) -> str:
    title = re.sub(r"[/\\:*?\"<>|\x00-\x1f]", "", title).strip() or "Hearth"
    return title[:60]


def save(png: bytes, title: str, home: Path | None = None, now: float | None = None) -> Path:
    """Keep a screenshot. Never overwrites one taken the same second."""
    now = time.time() if now is None else now
    out_dir = folder(home)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H.%M.%S", time.localtime(now))
    path = out_dir / f"{_safe(title)} {stamp}.png"
    n = 2
    while path.exists():
        path = out_dir / f"{_safe(title)} {stamp} {n}.png"
        n += 1
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(png)
    os.replace(tmp, path)
    return path


def take(title: str, home: Path | None = None) -> Path | None:
    """Capture what's on screen now (through gamescope) and keep it."""
    from .report import screenshot

    shot = screenshot()
    if shot is None:
        return None
    return save(shot[0], title, home)


def all_captures(home: Path | None = None) -> list[Capture]:
    """Every screenshot, newest first."""
    found = []
    try:
        entries = list(folder(home).glob("*.png"))
    except OSError:
        return []
    for path in entries:
        try:
            taken = path.stat().st_mtime
        except OSError:
            continue
        m = NAME.match(path.name)
        if m:
            try:
                taken = time.mktime(time.strptime(f"{m['date']} {m['time']}", "%Y-%m-%d %H.%M.%S"))
            except ValueError:
                pass
        found.append(Capture(path, m["title"] if m else path.stem, taken))
    return sorted(found, key=lambda c: (-c.taken, c.path.name))


def delete(capture: Capture) -> bool:
    try:
        capture.path.unlink()
        return True
    except OSError:
        return False
