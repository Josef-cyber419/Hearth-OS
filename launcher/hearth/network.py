"""Network status and Wi-Fi, through NetworkManager's command-line tool (nmcli).

Bazzite manages networking with NetworkManager, and it lets the person
logged in at the TV change Wi-Fi without a password prompt.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

Runner = Callable[[list[str]], tuple[int, str, str]]


def _run(argv: list[str], timeout: float = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, errors="replace")
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def available() -> bool:
    return shutil.which("nmcli") is not None


def fields(line: str) -> list[str]:
    """Split nmcli's terse (-t) output: ':' separates fields, '\\:' is a colon."""
    out, cur, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


@dataclass
class Status:
    connected: bool = False
    kind: str | None = None  # "ethernet" | "wifi"
    connection: str | None = None  # the connection's name (the network's name for Wi-Fi)
    device: str | None = None
    address: str | None = None

    def describe(self) -> str:
        if not self.connected:
            return "Not connected"
        how = "Ethernet" if self.kind == "ethernet" else f"Wi-Fi: {self.connection}"
        return f"{how} · {self.address}" if self.address else how


@dataclass
class Network:
    ssid: str
    signal: int
    secure: bool
    in_use: bool = False
    saved: bool = False

    def describe(self) -> str:
        state = "Connected" if self.in_use else "Saved" if self.saved else "Secured" if self.secure else "Open"
        return f"{state} · signal {self.signal}%"


def status(run: Runner = _run) -> Status:
    rc, out, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
    if rc:
        return Status()
    best = None
    for line in out.splitlines():
        dev, kind, state, conn = (fields(line) + ["", "", "", ""])[:4]
        if state != "connected" or kind not in ("ethernet", "wifi"):
            continue
        if best is None or (kind == "ethernet" and best.kind != "ethernet"):
            best = Status(True, kind, conn, dev)
    if best is None:
        return Status()
    rc, out, _ = run(["nmcli", "-t", "-g", "IP4.ADDRESS", "device", "show", best.device])
    if not rc and out.strip():
        best.address = out.strip().split("|")[0].strip().split("/")[0]
    return best


def wifi_enabled(run: Runner = _run) -> bool | None:
    rc, out, _ = run(["nmcli", "radio", "wifi"])
    return None if rc else out.strip() == "enabled"


def set_wifi(on: bool, run: Runner = _run) -> bool:
    return run(["nmcli", "radio", "wifi", "on" if on else "off"])[0] == 0


def saved_wifi(run: Runner = _run) -> set[str]:
    rc, out, _ = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    if rc:
        return set()
    return {f[0] for f in map(fields, out.splitlines()) if len(f) > 1 and f[1] == "802-11-wireless"}


def networks(rescan: bool = False, run: Runner = _run) -> list[Network]:
    """Wi-Fi networks in range, strongest first, one entry per name."""
    rc, out, _ = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                      "--rescan", "yes" if rescan else "auto"])
    if rc:
        return []
    saved = saved_wifi(run)
    found: dict[str, Network] = {}
    for line in out.splitlines():
        in_use, ssid, signal, security = (fields(line) + ["", "", "", ""])[:4]
        if not ssid:
            continue  # hidden networks
        net = Network(ssid, int(signal or 0), security not in ("", "--"), in_use == "*", ssid in saved)
        old = found.get(ssid)
        if old is None or net.in_use or (net.signal > old.signal and not old.in_use):
            found[ssid] = net
    return sorted(found.values(), key=lambda n: (not n.in_use, -n.signal))


def connect(ssid: str, password: str | None = None, saved: bool = False, run: Runner = _run) -> tuple[bool, str]:
    if saved and password is None:
        argv = ["nmcli", "connection", "up", "id", ssid]
    else:
        argv = ["nmcli", "device", "wifi", "connect", ssid] + (["password", password] if password else [])
    rc, out, err = run(argv)
    if rc == 0:
        return True, f"Connected to {ssid}"
    text = (err or out).strip()
    if "Secrets were required" in text or "802-1x" in text or "password" in text.lower():
        return False, "Wrong password?"
    return False, text.splitlines()[-1][:80] if text else "Couldn't connect"


def forget(ssid: str, run: Runner = _run) -> bool:
    return run(["nmcli", "connection", "delete", "id", ssid])[0] == 0
