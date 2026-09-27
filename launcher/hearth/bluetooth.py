"""Bluetooth: pair, connect and forget controllers and headsets (bluetoothctl)."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

Runner = Callable[[list[str]], tuple[int, str, str]]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x01|\x02")
MAC = re.compile(r"^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$", re.I)


def _run(argv: list[str], timeout: float = 40) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, errors="replace")
        return p.returncode, ANSI.sub("", p.stdout), ANSI.sub("", p.stderr)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def available() -> bool:
    return shutil.which("bluetoothctl") is not None


@dataclass
class Device:
    mac: str
    name: str
    paired: bool = False
    connected: bool = False
    kind: str = ""  # bluez's icon name: input-gaming, audio-headset, ...

    def describe(self) -> str:
        what = {"input-gaming": "Controller", "audio-headset": "Headset", "audio-headphones": "Headphones",
                "audio-card": "Speaker", "input-keyboard": "Keyboard", "input-mouse": "Mouse"}.get(self.kind, "")
        state = "Connected" if self.connected else "Paired" if self.paired else "Found nearby"
        return f"{what} · {state}" if what else state


def powered(run: Runner = _run) -> bool | None:
    rc, out, _ = run(["bluetoothctl", "show"])
    if rc or "Powered:" not in out:
        return None  # no adapter
    return re.search(r"Powered:\s*yes", out) is not None


def set_power(on: bool, run: Runner = _run) -> bool:
    return run(["bluetoothctl", "power", "on" if on else "off"])[0] == 0


def parse_info(mac: str, text: str) -> Device:
    def field(name: str) -> str:
        m = re.search(rf"^\s*{name}:\s*(.+)$", text, re.M)
        return m.group(1).strip() if m else ""

    return Device(mac, field("Alias") or field("Name") or mac, field("Paired") == "yes",
                  field("Connected") == "yes", field("Icon"))


def devices(run: Runner = _run) -> list[Device]:
    """Every device bluez knows (paired, or seen in a search), with details."""
    rc, out, _ = run(["bluetoothctl", "devices"])
    if rc:
        return []
    found = []
    for line in out.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) >= 2 and parts[0] == "Device" and MAC.match(parts[1]):
            mac = parts[1]
            rc, info, _ = run(["bluetoothctl", "info", mac])
            dev = parse_info(mac, info) if not rc else Device(mac, parts[2] if len(parts) > 2 else mac)
            found.append(dev)
    # Paired first, then by name; nameless devices (just an address) last.
    return sorted(found, key=lambda d: (not d.paired, d.name == d.mac or MAC.match(d.name) is not None,
                                        d.name.lower()))


def scan(seconds: int = 12, run: Runner = _run) -> None:
    run(["bluetoothctl", "--timeout", str(seconds), "scan", "on"])


def pair(mac: str, run: Runner = _run) -> tuple[bool, str]:
    """Pair, trust (so it reconnects by itself) and connect."""
    rc, out, err = run(["bluetoothctl", "--timeout", "25", "pair", mac])
    text = out + err
    if rc and "AlreadyExists" not in text and "successful" not in text.lower():
        return False, "Pairing failed: is it still in pairing mode?"
    run(["bluetoothctl", "trust", mac])
    ok = connect(mac, run)
    return ok, "Paired and connected" if ok else "Paired; turn it on to connect"


def connect(mac: str, run: Runner = _run) -> bool:
    rc, out, err = run(["bluetoothctl", "--timeout", "15", "connect", mac])
    return rc == 0 or "successful" in (out + err).lower()


def disconnect(mac: str, run: Runner = _run) -> bool:
    return run(["bluetoothctl", "disconnect", mac])[0] == 0


def forget(mac: str, run: Runner = _run) -> bool:
    return run(["bluetoothctl", "remove", mac])[0] == 0
