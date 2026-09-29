"""The TV, over HDMI-CEC (with a CEC adapter such as the Pulse-Eight).

Like a console's "one touch play": pressing Guide, or waking the home screen
from the screen saver, turns the TV on and switches it to Hearth's input, in
case someone switched it to something else. The work is done by
/usr/libexec/hearth/hearth-cec (cec-ctl), in the background.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

log = logging.getLogger("hearth.tv")

HELPER = "/usr/libexec/hearth/hearth-cec"
DEVICE = Path("/dev/cec0")
NUDGE_SECONDS = 30.0  # at most this often

_last: float = -1e9


def available(device: Path = DEVICE) -> bool:
    return device.exists()


def switch_here(tries: int = 1, now: float | None = None, device: Path = DEVICE, run=subprocess.Popen) -> bool:
    """Ask the TV to turn on and show Hearth (without waiting). `tries` > 1
    keeps asking until the TV says it's on. Returns whether it asked."""
    global _last
    now = time.monotonic() if now is None else now
    if not available(device) or now - _last < NUDGE_SECONDS:
        return False
    _last = now
    try:
        run([HELPER, "switch"], env={**os.environ, "HEARTH_CEC_TRIES": str(tries)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        log.warning("tv: %s", e)
        return False
    return True


def vendor(device: Path = DEVICE, run=subprocess.run) -> str | None:
    """The TV's make as it reports itself over CEC ("LG", "Samsung"...), or
    None without an adapter or an answer."""
    if not available(device):
        return None
    try:
        out = run([HELPER, "vendor"], capture_output=True, text=True, timeout=8).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out or None
