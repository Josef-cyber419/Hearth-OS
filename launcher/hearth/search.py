"""Search: find any game or app from the home screen.

Opened with the controller's View button (Share on PlayStation, − on
Switch), "/" on a keyboard, or the Search tile. Type with the on-screen
keyboard (or a real one); results update as you type and cover every tile
on the home screen plus every game in the Library.

Matching is forgiving, like a TV's: word starts count most ("mario" finds
"Super Mario Galaxy"), then anywhere in the name, then initials ("smg"),
then the platform ("wii" lists Wii games).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Nav

KEY_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm-:."]
ACTIONS = ["space", "delete", "clear"]
LIMIT = 30


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def score(query: str, name: str, platform: str | None = None) -> float | None:
    """How well `name` matches `query`: higher is better, None for no match."""
    q = query.strip().lower()
    if not q:
        return None
    n = name.lower()
    words = _words(n)
    q_words = _words(q)
    if n == q:
        return 100.0
    if n.startswith(q):
        return 90.0
    # Every word you typed starts a word in the name ("mar gal").
    if q_words and all(any(w.startswith(qw) for w in words) for qw in q_words):
        return 80.0 - len(words) * 0.1
    if q in n:
        return 60.0 - n.index(q) * 0.1
    # Initials: "smg" → Super Mario Galaxy.
    initials = "".join(w[0] for w in words)
    compact = q.replace(" ", "")
    if len(compact) >= 2 and initials.startswith(compact):
        return 50.0
    if platform and all(qw in _words(platform) for qw in q_words):
        return 30.0
    return None


def find(query: str, apps: list, limit: int = LIMIT) -> list:
    """Apps (tiles) matching `query`, best first, then by name."""
    scored = []
    for app in apps:
        s = score(query, app.name, getattr(app, "platform", None))
        if s is not None:
            scored.append((-s, app.name.lower(), app))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [a for _, _, a in scored[:limit]]


@dataclass
class Search:
    """The search screen's state: the query, the keyboard and the results."""

    catalog: list
    query: str = ""
    zone: str = "keys"  # "keys" or "results"
    row: int = 1
    col: int = 0
    pick: int = 0  # the result in focus
    results: list = field(default_factory=list)

    @property
    def rows(self) -> int:
        return len(KEY_ROWS) + 1  # the letters, then the action keys

    def key_at(self, row: int, col: int) -> str:
        return KEY_ROWS[row][col] if row < len(KEY_ROWS) else ACTIONS[col]

    def width(self, row: int) -> int:
        return len(KEY_ROWS[row]) if row < len(KEY_ROWS) else len(ACTIONS)

    def type(self, text: str) -> None:
        self.query = (self.query + text)[:40]
        self._update()

    def delete(self) -> None:
        self.query = self.query[:-1]
        self._update()

    def _update(self) -> None:
        self.results = find(self.query, self.catalog)
        self.pick = 0
        if not self.results and self.zone == "results":
            self.zone = "keys"

    def press(self, key: str) -> None:
        if key == "space":
            if self.query and not self.query.endswith(" "):
                self.type(" ")
        elif key == "delete":
            self.delete()
        elif key == "clear":
            self.query = ""
            self._update()
        else:
            self.type(key)

    def handle(self, nav: Nav):
        """Returns "close", the app to open, or None."""
        if nav in (Nav.BACK, Nav.MENU):
            return "close"
        if nav is Nav.FAVORITE:  # X: delete a letter, wherever you are
            self.delete()
            return None
        if self.zone == "results":
            if nav is Nav.LEFT:
                self.pick = max(0, self.pick - 1)
            elif nav is Nav.RIGHT:
                self.pick = min(len(self.results) - 1, self.pick + 1)
            elif nav is Nav.UP:
                self.zone = "keys"
                self.row = self.rows - 1
                self.col = min(self.col, self.width(self.row) - 1)
            elif nav is Nav.SELECT and self.results:
                return self.results[self.pick]
            return None
        if nav in (Nav.UP, Nav.DOWN):
            new = self.row + (1 if nav is Nav.DOWN else -1)
            if new >= self.rows:
                if self.results:
                    self.zone = "results"
                return None
            new = max(0, new)
            old_w, new_w = self.width(self.row), self.width(new)
            self.col = min(new_w - 1, (self.col * new_w) // old_w) if old_w != new_w else self.col
            self.row = new
        elif nav in (Nav.LEFT, Nav.RIGHT):
            self.col = (self.col + (1 if nav is Nav.RIGHT else -1)) % self.width(self.row)
        elif nav is Nav.SELECT:
            self.press(self.key_at(self.row, self.col))
        elif nav is Nav.TAB_NEXT and self.results:
            self.zone = "results"
        return None
