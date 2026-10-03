"""Loading the home-screen layout from apps.toml.

The defaults live in /usr/share/hearth/apps.toml (shipped in the image, and
updated with it). Your changes go in ~/.config/hearth/apps.toml and are layered
on top, so you keep getting new default tiles after updates:

    hide = ["plex", "android"]        # remove default tiles by id

    [[rows]]
    title = "Watch"                   # same title: add to / change that row
      [[rows.apps]]
      id = "kodi"                     # same id: change just these fields
      color = "#000000"
      [[rows.apps]]
      id = "vlc"                      # new id: a new tile
      name = "VLC"
      flatpak = "org.videolan.VLC"

    [[rows]]
    title = "Mine"                    # new title: a new row, before System

Put `replace = true` at the top to ignore the defaults entirely.
"""

from __future__ import annotations

import glob
import logging
import os
import shlex
import shutil
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

SYSTEM_CONFIG = Path("/usr/share/hearth/apps.toml")


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hearth" / "apps.toml"


def flatpak_dirs() -> list[Path]:
    return [
        Path("/var/lib/flatpak/app"),
        Path.home() / ".local/share/flatpak/app",
    ]


ICON_SIZES = ("512x512", "256x256", "128x128", "scalable")


def flatpak_icon(app: "App") -> str | None:
    """The icon a Flatpak app installs for itself, for tiles that just run it
    (not tiles that only need it, like the Lutris stores)."""
    if not app.flatpak or app.command[:3] != ("flatpak", "run", app.flatpak):
        return None
    for apps_dir in flatpak_dirs():
        icons = apps_dir.parent / "exports/share/icons/hicolor"
        for size in ICON_SIZES:
            for ext in ("png", "svg"):
                path = icons / size / "apps" / f"{app.flatpak}.{ext}"
                if path.is_file():
                    return str(path)
    return None


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class App:
    id: str
    name: str
    command: tuple[str, ...]
    color: str = "#3a3f58"
    icon: str | None = None
    # A drawing for tiles without an icon (emblems.py), e.g. "gears".
    emblem: str | None = None
    requires: tuple[str, ...] = ()
    requires_files: tuple[str, ...] = ()
    flatpak: str | None = None
    # Ask "are you sure?" before launching (power actions, desktop mode).
    confirm: bool = False
    # Holding the controller's Guide button returns home (off for apps like
    # Steam that use the Guide button themselves).
    home_button: bool = True
    # Keeps running while you use other apps; shown and hidden from the Quick
    # Menu (e.g. Discord). Launching its tile starts it if needed and shows it.
    background: bool = False
    # Controller drives a mouse pointer while this app is in front.
    pointer: bool = False
    # X11 WM_CLASS, to recognise the app's windows if its process can't be traced.
    wm_class: str | None = None
    # Hearth tags the app's windows so gamescope will show them. Off for Steam,
    # which does this itself.
    tag_windows: bool = True
    # A game's artwork (fills the tile) and its platform ("PlayStation 2").
    art: str | None = None
    platform: str | None = None
    # How far into it you are, 0..1 (Watch next): a thin bar along the foot.
    progress: float | None = None

    @property
    def builtin(self) -> bool:
        """Part of Hearth itself (e.g. the Settings app), not a program to run."""
        return bool(self.command) and self.command[0].startswith("hearth:")

    def missing(self) -> str | None:
        """Why this tile is hidden, or None if it can be shown."""
        if self.flatpak and not any((d / self.flatpak).is_dir() for d in flatpak_dirs()):
            return f"Flatpak {self.flatpak} not installed"
        for pattern in self.requires_files:
            # May be a glob pattern and may start with ~.
            if not glob.glob(os.path.expanduser(pattern)):
                return f"{pattern} not found"
        for command in self.requires:
            if not shutil.which(command):
                return f"command {command} not found"
        return None

    def available(self) -> bool:
        """Hide tiles whose program isn't installed instead of failing on launch."""
        return self.missing() is None


@dataclass(frozen=True)
class Row:
    title: str
    apps: tuple[App, ...]


@dataclass(frozen=True)
class Config:
    title: str = "Hearth"
    rows: tuple[Row, ...] = field(default_factory=tuple)
    # Freeze the game while the Quick Menu is open, like a console's home menu.
    pause_game: bool = True
    # Colour scheme, after a classic racing livery (see style.LIVERIES).
    livery: str = "gulf"
    # "reduced" turns off the intro, launch zoom and other decorative motion.
    motion: str = "full"
    # Wii Remotes on a DolphinBar (mode 4) drive Hearth like a TV remote.
    wii_remote: bool = True
    # When the Wii Remote pointer works as a mouse: "apps" (those with
    # pointer = true, e.g. Discord), "always", or "never". The Quick Menu can
    # switch it for the app in front.
    wii_mouse: str = "apps"
    wii_bar: str = "below"  # where the sensor bar sits: "below" or "above" the TV
    wii_speed: int = 100  # pointer speed, percent
    wii_steadiness: int = 45  # pointer smoothing, percent
    wii_hold: str = "upright"  # "upright" (pointing) or "sideways" (like an NES pad)
    wii_flip: bool = False  # the pointer moves up when you aim down: turn it round
    # Camera coordinates of two calibration targets (10% and 90% across and
    # down the screen): x1, y1, x2, y2. None until calibrated.
    wii_calibration: tuple[float, float, float, float] | None = None
    clock: str = "24h"  # or "12h"
    guide_hold: float = 1.5  # seconds to hold Guide to go home
    mouse_speed: int = 100  # controller-as-mouse speed, percent
    stick_deadzone: int = 15  # percent of full tilt ignored (worn sticks drift)
    confirm: str = "south"  # which face button confirms: "south" (Xbox/PlayStation) or "east" (Nintendo)
    # Button names shown on screen: "auto" (the controller, keyboard or Wii
    # Remote used last), "xbox", "playstation" or "nintendo".
    prompts: str = "auto"
    safe_area: int = 0  # percent kept clear at the screen's edges, for TVs that crop (overscan)
    home_recent: bool = True  # the "Continue" row of recently played games
    home_watch: bool = True  # the "Watch next" row: shows in progress on Jellyfin, Plex, Kodi
    game_art: bool = True  # find pictures online for emulated games without one (artfind.py)
    home_pins: bool = True  # the Favorites row
    sounds: bool = False  # soft UI sounds on the home screen (sounds.py)
    screensaver_minutes: int = 10  # 0 = never; protects OLED TVs from a still home screen
    # "ambient" (your games' art, slowly panning), "photos" (your own, from
    # photos_folder), "both", or "clock" (dark, just the time)
    screensaver: str = "ambient"
    photos_folder: str = ""  # where the photos are; "" is ~/Pictures (photos.py)
    sleep_minutes: int = 0  # 0 = never; sleep after this long idle on the home screen
    emulation_resolution: str = "auto"  # target for emulator upscaling: auto, 1080p, 1440p, 4k
    # Quick Resume: how many games stay paused in the background (0 = off),
    # and whether holding Guide pauses the game ("resume") or closes it.
    quick_resume: int = 2
    guide_hold_action: str = "resume"
    # Accessibility (each person's own): text size "normal", "large" or
    # "larger" (style.TEXT_SIZES), and the high-contrast look over the livery.
    text_size: str = "normal"
    contrast: bool = False
    remote_enabled: bool = True  # the phone remote's page on the home network (remote.py)
    # Casting (cast.py): the AirPlay and Spotify Connect receivers, and the
    # name a phone sees ("" = this PC's host name).
    cast_airplay: bool = True
    cast_spotify: bool = True
    cast_name: str = ""

    @property
    def scheme(self) -> str:
        """The colours to draw with: the livery, or high contrast when it's on."""
        return "contrast" if self.contrast else self.livery

    def app(self, app_id: str) -> App | None:
        return next((a for row in self.rows for a in row.apps if a.id == app_id), None)

    def visible(self) -> Config:
        """Config with unavailable apps (and rows left empty) removed."""
        rows = []
        for row in self.rows:
            apps = tuple(a for a in row.apps if a.available())
            if apps:
                rows.append(Row(row.title, apps))
        return replace(self, rows=tuple(rows))


def _parse_command(raw: dict, where: str) -> tuple[str, ...]:
    command = raw.get("command")
    flatpak = raw.get("flatpak")
    args = raw.get("args", [])
    if isinstance(args, str):
        args = shlex.split(args)
    if command is None:
        if not flatpak:
            raise ConfigError(f"{where}: needs either 'command' or 'flatpak'")
        return ("flatpak", "run", flatpak, *args)
    if isinstance(command, str):
        command = shlex.split(command)
    if not command or not all(isinstance(c, str) for c in command):
        raise ConfigError(f"{where}: 'command' must be a non-empty string or list of strings")
    return (*command, *args)


def _parse_app(raw: dict, where: str) -> App:
    for key in ("id", "name"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise ConfigError(f"{where}: missing '{key}'")
    requires = raw.get("requires", [])
    if isinstance(requires, str):
        requires = [requires]
    requires_files = raw.get("requires_files", [])
    if isinstance(requires_files, str):
        requires_files = [requires_files]
    return App(
        id=raw["id"],
        name=raw["name"],
        command=_parse_command(raw, where),
        color=raw.get("color", App.color),
        icon=raw.get("icon"),
        emblem=raw.get("emblem"),
        requires=tuple(requires),
        requires_files=tuple(requires_files),
        flatpak=raw.get("flatpak"),
        confirm=bool(raw.get("confirm", False)),
        home_button=bool(raw.get("home_button", True)),
        background=bool(raw.get("background", False)),
        pointer=bool(raw.get("pointer", False)),
        wm_class=raw.get("wm_class"),
        tag_windows=bool(raw.get("tag_windows", True)),
    )


def parse(data: dict) -> Config:
    rows = []
    seen: set[str] = set()
    for r, raw_row in enumerate(data.get("rows", [])):
        title = raw_row.get("title", "")
        apps = []
        for a, raw_app in enumerate(raw_row.get("apps", [])):
            app = _parse_app(raw_app, f"rows[{r}].apps[{a}]")
            if app.id in seen:
                raise ConfigError(f"duplicate app id '{app.id}'")
            seen.add(app.id)
            apps.append(app)
        rows.append(Row(title, tuple(apps)))
    quick_menu = data.get("quick_menu", {})
    theme = data.get("theme", {})
    motion = theme.get("motion", "full")
    if motion not in ("full", "reduced"):
        raise ConfigError("theme.motion must be \"full\" or \"reduced\"")
    wii = data.get("wii_remote", {})
    controllers = data.get("controllers", {})
    home_table = data.get("home", {})
    wii_mouse = _choice(wii, "wii_remote", "mouse", ("apps", "always", "never"))
    access = data.get("accessibility", {})
    calibration = wii.get("calibration")
    if calibration is not None and (not isinstance(calibration, (list, tuple)) or len(calibration) != 4):
        raise ConfigError("wii_remote.calibration must be 4 numbers (or left out)")
    return Config(
        title=data.get("title", "Hearth"),
        rows=tuple(rows),
        pause_game=bool(quick_menu.get("pause_game", True)),
        livery=str(theme.get("livery", "gulf")).lower(),
        motion=motion,
        wii_remote=bool(wii.get("enabled", True)),
        wii_mouse=wii_mouse,
        wii_bar=_choice(wii, "wii_remote", "sensor_bar", ("below", "above")),
        wii_speed=int(_number(wii, "wii_remote", "speed", 100, 25, 300)),
        wii_steadiness=int(_number(wii, "wii_remote", "steadiness", 45, 0, 90)),
        wii_hold=_choice(wii, "wii_remote", "hold", ("upright", "sideways")),
        wii_flip=bool(wii.get("flip_vertical", False)),
        wii_calibration=tuple(float(v) for v in calibration) if calibration else None,
        clock=_choice(theme, "theme", "clock", ("24h", "12h")),
        guide_hold=float(_number(controllers, "controllers", "guide_hold_seconds", 1.5, 0.5, 5)),
        mouse_speed=int(_number(controllers, "controllers", "mouse_speed", 100, 25, 300)),
        stick_deadzone=int(_number(controllers, "controllers", "stick_deadzone", 15, 5, 40)),
        confirm=_choice(controllers, "controllers", "confirm", ("south", "east")),
        prompts=_choice(controllers, "controllers", "prompts", ("auto", "xbox", "playstation", "nintendo")),
        safe_area=int(_number(theme, "theme", "safe_area", 0, 0, 10)),
        home_recent=bool(home_table.get("recent", True)),
        home_watch=bool(home_table.get("watch", True)),
        game_art=bool(home_table.get("art", True)),
        home_pins=bool(home_table.get("pins", True)),
        sounds=bool(home_table.get("sounds", False)),
        screensaver_minutes=int(_number(home_table, "home", "screensaver_minutes", 10, 0, 240)),
        screensaver=_choice(home_table, "home", "screensaver", ("ambient", "photos", "both", "clock")),
        photos_folder=str(home_table.get("photos_folder") or ""),
        sleep_minutes=int(_number(home_table, "home", "sleep_minutes", 0, 0, 1440)),
        emulation_resolution=_choice(data.get("emulation", {}), "emulation", "resolution",
                                     ("auto", "1080p", "1440p", "4k")),
        quick_resume=int(_number(home_table, "home", "quick_resume", 2, 0, 3)),
        guide_hold_action=_choice(controllers, "controllers", "guide_hold", ("resume", "close")),
        text_size=_choice(access, "accessibility", "text_size", ("normal", "large", "larger")),
        contrast=bool(access.get("contrast", False)),
        remote_enabled=bool(data.get("remote", {}).get("enabled", True)),
        cast_airplay=bool(data.get("cast", {}).get("airplay", True)),
        cast_spotify=bool(data.get("cast", {}).get("spotify", True)),
        cast_name=str(data.get("cast", {}).get("name") or "")[:40],
    )


def _choice(table: dict, name: str, key: str, options: tuple[str, ...]) -> str:
    value = table.get(key, options[0])
    if value not in options:
        raise ConfigError(f"{name}.{key} must be one of: {', '.join(options)}")
    return value


def _number(table: dict, name: str, key: str, default: float, low: float, high: float) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ConfigError(f"{name}.{key} must be a number from {low} to {high}")
    return value


def _read(path: Path) -> dict:
    with open(path, "rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from e


def merge(base: dict, user: dict) -> dict:
    """Layer user changes over the defaults (see the module docstring)."""
    if user.get("replace"):
        return user
    tables = ("quick_menu", "theme", "wii_remote", "controllers", "home", "emulation")
    merged = {**base, **{k: v for k, v in user.items() if k not in ("rows", "hide", *tables)}}
    for table in tables:
        merged[table] = {**base.get(table, {}), **user.get(table, {})}
    rows = [{**r, "apps": [dict(a) for a in r.get("apps", [])]} for r in base.get("rows", [])]
    by_title = {r.get("title"): r for r in rows}
    new_rows = []
    for urow in user.get("rows", []):
        row = by_title.get(urow.get("title"))
        if row is None:
            new_rows.append({**urow, "apps": [dict(a) for a in urow.get("apps", [])]})
            continue
        by_id = {a.get("id"): a for a in row["apps"]}
        for uapp in urow.get("apps", []):
            if uapp.get("id") in by_id:
                by_id[uapp["id"]].update(uapp)
            else:
                row["apps"].append(dict(uapp))
    # New rows go before the last default row (System), which stays last so
    # the Menu button still jumps to it.
    rows = rows[:-1] + new_rows + rows[-1:] if rows else new_rows
    hidden = set(user.get("hide", []))
    for row in rows:
        row["apps"] = [a for a in row["apps"] if a.get("id") not in hidden]
    merged["rows"] = [r for r in rows if r["apps"]]
    return merged


def load(path: Path | None = None, hide: bool = True) -> Config:
    """An explicit path is used as-is; otherwise defaults + your changes.
    Either way, choices made in the Settings app go on top. `hide=False`
    keeps tiles hidden from the Settings app (for its own list of tiles)."""
    from . import settings

    if path is not None:
        data = _read(path)
    else:
        user = user_config_path()
        data = _read(SYSTEM_CONFIG) if SYSTEM_CONFIG.exists() else {}
        if user.exists():
            data = merge(data, _read(user))
    try:
        config = parse(settings.apply(data, settings.load(), hide=hide))
    except ConfigError as e:
        # A bad settings.json mustn't take the home screen (and the Settings
        # tile, which is how you'd fix it) down with it.
        logging.getLogger("hearth").warning("ignoring %s: %s", settings.path(), e)
        config = parse(data)
    return personal(config)


def personal(config: Config) -> Config:
    """The config with the current person's own choices on top: their colour
    scheme (profiles.Person.livery), if they have one."""
    from dataclasses import replace

    from . import profiles, style

    person = profiles.current()
    if person is not None and person.livery in style.LIVERIES:
        return replace(config, livery=person.livery)
    return config
