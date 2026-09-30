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
    else the app in front (the home screen's window when nothing is)."""
    from Xlib import X

    appid = gs.get_cardinal(gs.root, "GAMESCOPECTRL_BASELAYER_APPID")
    fallback = None
    for win in gs.top_level_windows():
        try:
            if win.get_attributes().map_state != X.IsViewable:
                continue
            overlay = gs.get_cardinal(win, "STEAM_OVERLAY")
            if state.get("overlay_open") and overlay:
                return win
            if not overlay and appid and gs.get_cardinal(win, "STEAM_GAME") == appid:
                fallback = fallback or win
        except Exception:
            continue
    return fallback


def press(names: list[str], delay: float = 0.35, sleep=time.sleep) -> list[str]:
    """Press each button in turn. Returns problems, if any (empty: all sent)."""
    from Xlib import X, XK
    from Xlib.ext import xtest

    from .gamescope import Gamescope, adopt_session_display

    unknown = [n for n in names if n not in BUTTONS and n not in REQUESTS]
    if unknown:
        return [f"unknown button {n!r}: use {', '.join([*BUTTONS, *REQUESTS])}" for n in unknown]
    if not adopt_session_display():
        return ["no Game Mode display found: is Hearth running on the TV?"]
    gs = Gamescope.connect()
    if gs is None:
        return ["couldn't open Game Mode's display"]
    for name in names:
        if name in REQUESTS:
            session.update(lambda s, k=REQUESTS[name]: s["requests"].append(k))
            sleep(max(delay, 0.8))  # the Quick Menu slides in
            continue
        win = target(gs, session.read())
        if win is None:
            return [f"nothing in front to press {name!r} on"]
        code = gs.d.keysym_to_keycode(XK.string_to_keysym(BUTTONS[name]))
        win.set_input_focus(X.RevertToParent, X.CurrentTime)
        gs.d.sync()
        xtest.fake_input(gs.d, X.KeyPress, code)
        xtest.fake_input(gs.d, X.KeyRelease, code)
        gs.d.sync()
        sleep(delay)
    return []
