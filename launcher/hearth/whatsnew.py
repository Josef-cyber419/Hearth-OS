""""What's new": after an update, the home screen shows once what the new
version brought, from the changelog built into the image, like a console's
or TV's notes after a system update.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

CHANGELOG = Path("/usr/share/hearth/CHANGELOG.md")
HEADING = re.compile(r"^## (\d+\.\d+\.\d+)\b")
RELEASE = re.compile(r"^\d+\.\d+\.\d+$")  # not "dev" or "0.21.0-dev.abc1234"


def _seen_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path(os.environ.get("HOME") or Path.home()) / ".local/state")
    return Path(base) / "hearth/whats-new-seen"


def _plain(text: str) -> str:
    """Markdown to words: no **bold**, `code` or [links](...). Arrows become
    ">", which the TV font has."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\*\*|`", "", text).replace("\u2192", ">").strip()


def notes(version: str, changelog: Path = CHANGELOG) -> list[str]:
    """That version's changes, one line each, in plain words."""
    try:
        lines = changelog.read_text().splitlines()
    except OSError:
        return []
    out: list[str] = []
    inside = False
    for line in lines:
        m = HEADING.match(line)
        if line.startswith("## "):
            if inside:
                break
            inside = bool(m) and m.group(1) == version
            continue
        if not inside or not line.strip():
            continue
        if line.lstrip().startswith(("- ", "* ")):
            out.append(_plain(line.lstrip()[2:]))
        elif out:  # a bullet carried on to the next line
            out[-1] += " " + _plain(line)
    return out


def pending(version: str, changelog: Path = CHANGELOG) -> tuple[str, list[str]] | None:
    """(version, notes) if this version's notes haven't been shown yet."""
    if not RELEASE.match(version or ""):
        return None
    try:
        if _seen_path().read_text().strip() == version:
            return None
    except OSError:
        pass
    found = notes(version, changelog)
    return (version, found) if found else None


def mark_seen(version: str) -> None:
    path = _seen_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(version + "\n")
    except OSError:
        pass
