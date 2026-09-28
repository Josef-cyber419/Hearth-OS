"""Your games, wherever they live: Steam and the emulated consoles (ES-DE).

Used for the home screen's "Continue" (recently played) and "Pinned" rows
and the Library. Everything is read from local files, nothing from the
internet:

- Steam: installed games from each library's appmanifest_*.acf, when you
  last played from userdata/*/config/localconfig.vdf, artwork from Steam's
  own cache (appcache/librarycache).
- Emulation: game files in ~/ROMs/<system>/, names, favourites and play
  history from ES-DE's gamelists, artwork ES-DE's scraper downloaded.
- PC games that aren't in Steam (AppImages, e.g. a decompiled port): each
  AppImage in ~/Games/, or each folder in ~/Games/ holding one (see
  port_games).

ES-DE can't be asked to start one particular game, so Hearth starts pinned
and recent games itself, with the same emulators and arguments ES-DE uses
by default for the emulators Hearth installs.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("hearth")

STEAM_LAUNCHER = "/usr/libexec/hearth/hearth-steam"
RUN_GAME = "/usr/libexec/hearth/hearth-run-game"
RECENT = 10  # games in the Continue row


@dataclass(frozen=True)
class Game:
    key: str  # "steam:620", "rom:psx:Crash Bandicoot.chd"
    title: str
    system: str  # "steam", "psx", ...
    command: tuple[str, ...]
    last_played: float = 0.0
    art: str | None = None
    favorite: bool = False  # ES-DE's favourite star

    @property
    def platform(self) -> str:
        return SYSTEMS.get(self.system, (self.system.upper(),))[0]

    @property
    def is_steam(self) -> bool:
        return self.system == "steam"


# -- paths ---------------------------------------------------------------------


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(home() / ".local/state")
    return Path(base) / "hearth"


def steam_roots() -> list[Path]:
    h = home()
    out = []
    for p in (h / ".local/share/Steam", h / ".steam/steam", h / ".var/app/com.valvesoftware.Steam/.local/share/Steam"):
        try:
            if (p / "steamapps").is_dir() and p.resolve() not in [o.resolve() for o in out]:
                out.append(p)
        except OSError:
            continue
    return out


# -- Valve's KeyValues text format (.vdf / .acf) -------------------------------

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text: str) -> dict:
    """Valve KeyValues text: "key" "value" pairs and "key" { ... } blocks."""
    stack: list[dict] = [{}]
    key: str | None = None
    for m in _TOKEN.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            child: dict = {}
            if key is not None:
                stack[-1][key] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = s.replace('\\"', '"').replace("\\\\", "\\")
        else:
            stack[-1][key] = s.replace('\\"', '"').replace("\\\\", "\\")
            key = None
    return stack[0]


def _vdf_file(path: Path) -> dict:
    try:
        return parse_vdf(path.read_text(errors="replace"))
    except OSError:
        return {}


def _lower_keys(d: dict) -> dict:
    return {k.lower(): (_lower_keys(v) if isinstance(v, dict) else v) for k, v in d.items()}


# -- Steam ---------------------------------------------------------------------

# Runtimes and redistributables Steam installs alongside games.
NOT_GAMES = re.compile(r"^(Proton|Steam Linux Runtime|Steamworks Common|Steam Audio|SteamVR)", re.I)


def steam_last_played(root: Path) -> dict[str, float]:
    played: dict[str, float] = {}
    for cfg in glob.glob(str(root / "userdata/*/config/localconfig.vdf")):
        data = _lower_keys(_vdf_file(Path(cfg)))
        apps = (data.get("userlocalconfigstore", {}).get("software", {}).get("valve", {})
                .get("steam", {}).get("apps", {}))
        for appid, info in apps.items():
            if isinstance(info, dict):
                try:
                    played[appid] = max(played.get(appid, 0.0), float(info.get("lastplayed", 0)))
                except ValueError:
                    pass
    return played


def steam_art(root: Path, appid: str) -> str | None:
    """A landscape image of the game from Steam's own artwork cache."""
    cache = root / "appcache/librarycache"
    for pattern in (f"{appid}/header.jpg", f"{appid}/*/header.jpg", f"{appid}_header.jpg",
                    f"{appid}/library_hero.jpg", f"{appid}/*/library_hero.jpg", f"{appid}_library_hero.jpg"):
        found = sorted(glob.glob(str(cache / pattern)))
        if found:
            return found[0]
    return None


def steam_games() -> list[Game]:
    games: dict[str, Game] = {}
    for root in steam_roots():
        played = steam_last_played(root)
        folders = _lower_keys(_vdf_file(root / "steamapps/libraryfolders.vdf")).get("libraryfolders", {})
        paths = {root} | {Path(v["path"]) for v in folders.values() if isinstance(v, dict) and v.get("path")}
        for lib in paths:
            for manifest in glob.glob(str(lib / "steamapps/appmanifest_*.acf")):
                state = _lower_keys(_vdf_file(Path(manifest))).get("appstate", {})
                appid, name = state.get("appid"), state.get("name", "")
                if not appid or not name or NOT_GAMES.match(name) or appid in games:
                    continue
                if not int(state.get("stateflags", "4") or 4) & 4:
                    continue  # not fully installed
                last = max(played.get(appid, 0.0), float(state.get("lastplayed", 0) or 0))
                games[appid] = Game(f"steam:{appid}", name, "steam", (STEAM_LAUNCHER, f"steam://rungameid/{appid}"),
                                    last, steam_art(root, appid))
    return list(games.values())


# -- emulation (ES-DE) ---------------------------------------------------------

RA = "org.libretro.RetroArch"

# system: (name shown, [(flatpak app, arguments with {rom}, RetroArch core or None), ...])
# In order of preference, following ES-DE's defaults for what Hearth installs.
SYSTEMS: dict[str, tuple] = {
    "steam": ("Steam", []),
    "pc": ("PC", []),
    "nes": ("NES", [(RA, "-L {core} {rom}", "mesen_libretro"), (RA, "-L {core} {rom}", "nestopia_libretro")]),
    "snes": ("SNES", [(RA, "-L {core} {rom}", "snes9x_libretro")]),
    "n64": ("Nintendo 64", [("com.github.Rosalie241.RMG", "--nogui -q {rom}", None),
                            (RA, "-L {core} {rom}", "mupen64plus_next_libretro")]),
    "gb": ("Game Boy", [(RA, "-L {core} {rom}", "gambatte_libretro")]),
    "gbc": ("Game Boy Color", [(RA, "-L {core} {rom}", "gambatte_libretro")]),
    "gba": ("Game Boy Advance", [(RA, "-L {core} {rom}", "mgba_libretro")]),
    "nds": ("Nintendo DS", [("net.kuribo64.melonDS", "-f {rom}", None)]),
    "n3ds": ("Nintendo 3DS", [("org.azahar_emu.Azahar", "{rom}", None)]),
    "gc": ("GameCube", [("org.DolphinEmu.dolphin-emu", "-b -e {rom}", None)]),
    "wii": ("Wii", [("org.DolphinEmu.dolphin-emu", "-b -e {rom}", None)]),
    "wiiu": ("Wii U", [("info.cemu.Cemu", "-g {rom}", None)]),
    "switch": ("Switch", [("dev.eden_emu.eden", "-f -g {rom}", None)]),
    "psx": ("PlayStation", [("org.duckstation.DuckStation", "-batch -fullscreen {rom}", None)]),
    "ps2": ("PlayStation 2", [("net.pcsx2.PCSX2", "-batch -fullscreen {rom}", None)]),
    "ps3": ("PlayStation 3", [("net.rpcs3.RPCS3", "--no-gui {rom}", None)]),
    "psp": ("PSP", [("org.ppsspp.PPSSPP", "{rom}", None)]),
    "xbox": ("Xbox", [("app.xemu.xemu", "-dvd_path {rom}", None)]),
    "genesis": ("Genesis", [(RA, "-L {core} {rom}", "genesis_plus_gx_libretro")]),
    "megadrive": ("Mega Drive", [(RA, "-L {core} {rom}", "genesis_plus_gx_libretro")]),
    "mastersystem": ("Master System", [(RA, "-L {core} {rom}", "genesis_plus_gx_libretro")]),
    "dreamcast": ("Dreamcast", [(RA, "-L {core} {rom}", "flycast_libretro")]),
    "saturn": ("Saturn", [(RA, "-L {core} {rom}", "mednafen_saturn_libretro")]),
    "arcade": ("Arcade", [("org.mamedev.MAME", "-rompath {dir} {base}", None)]),
    "mame": ("Arcade", [("org.mamedev.MAME", "-rompath {dir} {base}", None)]),
}

# Files that aren't games (ES-DE's own notes, saves, disc parts listed by a playlist).
SKIP = re.compile(r"(^systeminfo\.txt$|^metadata\.txt$|\.(txt|xml|sav|srm|state\d*|png|jpg|nfo|bin)$)", re.I)
MULTI_DISC = re.compile(r"\((disc|disk|cd)\s*[2-9]", re.I)


def roms_dir() -> Path:
    return home() / "ROMs"


def esde_dir() -> Path:
    return home() / "ES-DE"


def flatpak_installed(app: str) -> bool:
    return any((d / app).is_dir() for d in (Path("/var/lib/flatpak/app"), home() / ".local/share/flatpak/app"))


def retroarch_core(core: str) -> str | None:
    path = home() / f".var/app/{RA}/config/retroarch/cores/{core}.so"
    return str(path) if path.exists() else None


def launch_command(system: str, rom: Path) -> tuple[str, ...] | None:
    """How to start this game directly, or None if its emulator isn't installed."""
    for app, args, core in SYSTEMS.get(system, ("", []))[1]:
        if not flatpak_installed(app):
            continue
        core_path = retroarch_core(core) if core else None
        if core and not core_path:
            continue
        parts = []
        for arg in args.split():
            parts.append(arg.format(rom=str(rom), core=core_path or "", dir=str(rom.parent), base=rom.stem))
        extra = ["-f"] if app == RA else []  # RetroArch: full screen
        return ("flatpak", "run", app, *extra, *parts)
    return None


def _esde_time(value: str | None) -> float:
    """ES-DE writes lastplayed as 20240131T203000 (local time)."""
    if not value:
        return 0.0
    try:
        return time.mktime(time.strptime(value[:15], "%Y%m%dT%H%M%S"))
    except ValueError:
        return 0.0


def gamelist(system: str) -> dict[str, dict]:
    """ES-DE's metadata for a system, keyed by ROM file name."""
    path = esde_dir() / "gamelists" / system / "gamelist.xml"
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return {}
    out = {}
    for g in root.iter("game"):
        rel = (g.findtext("path") or "").strip()
        if not rel:
            continue
        out[Path(rel).name] = {
            "name": (g.findtext("name") or "").strip(),
            "favorite": (g.findtext("favorite") or "").strip().lower() == "true",
            "hidden": (g.findtext("hidden") or "").strip().lower() == "true",
            "lastplayed": _esde_time(g.findtext("lastplayed")),
        }
    return out


def rom_art(system: str, rom: Path) -> str | None:
    """Artwork ES-DE's scraper downloaded: landscape kinds first, for the tiles."""
    media = esde_dir() / "downloaded_media" / system
    for kind in ("fanart", "screenshots", "titlescreens", "covers", "3dboxes", "marquees"):
        for ext in ("png", "jpg", "jpeg", "webp"):
            path = media / kind / f"{rom.stem}.{ext}"
            if path.exists():
                return str(path)
    return None


def pretty(stem: str) -> str:
    """"Super Mario 64 (USA) [!]" -> "Super Mario 64"."""
    return re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", stem).strip() or stem


def rom_games() -> list[Game]:
    games = []
    base = roms_dir()
    if not base.is_dir():
        return games
    for system in sorted(SYSTEMS):
        folder = base / system
        if system == "steam" or not folder.is_dir():
            continue
        meta = gamelist(system)
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for rom in entries:
            if rom.name.startswith(".") or MULTI_DISC.search(rom.name):
                continue
            if SKIP.search(rom.name) and not (rom.suffix.lower() == ".bin" and not rom.with_suffix(".cue").exists()
                                              and not rom.with_suffix(".CUE").exists()):
                continue  # a .bin is a game unless a .cue next to it is (PlayStation discs)
            if rom.is_dir() and system not in ("ps3", "wiiu", "switch"):
                continue  # other systems' games are files (PS3/Wii U games can be folders)
            info = meta.get(rom.name, {})
            if info.get("hidden"):
                continue
            command = launch_command(system, rom)
            if command is None:
                continue
            games.append(Game(f"rom:{system}:{rom.name}", info.get("name") or pretty(rom.stem), system, command,
                              info.get("lastplayed", 0.0), rom_art(system, rom), info.get("favorite", False)))
    return games


# -- PC games (AppImages) ------------------------------------------------------

ART = (".png", ".jpg", ".jpeg", ".webp")
SCRIPTS = ("start.sh", "launch.sh", "run.sh")
# Build details in AppImage names: "Dusk-v1.2.0-x86_64" -> "Dusk".
_BUILD = re.compile(r"^(x86[_-]64|amd64|x64|linux|appimage|v?\d+(\.\d+)*[a-z]?|release|nightly)$", re.I)


def ports_dir() -> Path:
    return home() / "Games"


def _title(stem: str) -> str:
    stem = re.sub(r"x86[_-]64", " ", stem, flags=re.I)
    words = [w for w in re.split(r"[\s_-]+", stem) if w]
    kept = [w for w in words if not _BUILD.match(w)]
    return pretty(" ".join(kept or words))


def _art(*candidates: Path) -> str | None:
    for base in candidates:
        for ext in ART:
            if base.with_suffix(ext).is_file():
                return str(base.with_suffix(ext))
    return None


def _is_appimage(path: Path) -> bool:
    return path.suffix.lower() == ".appimage" and path.is_file()


def _folder_program(folder: Path) -> Path | None:
    """The program in a game's folder: its AppImage, else a start script."""
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return None
    images = [e for e in entries if _is_appimage(e)]
    if images:
        return images[0]
    return next((folder / n for n in SCRIPTS if (folder / n).is_file()), None)


def port_games() -> list[Game]:
    """PC games outside Steam, from ~/Games/:

    - Name.AppImage, with optional artwork next to it (Name.png)
    - Name/ holding an AppImage (or start.sh), with optional cover.png: the
      folder's name is the title, so it can be anything you like. Keep the
      game's data files in the folder too; it's started from there.
    """
    base = ports_dir()
    games: list[Game] = []
    try:
        entries = sorted(base.iterdir())
    except OSError:
        return games
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if _is_appimage(entry):
            program, title, art = entry, _title(entry.stem), _art(entry)
        elif entry.is_dir():
            program = _folder_program(entry)
            if program is None:
                continue
            title, art = entry.name, _art(entry / "cover", entry / "art", program)
        else:
            continue
        games.append(Game(f"pc:{entry.name}", title, "pc", (RUN_GAME, str(program)), art=art))
    return games


# -- pins and play history -------------------------------------------------------


def _played_path() -> Path:
    return state_dir() / "played.json"


def played() -> dict[str, float]:
    """Games Hearth started itself (ES-DE and Steam only know about their own launches)."""
    try:
        data = json.loads(_played_path().read_text())
        return {k: float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_play(key: str) -> None:
    data = played()
    data[key] = time.time()
    try:
        path = _played_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)  # never a half-written file
    except OSError as e:
        log.debug("can't record play: %s", e)


def all_games() -> list[Game]:
    """Every game, most recently played first, then by name."""
    games = []
    try:
        games += steam_games()
    except Exception:  # a broken library file mustn't break the home screen
        log.exception("reading the Steam library")
    try:
        games += rom_games()
    except Exception:
        log.exception("reading ROMs")
    try:
        games += port_games()
    except Exception:
        log.exception("reading ~/Games")
    ours = played()
    games = [g if ours.get(g.key, 0) <= g.last_played else
             Game(g.key, g.title, g.system, g.command, ours[g.key], g.art, g.favorite) for g in games]
    return sorted(games, key=lambda g: (-g.last_played, g.title.lower()))


def recent(games: list[Game], limit: int = RECENT, hidden: set[str] | None = None) -> list[Game]:
    hidden = hidden or set()
    return [g for g in games if g.last_played > 0 and g.key not in hidden][:limit]


def pinned(games: list[Game], pins: list[str]) -> list[Game]:
    """Your pins in your order, then ES-DE favourites you haven't pinned."""
    by_key = {g.key: g for g in games}
    out = [by_key[k] for k in pins if k in by_key]
    out += [g for g in games if g.favorite and g.key not in pins]
    return out


# -- as home screen tiles ------------------------------------------------------

COLORS = {"steam": "#1b2838", "pc": "#3a4a5c", "psx": "#3b3f8c", "ps2": "#1f3d8a", "ps3": "#26262e", "psp": "#2d2d38",
          "gc": "#4b2a8a", "wii": "#5a6470", "wiiu": "#1f7a9c", "switch": "#b0202a", "n64": "#2f7a3a",
          "snes": "#5a4a8a", "nes": "#8a2a2a", "nds": "#5a5a5a", "n3ds": "#9c2a2a", "xbox": "#2f7a2f",
          "gba": "#4a3a8a", "gb": "#6a7a3a", "gbc": "#7a3a8a", "genesis": "#2a2a2a", "megadrive": "#2a2a2a",
          "dreamcast": "#c46a1a", "saturn": "#3a3a4a", "arcade": "#8a5a1a", "mame": "#8a5a1a"}


def as_app(game: Game):
    from .config import App

    # Steam runs its own interface and manages the screen itself (like the
    # Steam tile); emulators are ordinary apps Hearth shows and closes.
    return App(id=f"game:{game.key}", name=game.title, command=game.command,
               color=COLORS.get(game.system, "#3a3f58"), art=game.art, platform=game.platform,
               home_button=not game.is_steam, tag_windows=not game.is_steam)


def key_of(app_id: str) -> str | None:
    return app_id[len("game:"):] if app_id.startswith("game:") else None


def with_game_rows(config, games: list[Game] | None = None):
    """The home screen with "Continue" (recently played) and "Pinned" rows on top."""
    from dataclasses import replace

    from . import settings
    from .config import Row

    games = all_games() if games is None else games
    prefs = settings.load()
    rows = []
    if config.home_recent:
        apps = tuple(as_app(g) for g in recent(games, hidden=set(prefs.get("hide_recent", []))))
        if apps:
            rows.append(Row("Continue", apps))
    if config.home_pins:
        apps = tuple(as_app(g) for g in pinned(games, prefs.get("pins", [])))
        if apps:
            rows.append(Row("Pinned", apps))
    # Your own PC games (~/Games) get a row of their own: nothing else lists them.
    apps = tuple(as_app(g) for g in sorted(games, key=lambda g: g.title.lower()) if g.system == "pc")
    if apps:
        rows.append(Row("PC games", apps))
    return replace(config, rows=tuple(rows) + config.rows)


def library_config(games: list[Game] | None = None):
    """The Library: pinned, recently played, then one row per platform."""
    from . import settings
    from .config import Config, Row

    games = all_games() if games is None else games
    prefs = settings.load()
    rows = []
    pins = tuple(as_app(g) for g in pinned(games, prefs.get("pins", [])))
    if pins:
        rows.append(Row("Pinned", pins))
    played_recently = tuple(as_app(g) for g in recent(games, limit=20))
    if played_recently:
        rows.append(Row("Recently played", played_recently))
    by_system: dict[str, list[Game]] = {}
    for g in sorted(games, key=lambda g: g.title.lower()):
        by_system.setdefault(g.system, []).append(g)
    order = ["steam", "pc"] + [s for s in SYSTEMS if s not in ("steam", "pc")]
    for system in order:
        if system in by_system:
            rows.append(Row(SYSTEMS[system][0], tuple(as_app(g) for g in by_system[system])))
    return Config(title="Library", rows=tuple(rows))
