"""End to end: the real hub and overlay on a real X server (Xvfb), with fake
apps, driven by key presses and hearthctl, checked through the same window
properties gamescope reads. Screenshots are composited the way gamescope
would (the front app, then the overlay with alpha) into $HEARTH_E2E_SHOTS if set.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("Xlib")
pytestmark = pytest.mark.skipif(not shutil.which("Xvfb"), reason="needs Xvfb")

LAUNCHER = Path(__file__).resolve().parents[1]
FAKE_APP = Path(__file__).parent / "e2e" / "fake_app.py"


def wait_for(what, predicate, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            value = predicate()
        except Exception:
            value = None
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


class Harness:
    def __init__(self, tmp: Path) -> None:
        for n in range(110, 130):
            if not Path(f"/tmp/.X11-unix/X{n}").exists():
                break
        self.display = f":{n}"
        self.xvfb = subprocess.Popen(["Xvfb", self.display, "-screen", "0", "1280x720x24", "+extension", "COMPOSITE"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for("Xvfb", lambda: Path(f"/tmp/.X11-unix/X{n}").exists())
        self.tmp = tmp
        (tmp / "run").mkdir(exist_ok=True)  # the autouse runtime_dir fixture may have made it
        py = sys.executable
        (tmp / "apps.toml").write_text(f'''
title = "Hearth"
[[rows]]
title = "Play"
  [[rows.apps]]
  id = "game"
  name = "Fake Game"
  command = ["{py}", "{FAKE_APP}", "Fake Game", "fakegame"]
  color = "#8a3ffc"
  [[rows.apps]]
  id = "discord"
  name = "Discord"
  command = ["{py}", "{FAKE_APP}", "Discord", "discord"]
  background = true
  pointer = true
  wm_class = "discord"
  color = "#5865f2"
[[rows]]
title = "System"
  [[rows.apps]]
  id = "settings"
  name = "Settings"
  command = "hearth:settings"
  [[rows.apps]]
  id = "poweroff"
  name = "Power Off"
  command = "true"
  confirm = true
''')
        self.env = {**os.environ, "DISPLAY": self.display, "GAMESCOPE_WAYLAND_DISPLAY": "gamescope-0",
                    "XDG_RUNTIME_DIR": str(tmp / "run"), "HOME": str(tmp), "XDG_CONFIG_HOME": str(tmp / "cfg"),
                    "XDG_STATE_HOME": str(tmp / "state"), "PYTHONPATH": str(LAUNCHER),
                    "SDL_AUDIODRIVER": "dummy", "PYGAME_HIDE_SUPPORT_PROMPT": "1"}
        self.env.pop("SDL_VIDEODRIVER", None)
        self.hub = subprocess.Popen([sys.executable, "-m", "hearth", "--config", str(tmp / "apps.toml")],
                                    env=self.env, start_new_session=True,
                                    stdout=open(tmp / "hub.out", "w"), stderr=subprocess.STDOUT)
        os.environ["DISPLAY"] = self.display
        from hearth.gamescope import Gamescope

        self.gs = Gamescope.connect(self.display)

    def close(self) -> None:
        try:
            os.killpg(self.hub.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        subprocess.run(["pkill", "-f", str(FAKE_APP)])
        subprocess.run(["pkill", "-f", f"XDG_RUNTIME_DIR={self.tmp}"], capture_output=True)
        self.xvfb.terminate()

    def state(self) -> dict:
        return json.loads((self.tmp / "run/hearth/state.json").read_text())

    def ctl(self, *args: str) -> None:
        subprocess.run([sys.executable, "-m", "hearth.ctl", *args], env=self.env, check=True)

    def window(self, title: str):
        return self.gs.find_window(title)

    def tagged(self, title: str, appid: int):
        """The window with this title carrying this app ID. (SDL may replace a
        window when it goes full screen, so match on the tag, not just the title.)"""
        return next((w for w in self.gs.top_level_windows()
                     if self.gs.window_title(w) == title and self.gs.get_cardinal(w, "STEAM_GAME") == appid), None)

    def front_appid(self):
        return self.gs.get_cardinal(self.gs.root, "GAMESCOPECTRL_BASELAYER_APPID")

    def press(self, win, *keys: str) -> None:
        from Xlib import X, XK
        from Xlib.ext import xtest

        d = self.gs.d
        for key in keys:
            d.set_input_focus(win, X.RevertToParent, X.CurrentTime)
            d.sync()
            code = d.keysym_to_keycode(XK.string_to_keysym(key))
            xtest.fake_input(d, X.KeyPress, code)
            xtest.fake_input(d, X.KeyRelease, code)
            d.sync()
            time.sleep(0.25)

    def screenshot(self, name: str) -> None:
        """Composite like gamescope: the front app, then the overlay on top."""
        out = os.environ.get("HEARTH_E2E_SHOTS")
        if not out:
            return
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame
        from Xlib import X

        pygame.display.init()
        appid = self.front_appid()
        frame = pygame.Surface((1280, 720))
        overlay = None
        for win in self.gs.top_level_windows():
            if win.get_attributes().map_state != X.IsViewable:
                continue
            geo = win.get_geometry()
            if geo.width < 1280:
                continue
            img = win.get_image(0, 0, geo.width, geo.height, X.ZPixmap, 0xFFFFFFFF)
            surf = pygame.image.frombuffer(img.data, (geo.width, geo.height), "BGRA").copy()
            if self.gs.get_cardinal(win, "STEAM_OVERLAY"):
                if self.gs.get_cardinal(win, "_NET_WM_WINDOW_OPACITY"):
                    overlay = surf  # 32-bit, premultiplied alpha
            elif appid and self.gs.get_cardinal(win, "STEAM_GAME") == appid:
                # 24-bit windows leave the alpha byte empty: make them opaque.
                surf.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MAX)
                frame.blit(surf, (0, 0))
        if overlay is not None:
            frame.blit(overlay, (0, 0), special_flags=pygame.BLEND_PREMULTIPLIED)
        Path(out).mkdir(parents=True, exist_ok=True)
        pygame.image.save(frame, f"{out}/{name}.png")


@pytest.fixture
def harness(tmp_path):
    h = Harness(tmp_path)
    try:
        yield h
    except Exception:
        raise
    finally:
        for log in (tmp_path / "state/hearth/hearth.log", tmp_path / "hub.out"):
            if log.exists():
                print(f"--- {log.name} ---\n{log.read_text()[-4000:]}")
        h.close()


def test_full_session(harness):
    from hearth.gamescope import HOME_APPID, appid_for

    h = harness
    # 1. Boot: the home screen is tagged and in front, the overlay is ready.
    # The first start on a fresh CI runner is slow (pygame and fonts load cold).
    home = wait_for("home screen window, tagged", lambda: h.tagged("Hearth", HOME_APPID), timeout=30.0)
    wait_for("home in front", lambda: h.front_appid() == HOME_APPID)
    menu_win = wait_for("overlay window", lambda: h.window("Hearth Quick Menu"))
    assert h.gs.get_cardinal(menu_win, "STEAM_OVERLAY") == 1
    time.sleep(0.5)
    h.screenshot("1-home")

    # 2. Launch the game from its tile.
    h.press(home, "Return")
    wait_for("game window, tagged", lambda: h.tagged("Fake Game", appid_for("game")))
    assert h.front_appid() == appid_for("game")
    assert h.state()["foreground"]["id"] == "game"
    h.screenshot("2-game")

    # 3. Quick Menu over the game (hearthctl stands in for a Guide tap).
    h.ctl("menu")
    wait_for("menu open", lambda: h.state()["overlay_open"])
    wait_for("menu has input", lambda: h.gs.get_cardinal(menu_win, "STEAM_INPUT_FOCUS") == 1)
    time.sleep(0.6)
    h.screenshot("3-quick-menu")

    # 4. Discord tab → Start Discord: it runs in the background and comes to the front.
    h.press(menu_win, "e", "e")
    h.screenshot("4-discord-tab")
    h.press(menu_win, "Return")
    wait_for("menu closed", lambda: not h.state()["overlay_open"])
    wait_for("discord window, tagged", lambda: h.tagged("Discord", appid_for("discord")))
    wait_for("discord in front", lambda: h.front_appid() == appid_for("discord"))
    assert h.state()["foreground"]["id"] == "game"  # the game keeps running
    h.screenshot("5-discord")

    # 5. Back to the game from the menu.
    h.ctl("menu")
    wait_for("menu open", lambda: h.state()["overlay_open"])
    time.sleep(0.3)
    # The menu remembers its last tab (Discord); its first entry is "Back to Fake Game".
    h.screenshot("5b-back-to-game")
    h.press(menu_win, "Return")
    wait_for("game in front again", lambda: h.front_appid() == appid_for("game"))

    # 6. Go home: the game closes, Discord stays in the background.
    h.ctl("home")
    wait_for("game closed", lambda: h.state()["foreground"] is None)
    wait_for("home in front", lambda: h.front_appid() == HOME_APPID)
    assert "discord" in h.state()["background"]
    home = wait_for("home screen back", lambda: h.tagged("Hearth", HOME_APPID))
    time.sleep(0.5)
    h.screenshot("6-home-again")

    # 7. The Discord tile brings the running Discord forward (no second copy).
    h.press(home, "Right", "Return")
    wait_for("discord in front", lambda: h.front_appid() == appid_for("discord"))
    time.sleep(0.5)
    assert len([w for w in h.gs.top_level_windows() if h.gs.window_title(w) == "Discord"]) == 1

    # 8. The event timeline recorded the session, for `hearthctl report`.
    timeline = [json.loads(line) for line in (h.tmp / "state/hearth/events.jsonl").read_text().splitlines()]
    kinds = [(e["by"], e["event"], e.get("id")) for e in timeline]
    for expected in [("hub", "session_start", None), ("hub", "app_start", "game"),
                     ("overlay", "app_window", "game"), ("overlay", "menu_open", None),
                     ("overlay", "menu_close", None), ("hub", "app_exit", "game"),
                     (None, "background_start", "discord")]:
        assert any(expected[0] in (None, k[0]) and k[1] == expected[1] and (expected[2] is None or k[2] == expected[2]) for k in kinds), expected
    exit_event = next(e for e in timeline if e["event"] == "app_exit")
    assert exit_event["ended"] == "exited" and exit_event["seconds"] > 0

    # 9. Settings: change the livery with the remote; it's saved, and the
    #    Quick Menu picks it up without a restart.
    h.ctl("home")
    wait_for("home in front", lambda: h.front_appid() == HOME_APPID)
    home = wait_for("home screen", lambda: h.tagged("Hearth", HOME_APPID))
    time.sleep(0.4)
    h.press(home, "Tab", "Return")  # Menu jumps to the System row; Settings is first
    time.sleep(0.8)
    h.screenshot("9-settings")
    h.press(home, "Return", "Right")  # into Appearance; next livery
    saved = h.tmp / "cfg/hearth/settings.json"
    wait_for("livery saved", lambda: json.loads(saved.read_text())["theme"]["livery"] == "martini")
    h.screenshot("9-settings-martini")
    h.press(home, "Escape", "Escape")  # out of the category, out of Settings
    wait_for("overlay reloaded settings",
             lambda: "settings changed; reloaded" in (h.tmp / "state/hearth/hearth.log").read_text())
    assert h.front_appid() == HOME_APPID



def test_quick_resume(harness):
    from hearth.gamescope import HOME_APPID, appid_for

    h = harness
    home = wait_for("home screen", lambda: h.tagged("Hearth", HOME_APPID))
    wait_for("overlay window", lambda: h.window("Hearth Quick Menu"))
    time.sleep(0.5)
    h.press(home, "Return")
    wait_for("game in front", lambda: h.front_appid() == appid_for("game"))
    pid = h.state()["foreground"]["pid"]

    # Pause it (a held Guide button, or the Quick Menu's "Home, keep … paused").
    h.ctl("pause")
    wait_for("game paused", lambda: [e["id"] for e in h.state()["suspended"]] == ["game"])
    wait_for("home in front", lambda: h.front_appid() == HOME_APPID)
    assert h.state()["foreground"] is None
    assert Path(f"/proc/{pid}/stat").read_text().split()[2] == "T"  # stopped, still there
    home = wait_for("home screen back", lambda: h.tagged("Hearth", HOME_APPID))
    time.sleep(1.2)
    h.screenshot("qr-1-home-with-quick-resume")

    # The Quick Resume row is on top: pick the game there and it carries on.
    h.press(home, "Up", "Return")
    wait_for("game in front again", lambda: h.front_appid() == appid_for("game"))
    assert h.state()["suspended"] == [] and h.state()["foreground"]["pid"] == pid
    assert Path(f"/proc/{pid}/stat").read_text().split()[2] != "T"

    kinds = [json.loads(line) for line in (h.tmp / "state/hearth/events.jsonl").read_text().splitlines()]
    assert [e["action"] for e in kinds if e["event"] == "quick_resume"] == ["paused", "resumed"]
