"""OS version and updates.

Reading is unprivileged (`rpm-ostree status --json`). Installing goes through
/usr/libexec/hearth/hearth-update via a narrow sudoers rule, because a TV
remote can't answer a password prompt.
"""

from __future__ import annotations

import datetime as dt
import json
import re
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


BUSY = 75  # hearth-update's exit code when an update is already running


def in_progress(run=subprocess.run) -> bool:
    """Is an OS update running right now (ours, or Bazzite's automatic one)?"""
    for pattern in (["-x", "uupd"], ["-f", "^(/usr/bin/)?bootc (upgrade|switch)"],
                    ["-f", "^(/usr/bin/)?rpm-ostree (upgrade|rebase)"]):
        try:
            if run(["pgrep", *pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                return True
        except OSError:
            return False
    return False


def apply(log_file: Path | None = None, show: bool = False) -> str:
    """Download and stage the latest update: "ok", "busy" (one is already
    running; it finishes by itself) or "failed"."""
    if in_progress():
        return "busy"
    code = run_helper("apply", log_file, show, code=True)
    return "ok" if code == 0 else "busy" if code == BUSY else "failed"


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def tidy(output: str, lines: int = 20) -> list[str]:
    """The last `lines` lines of the updater's output, without its progress
    bar's escapes and redraws."""
    out = []
    for line in output.replace("\r", "\n").splitlines():
        line = ANSI.sub("", line).strip()
        if line and not (out and out[-1] == line):
            out.append(line)
    return out[-lines:]


def run_helper(action: str, log_file: Path | None = None, show: bool = False, code: bool = False):
    """Run `hearth-update apply|rollback` as root. True on success. With
    `show` (hearthctl) its output goes to the terminal. Otherwise it goes to
    update.log beside `log_file` (overwritten each time: its progress bar
    redraws five times a second, field report #47), and on a failure its last
    lines are added to `log_file`, so a failure always says why."""
    full = log_file.with_name("update.log") if log_file else None
    out = open(full, "w") if full else None if show else subprocess.DEVNULL
    try:
        rc = subprocess.run(["sudo", "-n", HELPER, action], stdout=out, stderr=subprocess.STDOUT).returncode
    except OSError:
        rc = 1
    finally:
        if full:
            out.close()
    if full and rc != 0:
        try:
            tail = tidy(full.read_text(errors="replace"))
            with open(log_file, "a") as f:
                f.write("".join(f"hearth-update {action}: {line}\n" for line in tail))
        except OSError:
            pass
    return rc if code else rc == 0


def update_esde() -> bool:
    try:
        return subprocess.run(["/usr/libexec/hearth/hearth-esde-update"]).returncode == 0
    except OSError:
        return False
