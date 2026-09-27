"""Integration tests against a real X server (Xvfb), standing in for
gamescope's Xwayland: window properties, focus, and the overlay itself."""

import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytest.importorskip("Xlib")
pytestmark = pytest.mark.skipif(not shutil.which("Xvfb"), reason="needs Xvfb")


@pytest.fixture(scope="module")
def xdisplay():
    for n in range(90, 110):
        if not Path(f"/tmp/.X11-unix/X{n}").exists():
            break
    proc = subprocess.Popen(["Xvfb", f":{n}", "-screen", "0", "1280x720x24", "+extension", "COMPOSITE"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if Path(f"/tmp/.X11-unix/X{n}").exists():
            break
        time.sleep(0.1)
    yield f":{n}"
    proc.terminate()


def test_window_properties(xdisplay):
    from Xlib import X

    from hearth.gamescope import HOME_APPID, OPAQUE, Gamescope

    gs = Gamescope.connect(xdisplay)
    d = gs.d
    win = d.screen().root.create_window(0, 0, 100, 100, 0, X.CopyFromParent)
    win.set_wm_name("probe")
    d.sync()
    assert gs.find_window("probe").id == win.id
    assert gs.client_pid(win) == os.getpid()  # via the X-Resource extension

    gs.tag(win, HOME_APPID)
    assert gs.is_tagged(win) and gs.get_cardinal(win, "STEAM_GAME") == HOME_APPID
    gs.show_app(HOME_APPID)
    assert gs.get_cardinal(gs.root, "GAMESCOPECTRL_BASELAYER_APPID") == HOME_APPID
    gs.show_app(None)
    assert gs.get_cardinal(gs.root, "GAMESCOPECTRL_BASELAYER_APPID") is None

    gs.make_overlay(win)
    assert gs.get_cardinal(win, "STEAM_OVERLAY") == 1
    assert gs.get_cardinal(win, "STEAM_INPUT_FOCUS") == 0
    gs.set_overlay_visible(win, True)
    assert gs.get_cardinal(win, "STEAM_INPUT_FOCUS") == 1
    assert gs.get_cardinal(win, "_NET_WM_WINDOW_OPACITY") == OPAQUE
    assert gs.argb_visual() is not None


OVERLAY_SCRIPT = textwrap.dedent('''
    import os, struct, sys, time
    from Xlib import X, display
    from hearth import overlay as ov, session
    from hearth.gamescope import Gamescope, appid_for, OPAQUE

    # A "Discord" window from another client, and Discord running in the background.
    other = display.Display()
    dwin = other.screen().root.create_window(0, 0, 300, 200, 0, X.CopyFromParent)
    dwin.set_wm_class("discord", "discord")
    dwin.map()
    other.sync()
    session.update(lambda s: s.update(background={"discord": {"name": "Discord", "pid": os.getpid(),
                                                              "wm_class": "discord", "pointer": True}}))

    gs = Gamescope.connect()
    visual = gs.argb_visual()
    os.environ["SDL_VIDEO_X11_VISUALID"] = hex(visual)
    os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
    import pygame
    from pygame._sdl2 import video
    pygame.display.init(); pygame.font.init(); pygame.joystick.init()
    size = pygame.display.get_desktop_sizes()[0]
    window = video.Window(ov.TITLE, size=size, position=(0, 0), borderless=True, hidden=True)
    renderer = video.Renderer(window)
    xwin = gs.find_window(ov.TITLE)
    gs.make_overlay(xwin)
    window.show()
    from hearth import config as cfg
    o = ov.Overlay(cfg.Config(rows=()), gs, window, renderer, xwin, transparent=True)

    o.housekeeping()
    assert gs.get_cardinal(dwin, "STEAM_GAME") == appid_for("discord"), "discord window not tagged"

    o.events.put("tap")
    for _ in range(40):
        o.handle_events(); o.t = min(1.0, o.t + 0.1); o.draw()
    assert o.open
    assert gs.get_cardinal(xwin, "STEAM_INPUT_FOCUS") == 1
    assert gs.get_cardinal(xwin, "_NET_WM_WINDOW_OPACITY") == OPAQUE
    assert session.read()["overlay_open"]

    w, h = size
    img = xwin.get_image(0, 0, w, h, X.ZPixmap, 0xFFFFFFFF)
    alpha = lambda x, y: struct.unpack_from("<I", img.data, (y * w + x) * 4)[0] >> 24
    panel, backdrop = alpha(w - 200, h // 2), alpha(50, h // 2)
    print("alpha panel", panel, "backdrop", backdrop)
    assert panel > 200, "panel should be nearly opaque"
    assert backdrop < 120, "game should show through on the left"

    o.events.put("tap")
    o.handle_events()
    while o.t > 0:
        o.t = max(0.0, o.t - 0.25); o.draw()
        if o.t == 0: o._hidden()
    assert gs.get_cardinal(xwin, "STEAM_INPUT_FOCUS") == 0
    assert gs.get_cardinal(xwin, "_NET_WM_WINDOW_OPACITY") == 0
    assert not session.read()["overlay_open"]
    print("OK")
''')


def test_overlay_end_to_end(xdisplay, runtime_dir):
    env = {**os.environ, "DISPLAY": xdisplay, "XDG_RUNTIME_DIR": str(runtime_dir),
           "PYTHONPATH": str(Path(__file__).parents[1]), "SDL_AUDIODRIVER": "dummy"}
    env.pop("SDL_VIDEODRIVER", None)
    result = subprocess.run([sys.executable, "-c", OVERLAY_SCRIPT], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_wii_remote_input_reaches_the_app(xdisplay):
    """What a Wii Remote does, as the app underneath sees it: the pointer
    moves there (through the hidden Quick Menu) and keys arrive."""
    from Xlib import X, display

    from hearth.gamescope import Gamescope
    from hearth.wiiinput import XTestSink

    app_conn = display.Display(xdisplay)
    root = app_conn.screen().root
    app = root.create_window(0, 0, 1280, 720, 0, X.CopyFromParent,
                             event_mask=X.KeyPressMask | X.PointerMotionMask)
    app.map()
    app_conn.sync()

    gs = Gamescope.connect(xdisplay)
    menu = gs.d.screen().root.create_window(0, 0, 1280, 720, 0, X.CopyFromParent)
    menu.map()
    gs.d.sync()
    gs.make_overlay(menu)
    gs.set_overlay_visible(menu, False)  # hidden: clicks must go through it

    app.set_input_focus(X.RevertToParent, X.CurrentTime)
    app_conn.sync()
    sink = XTestSink(gs.d)
    sink.move(0.25, 0.5)
    pointer = root.query_pointer()
    assert (pointer.root_x, pointer.root_y) == (319, 359)
    assert pointer.child.id == app.id  # not the Quick Menu's window

    sink.key("Return", True)
    sink.key("Return", False)
    deadline = time.time() + 3
    got = None
    while time.time() < deadline and got is None:
        while app_conn.pending_events():
            e = app_conn.next_event()
            if e.type == X.KeyPress:
                got = app_conn.keycode_to_keysym(e.detail, 0)
        time.sleep(0.05)
    from Xlib import XK

    assert got == XK.string_to_keysym("Return")

    gs.set_overlay_visible(menu, True)  # shown: the menu takes the pointer again
    sink.move(0.5, 0.5)
    assert root.query_pointer().child.id == menu.id
