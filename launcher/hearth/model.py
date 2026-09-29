"""Navigation state for the home screen, independent of rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from .config import App, Config


class Nav(Enum):
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    SELECT = auto()
    BACK = auto()
    MENU = auto()
    TAB_PREV = auto()
    TAB_NEXT = auto()
    OPTIONS = auto()  # Y / the Menu-style "more" button: favourite, move, hide, ...
    FAVORITE = auto()  # X: star / unstar the tile (the Favorites row)
    SEARCH = auto()  # View / Share / −, or "/": search games and apps


@dataclass
class Home:
    config: Config
    row: int = 0
    # Each row remembers its own column, like most TV launchers.
    cols: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if len(self.cols) != len(self.config.rows):
            self.cols = [0] * len(self.config.rows)
        self.clamp()

    def clamp(self) -> None:
        rows = self.config.rows
        if not rows:
            self.row = 0
            return
        self.row = max(0, min(self.row, len(rows) - 1))
        for i, row in enumerate(rows):
            self.cols[i] = max(0, min(self.cols[i], len(row.apps) - 1))

    @property
    def col(self) -> int:
        return self.cols[self.row] if self.cols else 0

    @property
    def selected(self) -> App | None:
        if not self.config.rows:
            return None
        return self.config.rows[self.row].apps[self.col]

    def move(self, nav: Nav) -> None:
        if not self.config.rows:
            return
        if nav is Nav.UP:
            self.row -= 1
        elif nav is Nav.DOWN:
            self.row += 1
        elif nav is Nav.LEFT:
            self.cols[self.row] -= 1
        elif nav is Nav.RIGHT:
            self.cols[self.row] += 1
        self.clamp()

    def select_id(self, app_id: str) -> bool:
        for r, row in enumerate(self.config.rows):
            for c, app in enumerate(row.apps):
                if app.id == app_id:
                    self.row, self.cols[r] = r, c
                    return True
        return False
