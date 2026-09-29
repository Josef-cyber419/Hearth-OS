"""Small notices over whatever's on screen, like a console's: a controller
running low, an app that just finished installing, an update ready.

The Quick Menu process shows them (it sits over every app); this module only
decides what to say, and says each thing once.
"""

from __future__ import annotations

from dataclasses import dataclass

SECONDS = 6.0  # how long a notice stays up
LOW, VERY_LOW, RECOVERED = 20, 10, 30  # battery %: warn, warn again, forget


@dataclass
class Toast:
    title: str
    detail: str = ""
    icon: str = "info"  # "battery" | "download" | "update" | "info"
    shown_at: float | None = None


class Notices:
    def __init__(self) -> None:
        self.queue: list[Toast] = []
        self._battery: dict[str, int] = {}  # controller: 0 fine, 1 warned low, 2 warned very low
        self._tiles: set[str] | None = None
        self._update: str | None = None

    def post(self, title: str, detail: str = "", icon: str = "info") -> None:
        if any(t.title == title for t in self.queue):
            return
        self.queue.append(Toast(title, detail, icon))

    def batteries(self, batteries) -> None:
        """batteries: battery.Battery readings."""
        for b in batteries:
            if b.percent is None:
                continue
            level = self._battery.get(b.name, 0)
            if b.charging or b.percent >= RECOVERED:
                self._battery[b.name] = 0
            elif b.percent <= VERY_LOW and level < 2:
                self._battery[b.name] = 2
                self.post("Controller battery very low", f"{b.name}: {b.percent}%. Charge it soon", "battery")
            elif b.percent <= LOW and level < 1:
                self._battery[b.name] = 1
                self.post("Controller battery low", f"{b.name}: {b.percent}%", "battery")

    def tiles(self, available: dict[str, str]) -> None:
        """available: {tile id: name} of tiles that can show now. The first
        call is the starting point; tiles that appear later just finished
        installing (Chrome, VacuumStream, ES-DE, a Flatpak...)."""
        ids = set(available)
        if self._tiles is not None:
            for tile in sorted(ids - self._tiles):
                self.post(f"{available[tile]} is ready", "Just installed: it's on the home screen now", "download")
        self._tiles = ids

    def update_ready(self, version: str | None) -> None:
        if version and version != self._update:
            self._update = version
            self.post("Update ready", "Restart to finish installing it", "update")

    def current(self, now: float) -> Toast | None:
        """The notice to show now, if any (each for SECONDS, one after another)."""
        while self.queue:
            toast = self.queue[0]
            if toast.shown_at is None:
                toast.shown_at = now
            if now - toast.shown_at < SECONDS:
                return toast
            self.queue.pop(0)
        return None
