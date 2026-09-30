"""The Settings app: every Hearth option, with a controller, TV remote or
Wii Remote. Opened from the Settings tile; runs in the home screen's window.

Categories on the left, their options on the right. Up/Down picks a
category, Right or A goes into it; there Up/Down picks an option,
Left/Right changes it, A presses it, B goes back. Changes apply at once and
are saved to ~/.config/hearth/settings.json (see settings.py).

Slow things (Wi-Fi scans, Bluetooth pairing, updates) run in the background;
their progress shows under the option.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

import pygame

from . import bluetooth, events, network, session, settings, storage, style, updates, wiimote
from . import config as cfg
from . import input as input_
from .config import App
from .input import InputMapper
from .model import Nav
from .quickmenu import Item, QuickMenu, Tab
from .quickmenu_view import QuickMenuView
from .style import mix

log = logging.getLogger("hearth")

CATEGORIES = [
    ("appearance", "Appearance", "Colours, motion and the clock."),
    ("home", "Home screen", "Which tiles show, and what Game Mode starts in."),
    ("audio", "Audio", "Where sound plays and which microphone is used, for every app."),
    ("controllers", "Controllers", "Connected controllers, the Guide button, and the controller as a mouse."),
    ("wii", "Wii Remote", "Wii Remotes on a DolphinBar: aiming, sensitivity and calibration."),
    ("emulation", "Emulation", "Emulator settings tuned for this PC and your TV."),
    ("bluetooth", "Bluetooth", "Pair controllers and headsets."),
    ("network", "Network", "Wired and Wi-Fi connections."),
    ("storage", "Storage", "Drives added after install: set them up for Steam games and ROMs."),
    ("family", "Family", "A daily play-time limit, a bedtime, and tiles locked with a PIN."),
    ("privacy", "Privacy", "No ads or tracking in Hearth, and how to turn off your TV's tracking."),
    ("system", "System", "Versions, updates and help."),
]


# -- background jobs -----------------------------------------------------------


class Jobs:
    """Slow work off the UI thread. Each job has a key; its latest message
    shows under the matching option."""

    def __init__(self) -> None:
        self.messages: dict[str, str] = {}
        self._running: set[str] = set()
        self._finished: queue.Queue[str] = queue.Queue()

    def busy(self, key: str) -> bool:
        return key in self._running

    def start(self, key: str, work: Callable[[], str | None], busy_message: str | None = None) -> None:
        if key in self._running:
            return
        self._running.add(key)
        if busy_message:
            self.messages[key] = busy_message

        def run() -> None:
            try:
                result = work()
                if result is not None:
                    self.messages[key] = result
                else:
                    self.messages.pop(key, None)
            except Exception as e:  # show it rather than lose it
                log.exception("settings job %s", key)
                self.messages[key] = f"Failed: {e}"
            finally:
                self._running.discard(key)
                self._finished.put(key)

        threading.Thread(target=run, daemon=True, name=f"settings-{key}").start()

    def finished(self) -> list[str]:
        out = []
        while not self._finished.empty():
            out.append(self._finished.get())
        return out


# -- on-screen keyboard --------------------------------------------------------


class Keyboard:
    """Typing with a controller: for Wi-Fi passwords and the like. A real
    keyboard types into it too."""

    LAYERS = {
        "lower": ["1234567890", "qwertyuiop", "asdfghjkl@", "zxcvbnm-_."],
        "upper": ["1234567890", "QWERTYUIOP", "ASDFGHJKL@", "ZXCVBNM-_."],
        "symbols": ["!@#$%^&*()", "-_=+[]{}\\|", ";:'\",.<>/?", "~`€£¥§°¡¿×"],
    }
    SPECIAL = ["shift", "symbols", "space", "delete", "show", "done"]

    def __init__(self, title: str, secret: bool = False, text: str = "") -> None:
        self.title = title
        self.secret = secret
        self.show = not secret
        self.text = text
        self.layer = "lower"
        self.row, self.col = 1, 0

    @property
    def special(self) -> list[str]:
        return [k for k in self.SPECIAL if k != "show" or self.secret]

    def key_at(self, row: int, col: int) -> str:
        if row < 4:
            return self.LAYERS[self.layer][row][col]
        return self.special[col]

    def handle(self, nav: Nav) -> str | None:
        """Returns "done" or "cancel" when finished."""
        rows = 5
        if nav in (Nav.UP, Nav.DOWN):
            new = (self.row + (1 if nav is Nav.DOWN else -1)) % rows
            if new == 4:
                self.col = min(len(self.special) - 1, self.col * len(self.special) // 10)
            elif self.row == 4:
                self.col = min(9, (self.col * 10 + 5) // len(self.special))
            self.row = new
        elif nav in (Nav.LEFT, Nav.RIGHT):
            width = 10 if self.row < 4 else len(self.special)
            self.col = (self.col + (1 if nav is Nav.RIGHT else -1)) % width
        elif nav is Nav.SELECT:
            return self.press(self.key_at(self.row, self.col))
        elif nav is Nav.BACK:
            if self.text:
                self.text = self.text[:-1]
            else:
                return "cancel"
        elif nav is Nav.MENU:
            return "done"
        elif nav is Nav.TAB_PREV:
            self.text = self.text[:-1]
        elif nav is Nav.TAB_NEXT:
            self.press("shift")
        return None

    def press(self, key: str) -> str | None:
        if key == "shift":
            self.layer = "lower" if self.layer == "upper" else "upper"
        elif key == "symbols":
            self.layer = "lower" if self.layer == "symbols" else "symbols"
        elif key == "space":
            self.text += " "
        elif key == "delete":
            self.text = self.text[:-1]
        elif key == "show":
            self.show = not self.show
        elif key == "done":
            return "done"
        else:
            self.text += key
            if self.layer == "upper":
                self.layer = "lower"  # like a phone: one capital, then back
        return None

    def type(self, text: str) -> None:
        self.text += text


# -- pointer calibration -------------------------------------------------------


class Calibration:
    """Aim at two targets; the camera positions of the sensor bar give an
    exact map from the remote's view to the screen."""

    def __init__(self) -> None:
        self.points: list[tuple[float, float]] = []
        self.message = "Point the Wii Remote at the target and press A"

    @property
    def target(self) -> tuple[float, float]:
        return wiimote.CALIBRATION_TARGETS[len(self.points)]

    def capture(self, raw: tuple[float, float] | None) -> tuple[float, float, float, float] | None | str:
        """Returns the calibration when both targets are done, "retry" if they
        didn't make sense, None while there's more to do."""
        if raw is None:
            self.message = "Can't see the sensor bar: point the Wii Remote at the TV"
            return None
        self.points.append(raw)
        if len(self.points) < len(wiimote.CALIBRATION_TARGETS):
            self.message = "Now the second target"
            return None
        result = wiimote.calibration_from(*self.points)
        if result is None:
            self.points = []
            self.message = "Those were too close together: aim right at each target"
            return "retry"
        return result


def read_aim(max_age: float = 1.0) -> tuple[float, float] | None:
    """Where the Wii Remote is aiming, as published by the Quick Menu process."""
    try:
        data = json.loads(session.aim_path().read_text())
    except (OSError, ValueError):
        return None
    if time.time() - data.get("t", 0) > max_age or not data.get("raw"):
        return None
    return tuple(data["raw"])  # type: ignore[return-value]


# -- system information --------------------------------------------------------


def hardware_summary() -> str:
    cpu = gpu = ""
    try:
        cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")), "")
    except OSError:
        pass
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
        try:
            product = (card / "device" / "product_name").read_text().strip()
        except OSError:
            product = ""
        if product:
            gpu = product
            break
    try:
        kb = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                  if line.startswith("MemTotal"))
        memory = f"{kb / 1024 / 1024:.0f} GB memory"
    except (OSError, StopIteration, ValueError):
        memory = ""
    cpu = re.sub(r"\s+\d+-Core Processor|\(R\)|\(TM\)|CPU @.*", "", cpu).strip()
    return " · ".join(p for p in (cpu, gpu, memory) if p) or "Unknown"


def temperatures() -> str:
    """CPU and GPU temperatures from the kernel's sensors (hwmon)."""
    found = {}
    for hw in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            name = (hw / "name").read_text().strip()
            temp = int((hw / "temp1_input").read_text()) / 1000
        except (OSError, ValueError):
            continue
        label = {"k10temp": "CPU", "coretemp": "CPU", "zenpower": "CPU", "amdgpu": "GPU"}.get(name)
        if label and label not in found:
            found[label] = f"{label} {temp:.0f}°C"
    return " · ".join(found[k] for k in ("CPU", "GPU") if k in found)


def play_test_sound() -> str | None:
    """A short chime through the default output (pw-play, or paplay)."""
    import subprocess
    import tempfile
    import wave

    from . import sounds

    tone = sounds.tone([(660, 0.15), (880, 0.15), (1320, 0.3)], volume=0.35)
    player = shutil.which("pw-play") or shutil.which("paplay")
    if not player:
        return "Can't play sound: no player (pw-play) found"
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        with wave.open(f.name, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sounds.RATE)
            w.writeframes(tone)
        try:
            subprocess.run([player, f.name], timeout=10, capture_output=True)
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"Couldn't play it: {e}"
    return "Heard it? If not, try another output"


def network_mask(prefix: int) -> str:
    import ipaddress

    return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)


def storage_breakdown() -> str:
    """Rough sizes of what takes the most space, via du (runs in the background)."""
    import subprocess

    home = Path.home()
    places = [("Steam games", [home / ".local/share/Steam/steamapps"]), ("ROMs", [home / "ROMs"]),
              ("Emulator and app data", [home / ".var/app"])]
    out = []
    for label, paths in places:
        existing = [str(p) for p in paths if p.exists()]
        if not existing:
            continue
        try:
            p = subprocess.run(["du", "-sb", "--apparent-size", *existing], capture_output=True, text=True,
                               timeout=120)
            total = sum(int(line.split()[0]) for line in p.stdout.splitlines() if line.split())
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
        out.append(f"{label} {total / 1e9:.0f} GB")
    return " · ".join(out) or "Nothing measured"


# -- the app -------------------------------------------------------------------


class SettingsApp:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path
        self.jobs = Jobs()
        self.zone = "nav"  # "nav": choosing a category; "items": inside one
        self.keyboard: Keyboard | None = None
        self._keyboard_done: Callable[[str], None] | None = None
        self.calibrating: Calibration | None = None
        self.launch: App | None = None  # an app to open on the way out (Desktop Mode)
        self.data: dict = {"net": None, "wifi": None, "networks": [], "bt_power": None, "bt": [],
                           "os": None, "drives": None, "ip": None, "audio": None, "tv": None, "loaded": set()}
        # Network changes being picked, not applied yet (each one reconnects).
        self.ip_method: str | None = None  # "auto" | "manual"
        self.ip_edit: dict | None = None  # the manual (static) address, router and prefix
        self.dns_choice: int | None = None
        self._refreshed = 0.0
        self.family_unlocked = False  # the PIN was entered this time in Settings
        self.reload()
        self.menu = QuickMenu([])
        self.refresh()
        self.load_for(self.menu.current.key)
        events.record("settings_open")

    # -- data -------------------------------------------------------------------

    def reload(self) -> None:
        try:
            self.config = cfg.load(self.config_path)
            self.all_tiles = cfg.load(self.config_path, hide=False)
        except (OSError, cfg.ConfigError) as e:
            log.error("settings: config: %s", e)
            self.config = self.all_tiles = cfg.Config(rows=())

    def put(self, table: str, key: str, value) -> None:
        settings.put(table, key, value)
        events.record("setting", name=f"{table}.{key}", value=value)
        self.reload()

    def load_for(self, category: str, force: bool = False) -> None:
        """Fetch what a category shows (in the background) the first time it's opened."""
        if category == "storage":  # drives come and go: look every time
            self.jobs.start("drives-load", self._load_drives)
            return
        if category == "audio":  # so do headsets and TVs
            self.jobs.start("audio-load", self._load_audio)
            return
        if category in self.data["loaded"] and not force:
            return
        self.data["loaded"].add(category)
        if category == "network":
            self.jobs.start("net-load", self._load_network)
        elif category == "bluetooth":
            self.jobs.start("bt-load", self._load_bluetooth)
        elif category == "system":
            self.jobs.start("os-load", self._load_os)
        elif category == "privacy":
            self.jobs.start("tv-load", self._load_tv)

    def _load_network(self, rescan: bool = False) -> None:
        if not network.available():
            return None
        self.data["net"] = status = network.status()
        self.data["ip"] = network.ip_config(status.connection) if status.connected and status.connection else None
        self.data["wifi"] = network.wifi_enabled()
        self.data["networks"] = network.networks(rescan) if self.data["wifi"] else []
        return None

    def _load_bluetooth(self) -> None:
        if not bluetooth.available():
            return None
        self.data["bt_power"] = bluetooth.powered()
        self.data["bt"] = bluetooth.devices() if self.data["bt_power"] else []
        return None

    def _load_audio(self) -> None:
        from .audio import Audio, Snapshot

        try:
            self.data["audio"] = Audio().snapshot()
        except (OSError, RuntimeError, ValueError) as e:
            log.warning("settings: audio: %s", e)
            self.data["audio"] = Snapshot()
        return None

    def _load_drives(self) -> None:
        self.data["drives"] = storage.drives()
        return None

    def _load_tv(self) -> None:
        from . import tv

        self.data["tv"] = tv.vendor() or ""  # asks the TV over HDMI-CEC; "" when it can't
        return None

    def _load_os(self) -> None:
        status = updates.os_status()
        self.data["os"] = status
        if self.data["net"] is None and network.available():
            self.data["net"] = network.status()
        return None

    # -- building the pages -----------------------------------------------------

    def refresh(self) -> None:
        self.menu.set_tabs(self.build())
        self._refreshed = time.monotonic()

    def build(self) -> list[Tab]:
        pages = {"appearance": self._appearance, "home": self._home, "audio": self._audio,
                 "controllers": self._controllers,
                 "wii": self._wii, "emulation": self._emulation, "bluetooth": self._bluetooth,
                 "network": self._network, "storage": self._storage, "family": self._family,
                 "privacy": self._privacy,
                 "system": self._system}
        tabs = []
        for key, title, _ in CATEGORIES:
            tab = Tab(key, title, "")
            tab.items = pages[key]()
            tabs.append(tab)
        return tabs

    def note(self, key: str, default: str = "") -> str:
        return self.jobs.messages.get(key, default)

    def _appearance(self) -> list[Item]:
        c = self.config
        names = list(style.LIVERIES)
        return [
            Item("livery", "Livery", "choice", value=names.index(c.livery) if c.livery in names else 0,
                 options=tuple(style.LIVERIES[n].name for n in names), detail="The colour scheme, after a racing car",
                 on_change=lambda i: self.put("theme", "livery", names[i])),
            Item("motion", "Motion", "choice", value=0 if c.motion == "full" else 1, options=("Full", "Reduced"),
                 detail="Reduced: no intro or zoom, menus move instantly",
                 on_change=lambda i: self.put("theme", "motion", ("full", "reduced")[i])),
            Item("clock", "Clock", "choice", value=0 if c.clock == "24h" else 1,
                 options=("24-hour (18:30)", "12-hour (6:30 pm)"),
                 on_change=lambda i: self.put("theme", "clock", ("24h", "12h")[i])),
            Item("safe-area", "Screen edges", "slider", value=c.safe_area, low=0, high=10, step=1,
                 detail="Raise this if your TV cuts off the edges (overscan)",
                 on_change=lambda v: self.put("theme", "safe_area", int(v))),
        ]

    # -- Watch next: Jellyfin and Plex sign-in -------------------------------------

    def _watch_items(self) -> list[Item]:
        from . import watchnext

        acc = watchnext.accounts()
        items = [Item("home-watch", "Watch next: shows and films in progress", "toggle", value=self.config.home_watch,
                      detail="From Jellyfin, Plex and Kodi; pick one to carry on where you stopped",
                      on_change=lambda on: self.put("home", "watch", bool(on)))]
        jf, plex = acc.get("jellyfin"), acc.get("plex")
        if jf:
            items.append(Item("jellyfin", "Jellyfin", "action", confirm=True,
                              detail=self.note("jellyfin", f"Connected to {jf.get('name')} as {jf.get('user')}: "
                                                           "A to disconnect"),
                              on_select=lambda: self._disconnect("jellyfin")))
        else:
            items.append(Item("jellyfin", "Connect Jellyfin", "action",
                              detail=self.note("jellyfin", "Finds your server; approve with a code on your phone"),
                              on_select=self._connect_jellyfin))
        if plex:
            items.append(Item("plex", "Plex", "action", confirm=True,
                              detail=self.note("plex", f"Connected to {plex.get('name')}: A to disconnect"),
                              on_select=lambda: self._disconnect("plex")))
        else:
            items.append(Item("plex", "Connect Plex", "action",
                              detail=self.note("plex", "Shows a code to enter at plex.tv/link"),
                              on_select=lambda: self.jobs.start("plex", self._plex_link, "Asking Plex for a code…")))
        return items

    def _disconnect(self, name: str) -> None:
        from . import watchnext

        watchnext.set_account(name, None)
        self.jobs.messages.pop(name, None)
        events.record("media_disconnect", service=name)
        self.refresh()

    def _connect_jellyfin(self) -> None:
        if self.jobs.messages.get("jellyfin", "").startswith("No Jellyfin server found"):
            self.open_keyboard("Jellyfin server address (e.g. 192.168.1.20)",
                               lambda text: self.jobs.start("jellyfin", lambda: self._jellyfin_link(text),
                                                            "Connecting…"))
            return
        self.jobs.start("jellyfin", self._jellyfin_link, "Looking for your Jellyfin server…")

    def _wait_for(self, key: str, check, message: str, seconds: float = 300, every: float = 3.0):
        """Show `message` and ask check() every few seconds until it returns
        something (or time runs out: None)."""
        self.jobs.messages[key] = message
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            time.sleep(every)
            result = check()
            if result:
                return result
        return None

    def _jellyfin_link(self, address: str | None = None) -> str:
        import urllib.error

        from . import watchnext

        if address:
            server = watchnext.normalize_server(address)
        else:
            found = watchnext.discover_jellyfin()
            if not found:
                return "No Jellyfin server found on this network: press A to type its address"
            server = watchnext.normalize_server(found[0]["Address"])
        try:
            qc = watchnext.quick_connect_start(server)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                return "Turn on Quick Connect in Jellyfin (Dashboard > General), then press A again"
            raise
        except OSError as e:
            return f"Couldn't reach {server}: {getattr(e, 'reason', e)}"
        code = qc["Code"]
        account = self._wait_for("jellyfin", lambda: watchnext.quick_connect_finish(server, qc["Secret"]),
                                 f"Enter code {code[:3]} {code[3:]} in Jellyfin on your phone: "
                                 "your profile > Quick Connect")
        if account is None:
            return "The code ran out: press A for a new one"
        watchnext.set_account("jellyfin", account)
        events.record("media_connect", service="jellyfin")
        watchnext.refresh_soon()
        return f"Connected to {account['name']} as {account['user']}"

    def _plex_link(self) -> str:
        from . import watchnext

        pin = watchnext.plex_pin_start()
        account = self._wait_for("plex", lambda: watchnext.plex_pin_finish(pin["id"]),
                                 f"Go to plex.tv/link on your phone and enter {pin['code']}")
        if account is None:
            return "The code ran out: press A for a new one"
        if not account["servers"]:
            return "Signed in, but no Plex server found on your account"
        watchnext.set_account("plex", account)
        events.record("media_connect", service="plex")
        watchnext.refresh_soon()
        return f"Connected to {account['name']}"

    def _reset_order(self) -> None:
        data = settings.load()
        data.pop("order", None)
        settings.save(data)
        self.jobs.messages["home-order"] = "Done: tiles are back in their usual order"
        self.refresh()

    def _home(self) -> list[Item]:
        from . import ctl

        hidden = set(settings.load().get("hide", []))
        c = self.config
        saver = (0, 5, 10, 15, 30, 60)
        sleep = (0, 30, 60, 120, 240)
        items = [
            Item("home-recent", "Continue: recently played games", "toggle", value=c.home_recent,
                 detail="A row of what you played last, Steam and emulated",
                 on_change=lambda on: self.put("home", "recent", bool(on))),
            *self._watch_items(),
            Item("home-pins", "Favorites row", "toggle", value=c.home_pins,
                 detail="Press X on any tile to star it (Y → Move to reorder); ES-DE favourites show too",
                 on_change=lambda on: self.put("home", "pins", bool(on))),
            Item("sounds", "Sounds", "toggle", value=c.sounds,
                 detail="A soft tick as you move, a chime when something opens",
                 on_change=lambda on: self.put("home", "sounds", bool(on))),
            Item("home-order", "Put tiles back in their usual order", "action", confirm=True,
                 detail=self.note("home-order", "Undoes Options → Move in every row (favourites stay)"),
                 on_select=self._reset_order),
            Item("quick-resume", "Quick Resume", "choice", value=c.quick_resume,
                 options=("Off", "Keep 1 game paused", "Keep 2 games paused", "Keep 3 games paused"),
                 detail="Hold Guide in a game to pause it and go home; it waits in a row up top",
                 on_change=lambda i: self.put("home", "quick_resume", int(i))),
            Item("saver", "Screen saver", "choice",
                 value=saver.index(c.screensaver_minutes) if c.screensaver_minutes in saver else 2,
                 options=tuple("Never" if m == 0 else f"After {m} minutes" if m < 60 else "After 1 hour"
                               for m in saver),
                 detail="Protects OLED TVs from a still picture",
                 on_change=lambda i: self.put("home", "screensaver_minutes", saver[i])),
            Item("saver-style", "Screen saver shows", "choice", value=0 if c.screensaver == "ambient" else 1,
                 options=("Your games' art", "Just the time"),
                 detail="Art drifts slowly and is dimmed, so it's kind to OLED TVs",
                 on_change=lambda i: self.put("home", "screensaver", ("ambient", "clock")[i])),
            Item("idle-sleep", "Sleep when left on the home screen", "choice",
                 value=sleep.index(c.sleep_minutes) if c.sleep_minutes in sleep else 0,
                 options=tuple("Never" if m == 0 else f"After {m} minutes" if m < 60 else
                               f"After {m // 60} hour{'s' if m > 60 else ''}" for m in sleep),
                 on_change=lambda i: self.put("home", "sleep_minutes", sleep[i])),
        ]
        for row in self.all_tiles.rows:
            for app in row.apps:
                if app.id in ("settings", "library"):
                    continue  # always there: Settings is how you'd get tiles back
                why = app.missing()
                items.append(Item(
                    f"tile-{app.id}", app.name, "toggle", value=app.id not in hidden,
                    detail=f"{row.title} row" + (" · shows once installed" if why else ""),
                    on_change=lambda on, a=app.id: (settings.set_hidden(a, not on), self.reload())))
        steam = ctl.disabled_flag().exists()
        if steam:
            items.append(Item("boot", "Start Game Mode in Hearth again", "action",
                              detail="Game Mode currently starts Steam. Takes effect after a restart",
                              on_select=lambda: self._set_boot_steam(False)))
        else:
            items.append(Item("boot", "Start Game Mode in Steam instead", "action", confirm=True,
                              detail="Takes effect after a restart. Undo from Desktop Mode: hearthctl enable",
                              on_select=lambda: self._set_boot_steam(True)))
        return items

    def _set_boot_steam(self, steam: bool) -> None:
        from . import ctl

        ctl.cmd_enable(not steam)
        self.jobs.messages["boot"] = "Saved: restart to apply"
        self.refresh()
        return None

    def _controllers(self) -> list[Item]:
        c = self.config
        items = []
        if pygame.joystick.get_init():
            names = [pygame.joystick.Joystick(i).get_name() for i in range(pygame.joystick.get_count())]
        else:
            names = []
        items.append(Item("connected", "Connected controllers", "info",
                          detail=", ".join(names) if names else "None right now"))
        items.append(Item("guide-hold", "Hold Guide to go home", "slider", value=c.guide_hold,
                          low=0.5, high=3.0, step=0.25, unit="{:g} s",
                          detail="How long to hold before you're back home",
                          on_change=lambda v: self.put("controllers", "guide_hold_seconds", float(v))))
        items.append(Item("guide-action", "Holding Guide in a game", "choice",
                          value=0 if c.guide_hold_action == "resume" else 1,
                          options=("Keeps it paused (Quick Resume)", "Closes it"),
                          detail="Quick Resume must be on to keep games paused",
                          on_change=lambda i: self.put("controllers", "guide_hold", ("resume", "close")[i])))
        items.append(Item("deadzone", "Stick dead zone", "slider", value=c.stick_deadzone,
                          low=5, high=40, step=5, unit="{:g}%",
                          detail="Raise it if a worn stick drifts in Hearth's menus or moves the pointer on its own",
                          on_change=lambda v: self.put("controllers", "stick_deadzone", int(v))))
        items.append(Item("mouse-speed", "Controller mouse speed", "slider", value=c.mouse_speed,
                          low=25, high=300, step=25, detail="Discord and other pointer apps",
                          on_change=lambda v: self.put("controllers", "mouse_speed", int(v))))
        items.append(Item("pause", "Pause the game under the Quick Menu", "toggle", value=c.pause_game,
                          on_change=lambda on: self.put("quick_menu", "pause_game", bool(on))))
        items.append(Item("confirm", "Confirm button", "choice", value=0 if c.confirm == "south" else 1,
                          options=("Bottom (Xbox, PlayStation)", "Right (Nintendo)"),
                          detail="In Hearth's menus. Games use their own layout",
                          on_change=lambda i: self.put("controllers", "confirm", ("south", "east")[i])))
        styles = ("auto", "xbox", "playstation", "nintendo")
        items.append(Item("prompts", "Button names on screen", "choice", value=styles.index(c.prompts),
                          options=("Automatic: what you used last", "Xbox: A B X Y", "PlayStation: shapes",
                                   "Nintendo: B A Y X"),
                          on_change=lambda i: self.put("controllers", "prompts", styles[i])))
        return items

    def _emulation(self) -> list[Item]:
        from . import emutune

        c = self.config
        choices = ("auto", "1080p", "1440p", "4k")
        height = emutune.target_height(c.emulation_resolution)
        tuned = set(settings.load().get("emulation_tuned", []))
        results = self.data.get("tune") or {}
        items = [
            Item("emu-res", "Upscale for", "choice", value=choices.index(c.emulation_resolution),
                 options=(f"Auto: your TV ({height}p)", "1080p", "1440p", "4K"),
                 detail="How sharp emulated games are drawn: higher needs a stronger GPU",
                 on_change=lambda i: self.put("emulation", "resolution", choices[i])),
            Item("emu-apply", "Apply recommended settings", "action",
                 detail=self.note("emu-apply", "Vulkan, upscaling, stutter-free shaders. Keeps a backup"),
                 on_select=self._tune),
        ]
        for tune in emutune.TUNES:
            if not emutune.installed(tune):
                continue
            state = results.get(tune.name) or (tune.summary(height) if tune.key in tuned
                                               else "Tuned automatically after you first open it")
            items.append(Item(f"emu-{tune.app}", tune.name, "info", detail=state))
        items.append(Item("emu-more", "Cemu, Eden, Azahar, RPCS3, xemu", "info",
                          detail="Recommended settings for these are in docs/EMULATION.md"))
        return items

    def _tune(self) -> None:
        from . import emutune

        def work() -> str:
            results = emutune.apply_all(self.config.emulation_resolution)
            self.data["tune"] = results
            data = settings.load()
            done = set(data.get("emulation_tuned", []))
            done |= {t.key for t in emutune.TUNES if results.get(t.name, "").startswith(("Vulkan",))}
            data["emulation_tuned"] = sorted(done)
            settings.save(data)
            events.record("emulators_tuned", manual=True, results=results)
            changed = sum(r.startswith("Vulkan") for r in results.values())
            return f"Done: {changed} emulator{'s' if changed != 1 else ''} updated"

        self.jobs.start("emu-apply", work, "Applying…")
        return None

    def _wii_status(self) -> str:
        state = session.read().get("wii") or {}
        slots = wiimote.find()
        if slots:
            if state.get("dolphin"):
                return "Dolphin is using the remotes right now"
            n = len(state.get("connected") or [])
            if n:
                return f"DolphinBar ready · {n} remote{'s' if n > 1 else ''} connected"
            return "DolphinBar ready · pair a remote: sync on the bar, then the red button in the remote"
        try:
            names = Path("/proc/bus/input/devices").read_text(errors="replace").lower()
        except OSError:
            names = ""
        if "mayflash" in names or "dolphinbar" in names:
            return "The DolphinBar isn't in mode 4: press its mode button until LED 4 lights"
        return "No DolphinBar found"

    def _wii(self) -> list[Item]:
        c = self.config
        calibrated = c.wii_calibration is not None
        items = [
            Item("wii-status", "Status", "info", detail=self._wii_status()),
            Item("wii-enabled", "Use Wii Remotes in Hearth", "toggle", value=c.wii_remote,
                 detail="Off: Hearth leaves them to Dolphin only",
                 on_change=lambda on: self.put("wii_remote", "enabled", bool(on))),
            Item("wii-bar", "Sensor bar", "choice", value=0 if c.wii_bar == "below" else 1,
                 options=("Below the TV", "Above the TV"),
                 on_change=lambda i: self.put("wii_remote", "sensor_bar", ("below", "above")[i])),
            Item("wii-hold", "Hold the remote", "choice", value=0 if c.wii_hold == "upright" else 1,
                 options=("Pointing at the TV", "Sideways (NES style)"),
                 detail="Sideways turns the D-pad and makes 2 / 1 the main buttons",
                 on_change=lambda i: self.put("wii_remote", "hold", ("upright", "sideways")[i])),
            Item("wii-speed", "Pointer speed", "slider", value=c.wii_speed, low=25, high=300, step=5,
                 detail="Calibrated: this is measured instead" if calibrated else "",
                 on_change=lambda v: self.put("wii_remote", "speed", int(v))),
            Item("wii-steady", "Pointer steadiness", "slider", value=c.wii_steadiness, low=0, high=90, step=5,
                 detail="Higher is steadier, lower is quicker",
                 on_change=lambda v: self.put("wii_remote", "steadiness", int(v))),
            Item("wii-flip", "Flip up/down", "toggle", value=c.wii_flip,
                 detail="Turn on if the pointer moves up when you aim down",
                 on_change=lambda on: self.put("wii_remote", "flip_vertical", bool(on))),
            Item("wii-mouse", "Use the pointer as a mouse", "choice",
                 value=("apps", "always", "never").index(c.wii_mouse),
                 options=("In pointer apps (Discord)", "Always", "Never"),
                 on_change=lambda i: self.put("wii_remote", "mouse", ("apps", "always", "never")[i])),
            Item("wii-calibrate", "Calibrate the pointer", "action",
                 detail=self.note("wii-calibrate", "Calibrated" if calibrated else
                                  "Aim at two targets so the pointer lands exactly where you point"),
                 on_select=self.start_calibration),
        ]
        if calibrated:
            items.append(Item("wii-uncalibrate", "Forget the calibration", "action", confirm=True,
                              detail="Go back to using the sensor bar and speed settings",
                              on_select=lambda: (self.put("wii_remote", "calibration", None), None)[1]))
        return items

    def _bluetooth(self) -> list[Item]:
        d = self.data
        if not bluetooth.available():
            return [Item("bt-none", "Bluetooth isn't available", "info", detail="bluetoothctl isn't installed")]
        if d["bt_power"] is None and "bluetooth" in d["loaded"] and not self.jobs.busy("bt-load"):
            return [Item("bt-none", "No Bluetooth adapter found", "info",
                         detail="An Intel AX210 card is the most reliable choice on Linux")]
        items = [Item("bt-power", "Bluetooth", "toggle", value=bool(d["bt_power"]),
                      on_change=lambda on: self.jobs.start("bt-power", lambda: (bluetooth.set_power(on),
                                                                                self._load_bluetooth())[1]))]
        if d["bt_power"]:
            items.append(Item("bt-scan", "Search for devices", "action",
                              detail=self.note("bt-scan", "Put the controller in pairing mode first"),
                              on_select=self._bt_scan))
            for dev in d["bt"]:
                if dev.paired:
                    items.append(Item(f"bt-{dev.mac}", dev.name, "action",
                                      detail=self.note(f"bt-{dev.mac}", dev.describe() +
                                                       (" · A: disconnect" if dev.connected else " · A: connect")),
                                      on_select=lambda dev=dev: self._bt_toggle(dev)))
                    items.append(Item(f"bt-forget-{dev.mac}", f"Forget {dev.name}", "action", confirm=True,
                                      on_select=lambda dev=dev: self._bt_job(f"bt-{dev.mac}", "Forgetting…",
                                                                             lambda: bluetooth.forget(dev.mac))))
                elif dev.name != dev.mac and not bluetooth.MAC.match(dev.name):
                    items.append(Item(f"bt-{dev.mac}", f"Pair {dev.name}", "action",
                                      detail=self.note(f"bt-{dev.mac}", dev.describe()),
                                      on_select=lambda dev=dev: self._bt_job(
                                          f"bt-{dev.mac}", "Pairing…", lambda: bluetooth.pair(dev.mac)[1])))
        return items

    def _bt_scan(self) -> None:
        def work() -> str:
            bluetooth.scan(12)
            self._load_bluetooth()
            return "Done: devices found are listed below"

        self.jobs.start("bt-scan", work, "Searching for 12 seconds…")
        return None

    def _bt_job(self, key: str, busy: str, work: Callable) -> None:
        def run() -> str | None:
            result = work()
            self._load_bluetooth()
            return result if isinstance(result, str) else None

        self.jobs.start(key, run, busy)
        return None

    def _bt_toggle(self, dev: bluetooth.Device) -> None:
        if dev.connected:
            return self._bt_job(f"bt-{dev.mac}", "Disconnecting…", lambda: bluetooth.disconnect(dev.mac))
        return self._bt_job(f"bt-{dev.mac}", "Connecting… (turn it on)",
                            lambda: None if bluetooth.connect(dev.mac) else "Couldn't connect: is it on?")

    def _network(self) -> list[Item]:
        d = self.data
        if not network.available():
            return [Item("net-none", "Networking settings aren't available", "info",
                         detail="NetworkManager (nmcli) isn't installed")]
        status = d["net"]
        items = [Item("net-status", "Connection", "info",
                      detail=self.note("net", status.describe() if status else "Checking…")),
                 Item("net-test", "Test the connection", "action",
                      detail=self.note("net-test", "Router, internet and name lookups"),
                      on_select=lambda: self.jobs.start("net-test", network.test, "Testing…"))]
        if status and status.connected and d["ip"] is not None:
            items += self._ip_items(status, d["ip"])
        if d["wifi"] is not None:
            items.append(Item("wifi", "Wi-Fi", "toggle", value=bool(d["wifi"]),
                              on_change=lambda on: self.jobs.start("net", lambda: (network.set_wifi(on),
                                                                                   self._load_network())[1])))
        if d["wifi"]:
            items.append(Item("wifi-scan", "Scan for networks", "action",
                              detail=self.note("wifi-scan", "Look for Wi-Fi networks again"),
                              on_select=lambda: self.jobs.start(
                                  "wifi-scan", lambda: (self._load_network(rescan=True), "Done")[1], "Scanning…")))
            for net in d["networks"]:
                items.append(Item(f"wifi-{net.ssid}", net.ssid, "action",
                                  detail=self.note(f"wifi-{net.ssid}", net.describe()),
                                  on_select=lambda net=net: self._wifi_connect(net)))
                if net.saved or net.in_use:
                    items.append(Item(f"wifi-forget-{net.ssid}", f"Forget {net.ssid}", "action", confirm=True,
                                      on_select=lambda net=net: self._net_job(
                                          f"wifi-{net.ssid}", "Forgetting…",
                                          lambda: None if network.forget(net.ssid) else "Couldn't forget it")))
        return items

    DNS_CHOICES = ("Automatic (from the router)", *network.DNS_PRESETS, "Custom")

    def _ip_items(self, status: network.Status, ip: network.IpConfig) -> list[Item]:
        """IP address and DNS for the connection in use. Choosing only picks;
        Apply changes it (each change reconnects)."""
        conn = status.connection
        method = self.ip_method or ip.method
        items = [Item("ip-method", "IP address", "choice", value=1 if method == "manual" else 0,
                      options=("Automatic (DHCP)", "Manual (static)"),
                      detail=self.note("ip-method", f"This PC: {status.address or '?'} on {conn}"),
                      on_change=lambda i: self._ip_method(ip, status, i))]
        if method == "manual":
            edit = self.ip_edit or self._ip_start(ip, status)
            items += [
                Item("ip-address", "Address", "action", detail=edit["address"] or "Not set: A to type it",
                     on_select=lambda: self._ip_type("address", "This PC's address, like 192.168.1.50")),
                Item("ip-prefix", "Subnet prefix", "slider", value=edit["prefix"], low=8, high=30, step=1,
                     unit="/{}", detail=f"Mask {network_mask(edit['prefix'])} (24 for most home networks)",
                     on_change=lambda v: self._ip_set("prefix", int(v))),
                Item("ip-gateway", "Router (gateway)", "action", detail=edit["gateway"] or "Not set: A to type it",
                     on_select=lambda: self._ip_type("gateway", "The router's address, like 192.168.1.1")),
            ]
        if method == "manual" or ip.method == "manual":
            items.append(Item("ip-apply", "Apply", "action", confirm=True,
                              confirm_label="Press A again: reconnect with these settings",
                              detail=self.note("ip-apply", "Reconnects; Automatic puts things back if it goes wrong"),
                              on_select=lambda: self._ip_apply(conn, method)))
        current = self.DNS_CHOICES.index(ip.dns_choice) if ip.dns_choice in self.DNS_CHOICES else 0
        shown = current if self.dns_choice is None else self.dns_choice
        name = self.DNS_CHOICES[shown]
        servers = ip.dns if shown == current and ip.dns else network.DNS_PRESETS.get(name, ())
        items.append(Item("dns", "DNS servers", "choice", value=shown, options=self.DNS_CHOICES,
                          detail=self.note("dns", ", ".join(servers) if servers else
                                           "Type them in after Apply" if name == "Custom" else "The router's"),
                          on_change=lambda i: setattr(self, "dns_choice", i)))
        if shown != current or name == "Custom":
            items.append(Item("dns-apply", "Apply DNS" if name != "Custom" else "Type custom DNS servers", "action",
                              detail=self.note("dns-apply", "Reconnects with them"),
                              on_select=lambda: self._dns(conn, ip, shown)))
        return items

    def _ip_start(self, ip: network.IpConfig, status: network.Status) -> dict:
        address, _, prefix = (ip.address or "").partition("/")
        self.ip_edit = {"address": address or status.address or "", "prefix": int(prefix or 24),
                        "gateway": ip.gateway or network.gateway()}
        return self.ip_edit

    def _ip_set(self, field: str, value) -> None:
        if self.ip_edit is not None:
            self.ip_edit[field] = value

    def _ip_method(self, ip: network.IpConfig, status: network.Status, i: int) -> None:
        self.ip_method = "manual" if i == 1 else "auto"
        if i == 1 and self.ip_edit is None:
            self._ip_start(ip, status)

    def _ip_type(self, field: str, title: str) -> None:
        def done(text: str) -> None:
            self._ip_set(field, text.strip())
            self.refresh()

        self.open_keyboard(title, done, text=(self.ip_edit or {}).get(field, ""))
        return None

    def _ip_apply(self, conn: str, method: str) -> None:
        if method == "auto":
            work = lambda: network.set_automatic(conn)  # noqa: E731
        else:
            edit = dict(self.ip_edit or {})
            problem = network.validate(edit.get("address", ""), edit.get("prefix", 24), edit.get("gateway", ""))
            if problem:
                self.jobs.messages["ip-apply"] = problem
                return None
            work = lambda: network.set_manual(conn, edit["address"], edit["prefix"], edit["gateway"])  # noqa: E731

        def run() -> str:
            ok, message = work()
            if ok:
                self.ip_method = None
                self.ip_edit = None
            return message

        self._net_job("ip-apply", "Reconnecting…", run)
        return None

    def _dns(self, conn: str, ip: network.IpConfig, choice: int) -> None:
        def apply(servers: tuple[str, ...] | None) -> None:
            def run() -> str:
                ok, message = network.set_dns(conn, servers)
                if ok:
                    self.dns_choice = None
                return message

            self._net_job("dns-apply", "Reconnecting…", run)

        name = self.DNS_CHOICES[choice]
        if name != "Custom":
            apply(network.DNS_PRESETS.get(name))
            return None

        def typed(text: str) -> None:
            servers = network.parse_dns(text)
            if isinstance(servers, str):
                self.jobs.messages["dns-apply"] = servers
                return
            apply(servers)

        self.open_keyboard("DNS servers, like 1.1.1.1 8.8.8.8", typed,
                           text=" ".join(ip.dns) if ip.dns_choice == "Custom" else "")
        return None

    def _net_job(self, key: str, busy: str, work: Callable[[], str | None]) -> None:
        def run() -> str | None:
            result = work()
            self._load_network()
            return result

        self.jobs.start(key, run, busy)
        return None

    def _wifi_connect(self, net: network.Network) -> None:
        key = f"wifi-{net.ssid}"
        if net.in_use:
            self.jobs.messages[key] = "Already connected"
            return None
        if net.secure and not net.saved:
            def submit(password: str) -> None:
                self._net_job(key, "Connecting…", lambda: network.connect(net.ssid, password)[1])

            self.open_keyboard(f"Password for {net.ssid}", submit, secret=True)
            return None
        return self._net_job(key, "Connecting…", lambda: network.connect(net.ssid, saved=net.saved)[1])

    def _audio(self) -> list[Item]:
        from .audio import Audio

        snap = self.data["audio"]
        if snap is None:
            return [Item("audio-none", "Looking for audio devices…", "info")]
        if not snap.outputs and not snap.inputs:
            return [Item("audio-none", "No audio devices found", "info", detail="Is PipeWire running?")]
        a = Audio()
        items = []
        out, mic = snap.output(), snap.input()
        if snap.outputs:
            names = [d.name for d in snap.outputs]
            items.append(Item("audio-output", "Sound plays through", "choice",
                              options=tuple(d.label for d in snap.outputs),
                              value=names.index(snap.default_output) if snap.default_output in names else 0,
                              detail=self.note("audio-output", "The default for every app, remembered after restart"),
                              on_change=lambda i: self._audio_job("audio-output",
                                                                  lambda: a.set_output(names[i], snap))))
        if out:
            items.append(Item("audio-volume", "Volume", "slider", value=min(100, out.percent), muted=out.muted,
                              on_change=lambda v, n=out.name: a.set_output_volume(n, v),
                              on_mute=lambda m, n=out.name: a.set_output_muted(n, m)))
            items.append(Item("audio-test", "Play a test sound", "action",
                              detail=self.note("audio-test", f"Through {out.label}"),
                              on_select=lambda: self.jobs.start("audio-test", play_test_sound)))
        if snap.inputs:
            names_in = [d.name for d in snap.inputs]
            items.append(Item("audio-input", "Microphone", "choice", options=tuple(d.label for d in snap.inputs),
                              value=names_in.index(snap.default_input) if snap.default_input in names_in else 0,
                              detail=self.note("audio-input", "For voice chat (Discord, games)"),
                              on_change=lambda i: self._audio_job("audio-input",
                                                                  lambda: a.set_input(names_in[i], snap))))
        else:
            items.append(Item("audio-input", "Microphone", "info", detail="None connected"))
        if mic:
            items.append(Item("audio-mic-level", "Microphone level", "slider", value=min(100, mic.percent),
                              muted=mic.muted,
                              on_change=lambda v, n=mic.name: a.set_input_volume(n, v),
                              on_mute=lambda m, n=mic.name: a.set_input_muted(n, m)))
            items.append(Item("audio-mic-mute", "Mute microphone", "toggle", value=mic.muted,
                              on_change=lambda m, n=mic.name: self._audio_job("audio-mic-mute",
                                                                              lambda: a.set_input_muted(n, m))))
        return items

    def _audio_job(self, key: str, work: Callable[[], None]) -> None:
        def run() -> None:
            work()
            self._load_audio()

        self.jobs.start(key, run)

    def _storage(self) -> list[Item]:
        free, total = storage.system_space()
        items = [
            Item("storage", "This PC's drive", "info",
                 detail=f"{storage.gb(free)} free of {storage.gb(total)}" if total else "?"),
            Item("storage-use", "What's using space", "action",
                 detail=self.note("storage-use", "Games, ROMs and emulator data"),
                 on_select=lambda: self.jobs.start("storage-use", storage_breakdown, "Measuring…")),
            Item("drives-scan", "Look for drives again", "action",
                 detail=self.note("drives-scan", "After plugging one in or fitting one inside"),
                 on_select=lambda: self.jobs.start("drives-scan", lambda: (self._load_drives(), None)[1],
                                                   "Looking…")),
        ]
        drives = self.data["drives"]
        if drives is None:
            items.append(Item("drives-none", "Looking for drives…", "info"))
        elif not drives:
            items.append(Item("drives-none", "No other drives", "info",
                              detail="Plug one in (USB) or fit one inside, then look again"))
        for drive in drives or ():
            items += self._drive_items(drive)
        return items

    def _drive_items(self, drive: storage.Drive) -> list[Item]:
        key = f"drive-{drive.path}"
        mount = drive.mounted_at
        if mount and drive.ready:
            try:
                free = f"{storage.gb(shutil.disk_usage(mount).free)} free"
            except OSError:
                free = ""
            games = storage.steam_games_on(mount)
            items = [
                Item(key, drive.name, "info",
                     detail=self.note(key, " · ".join(p for p in (f"Ready at {mount}", free) if p))),
                Item(f"{key}-steam", "Steam games on it", "toggle", value=storage.has_steam_library(mount),
                     detail=self.note(f"{key}-steam", f"{games} installed there" if games else
                                      "Then choose it when installing a game in Steam"),
                     on_change=lambda on: self._drive_job(f"{key}-steam", "Updating Steam's library list…",
                                                          lambda: (storage.add_steam_library if on
                                                                   else storage.remove_steam_library)(mount))),
                Item(f"{key}-roms", "ROMs on it", "toggle", value=storage.roms_on(mount),
                     detail=self.note(f"{key}-roms", "Moves your ROMs folder there; ES-DE finds them as before"),
                     on_change=lambda on: self._move_roms(f"{key}-roms", mount, on)),
                Item(f"{key}-release", "Stop using it", "action", confirm=True,
                     detail=self.note(f"{key}-release", "Nothing on it is erased; it can be unplugged after"),
                     on_select=lambda: self._release(drive)),
            ]
            return items
        if mount:  # set up by Hearth, but not mounted right now
            return [
                Item(key, drive.name, "info", detail=self.note(key, "Set up, but not mounted: restart to use it")),
                Item(f"{key}-release", "Forget it", "action", confirm=True,
                     detail=self.note(f"{key}-release", "Stop looking for it at start-up"),
                     on_select=lambda: self._release(drive)),
            ]
        items = [Item(key, drive.name, "info",
                      detail=self.note(key, f"Not set up · on it now: {drive.contents}"))]
        part = drive.usable_part
        if part is not None:
            items.append(Item(f"{key}-use", "Use it for games (keeps its files)", "action",
                              detail=f"It's formatted {part.fstype}, which suits Linux games",
                              on_select=lambda: self._drive_job(
                                  key, "Setting it up…",
                                  lambda: storage.use(part, storage.free_name(drive))[1])))
        items.append(Item(f"{key}-erase", "Erase it and set it up for games", "action", confirm=True,
                          confirm_label=f"Press A again to erase {drive.model or 'this drive'}",
                          detail=f"Deletes everything on it: {drive.contents}",
                          on_select=lambda: self._drive_job(
                              key, "Erasing and setting it up… (a minute or so)",
                              lambda: storage.erase(drive, storage.free_name(drive))[1])))
        return items

    def _drive_job(self, key: str, busy: str, work: Callable[[], str | None]) -> None:
        def run() -> str | None:
            try:
                return work()
            finally:
                self._load_drives()

        self.jobs.start(key, run, busy)
        return None

    def _move_roms(self, key: str, mount: str, on: bool) -> None:
        def progress(message: str) -> None:
            self.jobs.messages[key] = message

        to = Path(mount) / storage.ROMS_FOLDER if on else storage.roms_link()
        self._drive_job(key, "Moving ROMs…", lambda: storage.move_roms(to, progress=progress))
        return None

    def _release(self, drive: storage.Drive) -> None:
        key = f"drive-{drive.path}-release"
        busy = storage.in_use(drive)
        if busy:
            self.jobs.messages[key] = f"It still has {' and '.join(busy)}: turn those off first"
            return None
        part = drive.mounted_part
        if part is None:
            return None
        self._drive_job(f"drive-{drive.path}", "Stopping…", lambda: storage.release(part)[1])
        return None

    # -- Family: household limits behind a PIN ----------------------------------------

    def _family(self) -> list[Item]:
        from . import family

        r = family.rules()
        if not r.active:
            return [
                Item("family-about", "Household limits", "info",
                     detail="For everyone on this PC: a daily game-time limit, a bedtime, locked tiles"),
                Item("family-pin", "Set a PIN to start", "action", detail=self.note(
                     "family-pin", f"{family.PIN_LENGTH} digits; you'll need it to change these, or to play past "
                                   "the limits"),
                     on_select=self._set_pin),
            ]
        if not self.family_unlocked:
            return [Item("family-unlock", "Enter the PIN to change these", "action",
                         detail=self.note("family-unlock", "Household limits are on"),
                         on_select=self._unlock_family)]
        played = family.played_today()
        daily = list(family.DAILY_CHOICES)
        bed = list(family.BEDTIMES)
        items = [
            Item("family-daily", "Game time each day", "choice",
                 value=daily.index(r.daily_minutes) if r.daily_minutes in daily else 0,
                 options=tuple("No limit" if m == 0 else family.minutes_text(m * 60) for m in daily),
                 detail=f"Played today: {family.minutes_text(played)}. Films and TV apps don't count",
                 on_change=lambda i: self.put("family", "daily_minutes", daily[i])),
            Item("family-bedtime", "Bedtime", "choice", value=bed.index(r.bedtime) if r.bedtime in bed else 0,
                 options=tuple("None" if not b else b.replace("-", " to ") for b in bed),
                 detail="Games need the PIN in these hours",
                 on_change=lambda i: self.put("family", "bedtime", bed[i])),
            Item("family-when", "When time's up", "choice", value=1 if r.when_up == "close" else 0,
                 options=("Remind", "Close the game"),
                 detail="Closing warns a minute first, to save. The PIN gives "
                        f"{family.EXTRA_MINUTES} minutes more",
                 on_change=lambda i: self.put("family", "when_up", ("remind", "close")[i])),
        ]
        items.append(Item("family-locks", "Locked tiles", "info",
                          detail="These always need the PIN, whatever the time"))
        for row in self.config.rows:
            for app in row.apps:
                if app.builtin:
                    continue
                items.append(Item(f"lock-{app.id}", app.name, "toggle", value=app.id in r.locked,
                                  on_change=lambda on, a=app.id: self._set_locked(a, on)))
        items += [
            Item("family-change", "Change the PIN", "action", detail=self.note("family-pin", ""),
                 on_select=self._set_pin),
            Item("family-off", "Turn household limits off", "action", confirm=True,
                 detail="Removes the PIN and every limit", on_select=self._family_off),
        ]
        return items

    def _set_locked(self, app_id: str, on: bool) -> None:
        from . import family

        locked = family.rules().locked
        (locked.add if on else locked.discard)(app_id)
        self.put("family", "locked", sorted(locked))

    def _set_pin(self) -> None:
        from . import family

        def chosen(pin: str) -> None:
            if not family.valid_pin(pin):
                self.jobs.messages["family-pin"] = f"A PIN is {family.PIN_LENGTH} digits: try again"
            else:
                family.set_pin(pin)
                self.family_unlocked = True
                self.jobs.messages["family-pin"] = "PIN set"
                events.record("family_pin_set")
            self.refresh()

        self.open_keyboard(f"New PIN ({family.PIN_LENGTH} digits)", chosen, secret=True)

    def _unlock_family(self) -> None:
        from . import family

        def entered(pin: str) -> None:
            self.family_unlocked = family.check_pin(pin)
            self.jobs.messages["family-unlock"] = "" if self.family_unlocked else "Not that one"
            events.record("family_unlock", ok=self.family_unlocked)
            self.refresh()

        self.open_keyboard("PIN", entered, secret=True)

    def _family_off(self) -> None:
        from . import family

        family.set_pin(None)
        self.family_unlocked = False
        events.record("family_off")
        self.refresh()

    def _privacy(self) -> list[Item]:
        from . import privacy

        detected = privacy.guide_for(self.data["tv"])
        chosen = (settings.load().get("privacy") or {}).get("tv")
        guide = privacy.BY_KEY.get(chosen) or detected
        keys = [g.key for g in privacy.GUIDES]
        if self.data["tv"] is None:
            how = "Asking the TV…"
        elif detected is not None:
            how = f"Found over HDMI: {self.data['tv']}"
        elif self.data["tv"]:
            how = f"Your TV calls itself {self.data['tv']}: pick the closest"
        else:
            how = "Pick your TV's make (Hearth can tell with a CEC adapter)"
        items = [
            Item("hearth", "Hearth", "info", detail=privacy.HEARTH_PROMISE),
            Item("leaves", "What leaves this PC", "info", detail=privacy.WHAT_LEAVES),
            Item("tv-make", "Your TV", "choice", value=keys.index(guide.key) if guide else len(keys) - 1,
                 options=tuple(g.name for g in privacy.GUIDES), detail=how,
                 on_change=lambda i: self.put("privacy", "tv", keys[i])),
            Item("tv-why", "Turn off your TV's tracking", "info", detail=privacy.WHY_TV),
        ]
        shown = guide or privacy.BY_KEY["other"]
        items += [Item(f"tv-step-{n}", f"Step {n}", "info", detail=step) for n, step in enumerate(shown.steps, 1)]
        items.append(Item("tv-look", "Can't find it?", "info",
                          detail=f"Menus move between models: search the TV's settings for {shown.look_for}"))
        return items

    def _system(self) -> list[Item]:
        d = self.data
        os_status = d["os"]
        items = [
            Item("version", "Hearth", "info", detail=updates.hearth_version()),
            Item("os", "Operating system", "info",
                 detail=(f"{os_status.image or 'unknown image'} · {os_status.booted or '?'}" if os_status
                         else "Checking…")),
            Item("hardware", "Hardware", "info", detail=hardware_summary()),
            Item("temps", "Temperatures", "info", detail=temperatures() or "Not available"),
            Item("address", "Network address", "info",
                 detail=(d["net"].address or "Not connected") if d["net"] else "Checking…"),
            Item("updates", "Check for updates", "action",
                 detail=self.note("updates", "Updates also install automatically in the background"),
                 on_select=lambda: self.jobs.start("updates", self._update, "Updating… keep using Hearth")),
            Item("report", "Report a problem", "action",
                 detail=self.note("report", "Saves details for fixing a problem to your hearth-reports folder"),
                 on_select=lambda: self.jobs.start("report", self._report, "Saving a report…")),
        ]
        desktop = self.config.app("desktop")
        if desktop is not None:
            items.append(Item("desktop", "Desktop Mode", "action", confirm=True,
                              detail="For adding games and maintenance",
                              on_select=lambda: self._open(desktop)))
        return items

    def _update(self) -> str:
        from . import logs

        ok = updates.run_helper("apply", logs.log_path())
        status = updates.os_status()
        if not ok:
            return "Update failed: the reason is in hearthctl logs"
        return f"Version {status.staged} is ready: restart to finish" if status.update_ready else "Up to date"

    def _report(self) -> str:
        from . import report

        return f"Saved {report.make().name}"

    def _open(self, app: App) -> str:
        self.launch = app
        return "exit"

    # -- keyboard and calibration -----------------------------------------------

    def open_keyboard(self, title: str, done: Callable[[str], None], secret: bool = False, text: str = "") -> None:
        self.keyboard = Keyboard(title, secret, text)
        self._keyboard_done = done

    def start_calibration(self) -> None:
        self.calibrating = Calibration()
        session.update(lambda s: s.__setitem__("wii_raw", True))
        return None

    def _stop_calibration(self) -> None:
        self.calibrating = None
        session.update(lambda s: s.__setitem__("wii_raw", False))

    # -- input ------------------------------------------------------------------

    def handle(self, nav: Nav) -> str | None:
        """Returns "exit" to leave the Settings app."""
        if self.keyboard is not None:
            result = self.keyboard.handle(nav)
            if result == "done" and self._keyboard_done:
                self._keyboard_done(self.keyboard.text)
            if result in ("done", "cancel"):
                self.keyboard = None
            return None
        if self.calibrating is not None:
            if nav is Nav.BACK:
                self._stop_calibration()
            elif nav is Nav.SELECT:
                result = self.calibrating.capture(read_aim())
                if isinstance(result, tuple):
                    self.put("wii_remote", "calibration", list(result))
                    self.jobs.messages["wii-calibrate"] = "Calibrated: the pointer follows your aim"
                    self._stop_calibration()
                    self.refresh()
            return None

        if self.zone == "nav":
            if nav in (Nav.UP, Nav.DOWN, Nav.TAB_PREV, Nav.TAB_NEXT):
                step = -1 if nav in (Nav.UP, Nav.TAB_PREV) else 1
                self.menu.tab = max(0, min(len(self.menu.tabs) - 1, self.menu.tab + step))
                self.load_for(self.menu.current.key)
            elif nav in (Nav.RIGHT, Nav.SELECT):
                if any(i.selectable for i in self.menu.current.items):
                    self.zone = "items"
            elif nav in (Nav.BACK, Nav.MENU):
                return "exit"
            return None

        item = self.menu.selected
        if nav in (Nav.BACK, Nav.MENU) or (nav is Nav.LEFT and (item is None or item.kind in ("action", "info"))):
            self.zone = "nav"
            self.menu.confirming = None
            return None
        if nav in (Nav.TAB_PREV, Nav.TAB_NEXT):
            self.menu.tab = max(0, min(len(self.menu.tabs) - 1, self.menu.tab + (1 if nav is Nav.TAB_NEXT else -1)))
            self.load_for(self.menu.current.key)
            if not any(i.selectable for i in self.menu.current.items):
                self.zone = "nav"
            return None
        result = self.menu.handle(nav)
        self.refresh()
        return "exit" if result == "exit" else None

    def point(self, hit) -> None:
        """A pointer (Wii Remote or mouse) over a category or an option."""
        if hit is None or self.keyboard or self.calibrating:
            return
        kind, value = hit
        if kind == "tab" and value != self.menu.tab:
            self.menu.tab = value
            self.zone = "nav"
            self.load_for(self.menu.current.key)
        elif kind == "item":
            self.zone = "items"
            self.menu.select(value)

    def click(self, hit) -> str | None:
        if self.calibrating or self.keyboard:
            return self.handle(Nav.SELECT)
        self.point(hit)
        if hit is None:
            return None
        return self.handle(Nav.SELECT if hit[0] == "item" else Nav.RIGHT)

    def tick(self) -> None:
        if self.jobs.finished() or time.monotonic() - self._refreshed > 2.0:
            self.refresh()

    def close(self) -> None:
        if self.calibrating:
            self._stop_calibration()
        events.record("settings_close")


# -- drawing -------------------------------------------------------------------


class SettingsView(QuickMenuView):
    """Full screen: categories on the left, the chosen one's options on the right."""

    def __init__(self, size: tuple[int, int], livery: str = "gulf", motion: str = "full", clock: str = "24h") -> None:
        super().__init__(size, livery, motion, clock)
        u = self.u
        self.width, self.height = size
        self.margin = int(96 * u)
        self.header_h = int(150 * u)
        self.footer_h = int(96 * u)
        self.sidebar_w = int(420 * u)
        self.pad, self.pad_r = int(22 * u), int(22 * u)
        self.hits: list[tuple[pygame.Rect, tuple]] = []
        self._bg: tuple[str, pygame.Surface] | None = None
        self.pointer: tuple[int, int] | None = None
        self.pointer_at = 0.0

    def background(self) -> pygame.Surface:
        if self._bg is None or self._bg[0] != self.lv.name:
            lv, w, h = self.lv, self.width, self.height
            bg = style.gradient((w, h), style.lighten(lv.ink, 0.035), mix(lv.ink, (0, 0, 0), 0.35), vertical=True)
            layer = pygame.Surface((w, h), pygame.SRCALPHA)
            broad = int(h * 0.09)
            for i, (color, bw, a) in enumerate(((lv.accent, broad, 9), (lv.second, broad // 3, 11))):
                x0 = int(w * 0.66) + i * int(broad * 1.35)
                pygame.draw.polygon(layer, (*color, a), [(x0, h), (x0 + bw, h), (x0 + bw + h * 0.45, 0),
                                                         (x0 + h * 0.45, 0)])
            bg.blit(layer, (0, 0))
            self._bg = (lv.name, bg)
        return self._bg[1]

    def hit(self, pos: tuple[int, int]):
        self.pointer, self.pointer_at = pos, time.monotonic()
        return next((what for rect, what in self.hits if rect.collidepoint(pos)), None)

    def draw_settings(self, surf: pygame.Surface, app: SettingsApp) -> None:
        now = time.monotonic()
        self._dt, self._last = min(0.1, now - self._last), now
        c = app.config
        if (self.lv.name, self.reduced, self.clock) != (style.livery(c.livery).name, c.motion == "reduced", c.clock):
            self.set_theme(c.livery, c.motion, c.clock)  # live preview of Appearance changes
        lv, u = self.lv, self.u
        surf.blit(self.background(), (0, 0))
        self.hits = []

        # Header, like the home screen's.
        top = int(self.header_h * 0.36)
        cell = max(2, int(7 * u))
        style.checkered(surf, self.margin, top + int(9 * u), cell, 4, 3, lv.text)
        title = style.tracked(self.type(34, "cond", "semibold"), "SETTINGS", lv.text, 0.32)
        surf.blit(title, (self.margin + cell * 4 + int(20 * u), top))
        clock = self.type(48, "cond", "semibold").render(style.clock_text(self.clock), True, lv.text)
        surf.blit(clock, clock.get_rect(topright=(self.width - self.margin, top - int(12 * u))))
        rule_y = self.header_h - int(20 * u)
        style.blend_rect(surf, pygame.Rect(self.margin, rule_y, self.width - 2 * self.margin, max(1, int(u))),
                         (*lv.text, 34))
        style.stripes(surf, self.margin, rule_y - int(2 * u), int(72 * u), max(2, int(5 * u)),
                      (lv.accent, lv.second), vertical=False)

        self._draw_sidebar(surf, app)
        self._draw_page(surf, app)
        self._draw_footer_hints(surf, app)
        if app.calibrating:
            self._draw_calibration(surf, app.calibrating)
        if app.keyboard:
            self._draw_keyboard(surf, app.keyboard)
        if self.pointer and now - self.pointer_at < 2.5:
            style.draw_pointer(surf, self.pointer, u, lv)

    def _draw_sidebar(self, surf: pygame.Surface, app: SettingsApp) -> None:
        lv, u = self.lv, self.u
        y0 = self.header_h + int(26 * u)
        row_h = int(68 * u)
        f = self.type(24, "cond", "semibold")
        target = y0 + app.menu.tab * row_h
        y_bar = self.smooth.get("side_y", target, self._dt)
        active = app.zone == "nav"
        bar = pygame.Rect(self.margin - int(18 * u), int(y_bar), self.sidebar_w, row_h - int(8 * u))
        style.blend_rect(surf, bar, (*lv.text, 22 if active else 10), int(8 * u))
        style.stripes(surf, bar.x, bar.y + int(12 * u), bar.h - int(24 * u), max(3, int(5 * u)),
                      (lv.accent, lv.second), alpha=255 if active else 110)
        for i, (key, title, _) in enumerate(CATEGORIES):
            y = y0 + i * row_h
            on = i == app.menu.tab
            number = style.tracked(f, f"{i + 1:02d}", lv.accent if on else lv.dim, 0.1)
            label = style.tracked(f, title.upper(), lv.text if on else lv.dim, 0.24)
            cy = y + (row_h - int(8 * u)) // 2
            surf.blit(number, (self.margin + int(14 * u), cy - number.get_height() // 2))
            surf.blit(label, (self.margin + int(14 * u) + number.get_width() + int(18 * u), cy - label.get_height() // 2))
            self.hits.append((pygame.Rect(self.margin - int(18 * u), y, self.sidebar_w, row_h), ("tab", i)))

    def _draw_page(self, surf: pygame.Surface, app: SettingsApp) -> None:
        lv, u = self.lv, self.u
        x = self.margin + self.sidebar_w + int(56 * u)
        w = self.width - x - self.margin
        y = self.header_h + int(22 * u)
        key, title, description = CATEGORIES[app.menu.tab]
        heading = style.tracked(self.type(52, "cond", "semibold"), title.upper(), lv.text, 0.05)
        surf.blit(heading, (x, y))
        y += heading.get_height()
        sub = self.type(21, "text", "medium").render(description, True, lv.dim)
        surf.blit(sub, (x, y))
        y += sub.get_height() + int(20 * u)
        area_h = self.height - self.footer_h - y
        pane = pygame.Surface((w, area_h), pygame.SRCALPHA)
        self._draw_items(pane, app.menu, pygame.Rect(0, 0, w, area_h), 1.0,
                         highlight=1.0 if app.zone == "items" else 0.35)
        surf.blit(pane, (x, y))
        for rect, item_key in self.item_hits:
            self.hits.append((rect.move(x, y).clip(pygame.Rect(x, y, w, area_h)), ("item", item_key)))

    def _draw_footer_hints(self, surf: pygame.Surface, app: SettingsApp) -> None:
        cy = self.height - self.footer_h // 2
        if app.keyboard:
            hints = (("A", "Type"), ("B", "Delete"), ("START", "Done"))
        elif app.calibrating:
            hints = (("A", "Aimed at it"), ("B", "Cancel"))
        elif app.zone == "nav":
            hints = (("A", "Open"), ("B", "Close settings"))
        else:
            hints = (("A", "Select"), ("‹ ›", "Change"), ("B", "Back"))
        x = self.margin
        for button, label in hints:
            x = style.button_hint(surf, x, cy, button, label, self.type, self.lv)

    def _draw_calibration(self, surf: pygame.Surface, cal: Calibration) -> None:
        lv, u = self.lv, self.u
        shade = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        shade.fill((*lv.ink, 248))
        surf.blit(shade, (0, 0))
        tx, ty = cal.target
        center = (int(tx * self.width), int(ty * self.height))
        pulse = 0.5 + 0.5 * abs(((time.monotonic() * 1.2) % 2) - 1)
        r = int((34 + 10 * pulse) * u)
        style.circle(surf, (*lv.accent, 70), center, r + int(14 * u))
        style.circle(surf, lv.text, center, r)
        style.circle(surf, lv.accent, center, r * 0.55)
        style.circle(surf, lv.ink, center, r * 0.18)
        step = style.tracked(self.type(20, "cond", "semibold"), f"TARGET {len(cal.points) + 1} OF 2", lv.dim, 0.3)
        text = self.type(34, "text", "semibold").render(cal.message, True, lv.text)
        mid = self.height // 2
        surf.blit(step, step.get_rect(center=(self.width // 2, mid - int(30 * u))))
        surf.blit(text, text.get_rect(center=(self.width // 2, mid + int(16 * u))))

    def _draw_keyboard(self, surf: pygame.Surface, kb: Keyboard) -> None:
        lv, u = self.lv, self.u
        shade = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 170))
        surf.blit(shade, (0, 0))
        key_w, key_h, gap = int(92 * u), int(70 * u), int(10 * u)
        grid_w = key_w * 10 + gap * 9
        panel = pygame.Rect(0, 0, grid_w + int(80 * u), int(30 * u) + int(28 * u) + int(64 * u) + int(22 * u)
                            + 5 * (key_h + gap) + int(26 * u))
        panel.midbottom = (self.width // 2, self.height - self.footer_h)
        card = pygame.Surface(panel.size, pygame.SRCALPHA)
        card.blit(style.gradient(panel.size, style.lighten(lv.panel, 0.05), lv.panel, vertical=True), (0, 0))
        style.stripes(card, 0, 0, panel.h, int(12 * u), (lv.accent, lv.second))
        style.rounded(card, int(16 * u))
        surf.blit(card, panel.topleft)
        x0, y = panel.x + int(40 * u), panel.y + int(30 * u)
        cap = style.tracked(self.type(19, "cond", "semibold"), kb.title.upper(), lv.dim, 0.26)
        surf.blit(cap, (x0, y))
        y += cap.get_height() + int(10 * u)
        field = pygame.Rect(x0, y, grid_w, int(64 * u))
        style.blend_rect(surf, field, (*lv.text, 20), int(8 * u))
        shown = kb.text if kb.show else "•" * len(kb.text)
        text = self.type(32, "text", "semibold").render(shown + ("|" if int(time.monotonic() * 2) % 2 else ""),
                                                        True, lv.text)
        surf.blit(style.fit(text, field.w - int(30 * u)), (field.x + int(16 * u), field.centery - text.get_height() // 2))
        y = field.bottom + int(22 * u)
        f_key = self.type(30, "cond", "semibold")
        for row in range(4):
            for col in range(10):
                rect = pygame.Rect(x0 + col * (key_w + gap), y + row * (key_h + gap), key_w, key_h)
                self._key(surf, rect, kb.key_at(row, col), kb.row == row and kb.col == col, f_key)
        special = kb.special
        widths = {"space": 3.0, "done": 1.6}
        units = sum(widths.get(k, 1.3) for k in special)
        x = x0
        row_y = y + 4 * (key_h + gap)
        for col, key in enumerate(special):
            w = int((grid_w - gap * (len(special) - 1)) * widths.get(key, 1.3) / units)
            label = {"shift": "ABC" if kb.layer != "upper" else "abc", "symbols": "&123" if kb.layer != "symbols"
                     else "abc", "space": "SPACE", "delete": "DELETE", "show": "HIDE" if kb.show else "SHOW",
                     "done": "DONE"}[key]
            self._key(surf, pygame.Rect(x, row_y, w, key_h), label, kb.row == 4 and kb.col == col,
                      self.type(22, "cond", "semibold"), accent=key == "done")
            x += w + gap

    def _key(self, surf, rect, label, selected, font, accent=False) -> None:
        lv = self.lv
        if selected:
            pygame.draw.rect(surf, lv.accent, rect, border_radius=int(8 * self.u))
            color = lv.ink
        else:
            style.blend_rect(surf, rect, (*(lv.accent if accent else lv.text), 40 if accent else 16), int(8 * self.u))
            color = lv.text
        glyph = font.render(label, True, color)
        surf.blit(glyph, glyph.get_rect(center=rect.center))


def run(surface: pygame.Surface, config_path: Path | None = None, max_frames: int | None = None,
        input_blocked: Callable[[], bool] | None = None, offset: tuple[int, int] = (0, 0)) -> App | None:
    """Show the Settings app until it's closed. Returns an app to open next, if any."""
    app = SettingsApp(config_path)
    c = app.config
    view = SettingsView(surface.get_size(), c.livery, c.motion, c.clock)
    mapper = InputMapper()
    mapper.swap_confirm = c.confirm == "east"
    mapper.open_devices()
    clock = pygame.time.Clock()
    blocked = False
    frames = 0
    if input_blocked is None:
        def input_blocked() -> bool:
            return bool(session.read()["overlay_open"])
    try:
        while max_frames is None or frames < max_frames:
            frames += 1
            if frames % 8 == 0:
                was, blocked = blocked, input_blocked()
                if blocked and not was:
                    mapper.reset()
            now = pygame.time.get_ticks()
            navs: list[Nav] = []
            for event in pygame.event.get():
                if blocked:
                    continue
                if event.type == pygame.MOUSEMOTION:
                    app.point(view.hit((event.pos[0] - offset[0], event.pos[1] - offset[1])))
                    continue
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if app.click(view.hit((event.pos[0] - offset[0], event.pos[1] - offset[1]))) == "exit":
                        return app.launch
                    continue
                if app.keyboard and event.type == pygame.KEYDOWN and event.unicode and event.unicode.isprintable() \
                        and event.key not in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_BACKSPACE):
                    app.keyboard.type(event.unicode)
                    continue
                nav = mapper.translate(event, now)
                if nav is not None:
                    navs.append(nav)
            repeat = mapper.repeat(now)
            if repeat is not None and not blocked:
                navs.append(repeat)
            for nav in navs:
                if app.handle(nav) == "exit":
                    return app.launch
            app.tick()
            mapper.swap_confirm = app.config.confirm == "east"
            style.set_prompts(app.config.prompts, app.config.confirm)
            input_.set_deadzone(app.config.stick_deadzone)
            view.draw_settings(surface, app)
            pygame.display.flip()
            clock.tick(60)
        return None
    finally:
        app.close()
