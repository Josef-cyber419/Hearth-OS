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
from . import cast, events, homebutton, logs, session, settings, style, updates
from .audio import Audio, Snapshot, reset_restored_discord_mutes
from . import family
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
NOTICE_CHECK_SECONDS = 20.0  # batteries, new installs, updates
MOUSE_POINTER_SECONDS = 3.0  # the drawn pointer fades after the mouse rests this long


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
            # Stopping waits for the app (a few seconds for Kodi, Heroic,
            # Dolphin): in the background, so the menu closes at once (#65).
            threading.Thread(target=session.stop_entry, args=(state["foreground"],), daemon=True,
                             name="close-app").start()
        elif state["focus"] != "home":  # e.g. Discord in front of the home screen
            self.show("home")
        elif state.get("screen"):  # Settings: the hub closes it
            session.update(lambda s: s.__setitem__("close_screen", True))
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

    def switch_person(self):
        """Back to "Who's playing?": the hub closes what's in front and asks."""
        self.o.thaw()  # a paused game can't exit
        session.update(lambda s: s.__setitem__("switch_request", True))
        events.record("switch_person_asked")
        return "close"

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
                events.record("background_stop", id=app_id)
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

    def media(self, bus: str, action: str):
        """Play/pause/skip what's playing; the menu stays open to show it."""
        self.o.media.control(bus, action)  # on the media thread; the menu updates when it's done
        events.record("media", action=action)
        return None

    def set_wii_mouse(self, on: bool):
        """Remembered per app, across restarts."""
        key = focus_key(session.read())
        data = settings.load()
        data.setdefault("wii_mouse_apps", {})[key] = bool(on)
        settings.save(data)
        self.o._wii_mouse_apps = dict(data["wii_mouse_apps"])
        return None

    def screenshot(self):
        """Close the menu, then capture what's under it and say so."""
        title = self.o.title()
        threading.Thread(target=self.o.take_screenshot, args=(title,), daemon=True).start()
        return "close"

    def stop_cast(self):
        """Drop the phone that's casting: the receiver restarts (off the UI
        thread: stopping it waits for it to exit), and the screen goes back."""
        state = session.read()
        info = state.get("cast") or {}
        app_id = info.get("id") or (state["focus"] if cast.is_receiver(state["focus"]) else None)
        if not app_id:
            return "close"
        self.o.cast_watch.windows = {w: a for w, a in self.o.cast_watch.windows.items() if a != app_id}
        self.o.apply_focus(session.update(lambda s: cast.give_back(s, app_id)))
        events.record("cast_stop", id=app_id)
        config = self.o.config

        def work() -> None:
            try:
                cast.restart(app_id, config)
            except Exception:
                log.exception("stop casting")
            self.o.apply_focus(session.read())

        threading.Thread(target=work, daemon=True, name="stop-cast").start()
        return "close"

    def report(self):
        if (session.read().get("report") or {}).get("status") != "running":
            session.update(lambda s: s.__setitem__("report", {"status": "running"}))
            threading.Thread(target=self.o.run_report, daemon=True).start()
        self.o.refresh(force=True)
        return None  # stay open to show progress


def pointer_app_in_front(state: dict) -> bool:
    """Is the app in front one the controller drives as a mouse (pointer =
    true: Discord, the streaming websites)?"""
    focus = state["focus"]
    if focus in state["background"]:
        return bool(state["background"][focus].get("pointer", False))
    if focus == "foreground":
        return bool((state["foreground"] or {}).get("pointer", False))
    return False


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
        from .toasts import Notices

        self.notices = Notices()
        self.family = family.Watcher()  # household limits (Settings > Family)
        self._toast_showing = False
        self._noticed = -1e9
        from .perf import Monitor

        self.perf = Monitor()
        from .media import Watcher

        self.media = Watcher()
        self._perf_reading = None
        self._mouse_at: tuple[int, int] | None = None
        self._mouse_moved = -1e9
        # Hearth draws its own pointer over the menu (see mouse()).
        try:
            pygame.mouse.set_visible(False)
        except pygame.error:  # no display (tests)
            pass
        self.pointer_active = False

        size = window.size
        # Draw at up to 1080p and let the GPU scale: keeps 4K fast.
        scale = min(1.0, 1080 / size[1])
        self.size = size
        self.render_size = (int(size[0] * scale), int(size[1] * scale))
        self.surface = pygame.Surface(self.render_size, pygame.SRCALPHA)
        style.set_text_scale(config.text_size)
        self.view = QuickMenuView(self.render_size, config.scheme, config.motion, config.clock)

        self.open = False
        self.t = 0.0
        self.paused_unit: str | None = None
        self.opened_for: str | None = None
        self.state = session.read()
        self._refreshed = 0.0
        self._housekept = 0.0
        self._seen: set[int] = set()
        self._first_window: set[tuple] = set()  # launches whose first window we've timed
        self._slow_warned: set[tuple] = set()  # launches told "still starting" (#40)
        self.cast_watch = cast.Watch()  # receivers' windows: a new one takes the screen (cast.py)
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
        try:
            self._wii_mouse_apps = dict(settings.load().get("wii_mouse_apps") or {})
        except (OSError, ValueError, AttributeError):
            self._wii_mouse_apps = {}
        style.set_text_scale(c.text_size)
        self.view.set_theme(c.scheme, c.motion, c.clock)
        style.set_prompts(c.prompts, c.confirm)
        self.mapper.swap_confirm = c.confirm == "east"
        self.pointer.speed = c.mouse_speed / 100
        self.pointer.deadzone = c.stick_deadzone / 100
        input_.set_deadzone(c.stick_deadzone)
        if c.wii_remote and self.wii is None:
            from .wiiinput import WiiInput, XTestSink

            self.wii = WiiInput(XTestSink(self.gs.d) if self.gs else None, on_tap=lambda: self.events.put("tap"),
                                on_hold=lambda: self.events.put("wii_hold"))
            self.wii.on_input = self._wii_used
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
        if self.open and self.menu.current.key == "performance" or self._perf_reading is None:
            try:
                self._perf_reading = self.perf.read()
            except Exception:  # a sensor that misbehaves mustn't break the menu
                log.exception("performance reading")
        ctx = Context(self.audio, snapshot, self.state, self.actions,
                      discord_available=bool(discord and discord.available()), wii=wii,
                      frontend=game[0] if game else None, perf=self._perf_reading,
                      media=self.media.poll(), people=_people_active(), casting=cast.on_screen(self.state))
        self.menu.set_tabs(build_tabs(ctx))

    # -- updates ---------------------------------------------------------------

    def run_update(self) -> None:
        log.info("update: starting")
        result = updates.apply(logs.log_path())
        if result == "busy":
            # One is already downloading (Bazzite's automatic update, or an
            # earlier press): wait for it rather than calling it a failure.
            log.info("update: already running; waiting for it")
            self.wait_for_update()
        updates.update_esde()
        self.check_staged(failed=result == "failed")
        events.record("update", ok=result != "failed", result=(session.read().get("update") or {}).get("status"))

    def wait_for_update(self, every: float = 15.0, limit: float = 3 * 3600, sleep=time.sleep) -> None:
        waited = 0.0
        while updates.in_progress() and waited < limit:
            sleep(every)
            waited += every

    def take_screenshot(self, title: str) -> None:
        """Wait for the menu to finish hiding, then capture the screen."""
        from . import captures

        end = time.monotonic() + 2.0
        while (self.open or self.t > 0) and time.monotonic() < end:
            time.sleep(0.05)
        time.sleep(0.15)  # the next frame, without the menu
        try:
            path = captures.take(title)
        except Exception:
            log.exception("screenshot")
            path = None
        events.record("screenshot", ok=path is not None)
        if path is None:
            self.notices.post("Couldn't take a screenshot", "Details: hearthctl logs", "info")
        else:
            self.notices.post("Screenshot saved", f"{title} · see it with the Captures tile", "camera")

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
        elif updates.in_progress():
            result = {"status": "running"}  # still downloading: not "up to date" yet
            if (session.read().get("update") or {}).get("status") != "running":
                threading.Thread(target=self.run_update, daemon=True).start()  # follows it to the end
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
                and self.state["focus"] == "foreground" and session.pause_entry(fg)):
            self.paused_unit = fg["unit"]
            self._paused_entry = fg

    def thaw(self) -> None:
        if self.paused_unit:
            session.resume_entry(getattr(self, "_paused_entry", None) or {"unit": self.paused_unit})
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
        self._toast_showing = False  # a notice still up is shown again (see show_notice)
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
                    cast.give_back(s, k)  # a receiver that died mid-cast
                if s["focus"] in dead:
                    s["focus"] = "foreground" if s["foreground"] else "home"

            self.apply_focus(session.update(drop))

        if "discord" in self.state["background"] and not self._liveness_ticks:
            try:
                for s in reset_restored_discord_mutes(self.audio, self.audio.snapshot(), self._discord_streams_seen):
                    log.info("cleared a mute PipeWire restored on Discord's %s stream", s.app)
            except (OSError, RuntimeError, ValueError):
                pass

        self.watch_family()

        # The app closed under the open menu (e.g. held Guide): close the menu.
        if self.open and (self.state["foreground"] or {}).get("id") != self.opened_for:
            self.paused_unit = None
            self.close_menu()

        # Look for a downloaded update now and then (it's slow: in a thread).
        if now - self._update_checked > UPDATE_CHECK_SECONDS and \
                (self.state.get("update") or {}).get("status") != "running":
            self._update_checked = now
            threading.Thread(target=self.check_staged, daemon=True).start()

        self.pointer_active = not self.open and pointer_app_in_front(self.state)
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
                    # A receiver's window from before this overlay started
                    # (it was restarted mid-cast): still give the screen back when it goes.
                    tagged = self._receiver_for(self.gs.get_cardinal(win, "STEAM_GAME"))
                    if tagged:
                        self.cast_watch.windows.setdefault(win.id, tagged)
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
            self._cast_window(win.id, appid)
        self._seen &= present
        self._tries = {k: v for k, v in self._tries.items() if k in present}
        for app_id in self.cast_watch.prune(present):  # the phone stopped: back to what was there
            events.record("cast_end", id=app_id)
            self.apply_focus(session.update(lambda s, a=app_id: cast.give_back(s, a)))
        self._time_steam_window()

    def _receiver_for(self, appid: int | None) -> str | None:
        """The running receiver whose windows carry this app id, if any."""
        if not appid:
            return None
        return next((i for i in self.state["background"] if cast.is_receiver(i) and appid_for(i) == appid), None)

    def _cast_window(self, win_id: int, appid: int) -> None:
        """A receiver (AirPlay) just opened a window: a phone is casting, show it."""
        app_id = self._receiver_for(appid)
        if self.cast_watch.seen(win_id, app_id) == "take":
            events.record("cast_start", id=app_id)
            self.apply_focus(session.update(lambda s: cast.take_screen(s, app_id)))

    STEAM_APPID = 769  # what gamescope calls Steam's own interface

    def _time_steam_window(self) -> None:
        """Steam and its games tag their own windows, so the time to the first
        window is when gamescope lists the game (or Steam) as one it can show
        (field report #45; a game that never gets there is #40)."""
        fg = self.state["foreground"]
        if not fg or fg.get("tag_windows", True) or not fg.get("started"):
            return
        key = (fg["id"], fg["started"])
        if key in self._first_window:
            return
        game = fg["id"].split(":")[-1] if fg["id"].startswith("game:steam:") else None
        want = int(game) if game and game.isdigit() else self.STEAM_APPID
        if want in self.gs.get_cardinals(self.gs.root, "GAMESCOPE_FOCUSABLE_APPS"):
            self._first_window.add(key)
            events.record("app_window", id=fg["id"], seconds=round(time.time() - fg["started"], 1))

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
        owner = session.app_for_pid(pid, state) if pid else None  # the real id: it's hashed for STEAM_GAME
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
                if not self.open:
                    from . import tv

                    tv.switch_here()  # like a console: Guide brings the TV to Hearth
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
            if self.open and self.mouse(event, navs):
                continue
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

    def _wii_used(self) -> None:
        """A Wii Remote button went to the app in front: tell the home screen
        (it gets them as key presses) so its button hints show the Wii's."""
        style.note_input("wii")
        now = time.time()
        if now - getattr(self, "_wii_noted", 0) > 0.5:
            self._wii_noted = now
            session.update(lambda s: s.__setitem__("wii_input_at", now))

    def mouse(self, event, navs: list) -> bool:
        """A mouse (or trackpad) on the open menu: hover picks an option, a
        click uses it or opens a tab, the wheel moves or adjusts, right click
        closes. Returns True if the event was a mouse event."""
        from .model import Nav

        pg = self.pg
        if event.type == pg.MOUSEMOTION:
            self._mouse_at, self._mouse_moved = event.pos, time.monotonic()
            hit = self.view.hit(event.pos)
            if hit and hit[0] == "item":
                self.menu.point_at(hit[1])
            return True
        if event.type == pg.MOUSEBUTTONDOWN:
            self._mouse_at, self._mouse_moved = event.pos, time.monotonic()
            if event.button == 1:
                hit = self.view.hit(event.pos)
                if hit and hit[0] == "tab":
                    self.menu.open_tab(hit[1])
                elif hit:
                    self.menu.point_at(hit[1])
                    navs.append(Nav.SELECT)
            elif event.button == 3:
                navs.append(Nav.BACK)
            return True
        if event.type == pg.MOUSEWHEEL:
            item = self.menu.selected
            if item is not None and item.kind == "slider" and not self.menu.on_tabs:
                navs.append(Nav.RIGHT if event.y > 0 else Nav.LEFT)
            elif event.y:
                navs.append(Nav.UP if event.y > 0 else Nav.DOWN)
            return True
        return event.type == pg.MOUSEBUTTONUP

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
        override = self._wii_mouse_apps.get(key)
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
        if self.open:
            fresh, self.media.fresh = self.media.fresh, False
            self.refresh(force=fresh)  # right away when what's playing changed
        paused = bool(self.paused_unit)
        if not self.transparent:
            # No per-pixel alpha: the whole window is semi-opaque instead.
            self.surface.fill((0, 0, 0, 255))
        moved = time.monotonic() - self._mouse_moved < MOUSE_POINTER_SECONDS
        self.view.draw(self.surface, self.menu, self.title(), paused, self.t,
                       pointer=self._mouse_at if moved else None)
        self.present()
        self.frames.tick()

    def present(self) -> None:
        """Put self.surface on screen."""
        r = self.renderer
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

    def watch_family(self) -> None:
        """Household limits: count play time while a game is in front, warn
        before it runs out, and close the game if that's the rule."""
        fg = self.state.get("foreground") or {}
        playing = fg.get("id") if self.state.get("focus") == "foreground" else None
        try:
            actions = self.family.tick(playing)
        except Exception:  # never let the rules break the menu
            log.exception("family")
            return
        for action in actions:
            if action[0] == "notice":
                self.notices.post(action[1], action[2], icon="clock")
                events.record("family_notice", title=action[1])
            elif action[0] == "close" and playing:
                events.record("family_close", app=playing)
                self.actions.go_home()

    def watch_for_notices(self) -> None:
        """Every so often: controller batteries, newly installed apps, an update."""
        from . import battery

        now = time.monotonic()
        if now - self._noticed < NOTICE_CHECK_SECONDS:
            return
        self._noticed = now
        try:
            self.notices.batteries(battery.controllers())
            # Tiles you hid count too, so bringing one back isn't "just installed".
            fresh = cfg.load(self.config_path, hide=False)
            self.notices.tiles({a.id: a.name for row in fresh.rows for a in row.apps if a.available()})
            update = self.state.get("update") or {}
            if update.get("status") == "ready":
                self.notices.update_ready(update.get("version") or "ready")
            self.notice_slow_start()
        except Exception:  # a notice is never worth breaking the menu over
            log.exception("notices")

    SLOW_START_SECONDS = 150

    def notice_slow_start(self) -> None:
        """A Steam game still not on screen minutes after launch (field report
        #40: Steam's spinner for ever): say how to get out, once."""
        fg = self.state.get("foreground")
        if not fg or fg.get("tag_windows", True) or not fg.get("started"):
            return
        key = (fg["id"], fg["started"])
        if key in self._first_window or key in self._slow_warned:
            return
        if time.time() - fg["started"] >= self.SLOW_START_SECONDS:
            self._slow_warned.add(key)
            self.notices.post(f"{fg['name']} is taking a while to start", "Hold Guide to go back home")
            events.record("app_slow_start", id=fg["id"], seconds=round(time.time() - fg["started"]))

    def show_notice(self) -> bool:
        """Draw the current notice over the app (without taking its input).
        Returns True while one is up."""
        toast = self.notices.current(time.monotonic()) if self.transparent and self.gs else None
        if toast is None:
            if self._toast_showing:
                self._toast_showing = False
                if not self.open:
                    self.gs.set_overlay_visible(self.xwin, False)
            return False
        if not self._toast_showing:
            self._toast_showing = True
            events.record("notice", title=toast.title)
            self.gs.set_overlay_visible(self.xwin, True, 1.0, focus=False)
        self.surface.fill((0, 0, 0, 0))
        self.view.draw_toast(self.surface, toast, time.monotonic())
        self.present()
        return True

    def step(self, clock) -> None:
        self.handle_events()
        self.housekeeping()
        self.watch_for_notices()
        if not self.open and self.t == 0.0 and self.show_notice():
            clock.tick(30)
            return
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
        elif self.wii and self.wii.in_use():
            clock.tick(100)  # the pointer follows the remote smoothly (20 Hz while it lies still)
        else:
            clock.tick(20)


def _people_active() -> bool:
    from . import profiles

    try:
        return profiles.active()
    except Exception:
        return False


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
