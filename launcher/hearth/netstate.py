"""How the PC is connected, for the status bar by the clock: Wi-Fi with its
signal, wired, or not connected. Read straight from the kernel
(/sys/class/net, /proc/net/wireless), so it's cheap enough to check every
few seconds.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SYS = Path("/sys/class/net")
WIRELESS = Path("/proc/net/wireless")
MAX_QUALITY = 70  # what most Wi-Fi drivers report as full strength


@dataclass(frozen=True)
class Link:
    kind: str  # "wifi" | "wired" | "none"
    strength: int | None = None  # Wi-Fi signal, 0-100

    @property
    def bars(self) -> int:
        """0-4, like a phone's."""
        if self.kind != "wifi":
            return 0
        if self.strength is None:
            return 1  # connected, strength unknown: not "no signal"
        return min(4, max(1, (self.strength + 24) // 25))


def _wifi_quality(wireless: Path) -> dict[str, int]:
    """{interface: link quality 0-100} from /proc/net/wireless."""
    out = {}
    try:
        lines = wireless.read_text().splitlines()[2:]
    except OSError:
        return out
    for line in lines:
        name, _, rest = line.partition(":")
        fields = rest.split()
        if len(fields) >= 2:
            try:
                out[name.strip()] = max(0, min(100, round(float(fields[1].rstrip(".")) * 100 / MAX_QUALITY)))
            except ValueError:
                pass
    return out


NM_SECONDS = 30.0  # NetworkManager's signal reading, asked at most this often
_nm_cache: tuple[float, int | None] = (-NM_SECONDS, None)
_nm_asking = threading.Lock()


def _parse_signal(out: str) -> int | None:
    for line in out.splitlines():
        in_use, _, value = line.partition(":")
        if in_use.strip() == "*" and value.strip().isdigit():
            return max(0, min(100, int(value)))
    return None


def _ask_nm() -> None:
    global _nm_cache
    try:
        out = subprocess.run(["nmcli", "-t", "-f", "IN-USE,SIGNAL", "dev", "wifi", "list", "--rescan", "no"],
                             capture_output=True, text=True, timeout=3).stdout
        signal = _parse_signal(out)
    except (OSError, subprocess.SubprocessError):
        signal = None
    _nm_cache = (time.monotonic(), signal)
    _nm_asking.release()


def _nm_signal(run=None) -> int | None:
    """The connected Wi-Fi network's signal (0-100) from NetworkManager, for
    kernels without /proc/net/wireless (field report #38). The last answer,
    refreshed in the background every NM_SECONDS: nmcli mustn't hold up the
    home screen."""
    global _nm_cache
    now = time.monotonic()
    if now - _nm_cache[0] >= NM_SECONDS:
        if run is not None:  # tests
            _nm_cache = (now, _parse_signal(run()))
        elif _nm_asking.acquire(blocking=False):
            _nm_cache = (now, _nm_cache[1])  # not again until this one answers
            threading.Thread(target=_ask_nm, daemon=True, name="nmcli").start()
    return _nm_cache[1]


def link(sys: Path = SYS, wireless: Path = WIRELESS, nm=_nm_signal) -> Link:
    """The best connection that's up: wired beats Wi-Fi, like the network's own choice."""
    quality = _wifi_quality(wireless)
    best = Link("none")
    try:
        interfaces = sorted(sys.iterdir())
    except OSError:
        return best
    for iface in interfaces:
        if not (iface / "device").exists():  # loopback, bridges, VPNs, containers
            continue
        try:
            state = (iface / "operstate").read_text().strip()
        except OSError:
            continue
        if state != "up":
            continue
        if (iface / "wireless").exists() or (iface / "phy80211").exists():
            if best.kind == "none":
                strength = quality.get(iface.name)
                best = Link("wifi", strength if strength is not None else nm())
        else:
            return Link("wired")
    return best
