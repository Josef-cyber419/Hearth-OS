"""Wii Remotes as a Hearth remote, and optionally as a mouse.

The Quick Menu process owns the remotes (it runs the whole time) and turns
them into:

- the Quick Menu's own navigation, while it's open;
- keyboard keys for whatever is in front otherwise (arrows, Enter, Escape),
  like a TV remote: the home screen, Kodi, YouTube, ES-DE, Steam all take them;
- a pointer: on the home screen it highlights the tile you point at, and in
  mouse mode it moves the mouse and A / 2 click;
- Home: tap for the Quick Menu, hold to close the app and go home.

While Dolphin runs, Hearth lets go of the remotes so Wii games get them.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from . import events, wiimote
from .model import Nav
from .wiimote import A, B, DOWN, HOME, LEFT, MINUS, ONE, PLUS, RIGHT, TWO, UP

log = logging.getLogger("hearth")

HOLD_SECONDS = 1.0
REPEAT_DELAY = 0.4
REPEAT_RATE = 0.12
RESCAN_SECONDS = 5.0
DOLPHIN_CHECK_SECONDS = 1.0

MENU_NAVS = {UP: Nav.UP, DOWN: Nav.DOWN, LEFT: Nav.LEFT, RIGHT: Nav.RIGHT, A: Nav.SELECT, TWO: Nav.SELECT,
             B: Nav.BACK, ONE: Nav.BACK, MINUS: Nav.TAB_PREV, PLUS: Nav.TAB_NEXT}
KEYS = {UP: "Up", DOWN: "Down", LEFT: "Left", RIGHT: "Right", A: "Return", TWO: "Return",
        B: "Escape", ONE: "Escape", PLUS: "Menu", MINUS: "BackSpace"}
CLICKS = {A: 1, TWO: 3}  # mouse mode: A is a left click, 2 a right click
DIRECTIONS = (UP, DOWN, LEFT, RIGHT)
# Held sideways (D-pad on the left, like an NES pad): the D-pad turns a
# quarter, and 2 / 1 are the main buttons.
SIDEWAYS = {UP: LEFT, DOWN: RIGHT, LEFT: DOWN, RIGHT: UP, TWO: A, ONE: B}


def turn_sideways(buttons: int) -> int:
    out = buttons & ~(UP | DOWN | LEFT | RIGHT | ONE | TWO)
    for bit, becomes in SIDEWAYS.items():
        if buttons & bit:
            out |= becomes
    return out


class Sink(Protocol):
    """Where input goes when the Quick Menu is closed (the app in front)."""

    def key(self, name: str, down: bool) -> None: ...
    def move(self, x: float, y: float) -> None: ...
    def button(self, number: int, down: bool) -> None: ...


class XTestSink:
    """Sends input into gamescope's X server, as if from a keyboard and mouse.
    Every app Hearth shows runs there, and gamescope routes it to the one in
    front."""

    def __init__(self, display) -> None:
        from Xlib import XK

        self.d = display
        self.xk = XK
        self._codes: dict[str, int] = {}
        self._last: tuple[int, int] | None = None

    def _code(self, name: str) -> int:
        if name not in self._codes:
            self._codes[name] = self.d.keysym_to_keycode(self.xk.string_to_keysym(name))
        return self._codes[name]

    def key(self, name: str, down: bool) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        code = self._code(name)
        if code:
            xtest.fake_input(self.d, X.KeyPress if down else X.KeyRelease, code)
            self.d.sync()

    def move(self, x: float, y: float) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        geo = self.d.screen().root.get_geometry()
        pos = (int(x * (geo.width - 1)), int(y * (geo.height - 1)))
        if pos != self._last:
            self._last = pos
            xtest.fake_input(self.d, X.MotionNotify, x=pos[0], y=pos[1])
            self.d.sync()

    def button(self, number: int, down: bool) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        xtest.fake_input(self.d, X.ButtonPress if down else X.ButtonRelease, number)
        self.d.sync()


class WiiInput:
    def __init__(self, sink: Sink | None, on_tap: Callable[[], None], on_hold: Callable[[], None],
                 find: Callable[[], list[str]] = wiimote.find,
                 dolphin: Callable[[], bool] = wiimote.dolphin_running) -> None:
        self.sink = sink
        self.on_tap, self.on_hold = on_tap, on_hold
        self._find, self._dolphin = find, dolphin
        self.remotes: dict[str, wiimote.Remote] = {}
        self.released = False  # Dolphin has the remotes
        self._rescanned = -1e9
        self._dolphin_checked = -1e9
        self._held = 0  # buttons held, across all remotes
        self._home_down: float | None = None
        self._home_fired = False
        self._repeat: tuple[int, float] | None = None  # (direction, next repeat time) in the menu
        self._keys_down: dict[int, str] = {}
        self._clicks_down: dict[int, int] = {}
        self._was_connected: set[str] = set()
        self.sideways = False
        self._aim: dict = {}

    def configure(self, config) -> None:
        """Apply the Wii Remote settings (see config.Config)."""
        self.sideways = config.wii_hold == "sideways"
        self._aim = {"speed": config.wii_speed, "steadiness": config.wii_steadiness, "bar": config.wii_bar,
                     "calibration": config.wii_calibration}
        for r in self.remotes.values():
            r.aim.configure(**self._aim)

    @property
    def raw(self) -> tuple[float, float] | None:
        """Where the sensor bar is in the camera's view (for calibration)."""
        return next((r.aim.raw for r in self.remotes.values() if r.connected and r.aim.raw), None)

    @property
    def connected(self) -> list[int]:
        return sorted(r.player for r in self.remotes.values() if r.connected)

    @property
    def active(self) -> bool:
        """A remote is connected (so the caller should poll often)."""
        return not self.released and any(r.connected for r in self.remotes.values())

    @property
    def pointer(self) -> tuple[float, float] | None:
        return next((r.pointer for r in self.remotes.values() if r.connected and r.pointer), None)

    def _rescan(self) -> None:
        paths = set(self._find())
        for path in list(self.remotes):
            if path not in paths:
                self.remotes.pop(path).close()
        for i, path in enumerate(sorted(paths)):
            if path not in self.remotes:
                remote = wiimote.Remote(path, player=i + 1)
                if self._aim:
                    remote.aim.configure(**self._aim)
                if remote.open():
                    self.remotes[path] = remote

    def _release_all(self) -> None:
        for r in self.remotes.values():
            r.close()
        self.remotes.clear()
        self._was_connected.clear()
        self._held = 0
        self._home_down = None
        self._lift_everything()

    def _lift_everything(self) -> None:
        """Let go of any key or click we're holding down in the app."""
        if self.sink:
            for name in self._keys_down.values():
                self.sink.key(name, False)
            for number in self._clicks_down.values():
                self.sink.button(number, False)
        self._keys_down.clear()
        self._clicks_down.clear()

    def poll(self, menu_open: bool, pointing: bool, mouse: bool, now: float | None = None) -> list[Nav]:
        """Read the remotes and act on them. Returns navigation for the
        Quick Menu (only while it's open)."""
        now = time.monotonic() if now is None else now
        if now - self._dolphin_checked >= DOLPHIN_CHECK_SECONDS:
            self._dolphin_checked = now
            dolphin = self._dolphin()
            if dolphin and not self.released:
                log.info("wii remote: Dolphin is running; handing the remotes over")
                self._release_all()
            elif not dolphin and self.released:
                log.info("wii remote: Dolphin closed; taking the remotes back")
                self._rescanned = -1e9
            self.released = dolphin
        if self.released:
            return []
        if now - self._rescanned >= RESCAN_SECONDS:
            self._rescanned = now
            self._rescan()

        for path, r in self.remotes.items():
            r.read(now)
            if not r.connected:
                r.probe(now)
            if r.connected and path not in self._was_connected:
                self._was_connected.add(path)
                log.info("wii remote: player %d connected (%s)", r.player, path)
                events.record("wii_remote", player=r.player, connected=True)
            elif not r.connected and path in self._was_connected:
                self._was_connected.discard(path)
                events.record("wii_remote", player=r.player, connected=False)

        held = 0
        for r in self.remotes.values():
            if r.connected:
                held |= r.buttons
        if self.sideways:
            held = turn_sideways(held)
        pressed, released = held & ~self._held, self._held & ~held
        self._held = held
        navs = self._home(pressed, released, held, now)
        if menu_open:
            self._lift_everything()
            navs += self._menu(pressed, held, now)
        else:
            self._repeat = None
            self._app(pressed, released, mouse)
            pointer = self.pointer
            if pointer and self.sink and (pointing or mouse):
                self.sink.move(*pointer)
        return navs

    def _home(self, pressed: int, released: int, held: int, now: float) -> list[Nav]:
        if pressed & HOME:
            self._home_down, self._home_fired = now, False
        if self._home_down is not None and held & HOME and not self._home_fired \
                and now - self._home_down >= HOLD_SECONDS:
            self._home_fired = True
            self.on_hold()
        if released & HOME and self._home_down is not None:
            if not self._home_fired:
                self.on_tap()
            self._home_down = None
        return []

    def _menu(self, pressed: int, held: int, now: float) -> list[Nav]:
        navs = [nav for bit, nav in MENU_NAVS.items() if pressed & bit]
        new_dir = next((d for d in DIRECTIONS if pressed & d), None)
        if new_dir is not None:
            self._repeat = (new_dir, now + REPEAT_DELAY)
        elif self._repeat is not None:
            direction, due = self._repeat
            if not held & direction:
                self._repeat = None
            elif now >= due:
                navs.append(MENU_NAVS[direction])
                self._repeat = (direction, now + REPEAT_RATE)
        return navs

    def _app(self, pressed: int, released: int, mouse: bool) -> None:
        if not self.sink:
            return
        for bit in KEYS:
            if pressed & bit:
                if mouse and bit in CLICKS:
                    self._clicks_down[bit] = CLICKS[bit]
                    self.sink.button(CLICKS[bit], True)
                else:
                    self._keys_down[bit] = KEYS[bit]
                    self.sink.key(KEYS[bit], True)
            if released & bit:
                if bit in self._clicks_down:
                    self.sink.button(self._clicks_down.pop(bit), False)
                if bit in self._keys_down:
                    self.sink.key(self._keys_down.pop(bit), False)

    def close(self) -> None:
        self._release_all()
