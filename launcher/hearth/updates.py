"""OS version and updates.

Reading is unprivileged (`rpm-ostree status --json`). Installing goes through
/usr/libexec/hearth/hearth-update via a narrow sudoers rule, because a TV
remote can't answer a password prompt.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

VERSION_FILE = Path("/usr/share/hearth/version.json")
HELPER = "/usr/libexec/hearth/hearth-update"
# Update channels: the image tag each follows. "live" is built from the main
# branch, "staging" from the staging branch (new work, to try before it goes live).
CHANNELS = {"live": "latest", "staging": "staging"}


def hearth_version() -> str:
    try:
        return json.loads(VERSION_FILE.read_text()).get("version", "dev")
    except (OSError, ValueError):
        return "dev"


@dataclass(frozen=True)
class OsStatus:
    image: str | None = None  # e.g. ghcr.io/you/hearth-os:latest
    booted: str | None = None  # version or date of the running image
    staged: str | None = None  # an update downloaded and waiting for a restart
    rollback: str | None = None  # the previous image, restorable

    @property
    def update_ready(self) -> bool:
        return self.staged is not None


def _label(d: dict) -> str:
    if d.get("version"):
        return str(d["version"])
    if d.get("timestamp"):
        return dt.datetime.fromtimestamp(d["timestamp"], dt.timezone.utc).strftime("%Y-%m-%d")
    return str(d.get("checksum", "?"))[:12]


def parse_status(data: dict) -> OsStatus:
    deps = data.get("deployments", [])
    booted = next((d for d in deps if d.get("booted")), None)
    staged = next((d for d in deps if d.get("staged")), None)
    rollback = next((d for d in deps if not d.get("booted") and not d.get("staged")), None)
    image = None
    if booted:
        ref = booted.get("container-image-reference") or ""
        image = ref.split(":", 1)[1] if ref.startswith("ostree-") else ref or None
    return OsStatus(
        image=image,
        booted=_label(booted) if booted else None,
        staged=_label(staged) if staged else None,
        rollback=_label(rollback) if rollback else None,
    )


def split_image(image: str) -> tuple[str, str]:
    """ "docker://ghcr.io/you/hearth-os:latest" -> ("ghcr.io/you/hearth-os", "latest")."""
    ref = image.split("://", 1)[-1]
    name, sep, tag = ref.rpartition(":")
    if not sep or "/" in tag:  # no tag (a ":" in a registry port doesn't count)
        return ref, "latest"
    return name, tag


def channel_of(image: str | None) -> str | None:
    """The channel an image follows ("live", "staging"), or its tag if it's neither."""
    if not image:
        return None
    tag = split_image(image)[1]
    return next((name for name, t in CHANNELS.items() if t == tag), tag)


def channel_image(image: str, channel: str) -> str:
    """The same image on another channel."""
    return f"{split_image(image)[0]}:{CHANNELS[channel]}"


def os_status() -> OsStatus:
    try:
        out = subprocess.run(["rpm-ostree", "status", "--json"], capture_output=True, text=True, timeout=20)
        return parse_status(json.loads(out.stdout)) if out.returncode == 0 else OsStatus()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return OsStatus()


def run_helper(action: str, log_file: Path | None = None, show: bool = False) -> bool:
    """Run `hearth-update apply|rollback` as root. True on success. Its output
    goes to `log_file`, or to the terminal with `show` (hearthctl), so a
    failure always says why."""
    out = open(log_file, "a") if log_file else None if show else subprocess.DEVNULL
    try:
        return subprocess.run(["sudo", "-n", HELPER, action], stdout=out, stderr=subprocess.STDOUT).returncode == 0
    except OSError:
        return False
    finally:
        if log_file:
            out.close()


def update_esde() -> bool:
    try:
        return subprocess.run(["/usr/libexec/hearth/hearth-esde-update"]).returncode == 0
    except OSError:
        return False
