"""Guide-button gestures, read straight from input devices so they work
whatever app has focus:

- hold Guide (or press a remote's Home key): return to the home screen
- tap Guide (or press a remote's Menu key): open the Quick Menu

Reads input devices directly with python-evdev (read-only, no grab), so it
works whatever app has focus. Optional: without evdev this is a no-op.
"""

from __future__ import annotations

import logging
import selectors
import threading
import time
from typing import Callable

log = logging.getLogger("hearth")

HOLD_SECONDS = 1.5

# Linux input event codes (linux/input-event-codes.h).
BTN_MODE = 0x13C  # Guide / Xbox / PS button
KEY_HOMEPAGE = 172  # "Home" key on media remotes and FLIRC
KEY_MENU = 139  # "Menu" key on media remotes and FLIRC
HOLD_KEYS = {BTN_MODE}
TAP_KEYS = {KEY_HOMEPAGE}
# A Guide press shorter than this is a tap.
TAP_MAX_SECONDS = 0.4
EV_KEY = 0x01

try:
    import evdev
except ImportError:  # pragma: no cover - depends on the system
    evdev = None


class HomeButton:
    """Tracks key state; decides when a "go home" gesture happened."""

    keys = HOLD_KEYS | TAP_KEYS

    def __init__(self, hold_seconds: float = HOLD_SECONDS) -> None:
        self.hold_seconds = hold_seconds
        self._held_since: float | None = None

    def key(self, code: int, value: int, now: float) -> bool:
        """Feed a key event (value 1=down, 0=up, 2=repeat). True = go home."""
        if code in TAP_KEYS and value == 1:
            return True
        if code in HOLD_KEYS:
            if value == 1:
                self._held_since = now
            elif value == 0:
                self._held_since = None
        return self.tick(now)

    def tick(self, now: float) -> bool:
        if self._held_since is not None and now - self._held_since >= self.hold_seconds:
            self._held_since = None
            return True
        return False


class GuideTap:
    """Decides when the Quick Menu gesture happened: a short Guide press."""

    keys = {BTN_MODE, KEY_MENU}

    def __init__(self, tap_max: float = TAP_MAX_SECONDS) -> None:
        self.tap_max = tap_max
        self._pressed_at: float | None = None

    def key(self, code: int, value: int, now: float) -> bool:
        if code == KEY_MENU:
            return value == 1
        if code == BTN_MODE:
            if value == 1:
                self._pressed_at = now
            elif value == 0 and self._pressed_at is not None:
                tapped = now - self._pressed_at <= self.tap_max
                self._pressed_at = None
                return tapped
        return False

    def tick(self, now: float) -> bool:
        return False


class Watcher(threading.Thread):
    """Calls `on_fire` when the gesture happens. With `repeat`, keeps
    watching afterwards (the Quick Menu); otherwise stops (going home)."""

    def __init__(self, on_fire: Callable[[], None], gesture=HomeButton, repeat: bool = False,
                 **options) -> None:
        super().__init__(daemon=True, name="hearth-guide-button")
        self.on_fire = on_fire
        self.gesture = gesture
        self.repeat = repeat
        self.options = options  # for the gesture, e.g. hold_seconds
        self._stopping = threading.Event()

    def stop(self) -> None:
        self._stopping.set()

    def run(self) -> None:
        if evdev is None:
            return
        sel = selectors.DefaultSelector()
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                keys = set(dev.capabilities().get(EV_KEY, []))
            except OSError:
                continue
            if keys & self.gesture.keys:
                sel.register(dev, selectors.EVENT_READ)
            else:
                dev.close()
        if not sel.get_map():
            log.info("guide button: no Guide/Home capable devices found")
            return

        button = self.gesture(**self.options)
        try:
            while not self._stopping.is_set():
                fired = False
                for key, _ in sel.select(timeout=0.1):
                    try:
                        events = list(key.fileobj.read())
                    except OSError:  # device unplugged
                        sel.unregister(key.fileobj)
                        continue
                    for ev in events:
                        if ev.type == EV_KEY and button.key(ev.code, ev.value, time.monotonic()):
                            fired = True
                fired = button.tick(time.monotonic()) or fired
                if fired:
                    self._fire()
                    if not self.repeat:
                        return
        finally:
            for key in list(sel.get_map().values()):
                key.fileobj.close()
            sel.close()

    def _fire(self) -> None:
        if not self._stopping.is_set():
            self.on_fire()
