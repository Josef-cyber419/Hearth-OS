"""A flight recorder: what happened on this PC, as one JSON object per line.

App launches and exits (with how long they ran and how they ended), how long
each app took to show its first window, Quick Menu use, home-screen frame
rates, crashes. Small, local only, and included in `hearthctl report`, so a
problem can be traced after the fact instead of reproduced.

    hearthctl events        read it
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

MAX_BYTES = 1_000_000  # then events.jsonl.1 takes over; about a month of normal use
_role = "hearth"


def path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "hearth" / "events.jsonl"


def set_role(role: str) -> None:
    global _role
    _role = role


def record(kind: str, **fields) -> None:
    """Append an event. Never raises: diagnostics mustn't break the TV."""
    entry = {"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "by": _role, "event": kind, **fields}
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > MAX_BYTES:
            p.replace(p.with_name(p.name + ".1"))
        with open(p, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError as e:
        log.debug("can't record event %s: %s", kind, e)


def read(limit: int | None = None) -> list[dict]:
    """The most recent events, oldest first."""
    p = path()
    lines: list[str] = []
    for f in (p.with_name(p.name + ".1"), p):
        try:
            lines += f.read_text(errors="replace").splitlines()
        except OSError:
            pass
    if limit is not None:
        lines = lines[-limit:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def describe(e: dict) -> str:
    """One readable line for an event."""
    extra = " ".join(f"{k}={v}" for k, v in e.items() if k not in ("t", "by", "event"))
    return f"{e.get('t', '?')}  {e.get('by', '?'):<7} {e.get('event', '?'):<16} {extra}".rstrip()


class FrameStats:
    """Frame times for a stretch of drawing: is the UI actually smooth here?"""

    SLOW_MS = 1000 / 30  # a frame slower than this is a visible hitch

    def __init__(self) -> None:
        self.times: list[float] = []
        self._last: float | None = None

    def tick(self) -> None:
        now = time.monotonic()
        if self._last is not None:
            self.times.append((now - self._last) * 1000)
        self._last = now

    def pause(self) -> None:
        """Don't count the gap while nothing is being drawn."""
        self._last = None

    def summary(self) -> dict | None:
        if len(self.times) < 30:
            return None
        ordered = sorted(self.times)
        return {
            "frames": len(ordered),
            "fps": round(1000 / (sum(ordered) / len(ordered)), 1),
            "p95_ms": round(ordered[int(len(ordered) * 0.95)], 1),
            "worst_ms": round(ordered[-1], 1),
            "hitches": sum(t > self.SLOW_MS for t in ordered),
        }
