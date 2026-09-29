"""Controller batteries, for the home screen's status bar (like a console's).

Linux lists them with the other power supplies: /sys/class/power_supply/*
with scope "Device" (the PC's own battery, if any, is scope "System"). Xbox
controllers (xpadneo, xone), DualSense/DualShock and Switch Pro controllers
report one; many give a percentage, some only a level.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SYSFS = Path("/sys/class/power_supply")
LEVELS = {"full": 100, "high": 75, "normal": 50, "low": 20, "critical": 5}
LOW = 20  # at or under this, the status bar shows it in the livery's accent colour


@dataclass(frozen=True)
class Battery:
    name: str
    percent: int | None
    charging: bool

    @property
    def low(self) -> bool:
        return self.percent is not None and self.percent <= LOW and not self.charging


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def controllers(root: Path = SYSFS) -> list[Battery]:
    out = []
    try:
        supplies = sorted(root.iterdir())
    except OSError:
        return out
    for d in supplies:
        if _read(d / "scope").lower() != "device" or _read(d / "type").lower() != "battery":
            continue
        capacity = _read(d / "capacity")
        if capacity.isdigit():
            percent: int | None = max(0, min(100, int(capacity)))
        else:
            percent = LEVELS.get(_read(d / "capacity_level").lower())
        status = _read(d / "status").lower()
        name = _read(d / "model_name") or d.name
        out.append(Battery(name, percent, status in ("charging", "full")))
    return out
