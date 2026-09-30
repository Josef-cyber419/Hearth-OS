"""State shared between the hub (home screen) and the overlay (Quick Menu),
and systemd scopes for the apps Hearth runs.

Each app runs in its own systemd user scope, a cgroup holding the app and
everything it spawns, including Flatpak sandboxes. That gives three things a
process group can't: pausing a whole game (cgroup freezer), closing all of it
reliably, and finding which app an X window belongs to (via /proc/PID/cgroup).
"""

from __future__ import annotations

import contextlib
import copy
import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterator

from . import events

UNIT_RE = re.compile(r"hearth-(app|bg)-(.+)_\d+\.scope")


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/hearth-{os.getuid()}"
    path = Path(base) / "hearth"
    path.mkdir(parents=True, exist_ok=True)
    return path


# -- shared state --------------------------------------------------------------
#
# {
#   "foreground": {"id", "name", "unit", "home_button", "tag_windows"} | null,
#   "background": {"<id>": {"name", "unit", "wm_class", "pointer"}},
#   "focus": "home" | "foreground" | "<background id>",
#   "overlay_open": bool,
#   "paused": bool,
#   "requests": ["menu" | "home", ...]   (from hearthctl; handled by the overlay)
#   "update": {"status": "running" | "ready" | "current" | "failed", "version"} | null,
#   "report": {"status": "running" | "done" | "failed", "file"} | null,
#   "wii_mouse": {app id: bool},  (Quick Menu's per-app override of wii_remote.mouse)
#   "wii": {"connected": [player, ...], "dolphin": bool} | null,  (from the overlay)
#   "wii_raw": bool,  (the Settings app is calibrating: the overlay writes wii-aim.json)
#   "suspended": [{like foreground, + "paused_at"}, ...],  (Quick Resume: games kept paused, oldest first)
#   "suspend_request": bool   (the Quick Menu or a held Guide asks the hub to pause the game and go home)
# }

DEFAULT_STATE = {"foreground": None, "background": {}, "focus": "home", "overlay_open": False,
                 "paused": False, "requests": [], "update": None, "report": None,
                 "wii_mouse": {}, "wii": None, "wii_raw": False,
                 "suspended": [], "suspend_request": False}


def _state_path() -> Path:
    return runtime_dir() / "state.json"


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    with open(runtime_dir() / "state.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def aim_path() -> Path:
    """Where a Wii Remote is aiming, while the Settings app calibrates."""
    return runtime_dir() / "wii-aim.json"


def state_path() -> Path:
    return _state_path()


def _read_unlocked() -> dict:
    try:
        data = json.loads(_state_path().read_text())
    except (OSError, ValueError):
        data = {}
    return {**copy.deepcopy(DEFAULT_STATE), **data}


def read() -> dict:
    with _locked():
        return _read_unlocked()


def update(change: Callable[[dict], None]) -> dict:
    """Read-modify-write the state atomically; returns the new state."""
    with _locked():
        state = _read_unlocked()
        change(state)
        fd, tmp = tempfile.mkstemp(dir=runtime_dir(), prefix=".state")
        with os.fdopen(fd, "w") as f:
            json.dump(state, f)
        os.replace(tmp, _state_path())
        return state


# -- scopes --------------------------------------------------------------------


def scopes_available() -> bool:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return bool(shutil.which("systemd-run") and runtime and Path(runtime, "systemd", "private").exists())


def unit_name(kind: str, app_id: str) -> str:
    return f"hearth-{kind}-{safe_id(app_id)}_{time.monotonic_ns() % 10**9}.scope"


def scoped(unit: str, command: tuple[str, ...]) -> list[str]:
    """Wrap a command so it runs in its own scope (systemd-run execs it in place)."""
    return ["systemd-run", "--user", "--scope", "--collect", "--quiet", f"--unit={unit}", "--", *command]


def systemctl(*args: str) -> bool:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def freeze(unit: str) -> bool:
    return systemctl("freeze", unit)


def thaw(unit: str) -> bool:
    return systemctl("thaw", unit)


def stop(unit: str) -> bool:
    return systemctl("stop", unit)


def is_active(unit: str) -> bool:
    return systemctl("is-active", "--quiet", unit)


# -- Quick Resume: pausing a whole app and bringing it back ------------------------


def app_units(unit: str | None, pid: int | None, proc: Path = Path("/proc")) -> list[str]:
    """The scopes an app runs in: the one Hearth started it in, plus any its
    processes moved to. Flatpak moves every app it starts into a scope of its
    own (app-flatpak-<id>-<pid>.scope), so pausing, closing or checking only
    Hearth's scope would miss the app itself."""
    units = [unit] if unit else []
    if not pid:
        return units
    procs = _processes(proc)
    for p in [pid, *_descendants(pid, procs)]:
        try:
            path = (proc / str(p) / "cgroup").read_text().strip().split("::", 1)[1]
        except (OSError, IndexError):
            continue
        name = path.rstrip("/").rsplit("/", 1)[-1]
        if name.startswith("app-flatpak-") and name.endswith(".scope") and name not in units:
            units.append(name)
    return units


def _units(info: dict) -> list[str]:
    return app_units(info.get("unit"), info.get("pid"))


def _pid_alive(pid: int | None) -> bool:
    try:
        # Field 3 of /proc/PID/stat is the state; Z = exited but not reaped.
        text = Path(f"/proc/{pid}/stat").read_text()
        return text[text.rfind(")") + 2:].split()[0] != "Z"
    except (OSError, IndexError, TypeError):
        return False


def pause_entry(info: dict) -> bool:
    """Freeze an app and everything it started. Without a systemd scope, stop
    its process group instead (the app runs in its own session, see spawn)."""
    if info.get("unit"):
        results = [freeze(u) for u in _units(info)]
        return any(results)
    try:
        os.killpg(info["pid"], signal.SIGSTOP)
        return True
    except (OSError, KeyError):
        return False


def resume_entry(info: dict) -> bool:
    if info.get("unit"):
        results = [thaw(u) for u in _units(info)]
        return any(results)
    try:
        os.killpg(info["pid"], signal.SIGCONT)
        return True
    except (OSError, KeyError):
        return False


def entry_alive(info: dict) -> bool:
    # Hearth's scope, or the process it started (which stays while a Flatpak
    # app runs, even after Flatpak moved the app to a scope of its own).
    if info.get("unit") and is_active(info["unit"]):
        return True
    return _pid_alive(info.get("pid"))


def close_suspended(info: dict) -> None:
    """Close a paused app (it has to be running to hear the request)."""
    resume_entry(info)
    stop_entry(info)
    if not info.get("unit"):
        try:
            os.killpg(info["pid"], signal.SIGCONT)
        except (OSError, KeyError):
            pass


def app_for_pid(pid: int, state: dict | None = None) -> tuple[str, str] | None:
    """("app" | "bg", app id) for a process Hearth started, from its cgroup."""
    try:
        cgroup = Path(f"/proc/{pid}/cgroup").read_text()
    except OSError:
        return None
    return app_for_cgroup(cgroup, state)


def _entries(state: dict) -> Iterator[tuple[str, dict]]:
    """(app id, entry) for everything Hearth has running."""
    fg = state.get("foreground")
    if fg:
        yield fg.get("id", ""), fg
    for app_id, info in (state.get("background") or {}).items():
        yield app_id, info
    for entry in state.get("suspended") or []:
        yield entry.get("id", ""), entry


def app_for_cgroup(cgroup: str, state: dict | None = None) -> tuple[str, str] | None:
    """The app a cgroup belongs to. The unit name only carries a tidied-up id
    ("game:pc:Dusk.AppImage" becomes "game-pc-Dusk-AppImage"), so with the
    session state the real id is looked up by the unit (then the tidied id)."""
    for part in reversed(cgroup.strip().split("/")):
        m = UNIT_RE.fullmatch(part)
        if not m:
            continue
        kind, safe = m.group(1), m.group(2)
        if state is not None:
            entries = list(_entries(state))
            for app_id, info in entries:
                if info.get("unit") == part:
                    return kind, app_id
            for app_id, _info in entries:
                if safe_id(app_id) == safe:
                    return kind, app_id
        return kind, safe
    return None


def safe_id(app_id: str) -> str:
    """An app id as it can appear in a unit name."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", app_id)


# -- running apps --------------------------------------------------------------

SHIM_DIR = Path("/usr/libexec/hearth/shims")


def app_env() -> dict[str, str]:
    env = dict(os.environ)
    # Shims (e.g. steamos-session-select) make "exit" inside apps land back home.
    if SHIM_DIR.is_dir():
        env["PATH"] = f"{SHIM_DIR}:{env.get('PATH', '')}"
    env["HEARTH_SESSION"] = "1"
    return env


def spawn(kind: str, app_id: str, command: tuple[str, ...]) -> tuple[subprocess.Popen, str | None]:
    """Start an app in its own scope (when systemd is available) and session."""
    unit = unit_name(kind, app_id) if scopes_available() else None
    argv = scoped(unit, command) if unit else list(command)
    proc = subprocess.Popen(argv, env=app_env(), start_new_session=True)
    return proc, unit


def start_background(app) -> None:
    """Start a background app (e.g. Discord) unless it's already running."""
    state = read()
    if app.id in state["background"] and background_alive(state["background"][app.id]):
        return
    proc, unit = spawn("bg", app.id, app.command)
    events.record("background_start", id=app.id)
    info = {"name": app.name, "unit": unit, "pid": proc.pid, "wm_class": app.wm_class, "pointer": app.pointer}
    update(lambda s: s["background"].__setitem__(app.id, info))


def background_alive(info: dict) -> bool:
    # The scope can empty while the app runs: Flatpak moves the app it
    # starts into a scope of its own (app-flatpak-*.scope). The process we
    # started (flatpak run) stays for the app's lifetime, so it counts too.
    # (Only checking the scope dropped Discord a few seconds after it opened.)
    return entry_alive(info)


# -- games inside a frontend (ES-DE) ---------------------------------------------

FRONTENDS = {"es-de": "ES-DE"}  # process name: what to call it


def _processes(proc: Path) -> dict[int, tuple[int, str]]:
    """pid: (parent pid, name), for every process we can see."""
    out = {}
    for stat in proc.glob("[0-9]*/stat"):
        try:
            text = stat.read_text()
        except OSError:
            continue
        # "pid (name) state ppid ...": the name may contain spaces and brackets.
        name = text[text.find("(") + 1:text.rfind(")")]
        fields = text[text.rfind(")") + 2:].split()
        out[int(stat.parent.name)] = (int(fields[1]), name)
    return out


def _descendants(pid: int, procs: dict[int, tuple[int, str]]) -> list[int]:
    children: dict[int, list[int]] = {}
    for p, (parent, _) in procs.items():
        children.setdefault(parent, []).append(p)
    out, todo = [], list(children.get(pid, []))
    while todo:
        p = todo.pop()
        out.append(p)
        todo.extend(children.get(p, []))
    return out


def frontend_game(info: dict | None, proc: Path = Path("/proc")) -> tuple[str, list[int]] | None:
    """If the app in front is a frontend (ES-DE) running a game: (frontend
    name, the game's processes). Closing those leaves the frontend's list."""
    if not info or not info.get("pid"):
        return None
    procs = _processes(proc)
    for pid in [info["pid"], *_descendants(info["pid"], procs)]:
        name = procs.get(pid, (0, ""))[1]
        if name in FRONTENDS:
            game = _descendants(pid, procs)
            return (FRONTENDS[name], game) if game else None
    return None


def quit_game(pids: list[int], wait: float = 3.0, kill=os.kill, alive=None, sleep=time.sleep) -> None:
    """Ask the game's processes to quit (emulators save and exit on SIGTERM),
    then force the ones that don't."""
    alive = alive or (lambda p: Path(f"/proc/{p}").exists())
    for pid in pids:
        try:
            kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and any(alive(p) for p in pids):
        sleep(0.1)
    for pid in pids:
        if alive(pid):
            try:
                kill(pid, signal.SIGKILL)
            except OSError:
                pass


GRACE_SECONDS = 2.0  # how long an app gets to exit by itself before its scope is stopped


def ask_to_exit(pid: int | None, wait: float = GRACE_SECONDS, sleep=time.sleep) -> bool:
    """SIGTERM the app's process group and give it a moment to exit by
    itself. An AppImage runs from a FUSE mount held by a helper in the same
    scope; stopping the scope kills both at once and the game dies of SIGBUS
    (field report #41). True if it's gone."""
    if not pid:
        return False
    try:
        os.killpg(pid, 15)
    except OSError:
        return not _pid_alive(pid)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        sleep(0.1)
    return not _pid_alive(pid)


def stop_entry(info: dict) -> None:
    """Close an app (foreground or background) and everything it started:
    ask it to exit, then stop what's left of its scope."""
    units = _units(info) if info.get("unit") else []
    if units:
        for u in units:
            thaw(u)
        ask_to_exit(info.get("pid"))
        stopped = [stop(u) for u in units]
        if all(stopped) and not _pid_alive(info.get("pid")):
            return
    try:
        os.killpg(info["pid"], 15)
    except (OSError, KeyError):
        pass


def focus_order(state: dict) -> list[int] | None:
    """What gamescope should show, as app IDs in priority order: the first
    one with a window is shown, so the home screen is the fallback while an
    app is still starting. None means "leave it to gamescope/Steam" (used
    while Steam, which manages this itself, is in front)."""
    from .gamescope import HOME_APPID, appid_for

    focus, fg = state.get("focus", "home"), state.get("foreground")
    fg_ids = [appid_for(fg["id"])] if fg and fg.get("tag_windows", True) else []
    if focus in state.get("background", {}):
        return [appid_for(focus), *fg_ids, HOME_APPID]
    if fg:  # while an app runs, the home screen is only a fallback
        return [*fg_ids, HOME_APPID] if fg_ids else None
    return [HOME_APPID]


def focus_appid(state: dict) -> int | None:
    """The app gamescope should show first."""
    order = focus_order(state)
    return order[0] if order else None
