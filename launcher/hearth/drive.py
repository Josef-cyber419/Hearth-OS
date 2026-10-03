"""Driving the TV from a terminal: `hearthctl press up up a`.

For testing on the real PC (see docs/FIELD_TESTS.md): sends the keys Hearth
understands to what's in front (the home screen, Settings, or the Quick Menu
when it's open), like a keyboard plugged into the PC. The Guide button isn't
a key: `guide` opens or closes the Quick Menu through Hearth itself, and
`home` goes home.
"""

from __future__ import annotations

import time

from . import session

# Button -> X keysym, per launcher/hearth/input.py's KEYS.
BUTTONS = {
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "a": "Return", "b": "Escape", "x": "f", "y": "o", "view": "slash", "menu": "Tab",
    "lb": "q", "rb": "e",
}
REQUESTS = {"guide": "menu", "home": "home"}


def target(gs, state: dict):
    """The window that should get the key: the Quick Menu when it's open,
    else the window of the first app gamescope is asked to show (the home
    screen's when nothing else is)."""
    from Xlib import X

    # The ids in priority order; a Steam game's list is several long
    # ("413091, 769, 814380"; field report #43).
    appids = gs.get_cardinals(gs.root, "GAMESCOPECTRL_BASELAYER_APPID")
    by_id = {}
    for win in gs.top_level_windows():
        try:
            if win.get_attributes().map_state != X.IsViewable:
                continue
            overlay = gs.get_cardinal(win, "STEAM_OVERLAY")
            if state.get("overlay_open") and overlay:
                return win
            if not overlay:
                by_id.setdefault(gs.get_cardinal(win, "STEAM_GAME"), win)
        except Exception:
            continue
    return next((by_id[a] for a in appids if a in by_id), None)


HOLD = 0.06  # a real key is held for a moment; back-to-back down/up can be missed or read as held

# Characters whose X keysym isn't just the character (for typing from the phone remote).
KEYSYM_NAMES = {
    " ": "space", "\n": "Return", "\t": "Tab", ".": "period", ",": "comma", "-": "minus", "_": "underscore",
    "@": "at", "!": "exclam", "?": "question", ":": "colon", ";": "semicolon", "'": "apostrophe",
    '"': "quotedbl", "/": "slash", "\\": "backslash", "#": "numbersign", "$": "dollar", "%": "percent",
    "&": "ampersand", "*": "asterisk", "(": "parenleft", ")": "parenright", "+": "plus", "=": "equal",
    "<": "less", ">": "greater", "[": "bracketleft", "]": "bracketright", "{": "braceleft", "}": "braceright",
    "|": "bar", "^": "asciicircum", "~": "asciitilde", "`": "grave",
}


class Keys:
    """Keys into gamescope's X server, like a keyboard plugged into the PC:
    the buttons Hearth understands (BUTTONS) and typed text, to whatever is
    in front. One connection; calls are serialised (the phone remote's
    server answers on several threads)."""

    def __init__(self, gs, sleep=time.sleep) -> None:
        import threading

        self.gs = gs
        self.sleep = sleep
        self._lock = threading.Lock()
        self._focused: int | None = None

    @classmethod
    def connect(cls) -> "Keys | None":
        from .gamescope import Gamescope, adopt_session_display

        if not adopt_session_display():
            return None
        gs = Gamescope.connect()
        return cls(gs) if gs is not None else None

    def _focus(self) -> bool:
        from Xlib import X

        win = target(self.gs, session.read())
        if win is None:
            return False
        if self._focused != win.id:  # re-focusing every press can drop the press after it
            win.set_input_focus(X.RevertToParent, X.CurrentTime)
            self.gs.d.sync()
            self._focused = win.id
        return True

    def _tap(self, code: int, shift: int | None = None) -> None:
        from Xlib import X
        from Xlib.ext import xtest

        d = self.gs.d
        if shift:
            xtest.fake_input(d, X.KeyPress, shift)
        xtest.fake_input(d, X.KeyPress, code)
        d.sync()
        self.sleep(HOLD)
        xtest.fake_input(d, X.KeyRelease, code)
        if shift:
            xtest.fake_input(d, X.KeyRelease, shift)
        d.sync()

    def press(self, name: str) -> str | None:
        """Press one button; a problem, or None when it was sent."""
        from Xlib import XK

        if name in REQUESTS:
            session.update(lambda s, k=REQUESTS[name]: s["requests"].append(k))
            self._focused = None  # the Quick Menu came or went
            return None
        if name not in BUTTONS:
            return f"unknown button {name!r}: use {', '.join([*BUTTONS, *REQUESTS])}"
        with self._lock:
            if not self._focus():
                return f"nothing in front to press {name!r} on"
            self._tap(self.gs.d.keysym_to_keycode(XK.string_to_keysym(BUTTONS[name])))
        return None

    def type(self, text: str) -> str | None:
        """Type text (ASCII: letters, digits, punctuation; a newline is Enter).
        Characters the keyboard map hasn't got are left out."""
        from Xlib import XK

        with self._lock:
            if not self._focus():
                return "nothing in front to type into"
            d = self.gs.d
            shift = d.keysym_to_keycode(XK.string_to_keysym("Shift_L"))
            for ch in text:
                keysym = XK.string_to_keysym(KEYSYM_NAMES.get(ch, ch))
                code = d.keysym_to_keycode(keysym) if keysym else 0
                if not code:
                    continue
                # The key's plain keysym is something else (e.g. "a" for "A"): hold Shift.
                shifted = d.keycode_to_keysym(code, 0) != keysym
                self._tap(code, shift if shifted else None)
        return None


def press(names: list[str], delay: float = 0.6, sleep=time.sleep) -> list[str]:
    """Press each button in turn. Returns problems, if any (empty: all sent)."""
    unknown = [n for n in names if n not in BUTTONS and n not in REQUESTS]
    if unknown:
        return [f"unknown button {n!r}: use {', '.join([*BUTTONS, *REQUESTS])}" for n in unknown]
    keys = Keys.connect()
    if keys is None:
        from .gamescope import adopt_session_display

        return ["no Game Mode display found: is Hearth running on the TV?" if not adopt_session_display()
                else "couldn't open Game Mode's display"]
    keys.sleep = sleep
    for name in names:
        problem = keys.press(name)
        if problem:
            return [problem]
        sleep(max(delay, 0.8) if name in REQUESTS else delay)  # the Quick Menu slides in
    return []
