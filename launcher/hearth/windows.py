"""`hearthctl windows`: what gamescope can see, for an app that never
reaches the screen (field reports #39, #40).

Lists gamescope's focus properties and every top-level window on each of
its X displays (games often get a second one, :1), with the app id tagged
on the window, its owner in Hearth's session, and a verdict for the app in
front: is its id asked for, does a window carry it, does gamescope call it
focusable?
"""

from __future__ import annotations

import os

from . import session

ROOT_PROPS = ("GAMESCOPECTRL_BASELAYER_APPID", "GAMESCOPE_FOCUSABLE_APPS", "GAMESCOPE_FOCUSED_APP",
              "GAMESCOPE_FOCUSED_WINDOW")


def displays() -> list[str]:
    """The session's display, then the extra ones gamescope gives games."""
    first = os.environ.get("DISPLAY") or ":0"
    return [first] + [d for d in (":0", ":1", ":2") if d != first]


def window_lines(gs, state: dict) -> list[str]:
    from Xlib import X

    out = []
    for win in gs.top_level_windows():
        try:
            mapped = win.get_attributes().map_state == X.IsViewable
            game = gs.get_cardinal(win, "STEAM_GAME")
            overlay = gs.get_cardinal(win, "STEAM_OVERLAY")
            pid = gs.client_pid(win)
            wm_class = gs.wm_class(win)
            title = gs.window_title(win)
        except Exception:
            continue
        owner = session.app_for_pid(pid, state) if pid else None
        bits = [f"0x{win.id:x}", "shown" if mapped else "hidden", f"app={game}" if game else "untagged"]
        if overlay:
            bits.append("overlay")
        if wm_class:
            bits.append(f"class={wm_class[1] or wm_class[0]}")
        if pid:
            bits.append(f"pid={pid}")
        if owner:
            bits.append(f"hearth={owner[1]}")
        if title:
            bits.append(f'"{title[:50]}"')
        out.append("  " + "  ".join(bits))
    return out or ["  (no windows)"]


def verdict(state: dict, base: list[int], focusable: list[int], tagged: set[int]) -> list[str]:
    """For the app in front: where it is on the way to the screen."""
    from .gamescope import appid_for

    fg = state.get("foreground")
    if not fg:
        return ["Nothing in front: the home screen."]
    steam = fg["id"].split(":")[-1] if fg["id"].startswith("game:steam:") else None
    want = int(steam) if steam and steam.isdigit() else appid_for(fg["id"])
    out = [f"In front: {fg.get('name')} ({fg['id']}), app id {want}"]
    out.append(f"  asked for (base layer): {'yes' if want in base else 'NO'}")
    out.append(f"  a window carries it: {'yes' if want in tagged else 'NO'}")
    out.append(f"  gamescope calls it focusable: {'yes' if want in focusable else 'NO'}")
    if want in tagged and want not in focusable:
        out.append("  -> gamescope sees the window but won't focus it: check it's mapped, not override-redirect,"
                   " and which display it's on")
    elif want not in tagged:
        out.append("  -> no window is tagged with this id yet: still loading, or tagged with another id"
                   " (compare the app= values above)")
    return out


def dump() -> str:
    from .gamescope import Gamescope, adopt_session_display

    adopt_session_display()
    state = session.read()
    lines = []
    base: list[int] = []
    focusable: list[int] = []
    tagged: set[int] = set()
    seen_any = False
    for name in displays():
        gs = Gamescope.connect(name)
        if gs is None:
            continue
        seen_any = True
        lines.append(f"Display {name}")
        try:
            props = {p: gs.get_cardinals(gs.root, p) for p in ROOT_PROPS}
        except Exception:
            props = {}
        for p, values in props.items():
            if values:
                lines.append(f"  {p} = {', '.join(map(str, values))}")
        if props.get("GAMESCOPECTRL_BASELAYER_APPID"):
            base = props["GAMESCOPECTRL_BASELAYER_APPID"]
        if props.get("GAMESCOPE_FOCUSABLE_APPS"):
            focusable = props["GAMESCOPE_FOCUSABLE_APPS"]
        for win in gs.top_level_windows():
            try:
                game = gs.get_cardinal(win, "STEAM_GAME")
            except Exception:
                continue
            if game:
                tagged.add(game)
        lines += window_lines(gs, state)
        try:
            gs.d.close()
        except Exception:
            pass
    if not seen_any:
        return "No Game Mode display found: is Hearth running on the TV?"
    lines += [""] + verdict(state, base, focusable, tagged)
    return "\n".join(lines)
