"""The Quick Menu overlay: a long-running companion to the hub.

- Tap Guide (or a remote's Menu key) anywhere: the Quick Menu slides in over
  the current app, which is paused while it's open (configurable).
- Hold Guide while a background app (Discord) is in front: back to the game.
- Tags new windows with their app's ID so gamescope will show them.
- While a background app with `pointer = true` is in front, the controller
  drives a mouse pointer.
- Wii Remotes on a DolphinBar work as a remote and a pointer (wiiinput.py).

Started by the hub (`python -m hearth.overlay`); safe to restart any time.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from . import config as cfg
from . import input as input_
from . import events, homebutton, logs, session, settings, style, updates
from .audio import Audio, Snapshot, reset_restored_discord_mutes
from .gamescope import Gamescope, appid_for

log = logging.getLogger("hearth")

TITLE = "Hearth Quick Menu"
ANIM_SECONDS = 0.3
REFRESH_SECONDS = 1.5
# After a change, re-read audio state this soon (not instantly: holding a
# direction on a slider would otherwise run pactl every repeat).
AFTER_CHANGE_SECONDS = 0.35
HOUSEKEEPING_SECONDS = 0.5
UPDATE_CHECK_SECONDS = 30 * 60
# Without real transparency, the whole overlay is drawn at this opacity.
FALLBACK_OPACITY = 0.93


class Actions:
    """What Quick Menu entries do. Each returns "close" to close the menu."""

    def __init__(self, overlay: "Overlay") -> None:
        self.o = overlay

    def resume(self):
        return "close"

    def go_home(self):
        state = session.read()
        if state["foreground"]:
            self.o.thaw()
            session.stop_entry(state["foreground"])
        elif state["focus"] != "home":  # e.g. Discord in front of the home screen
            self.show("home")
        return "close"

    def quit_game(self):
        """Close the game running inside ES-DE; ES-DE stays, on its list."""
        game = session.frontend_game(session.read()["foreground"])
        if game:
            self.o.thaw()  # a paused game can't hear the request to quit
            events.record("quit_game", frontend=game[0], processes=len(game[1]))
            threading.Thread(target=session.quit_game, args=(game[1],), daemon=True).start()
        return "close"

    def quick_resume(self):
        """Go home and keep the game paused; the hub pauses it (and keeps it
        paused, so don't thaw it when the menu closes)."""
        if (session.read()["foreground"] or {}).get("resumable"):
            self.o.paused_unit = None
            session.update(lambda s: s.__setitem__("suspend_request", True))
            return "close"
        return self.go_home()

    def start_background(self, app_id):
        app = self.o.config.app(app_id)
        if app is None:
            return None
        session.start_background(app)
        return self.show(app_id)

    def show(self, target):
        state = session.update(lambda s: s.__setitem__("focus", target))
        self.o.apply_focus(state)
        return "close"

    def stop_background(self, app_id):
        def change(s):
            info = s["background"].pop(app_id, None)
            if info:
                session.stop_entry(info)
            if s["focus"] == app_id:
                s["focus"] = "foreground" if s["foreground"] else "home"

        self.o.apply_focus(session.update(change))
        self.o.refresh(force=True)
        return None

    def power(self, action):
        events.record("power", action=action)
        self.o.thaw()
        subprocess.Popen(["systemctl", action])
        return "close"

    def update(self):
        if (session.read().get("update") or {}).get("status") != "running":
            session.update(lambda s: s.__setitem__("update", {"status": "running"}))
            threading.Thread(target=self.o.run_update, daemon=True).start()
        self.o.refresh(force=True)
        return None  # stay open to show progress

    def set_wii_mouse(self, on: bool):
        key = focus_key(session.read())
        session.update(lambda s: s.setdefault("wii_mouse", {}).__setitem__(key, bool(on)))
        self.o.state = session.read()
        return None

    def report(self):
        if (session.read().get("report") or {}).get("status") != "running":
            session.update(lambda s: s.__setitem__("report", {"status": "running"}))
            threading.Thread(target=self.o.run_report, daemon=True).start()
        self.o.refresh(force=True)
        return None  # stay open to show progress


def focus_key(state: dict) -> str:
    """The app in front: "home", a background app's id, or the foreground app's id."""
    if state["focus"] == "foreground":
        return (state["foreground"] or {}).get("id") or "home"
    return state["focus"]


class Overlay:
    def __init__(self, config: cfg.Config, gs: Gamescope | None, window, renderer, xwin, transparent: bool,
                 config_path: Path | None = None) -> None:
        import pygame

        from .input import InputMapper
        from .pointer import Pointer, make_uinput
        from .quickmenu import QuickMenu
        from .quickmenu_view import QuickMenuView

        self.pg = pygame
        self.config = config
        self.config_path = config_path
        self.gs, self.window, self.renderer, self.xwin = gs, window, renderer, xwin
        self.transparent = transparent
        self.audio = Audio()
        self.actions = Actions(self)
        self.menu = QuickMenu([])
        self.mapper = InputMapper()
        self.mapper.open_devices()
        self.pointer = Pointer(make_uinput())
        self.pointer_active = False

        size = window.size
        # Draw at up to 1080p and let the GPU scale: keeps 4K fast.
        scale = min(1.0, 1080 / size[1])
        self.size = size
        self.render_size = (int(size[0] * scale), int(size[1] * scale))
        self.surface = pygame.Surface(self.render_size, pygame.SRCALPHA)
        self.view = QuickMenuView(self.render_size, config.livery, config.motion, config.clock)

        self.open = False
        self.t = 0.0
        self.paused_unit: str | None = None
        self.opened_for: str | None = None
        self.state = session.read()
        self._refreshed = 0.0
        self._housekept = 0.0
        self._seen: set[int] = set()
        self._first_window: set[tuple] = set()  # launches whose first window we've timed
        self._opened_at = 0.0
        self.frames = events.FrameStats()
        self._tries: dict[int, int] = {}
        self._liveness_ticks = 0
        self._audio_error: str | None = None
        self._discord_streams_seen: set[int] = set()

        self._update_checked = 0.0
        self.events: queue.Queue[str] = queue.Queue()
        homebutton.Watcher(lambda: self.events.put("tap"), homebutton.GuideTap, repeat=True).start()
        homebutton.Watcher(lambda: self.events.put("hold"), homebutton.HomeButton, repeat=True,
                           hold_seconds=config.guide_hold).start()
        self.wii = None
        self._settings_mtime = settings.mtime()
        self._wii_status: dict | None = None
        self._raw_written = 0.0
        self.apply_config()

    def apply_config(self) -> None:
        """Use the current settings: look, Wii Remote aim, mouse speed."""
        c = self.config
        self.view.set_theme(c.livery, c.motion, c.clock)
        style.set_prompts(c.prompts, c.confirm)
        self.mapper.swap_confirm = c.confirm == "east"
        self.pointer.speed = c.mouse_speed / 100
        self.pointer.deadzone = c.stick_deadzone / 100
        input_.set_deadzone(c.stick_deadzone)
        if c.wii_remote and self.wii is None:
            from .wiiinput import WiiInput, XTestSink

            self.wii = WiiInput(XTestSink(self.gs.d) if self.gs else None, on_tap=lambda: self.events.put("tap"),
                                on_hold=lambda: self.events.put("wii_hold"))
        elif not c.wii_remote and self.wii is not None:
            self.wii.close()  # let go of the remotes entirely
            self.wii = None
            self._wii_status = None
            session.update(lambda s: s.__setitem__("wii", None))
        if self.wii:
            self.wii.configure(c)

    # -- state -----------------------------------------------------------------

    def title(self) -> str:
        s = self.state
        if s["focus"] in s["background"]:
            return s["background"][s["focus"]]["name"]
        return (s["foreground"] or {}).get("name") or "Home"

    def apply_focus(self, state: dict) -> None:
        self.state = state
        if self.gs:
            self.gs.show_app(session.focus_order(state))

    def refresh(self, force: bool = False) -> None:
        from .quickmenu import Context, build_tabs

        now = time.monotonic()
        if not force and now - self._refreshed < REFRESH_SECONDS:
            return
        self._refreshed = now
        self.state = session.read()
        try:
            snapshot = self.audio.snapshot()
            self._audio_error = None
        except (OSError, RuntimeError, ValueError) as e:
            if str(e) != self._audio_error:  # log once, not every refresh
                log.warning("audio unavailable: %s", e)
                self._audio_error = str(e)
            snapshot = Snapshot()
        discord = self.config.app("discord")
        wii = {"mouse": self.wii_mouse(), "app": self.title()} if self.wii and self.wii.active else None
        game = session.frontend_game(self.state.get("foreground"))
        ctx = Context(self.audio, snapshot, self.state, self.actions,
                      discord_available=bool(discord and discord.available()), wii=wii,
                      frontend=game[0] if game else None)
        self.menu.set_tabs(build_tabs(ctx))

    # -- updates ---------------------------------------------------------------

    def run_update(self) -> None:
        log.info("update: starting")
        ok = updates.run_helper("apply", logs.log_path())
        updates.update_esde()
        self.check_staged(failed=not ok)
        events.record("update", ok=ok, result=(session.read().get("update") or {}).get("status"))

    def run_report(self) -> None:
        from . import report

        try:
            path = report.make(with_screenshot=True)
            log.info("report saved: %s", path)
            result = {"status": "done", "file": path.name}
        except Exception:
            log.exception("report failed")
            result = {"status": "failed"}
        session.update(lambda s: s.__setitem__("report", result))
        self._refreshed = 0.0  # show the result next frame

    def check_staged(self, failed: bool = False) -> None:
        """Record whether an update is downloaded and waiting for a restart
        (ours, or one Bazzite's automatic updater fetched in the background)."""
        status = updates.os_status()
        if status.update_ready:
            result = {"status": "ready", "version": status.staged}
        elif failed:
            result = {"status": "failed"}
        else:
            result = {"status": "current"}
        log.info("update: %s", result)
        session.update(lambda s: s.__setitem__("update", result))

    # -- pause -----------------------------------------------------------------

    def freeze(self) -> None:
        fg = self.state["foreground"]
        if (self.config.pause_game and fg and fg.get("unit") and fg.get("home_button", True)
                and self.state["focus"] == "foreground" and session.freeze(fg["unit"])):
            self.paused_unit = fg["unit"]

    def thaw(self) -> None:
        if self.paused_unit:
            session.thaw(self.paused_unit)
            self.paused_unit = None

    # -- open/close ------------------------------------------------------------

    def open_menu(self) -> None:
        self.config = load_config(self.config_path, self.config)
        self.apply_config()
        self.state = session.read()
        fg = self.state["foreground"]
        if fg and not fg.get("home_button", True) and self.state["focus"] == "foreground":
            return  # Steam: the Guide button opens Steam's own menu
        self.refresh(force=True)
        self.freeze()
        session.update(lambda s: s.update(overlay_open=True, paused=bool(self.paused_unit)))
        self.opened_for = (fg or {}).get("id")
        self.open = True
        self._opened_at = time.monotonic()
        self.frames = events.FrameStats()
        events.record("menu_open", over=self.opened_for or self.state["focus"], paused=bool(self.paused_unit))
        self.pointer.reset()
        if self.gs and self.xwin:
            self.gs.set_overlay_visible(self.xwin, True, 1.0 if self.transparent else FALLBACK_OPACITY)

    def close_menu(self) -> None:
        self.open = False  # the slide-out animation finishes in run()

    def _hidden(self) -> None:
        events.record("menu_close", seconds=round(time.monotonic() - self._opened_at, 1),
                      **(self.frames.summary() or {}))
        if self.gs and self.xwin:
            self.gs.set_overlay_visible(self.xwin, False)
        self.thaw()
        session.update(lambda s: s.update(overlay_open=False, paused=False))

    # -- background work -------------------------------------------------------

    def housekeeping(self) -> None:
        now = time.monotonic()
        if now - self._housekept < HOUSEKEEPING_SECONDS:
            return
        self._housekept = now
        if settings.mtime() != self._settings_mtime:
            # Changed in the Settings app: use it straight away.
            self._settings_mtime = settings.mtime()
            self.config = load_config(self.config_path, self.config)
            self.apply_config()
            log.info("settings changed; reloaded")
        requests: list[str] = []
        self.state = session.read()
        if self.state["requests"]:
            self.state = session.update(lambda s: (requests.extend(s["requests"]), s.__setitem__("requests", [])))
        for request in requests:
            log.info("request: %s", request)
            if request == "menu":
                self.events.put("tap")
            elif request == "home":
                self.actions.go_home()
                self.close_menu()
            elif request == "pause":
                self.actions.quick_resume()
                self.close_menu()

        self._liveness_ticks = (self._liveness_ticks + 1) % 6  # every ~3 s: it runs systemctl
        dead = [] if self._liveness_ticks else [
            k for k, info in self.state["background"].items() if not session.background_alive(info)]
        if dead:
            def drop(s):
                for k in dead:
                    s["background"].pop(k, None)
                if s["focus"] in dead:
                    s["focus"] = "foreground" if s["foreground"] else "home"

            self.apply_focus(session.update(drop))

        if "discord" in self.state["background"] and not self._liveness_ticks:
            try:
                for s in reset_restored_discord_mutes(self.audio, self.audio.snapshot(), self._discord_streams_seen):
                    log.info("cleared a mute PipeWire restored on Discord's %s stream", s.app)
            except (OSError, RuntimeError, ValueError):
                pass

        # The app closed under the open menu (e.g. held Guide): close the menu.
        if self.open and (self.state["foreground"] or {}).get("id") != self.opened_for:
            self.paused_unit = None
            self.close_menu()

        # Look for a downloaded update now and then (it's slow: in a thread).
        if now - self._update_checked > UPDATE_CHECK_SECONDS and \
                (self.state.get("update") or {}).get("status") != "running":
            self._update_checked = now
            threading.Thread(target=self.check_staged, daemon=True).start()

        focus = self.state["focus"]
        self.pointer_active = (not self.open and focus in self.state["background"]
                               and self.state["background"][focus].get("pointer", False))
        if not self.pointer_active:
            self.pointer.reset()
        self.tag_windows()

    def tag_windows(self) -> None:
        if not self.gs:
            return
        from Xlib import X
        from Xlib.error import XError

        present = set()
        for win in self.gs.top_level_windows():
            present.add(win.id)
            if win.id in self._seen or (self.xwin and win.id == self.xwin.id):
                continue
            try:
                if win.get_attributes().map_state != X.IsViewable:
                    continue
                if self.gs.is_tagged(win):
                    self._seen.add(win.id)
                    continue
                appid = self.owner_appid(win)
            except XError:
                continue
            if appid is None:
                # Not ours (yet): check again a few times, then leave it alone.
                self._tries[win.id] = self._tries.get(win.id, 0) + 1
                if self._tries[win.id] > 20:
                    self._seen.add(win.id)
                continue
            self.gs.tag(win, appid)
            self._seen.add(win.id)
            self._time_first_window(appid)
        self._seen &= present
        self._tries = {k: v for k, v in self._tries.items() if k in present}

    def _time_first_window(self, appid: int) -> None:
        """How long the app in front took to show its first window."""
        fg = self.state["foreground"]
        if not fg or appid != appid_for(fg["id"]) or not fg.get("started"):
            return
        key = (fg["id"], fg["started"])
        if key not in self._first_window:
            self._first_window.add(key)
            events.record("app_window", id=fg["id"], seconds=round(time.time() - fg["started"], 1))

    def owner_appid(self, win) -> int | None:
        state = self.state
        pid = self.gs.client_pid(win)
        owner = session.app_for_pid(pid) if pid else None
        fg = state["foreground"]
        if owner:
            kind, app_id = owner
            if kind == "app" and fg and fg["id"] == app_id and not fg.get("tag_windows", True):
                self._seen.add(win.id)  # Steam tags its own windows
                return None
            return appid_for(app_id)
        wm_class = [c.lower() for c in (self.gs.wm_class(win) or ())]
        for app_id, info in state["background"].items():
            if info.get("wm_class") and info["wm_class"].lower() in wm_class:
                return appid_for(app_id)
        if fg and fg.get("tag_windows", True):
            return appid_for(fg["id"])
        return None

    # -- main loop -------------------------------------------------------------

    def handle_events(self) -> None:
        from .model import Nav

        while not self.events.empty():
            kind = self.events.get()
            if kind == "tap":
                self.close_menu() if self.open else self.open_menu()
            elif kind == "hold" and not self.open:
                self.back_from_background()
            elif kind == "wii_hold":
                # Holding Home on a Wii Remote: like holding Guide, from anywhere.
                if self.open:
                    self.close_menu()
                if not self.back_from_background():
                    if self.config.guide_hold_action == "resume":
                        self.actions.quick_resume()
                    else:
                        self.actions.go_home()

        now = self.pg.time.get_ticks()
        navs = []
        for event in self.pg.event.get():
            if event.type == self.pg.CONTROLLERBUTTONDOWN and event.button == self.pg.CONTROLLER_BUTTON_GUIDE:
                continue  # Guide taps arrive via the watcher; don't also handle them here
            nav = self.mapper.translate(event, now)
            if self.open and nav is not None:
                navs.append(nav)
            elif self.pointer_active:
                self.pointer.handle(event)
        if self.open:
            repeat = self.mapper.repeat(now)
            if repeat is not None:
                navs.append(repeat)
        if self.wii:
            navs += self.wii.poll(self.open, pointing=self.state["focus"] == "home", mouse=self.wii_mouse())
            self.publish_wii()
        for nav in navs:
            log.debug("menu input: %s on %s", nav.name, getattr(self.menu.selected, "key", None))
            if nav is Nav.MENU:  # Start closes the menu, like B
                nav = Nav.BACK
            if self.menu.handle(nav) == "close":
                self.close_menu()
                break
            self._refreshed = min(self._refreshed, time.monotonic() - REFRESH_SECONDS + AFTER_CHANGE_SECONDS)

    def publish_wii(self) -> None:
        """Tell the Settings app which remotes are connected, and while it's
        calibrating, where the remote is aiming."""
        status = {"connected": self.wii.connected, "dolphin": self.wii.released}
        if status != self._wii_status:
            self._wii_status = status
            session.update(lambda s: s.__setitem__("wii", status))
        now = time.monotonic()
        if self.state.get("wii_raw") and now - self._raw_written >= 0.05:
            self._raw_written = now
            raw = self.wii.raw
            try:
                session.aim_path().write_text(json.dumps({"raw": raw, "t": time.time()}))
            except OSError:
                pass

    def back_from_background(self) -> bool:
        """With a background app (Discord) in front, go back to what was
        behind it. Returns False if there's no background app in front."""
        state = session.read()
        if state["focus"] not in state["background"]:
            return False
        back = "foreground" if state["foreground"] else "home"
        self.apply_focus(session.update(lambda s: s.__setitem__("focus", back)))
        return True

    def wii_mouse(self) -> bool:
        """Whether the Wii Remote pointer drives the mouse for the app in front."""
        state = self.state
        key = focus_key(state)
        override = state.get("wii_mouse", {}).get(key)
        if override is not None:
            return bool(override)
        if key == "home" or self.config.wii_mouse == "never":
            return False
        if self.config.wii_mouse == "always":
            return True
        if key in state["background"]:
            return bool(state["background"][key].get("pointer"))
        app = self.config.app(key)
        return bool(app and app.pointer)

    def draw(self) -> None:
        r = self.renderer
        if self.open:
            self.refresh()
        paused = bool(self.paused_unit)
        if not self.transparent:
            # No per-pixel alpha: the whole window is semi-opaque instead.
            self.surface.fill((0, 0, 0, 255))
        self.view.draw(self.surface, self.menu, self.title(), paused, self.t)
        try:
            frame = self.surface.premul_alpha()
        except AttributeError:  # older pygame
            frame = self.surface
        from pygame._sdl2 import video

        tex = video.Texture.from_surface(r, frame)
        tex.blend_mode = 0  # copy pixels (already premultiplied) as they are
        r.draw_color = (0, 0, 0, 0)
        r.clear()
        tex.draw(dstrect=(0, 0, *self.size))
        r.present()
        self.frames.tick()

    def run(self) -> None:
        clock = self.pg.time.Clock()
        failures: list[float] = []
        while True:
            try:
                self.step(clock)
            except Exception:
                # Keep the overlay alive through unexpected errors (a flaky
                # pactl, an X error); give up only if it keeps failing.
                log.exception("overlay error")
                now = time.monotonic()
                failures = [t for t in failures if now - t < 60] + [now]
                if len(failures) > 10:
                    raise
                time.sleep(0.5)

    def step(self, clock) -> None:
        self.handle_events()
        self.housekeeping()
        target = 1.0 if self.open else 0.0
        if self.t != target or self.open:
            step = clock.get_time() / 1000 / ANIM_SECONDS
            self.t = min(target, self.t + step) if target > self.t else max(target, self.t - step)
            self.draw()
            if self.t == 0.0 and not self.open:
                self._hidden()
            clock.tick(60)
        elif self.pointer_active:
            self.pointer.tick(clock.get_time() / 1000)
            clock.tick(120)
        elif self.wii and self.wii.active:
            clock.tick(100)  # the pointer follows the remote smoothly
        else:
            clock.tick(20)


def load_config(path: Path | None, fallback: cfg.Config | None = None) -> cfg.Config:
    try:
        return cfg.load(path)
    except (OSError, cfg.ConfigError) as e:
        log.error("config: %s", e)
        return fallback or cfg.Config(rows=())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hearth-overlay", description="Hearth Quick Menu overlay")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    logs.setup("overlay")

    gs = Gamescope.connect()
    visual = gs.argb_visual() if gs else None
    if visual:
        os.environ["SDL_VIDEO_X11_VISUALID"] = hex(visual)
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")
    # Controller input keeps flowing while another app has focus (pointer
    # mode); while the menu is open, gamescope gives this window the focus.
    os.environ["SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"] = "1"
    os.environ.setdefault("SDL_RENDER_SCALE_QUALITY", "1")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

    import pygame
    from pygame._sdl2 import video

    pygame.display.init()
    pygame.font.init()
    pygame.joystick.init()
    size = pygame.display.get_desktop_sizes()[0]
    window = video.Window(TITLE, size=size, position=(0, 0), borderless=True, hidden=True)
    renderer = video.Renderer(window)
    xwin = gs.find_window(TITLE) if gs else None
    if not (gs and xwin):
        # Without gamescope's X11 there's no way to draw over apps; don't
        # leave a stray window on the screen. Exit 0 so the hub doesn't
        # restart us.
        log.warning("not running under gamescope/X11: Quick Menu disabled")
        return 0
    gs.make_overlay(xwin)
    window.show()

    # Starting fresh: nothing is open, whatever a previous run left behind.
    session.update(lambda s: s.update(overlay_open=False, paused=False))
    overlay = Overlay(load_config(args.config), gs, window, renderer, xwin,
                      transparent=visual is not None, config_path=args.config)
    try:
        overlay.run()
    finally:
        overlay.thaw()
        # Don't leave the home screen ignoring the controller.
        session.update(lambda s: s.update(overlay_open=False, paused=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
