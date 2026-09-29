"""The Captures screen: your screenshots in a grid, one full screen at a
time, and deleting ones you don't want. (Drawn by ui.HomeScreen.)"""

from __future__ import annotations

from dataclasses import dataclass, field

from .captures import Capture, delete
from .model import Nav

COLS = 4


@dataclass
class Gallery:
    items: list[Capture]
    pick: int = 0
    full: bool = False  # one screenshot, full screen
    confirming: bool = False  # "delete it?" asked
    message: str = ""
    deleted: list[Capture] = field(default_factory=list)

    @property
    def current(self) -> Capture | None:
        return self.items[self.pick] if self.items else None

    def handle(self, nav: Nav) -> str | None:
        """Returns "close" when done."""
        self.message = ""
        if self.confirming:
            self.confirming = False
            if nav in (Nav.SELECT, Nav.FAVORITE):
                self._delete()
            return None
        if nav is Nav.BACK:
            if self.full:
                self.full = False
                return None
            return "close"
        if not self.items:
            return "close" if nav in (Nav.SELECT, Nav.MENU) else None
        if nav is Nav.FAVORITE:  # X: delete (asks first)
            self.confirming = True
            return None
        if self.full:
            if nav in (Nav.LEFT, Nav.RIGHT):
                self.pick = (self.pick + (1 if nav is Nav.RIGHT else -1)) % len(self.items)
            return None
        if nav is Nav.SELECT:
            self.full = True
        elif nav is Nav.LEFT and self.pick % COLS:
            self.pick -= 1
        elif nav is Nav.RIGHT and self.pick % COLS < COLS - 1 and self.pick + 1 < len(self.items):
            self.pick += 1
        elif nav is Nav.UP and self.pick >= COLS:
            self.pick -= COLS
        elif nav is Nav.DOWN and self.pick + COLS < len(self.items):
            self.pick += COLS
        elif nav is Nav.DOWN and self.pick // COLS < (len(self.items) - 1) // COLS:
            self.pick = len(self.items) - 1  # the last, shorter row
        return None

    def _delete(self) -> None:
        cap = self.current
        if cap is None:
            return
        if not delete(cap):
            self.message = "Couldn't delete it"
            return
        self.deleted.append(cap)
        self.items.pop(self.pick)
        self.pick = min(self.pick, max(0, len(self.items) - 1))
        self.message = "Deleted"
        if not self.items:
            self.full = False
