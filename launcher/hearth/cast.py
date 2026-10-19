"""Casting from a phone (Settings → Casting).

The PC shows up on the home network as a screen and a speaker:

- **AirPlay** (UxPlay): an iPhone, iPad or Mac sends a video, photos, music
  or its whole screen. When a picture arrives, UxPlay opens a window; Hearth
  brings it to the front over whatever was there, and goes back when it
  closes. Music alone has no window: it just plays.
- **Spotify Connect** (spotifyd): the Spotify app on any phone lists the PC
  as a speaker. Needs Spotify Premium. Plays through PipeWire, so the Quick
  Menu's volume and Now playing work.
- **YouTube**: the YouTube tile is YouTube's own TV app, which links to the
  phone with a TV code (Settings → Casting says where to find it).

The receivers run in the background like Discord does (session.py's
background entries, in their own scopes), started by the hub with the
session, and their windows are recognised the same way (the process is in
Hearth's scope). "cast:" ids keep them off the home screen and the Quick
Menu's app lists.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass

from . import session
from .config import App, Config

log = logging.getLogger("hearth")

AIRPLAY = "cast:airplay"
SPOTIFY = "cast:spotify"
RECEIVER_IDS = (AIRPLAY, SPOTIFY)


@dataclass(frozen=True)
class Receiver:
    id: str
    name: str  # on screen
    setting: str  # [cast] key that turns it on
    script: str
    requires: tuple[str, ...] = ()
    requires_files: tuple[str, ...] = ()
    needs: str = ""  # what's missing when it can't run, in plain words
    installer: str = ""  # the user service that fetches the program, if one does

    def app(self, name: str) -> App:
        return App(id=self.id, name=self.name, command=(self.script, name), background=True,
                   requires=self.requires, requires_files=self.requires_files, color="#2b3a4a")


RECEIVERS = (
    Receiver(AIRPLAY, "AirPlay", "airplay", "/usr/libexec/hearth/hearth-airplay", requires=("uxplay",),
             needs="UxPlay isn't installed in this build"),
    Receiver(SPOTIFY, "Spotify", "spotify", "/usr/libexec/hearth/hearth-spotify",
             requires_files=("~/Applications/spotifyd",),
             needs="spotifyd is still being installed (needs the network once)",
             installer="hearth-spotify-update.service"),
)


def installer_failed(unit: str) -> bool:
    """Whether the service that installs a receiver's program gave up (a
    checksum that didn't match, no release): then "still being installed"
    would be a lie (field report #57)."""
    return session.systemctl("is-failed", "--quiet", unit)


def probe(config: Config) -> dict[str, tuple[str, bool]]:
    """For each receiver: what's missing for it to run ("" if nothing), and
    whether its installer failed. Runs commands: not for the UI thread."""
    return {r.id: (app.missing() or "", bool(r.installer) and app.missing() is not None
                   and installer_failed(r.installer)) for r, app, _ in receivers(config)}


def is_receiver(app_id: str | None) -> bool:
    return bool(app_id) and str(app_id).startswith("cast:")


def device_name(config: Config) -> str:
    """What the phone lists: the name chosen in Settings, else the PC's."""
    if config.cast_name:
        return config.cast_name
    host = (socket.gethostname() or "").split(".")[0]
    return host if host and host.lower() not in ("localhost", "bazzite", "fedora") else "Hearth"


def wanted(config: Config) -> dict[str, bool]:
    return {AIRPLAY: config.cast_airplay, SPOTIFY: config.cast_spotify}


def receivers(config: Config) -> list[tuple[Receiver, App, bool]]:
    """(receiver, its app, wanted) for each one; `app.missing()` says if it can run."""
    name = device_name(config)
    on = wanted(config)
    return [(r, r.app(name), on[r.id]) for r in RECEIVERS]


def status(config: Config, background: dict, probed: dict[str, tuple[str, bool]] | None = None
           ) -> list[tuple[Receiver, str, str]]:
    """(receiver, state, words) for each: "off", "missing", "running" or
    "stopped", in plain words for the sofa; shared by Settings and hearthctl.
    `probed` is probe()'s answer, taken beforehand off the UI thread."""
    out = []
    name = device_name(config)
    probed = probe(config) if probed is None else probed
    for receiver, app, on in receivers(config):
        missing, failed = probed.get(receiver.id, ("", False))
        if not on:
            out.append((receiver, "off", "Off"))
        elif missing:
            words = f"{receiver.name}'s program couldn't be installed; hearthctl check says why" if failed \
                else receiver.needs
            out.append((receiver, "missing", words))
        elif app.id in background:
            out.append((receiver, "running", f'Ready: look for "{name}"'))
        else:
            out.append((receiver, "stopped", "Starts with the home screen"))
    return out


def ensure(config: Config, wait: bool = False) -> None:
    """Start the receivers that are on and can run; stop the ones turned off
    (in the background: stopping waits for the program). The hub does this
    with each visit to the home screen and once a minute (keep()); the
    overlay after Stop casting. One at a time, across processes, so a
    receiver is never started twice."""
    to_stop = []
    with session.held("cast"):
        state = session.read()
        for _receiver, app, on in receivers(config):
            info = state["background"].get(app.id)
            running = bool(info) and session.background_alive(info)
            if info and not running:  # died (or was killed): forget it, then start it again below
                session.update(lambda s, i=app.id: (s["background"].pop(i, None), give_back(s, i)))
            if on and app.available():
                if running and info.get("name_arg") != app.command[1]:
                    to_stop.append(app.id)  # renamed in Settings: restart under the new name
                    continue
                if not running:
                    session.start_background(app)
                    session.update(lambda s, i=app.id, n=app.command[1]: s["background"].get(i, {}).__setitem__(
                        "name_arg", n))
            elif running:
                to_stop.append(app.id)
    threads = [session.in_background(f"stop-{app_id}", stop, app_id) for app_id in to_stop]
    if wait:
        for t in threads:
            t.join()


_keeper: dict = {}


def keep(load_config, every: float = 60.0) -> None:
    """Keep the receivers as Settings says while the home screen is up: one
    that crashed, or whose program was installed after boot (spotifyd
    arrives a minute after the first login), comes back within `every`
    seconds. `load_config` is called each round; None stops the keeper."""
    _keeper["load"] = load_config
    if load_config is None or _keeper.get("thread"):
        return

    def work() -> None:
        while _keeper.get("load") is not None:
            time.sleep(every)
            load = _keeper.get("load")
            if load is None:
                break
            try:
                state = session.read()
                if state["focus"] == "home" and not state["foreground"]:
                    ensure(load())
            except Exception:  # noqa: BLE001 - keep keeping
                log.exception("cast keeper")

    _keeper["thread"] = threading.Thread(target=work, daemon=True, name="cast-keeper")
    _keeper["thread"].start()


def stop(app_id: str) -> None:
    """Stop a receiver (the phone sees it vanish) and forget it."""
    with session.held("cast"):
        state = session.read()
        info = state["background"].pop(app_id, None)
        if info:
            session.update(lambda s: s["background"].pop(app_id, None))  # claimed: nobody else stops or restarts it
    if info:
        session.stop_entry(info)

    def drop(s):
        s["background"].pop(app_id, None)
        give_back(s, app_id)
        if s["focus"] == app_id:
            s["focus"] = "foreground" if s["foreground"] else "home"

    session.update(drop)


def restart(app_id: str, config: Config) -> None:
    """Drop the phone that's casting (Quick Menu → Stop casting): the receiver
    comes straight back, ready for the next one."""
    stop(app_id)
    ensure(config, wait=True)


# -- who's on screen -------------------------------------------------------------
#
# state["cast"] = {"id", "name", "since", "back"} while a receiver's window
# is in front; "back" is where focus goes when it closes.


def take_screen(s: dict, app_id: str) -> None:
    """A receiver's window appeared: show it, remembering what was in front."""
    info = s["background"].get(app_id)
    if not info or s["focus"] == app_id:
        return
    s["cast"] = {"id": app_id, "name": info.get("name") or app_id, "since": time.time(), "back": s["focus"]}
    s["focus"] = app_id


def give_back(s: dict, app_id: str) -> None:
    """The window closed (or casting was stopped): back to what was there."""
    cast = s.get("cast")
    if not cast or cast.get("id") != app_id:
        return
    s["cast"] = None
    if s["focus"] != app_id:
        return  # the person already went home (held Guide)
    back = cast.get("back")
    if back == "foreground" and s["foreground"] or back in s["background"]:
        s["focus"] = back
    else:
        s["focus"] = "foreground" if s["foreground"] else "home"


class Watch:
    """The overlay's bookkeeping of receiver windows: which X windows belong
    to which receiver, so a new one takes the screen and a vanished one
    gives it back. Returns what to do; the overlay applies it."""

    def __init__(self) -> None:
        self.windows: dict[int, str] = {}

    def seen(self, win_id: int, app_id: str | None) -> str | None:
        """A window was just tagged for app_id; "take" if it's a receiver's."""
        if not is_receiver(app_id) or win_id in self.windows:
            return None
        self.windows[win_id] = str(app_id)
        return "take"

    def prune(self, present: set[int]) -> list[str]:
        """Receivers whose windows are gone (ids), to give the screen back."""
        gone = [app_id for win_id, app_id in self.windows.items() if win_id not in present]
        self.windows = {w: a for w, a in self.windows.items() if w in present}
        return [a for a in gone if a not in self.windows.values()]


def on_screen(state: dict) -> str | None:
    """The receiver casting to the screen right now, by name; None if none."""
    cast = state.get("cast")
    if cast and state.get("focus") == cast.get("id"):
        return cast.get("name")
    return None
