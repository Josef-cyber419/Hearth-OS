"""Talking to gamescope through X11 window properties.

In Game Mode, gamescope runs with --steam, where only windows carrying a
STEAM_GAME app ID can be focused, and the root window's
GAMESCOPECTRL_BASELAYER_APPID picks which app is shown. Steam normally does
both; Hearth does them for itself and the apps it launches. The Quick Menu is
a STEAM_OVERLAY window: drawn above everything, and given input with
STEAM_INPUT_FOCUS. (See gamescope's steamcompmgr.cpp.)

Every function here is a no-op when there's no X display or python-xlib.
"""

from __future__ import annotations

import logging
import os
import zlib
from pathlib import Path

log = logging.getLogger("hearth")

try:
    from Xlib import X, Xatom, display as xdisplay
    from Xlib.error import XError
except ImportError:  # pragma: no cover - depends on the system
    xdisplay = None

# App IDs for windows Hearth tags. Real Steam app IDs are below ~5M, and
# non-Steam shortcuts have the top bit set, so this range is free.
HOME_APPID = 0x4E480000
OPAQUE = 0xFFFFFFFF


def appid_for(app_id: str) -> int:
    return HOME_APPID + 1 + zlib.crc32(app_id.encode()) % 0xFFFE


SESSION_VARS = ("DISPLAY", "XAUTHORITY", "GAMESCOPE_WAYLAND_DISPLAY", "XDG_RUNTIME_DIR")


def adopt_session_display(proc: Path = Path("/proc"), uid: int | None = None) -> bool:
    """From an SSH login (no DISPLAY), borrow Game Mode's display from the
    running home screen, so hearthctl screenshot/press/check can reach the
    TV. Returns whether a display is set."""
    if os.environ.get("DISPLAY"):
        return True
    uid = os.getuid() if uid is None else uid
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            if d.stat().st_uid != uid:
                continue
            args = (d / "cmdline").read_bytes().split(b"\0")
            if b"-m" not in args or args[args.index(b"-m") + 1] not in (b"hearth", b"hearth.overlay"):
                continue
            env = dict(v.split("=", 1) for v in (d / "environ").read_text(errors="replace").split("\0") if "=" in v)
        except (OSError, IndexError, ValueError):
            continue
        if env.get("DISPLAY"):
            for key in SESSION_VARS:
                if env.get(key):
                    os.environ[key] = env[key]
            return True
    return False


class Gamescope:
    def __init__(self, dpy) -> None:
        self.d = dpy
        self.root = dpy.screen().root
        self._atoms: dict[str, int] = {}

    @classmethod
    def connect(cls, name: str | None = None) -> "Gamescope | None":
        if xdisplay is None:
            return None
        try:
            return cls(xdisplay.Display(name))
        except Exception as e:  # no display, auth failure...
            log.info("gamescope: no X display (%s)", e)
            return None

    def atom(self, name: str) -> int:
        if name not in self._atoms:
            self._atoms[name] = self.d.intern_atom(name)
        return self._atoms[name]

    def window(self, wid: int):
        return self.d.create_resource_object("window", wid)

    def _set_cardinals(self, win, name: str, values: list[int]) -> None:
        win.change_property(self.atom(name), Xatom.CARDINAL, 32, values)

    def get_cardinal(self, win, name: str) -> int | None:
        try:
            prop = win.get_full_property(self.atom(name), X.AnyPropertyType)
        except XError:
            return None
        return int(prop.value[0]) if prop and len(prop.value) else None

    # -- windows ---------------------------------------------------------------

    def argb_visual(self) -> int | None:
        """A 32-bit TrueColor visual, for windows with real transparency."""
        for depth in self.d.screen().allowed_depths:
            if depth.depth == 32:
                for visual in depth.visuals:
                    if visual.visual_class == X.TrueColor:
                        return visual.visual_id
        return None

    def top_level_windows(self) -> list:
        try:
            return list(self.root.query_tree().children)
        except XError:
            return []

    def window_title(self, win) -> str | None:
        """_NET_WM_NAME (UTF-8, what SDL and most toolkits set) or WM_NAME."""
        try:
            prop = win.get_full_property(self.atom("_NET_WM_NAME"), self.atom("UTF8_STRING"))
            if prop and prop.value:
                value = prop.value
                return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
            name = win.get_wm_name()
            return name.decode("latin-1") if isinstance(name, bytes) else name
        except XError:
            return None

    def find_window(self, title: str):
        for win in self.top_level_windows():
            if self.window_title(win) == title:
                return win
        return None

    def wm_class(self, win) -> tuple[str, str] | None:
        try:
            return win.get_wm_class()
        except XError:
            return None

    def client_pid(self, win) -> int | None:
        """PID of the process that owns a window, as seen from the host.

        Prefers the X-Resource extension (correct even for sandboxed Flatpak
        apps, whose _NET_WM_PID is from inside their PID namespace)."""
        try:
            from Xlib.ext import res

            if self.d.has_extension("X-Resource"):
                reply = self.d.res_query_client_ids([{"client": win.id, "mask": res.LocalClientPIDMask}])
                for cid in reply.ids:
                    if cid.value:
                        return int(cid.value[0])
        except Exception:
            pass
        return self.get_cardinal(win, "_NET_WM_PID")

    def tag(self, win, appid: int) -> None:
        """Give a window an app ID so gamescope can focus it."""
        self._set_cardinals(win, "STEAM_GAME", [appid])
        self.d.sync()  # wait until the X server has applied it

    def is_tagged(self, win) -> bool:
        return bool(self.get_cardinal(win, "STEAM_GAME"))

    # -- focus -----------------------------------------------------------------

    def show_app(self, appids: int | list[int] | None) -> None:
        """Bring an app to the front; None hands focus back to gamescope/Steam.

        A list is a priority order: gamescope shows the first app that has a
        window, so [game, home] keeps the home screen's "Starting…" up until
        the game's window appears."""
        if appids is None:
            self.root.delete_property(self.atom("GAMESCOPECTRL_BASELAYER_APPID"))
        else:
            self._set_cardinals(self.root, "GAMESCOPECTRL_BASELAYER_APPID",
                                [appids] if isinstance(appids, int) else list(appids))
        self.d.sync()  # wait until the X server has applied it

    # -- overlay ---------------------------------------------------------------

    def request_screenshot(self, kind: int = 3) -> None:
        """Ask gamescope to save the screen to /tmp/gamescope.png. kind 3 is
        the full composition: the app plus any overlays on top of it."""
        self._set_cardinals(self.root, "GAMESCOPECTRL_REQUEST_SCREENSHOT", [kind])

    def set_click_through(self, win, through: bool) -> None:
        """While the Quick Menu is hidden its window still covers the screen;
        an empty input shape lets the mouse reach the app underneath."""
        from Xlib.ext import shape

        if through:
            win.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, [])
        else:
            win.shape_mask(shape.SO.Set, shape.SK.Input, 0, 0, 0)  # 0 = None: back to the whole window
        self.d.sync()

    def make_overlay(self, win) -> None:
        self._set_cardinals(win, "STEAM_OVERLAY", [1])
        self.set_overlay_visible(win, False)

    def set_overlay_visible(self, win, visible: bool, opacity: float = 1.0, focus: bool = True) -> None:
        """Show or hide the overlay. `focus`: it takes keyboard/mouse input
        (the Quick Menu); without it, it only shows (a notice), and input
        carries on reaching the app underneath."""
        takes_input = visible and focus
        self._set_cardinals(win, "_NET_WM_WINDOW_OPACITY", [int(OPAQUE * opacity) if visible else 0])
        # 1 = the overlay gets keyboard/mouse input, like Steam's Quick Access menu.
        self._set_cardinals(win, "STEAM_INPUT_FOCUS", [1 if takes_input else 0])
        try:
            self.set_click_through(win, not takes_input)
        except Exception as e:  # no SHAPE extension: only the pointer is affected
            log.debug("click-through: %s", e)
        self.d.sync()  # wait until the X server has applied it
