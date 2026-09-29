"""How the PC is connected, for the status bar by the clock: Wi-Fi with its
signal, wired, or not connected. Read straight from the kernel
(/sys/class/net, /proc/net/wireless), so it's cheap enough to check every
few seconds.
"""

from __future__ import annotations

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
        if self.kind != "wifi" or self.strength is None:
            return 0
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


def link(sys: Path = SYS, wireless: Path = WIRELESS) -> Link:
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
                best = Link("wifi", quality.get(iface.name))
        else:
            return Link("wired")
    return best
