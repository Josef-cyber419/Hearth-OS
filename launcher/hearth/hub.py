"""The session hub: home screen -> app -> home screen, forever.

This runs as the client of the Game Mode (gamescope) session. The home screen
releases the display before an app starts so the app gets the whole screen,
then comes back when the app exits. Background apps (Discord) are started
and brought to the front without leaving the home screen.
"""

from __future__ import annotations

import argparse
import copy
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pygame

from . import config as cfg
from . import input as input_
from . import desktopguide, events, homebutton, library, logs, session, sounds, style, ui, updates
from .gamescope import HOME_APPID, Gamescope
from .model import Home

log = logging.getLogger("hearth")

# An app that dies this quickly with an error most likely failed to start.
QUICK_FAIL_SECONDS = 3
# Grace period between asking an app to quit and killing it.
TERM_TIMEOUT_SECONDS = 5
# Apps that handle Guide themselves (Steam) still close, back to Hearth, when
# Guide is held this long: a way out if the app hangs (e.g. Steam stuck on
# "Switching to Desktop"). Long enough not to get in the way of the app's own
# Guide hold.
ESCAPE_HOLD_SECONDS = 4.0


def resumable(app: cfg.App, config: cfg.Config | None) -> bool:
    """Can Quick Resume keep this app paused? Apps Hearth shows and closes
    itself, yes; Steam (which manages its own screen and games) and background
    apps, no."""
    return bool(config and config.quick_resume and app.tag_windows and app.home_button and not app.background
                and not app.builtin)


def launch(app: cfg.App, dry_run: bool = False, gs: Gamescope | None = None,
           hold_seconds: float = homebutton.HOLD_SECONDS, config: cfg.Config | None = None) -> str | None:
    """Run an app until it exits or is paused (Quick Resume). Returns an
    error message for the home screen."""
    log.info("launching %s: %s", app.id, " ".join(app.command))
    if dry_run:
        print("would run:", " ".join(app.command), flush=True)
        return None
    if not shutil.which(app.command[0]):
        return f"Couldn't start {app.name}: {app.command[0]} not found"
    try:
        proc, unit = session.spawn("app", app.id, app.command)
    except OSError as e:
        log.error("failed to start %s: %s", app.id, e)
        events.record("launch_failed", id=app.id, error=str(e))
        return f"Couldn't start {app.name}: {e.strerror or e}"
    events.record("app_start", id=app.id, scope=bool(unit))
    info = {"id": app.id, "name": app.name, "unit": unit, "pid": proc.pid, "started": time.time(),
            "home_button": app.home_button, "tag_windows": app.tag_windows, "art": app.art,
            "platform": app.platform, "color": app.color, "resumable": resumable(app, config),
            "pointer": app.pointer}
    PROCS[app.id] = proc
    return run_foreground(info, gs, hold_seconds, config)


# Processes of apps we started, so their exit status can be collected (they
# may be paused for a while under Quick Resume).
PROCS: dict[str, subprocess.Popen] = {}


def run_foreground(info: dict, gs: Gamescope | None, hold_seconds: float, config: cfg.Config | None) -> str | None:
    """Show an app and wait until it exits, is closed with Guide, or is
    paused for Quick Resume."""
    state = session.update(lambda s: s.update(foreground=info, focus="foreground", suspend_request=False))
    if gs:
        gs.show_app(session.focus_order(state))
    proc = PROCS.get(info["id"])
    started = time.monotonic() - max(0.0, time.time() - info.get("started", time.time()))
    in_front_since = time.monotonic()  # play time counts only while it's on screen
    outcome = {"sent_home": False}
    keep_paused = info.get("resumable") and (config is None or config.guide_hold_action == "resume")

    def go_home() -> None:
        current = session.read()
        if current["focus"] in current["background"]:
            return  # Discord etc. is in front: the overlay handles this hold
        if keep_paused:
            session.update(lambda s: s.__setitem__("suspend_request", True))
            return
        outcome["sent_home"] = True
        if proc is not None:
            stop_app(proc, info.get("unit"))
        else:
            session.stop_entry(info)

    def escape() -> None:
        current = session.read()
        if current["focus"] in current["background"]:
            return
        log.info("%s: Guide held %.0fs, closing it", info["id"], ESCAPE_HOLD_SECONDS)
        outcome["sent_home"] = True
        # hearth-steam keeps its "Steam was in Hearth" marker when stopped
        # from outside; this isn't a trip to the desktop.
        desktopguide.steam_marker().unlink(missing_ok=True)
        if proc is not None:
            stop_app(proc, info.get("unit"))
        else:
            session.stop_entry(info)
        desktopguide.steam_marker().unlink(missing_ok=True)

    if info.get("home_button"):
        watcher = homebutton.Watcher(go_home, hold_seconds=hold_seconds)
    else:
        watcher = homebutton.Watcher(escape, hold_seconds=max(ESCAPE_HOLD_SECONDS, hold_seconds))
    watcher.start()
    returncode = None
    suspended = False
    try:
        while True:
            if proc is not None:
                returncode = proc.poll()
                if returncode is not None:
                    break
            elif not session.entry_alive(info):
                break
            if info.get("resumable") and session.read().get("suspend_request"):
                suspended = suspend(info)
                if suspended:
                    break
                session.update(lambda s: s.__setitem__("suspend_request", False))
            time.sleep(0.1)
    finally:
        watcher.stop()
        session.update(lambda s: s.update(foreground=None, focus="home", paused=False, suspend_request=False))
        key = library.key_of(info["id"])
        if key and not library.counts_own_time(key):  # Steam and Lutris count their own games' time
            library.add_playtime(key, time.monotonic() - in_front_since)
    if suspended:
        return None
    PROCS.pop(info["id"], None)
    elapsed = time.monotonic() - started
    if outcome["sent_home"]:
        events.record("app_exit", id=info["id"], ended="guide", seconds=round(elapsed, 1))
        return None
    log.info("%s exited with %s after %.1fs", info["id"], returncode, elapsed)
    failed = returncode not in (None, 0) and elapsed < QUICK_FAIL_SECONDS
    events.record("app_exit", id=info["id"], ended="failed" if failed else "exited", code=returncode,
                  seconds=round(elapsed, 1))
    if failed:
        return f"{info['name']} closed unexpectedly (exit code {returncode})"
    return None


def suspend(info: dict) -> bool:
    """Quick Resume: pause the app and keep it for later."""
    if not session.pause_entry(info):
        log.warning("couldn't pause %s for Quick Resume", info["id"])
        return False
    paused = {**info, "paused_at": time.time()}
    session.update(lambda s: s.__setitem__("suspended", [e for e in s["suspended"] if e["id"] != info["id"]]
                                           + [paused]))
    events.record("quick_resume", id=info["id"], action="paused")
    log.info("paused %s for Quick Resume", info["id"])
    return True


def resume(app_id: str, gs: Gamescope | None, hold_seconds: float, config: cfg.Config | None) -> str | None:
    """Bring a paused app back exactly where it was."""
    entry = next((e for e in session.read()["suspended"] if e["id"] == app_id), None)
    session.update(lambda s: s.__setitem__("suspended", [e for e in s["suspended"] if e["id"] != app_id]))
    if entry is None or not session.entry_alive(entry):
        PROCS.pop(app_id, None)
        return "That game had already closed"
    session.resume_entry(entry)
    events.record("quick_resume", id=app_id, action="resumed",
                  paused_minutes=round((time.time() - entry.get("paused_at", time.time())) / 60, 1))
    info = {k: v for k, v in entry.items() if k != "paused_at"}
    return run_foreground(info, gs, hold_seconds, config)


def close_paused(app_id: str) -> None:
    entry = next((e for e in session.read()["suspended"] if e["id"] == app_id), None)
    session.update(lambda s: s.__setitem__("suspended", [e for e in s["suspended"] if e["id"] != app_id]))
    if entry is None:
        return
    session.close_suspended(entry)
    proc = PROCS.pop(app_id, None)
    if proc is not None:
        try:
            proc.wait(timeout=TERM_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            stop_process_group(proc)
    events.record("quick_resume", id=app_id, action="closed")


def make_room(config: cfg.Config) -> None:
    """Keep at most `quick_resume` games paused: close the oldest beyond that."""
    paused = session.read()["suspended"]
    while len(paused) >= max(1, config.quick_resume):
        close_paused(paused[0]["id"])
        paused = session.read()["suspended"]


def quick_resume_row(config: cfg.Config) -> cfg.Row | None:
    """The paused games, newest first, as tiles."""
    entries = [e for e in session.read()["suspended"] if session.entry_alive(e)]
    if not entries or not config.quick_resume:
        return None
    apps = []
    for e in reversed(entries):
        minutes = int((time.time() - e.get("paused_at", time.time())) // 60)
        ago = "just now" if minutes < 1 else f"{minutes} min" if minutes < 60 else f"{minutes // 60} h"
        apps.append(cfg.App(id=f"resume:{e['id']}", name=e["name"], command=("hearth:resume", e["id"]),
                            color=e.get("color") or "#3a3f58", art=e.get("art"), platform=f"Paused · {ago}"))
    return cfg.Row("Quick Resume", tuple(apps))


def stop_app(proc: subprocess.Popen, unit: str | None) -> None:
    """Close the app and everything it started (thawing it first if paused)."""
    if unit:
        # Hearth's scope and any a Flatpak app moved to (see session.app_units).
        units = session.app_units(unit, proc.pid)
        for u in units:
            session.thaw(u)
        for u in units:
            session.stop(u)
        try:
            proc.wait(timeout=TERM_TIMEOUT_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass
    stop_process_group(proc)


def stop_process_group(proc: subprocess.Popen) -> None:
    """SIGTERM the app's process group, then SIGKILL if it doesn't exit."""

    def signal_group(sig: int) -> None:
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass

    signal_group(signal.SIGTERM)
    try:
        proc.wait(timeout=TERM_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        signal_group(signal.SIGKILL)


def show_background(app: cfg.App, gs: Gamescope | None) -> None:
    """Start a background app if needed and bring it to the front."""
    session.start_background(app)
    state = session.update(lambda s: s.__setitem__("focus", app.id))
    if gs:
        gs.show_app(session.focus_order(state))


def open_display(windowed: bool) -> pygame.Surface:
    pygame.display.init()
    pygame.font.init()
    pygame.joystick.init()
    pygame.display.set_caption("Hearth")
    pygame.mouse.set_visible(windowed)
    if windowed:
        return pygame.display.set_mode((1280, 720))
    # Draw at up to 1080p and let SDL scale it on the GPU, so animation stays
    # smooth on a 4K TV (the UI's sizes follow the screen height anyway).
    info = pygame.display.Info()
    if info.current_h > 1080:
        size = (round(info.current_w * 1080 / info.current_h), 1080)
        surface = pygame.display.set_mode(size, pygame.FULLSCREEN | pygame.SCALED)
    else:
        surface = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    events.record("display", screen=f"{info.current_w}x{info.current_h}",
                  drawn_at="x".join(map(str, surface.get_size())), driver=pygame.display.get_driver())
    return surface


def show_home(gs: Gamescope | None) -> None:
    """Tag the home screen's window and bring it to the front."""
    if not gs:
        return
    wid = pygame.display.get_wm_info().get("window")
    if wid:
        gs.tag(gs.window(wid), HOME_APPID)
    gs.show_app(session.focus_order(session.read()))


class OverlayProcess:
    """Keeps the Quick Menu overlay running next to the hub, all the time:
    a watchdog thread restarts it within seconds if it dies, on the home
    screen or in a game (not just between apps)."""

    CHECK_SECONDS = 2.0

    def __init__(self, config_path: Path | None) -> None:
        self.args = [sys.executable, "-m", "hearth.overlay"]
        if config_path:
            self.args += ["--config", str(config_path)]
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._watchdog: threading.Thread | None = None
        self._stopping = threading.Event()

    def stop(self) -> None:
        """Stop watching (the Quick Menu itself keeps running)."""
        self._stopping.set()

    def ensure(self) -> None:
        with self._lock:
            # Exit code 0 means "can't run here" (no gamescope): don't retry.
            if self.proc is not None and self.proc.poll() in (None, 0):
                return
            if self.proc is not None:
                log.warning("Quick Menu overlay exited (%s); restarting", self.proc.returncode)
                events.record("overlay_restart", code=self.proc.returncode)
                recover_from_overlay_crash()
            self.proc = subprocess.Popen(self.args)
        if self._watchdog is None and not self._stopping.is_set():
            self._watchdog = threading.Thread(target=self._watch, daemon=True, name="hearth-overlay-watchdog")
            self._watchdog.start()

    def _watch(self) -> None:
        while not self._stopping.wait(self.CHECK_SECONDS):
            try:
                self.ensure()
            except Exception:  # never let the watchdog die
                log.exception("Quick Menu watchdog")


def recover_from_overlay_crash() -> None:
    """A Quick Menu that died while open can leave the home screen ignoring
    the controller ("the menu is open") and the game frozen. Undo both."""
    state = session.read()
    fg = state.get("foreground") or {}
    if state.get("paused") and fg.get("unit"):
        session.resume_entry(fg)
    session.update(lambda s: s.update(overlay_open=False, paused=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hearth", description="Hearth TV home screen")
    parser.add_argument("--config", type=Path, help="apps.toml to use (default: user, then system)")
    parser.add_argument("--windowed", action="store_true", help="run in a 1280x720 window (development)")
    parser.add_argument("--dry-run", action="store_true", help="print commands instead of running them")
    parser.add_argument("--show-all", action="store_true", help="show tiles even if the app isn't installed")
    parser.add_argument("--overlay", action=argparse.BooleanOptionalAction, default=None,
                        help="run the Quick Menu overlay (default: on under gamescope)")
    args = parser.parse_args(argv)
    logs.setup("hub")
    events.record("session_start", version=updates.hearth_version(), game_mode=bool(
        os.environ.get("GAMESCOPE_WAYLAND_DISPLAY")), pygame=pygame.version.ver, sdl=".".join(
        map(str, pygame.get_sdl_version())))

    in_gamescope = bool(os.environ.get("GAMESCOPE_WAYLAND_DISPLAY"))
    gs = Gamescope.connect() if in_gamescope else None
    overlay = OverlayProcess(args.config) if (args.overlay if args.overlay is not None else in_gamescope) else None
    # Fresh session: nothing in front, but keep background apps that are
    # still running (the hub may have restarted without them).
    # The same goes for games paused by Quick Resume.
    session.update(lambda s: s.update(copy.deepcopy(session.DEFAULT_STATE), background={
        k: v for k, v in s["background"].items() if session.background_alive(v)},
        suspended=[e for e in s.get("suspended", []) if session.entry_alive(e)]))

    dev_mode = args.windowed or args.dry_run
    state = {"last_id": None, "message": None, "surface": None, "intro": "boot"}
    failures: list[float] = []
    while True:
        try:
            if step(args, gs, overlay, dev_mode, state) == "quit":
                return 0
        except Exception as e:
            # Never take the whole TV session down: log it, show it, carry on.
            # (If it keeps failing, give up and let gamescope-session fall
            # back to the desktop.)
            log.exception("home screen error")
            now = time.monotonic()
            failures = [t for t in failures if now - t < 60] + [now]
            if len(failures) > 5:
                raise
            pygame.quit()
            state["surface"] = None
            state["message"] = f"Something went wrong ({type(e).__name__}); details: hearthctl logs"


def home_config(args, state: dict | None = None) -> cfg.Config:
    """The home screen's contents: apps.toml + settings, and your games on top."""
    try:
        config = cfg.load(args.config)
    except (OSError, cfg.ConfigError) as e:
        log.error("config: %s", e)
        config = cfg.Config(rows=())
        if state is not None:
            state["message"] = f"Config error: {e}"
    if not args.show_all:
        config = config.visible()
    from . import profiles

    if not profiles.active():  # "Switch person" only once there are people
        from dataclasses import replace as _replace

        config = _replace(config, rows=tuple(r for r in (
            cfg.Row(r.title, tuple(a for a in r.apps if a.command[:1] != ("hearth:people",))) for r in config.rows)
            if r.apps))
    try:
        config = library.with_game_rows(config)
    except Exception:  # never lose the home screen over the game library
        log.exception("game rows")
    row = quick_resume_row(config)
    if row is not None:
        from dataclasses import replace

        config = replace(config, rows=(row,) + config.rows)
    return config


PERSON = "hearth:person"  # a tile on "Who's playing?": hearth:person <id>


def picker_config() -> cfg.Config:
    """ "Who's playing?": one tile per person."""
    from . import profiles

    tiles = tuple(cfg.App(id=f"person:{p.id}", name=p.name, command=(PERSON, p.id), color=p.color)
                  for p in profiles.people())
    return cfg.Config(title="Who's playing?", rows=(cfg.Row("People", tiles),))


def switch_person(pid: str) -> None:
    """Hand the TV to someone else: close what was theirs (paused games,
    Steam, Discord), then bring in their Steam sign-in and Discord."""
    from . import profiles, storage

    if pid == profiles.current_id():
        return
    try:
        profiles.note_steam_account()  # remember the last person's Steam account
    except Exception:
        log.exception("noting the Steam account")
    for entry in list(session.read()["suspended"]):
        close_paused(entry["id"])
    per_person = set(profiles.PER_PERSON_TILES)
    try:
        per_person |= {a.id for row in cfg.load(hide=False).rows for a in row.apps
                       if a.flatpak in profiles.PER_PERSON_APPS}
    except (OSError, cfg.ConfigError):
        pass
    for app_id, info in list(session.read()["background"].items()):
        if app_id in per_person:
            session.stop_entry(info)
            session.update(lambda s, a=app_id: s["background"].pop(a, None))
    if storage.steam_running():
        subprocess.run(["steam", "-shutdown"], capture_output=True, timeout=30, check=False)
        deadline = time.monotonic() + 20
        while storage.steam_running() and time.monotonic() < deadline:
            time.sleep(0.5)
    problems = profiles.switch(pid)
    events.record("person_switched", person=pid, problems=problems)


def eviction_question(app: cfg.App, config: cfg.Config) -> str | None:
    """Starting another game with Quick Resume full closes the oldest paused
    one: say so first."""
    paused = session.read()["suspended"]
    if not resumable(app, config) or any(e["id"] == app.id for e in paused):
        return None
    if len(paused) < max(1, config.quick_resume):
        return None
    return f"THIS CLOSES PAUSED {paused[0]['name'].upper()}"


def tune_emulators(resolution: str) -> None:
    """Give each emulator recommended settings once it has created its own
    config (after its first run), and make ES-DE use them. See emutune.py
    and esde.py."""
    from . import emutune, esde, settings

    try:
        esde.setup()
    except Exception:
        log.exception("setting up ES-DE")

    try:
        done = set(settings.load().get("emulation_tuned", []))
        new = emutune.auto(resolution, set(done))
        if new != done:
            data = settings.load()
            data["emulation_tuned"] = sorted(new)
            settings.save(data)
            events.record("emulators_tuned", emulators=sorted(new - done))
    except Exception:
        log.exception("tuning emulators")


def step(args, gs: Gamescope | None, overlay: OverlayProcess | None, dev_mode: bool, state: dict) -> str | None:
    """One round of: show the home screen, then run what was picked."""
    config = home_config(args, state)
    style.set_prompts(config.prompts, config.confirm)
    sounds.enable(config.sounds)
    input_.set_deadzone(config.stick_deadzone)
    if overlay:
        overlay.ensure()

    home = Home(config)
    if state["last_id"]:
        home.select_id(state["last_id"])

    if state["surface"] is None:
        state["surface"] = open_display(args.windowed)
    if not state.get("tuned"):
        state["tuned"] = True
        threading.Thread(target=tune_emulators, args=(config.emulation_resolution,), daemon=True).start()
    show_home(gs)
    current = session.read()
    ready = (current.get("update") or {}).get("status") == "ready"
    stats = events.FrameStats()
    view, offset = style.inset(state["surface"], config.safe_area)
    common = dict(input_blocked=lambda: session.read()["overlay_open"], livery=config.livery, motion=config.motion,
                  clock=config.clock, swap_confirm=config.confirm == "east", offset=offset,
                  saver_after=config.screensaver_minutes * 60, saver_style=config.screensaver,
                  ask=lambda a: eviction_question(a, config))
    from . import profiles

    if profiles.active() and not state.get("person_chosen"):
        # "Who's playing?" at start, and from the Switch person tile (B goes
        # back to whoever was playing, once someone has been picked).
        picker = Home(picker_config())
        picker.select_id(f"person:{profiles.current_id()}")
        chosen = ui.run(view, picker, "Who's playing?", back_exits=bool(state.get("person_picked")),
                        intro=state["intro"], hints=(("A", "Choose"),), **{**common, "ask": None})
        state["intro"] = None
        if chosen is not None and chosen.command[:1] == (PERSON,):
            switch_person(chosen.command[1])
            state["person_picked"] = True
        elif chosen is None and not state.get("person_picked"):
            return "quit" if dev_mode else None
        state["person_chosen"] = True
        return None
    from . import whatsnew

    app = ui.run(view, home, config.title, message=state["message"], allow_quit=dev_mode, stats=stats,
                 badge="Update ready: restart to finish" if ready else None,
                 running=set(current["background"]), intro=state["intro"],
                 rebuild=lambda: home_config(args), sleep_after=config.sleep_minutes * 60,
                 whats_new=whatsnew.pending(updates.hearth_version()), **common)
    state["message"] = None
    state["intro"] = None
    frames = stats.summary()
    if frames:
        events.record("home_frames", **frames)
    if app is None:
        return "quit"
    state["last_id"] = app.id

    if app.command[0] == "hearth:settings":
        from . import settings_app

        # Runs in this window; it may hand back an app to open (Desktop Mode).
        app = settings_app.run(view, args.config, offset=offset)
        if app is None:
            return None
    elif app.command[0] == "hearth:library":
        events.record("library_open")
        library_home = Home(library.library_config())
        app = ui.run(view, library_home, "Library", back_exits=True, rebuild=library.library_config,
                     hints=(("A", "Play"), ("Y", "Pin"), ("B", "Back")), **common)
        if app is None:
            return None
    if app.command[0] == "hearth:people":
        state["person_chosen"] = False  # back to "Who's playing?"
        return None
    if app.command[0] == "hearth:resume":
        app_id = app.command[1]
        return foreground(state, gs, lambda: resume(app_id, gs, config.guide_hold, config))
    if app.builtin:
        return None
    if any(e["id"] == app.id for e in session.read()["suspended"]):
        # Picked again from another row: carry on where it was paused.
        return foreground(state, gs, lambda: resume(app.id, gs, config.guide_hold, config))
    key = library.key_of(app.id)
    if key:
        library.record_play(key)

    if resumable(app, config) and not args.dry_run:
        make_room(config)  # the home screen asked first (eviction_question)

    if app.background and not args.dry_run:
        # The home screen stays open behind it; the Quick Menu or a held
        # Guide button brings it back.
        show_background(app, gs)
        return None

    if gs and app.tag_windows:
        # Keep a "Starting…" screen up; gamescope switches to the app as soon
        # as its window appears (see session.focus_order), instead of
        # showing black while it loads.
        ui.draw_loading(state["surface"], app, config.livery)
        return foreground(state, gs, lambda: launch(app, dry_run=args.dry_run, gs=gs,
                                                    hold_seconds=config.guide_hold, config=config))

    # Release the screen and input devices entirely (e.g. for Steam, which
    # manages gamescope's focus itself and must not be covered).
    pygame.quit()
    state["surface"] = None
    state["message"] = launch(app, dry_run=args.dry_run, gs=gs, hold_seconds=config.guide_hold, config=config)
    state["intro"] = "return"
    if app.id == "steam":
        from . import profiles

        try:
            profiles.note_steam_account()  # whoever signed in is this person's Steam
        except Exception:
            log.exception("noting the Steam account")
    return None


def foreground(state: dict, gs: Gamescope | None, run) -> None:
    """Run an app in front with the home screen kept open behind it (under
    gamescope; otherwise the window is closed while it runs)."""
    if gs is None:
        pygame.quit()
        state["surface"] = None
    state["message"] = run()
    state["intro"] = "return"
    if gs is not None:
        pygame.event.clear()  # drop input that queued up while the app ran
    return None
