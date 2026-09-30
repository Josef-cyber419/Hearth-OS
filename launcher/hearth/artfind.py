"""Finding pictures for emulated games that don't have one.

ES-DE's own scraper (ScreenScraper, TheGamesDB) is the best source, but it
has to be run by hand from ES-DE. For every game it hasn't covered, Hearth
looks in libretro's thumbnail library (thumbnails.libretro.com, the one
RetroArch uses): title screens, in-game shots and box art for most consoles,
free, with no account. Files there are named like No-Intro ROM sets ("Super
Mario 64 (USA)"), so a well-named ROM matches exactly; others are matched by
title, preferring the ROM's own region.

It runs in the background a little at a time; pictures land in
~/.local/share/hearth/art/<system>/ and show up on the next library read.
Only game names are sent (as the file names asked for). Turn it off in
Settings → Home screen.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger("hearth")

BASE = "https://thumbnails.libretro.com"
# Landscape pictures first: tiles are wide.
KINDS = ("Named_Titles", "Named_Snaps", "Named_Boxarts")
# ES-DE's system folders -> libretro's names for them.
SYSTEMS = {
    "nes": "Nintendo - Nintendo Entertainment System",
    "snes": "Nintendo - Super Nintendo Entertainment System",
    "n64": "Nintendo - Nintendo 64",
    "gb": "Nintendo - Game Boy",
    "gbc": "Nintendo - Game Boy Color",
    "gba": "Nintendo - Game Boy Advance",
    "nds": "Nintendo - Nintendo DS",
    "n3ds": "Nintendo - Nintendo 3DS",
    "gc": "Nintendo - GameCube",
    "wii": "Nintendo - Wii",
    "psx": "Sony - PlayStation",
    "ps2": "Sony - PlayStation 2",
    "psp": "Sony - PlayStation Portable",
    "ps3": "Sony - PlayStation 3",
    "genesis": "Sega - Mega Drive - Genesis",
    "megadrive": "Sega - Mega Drive - Genesis",
    "mastersystem": "Sega - Master System - Mark III",
    "dreamcast": "Sega - Dreamcast",
    "saturn": "Sega - Saturn",
    "xbox": "Microsoft - Xbox",
    "arcade": "MAME",
    "mame": "MAME",
}
REGIONS = ("USA", "World", "Europe", "Japan")  # when the ROM doesn't say
INDEX_DAYS = 30  # re-read a system's list of pictures this often
MISS_DAYS = 14  # don't ask again for a game that wasn't found for this long
RUN_EVERY = 6 * 3600
PER_RUN = 150  # pictures fetched per run, so a big collection fills in over a few
PAUSE = 0.4  # seconds between downloads: gentle on a free service
TIMEOUT = 20


def _data() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "hearth"


def _cache() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "hearth" / "art-index"


def art_dir(system: str) -> Path:
    return _data() / "art" / system


def found(system: str, stem: str) -> str | None:
    """A picture found earlier for this ROM, if any."""
    path = art_dir(system) / f"{stem}.png"
    return str(path) if path.is_file() else None


def libretro_name(name: str) -> str:
    """libretro's file names swap these characters for underscores."""
    return re.sub(r'[&*/:`<>?\\|"]', "_", name)


def _key(name: str) -> str:
    """A title reduced for matching: no tags, articles, punctuation or case."""
    title = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", name)
    title = re.sub(r",\s*the\b", "", title, flags=re.I)
    title = re.sub(r"^the\s+", "", title, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def _tags(name: str) -> str:
    return " ".join(re.findall(r"\(([^)]*)\)", name))


def best_match(stem: str, names: list[str]) -> str | None:
    """The picture for this ROM: its exact name, else the same title, in the
    ROM's region if it says, else the usual region order."""
    wanted = libretro_name(stem)
    if wanted in names:
        return wanted
    key = _key(stem)
    if not key:
        return None
    same = [n for n in names if _key(n) == key]
    if not same:
        return None
    tags = _tags(stem)
    order = [r for r in REGIONS if r in tags] + list(REGIONS)

    def rank(name: str) -> tuple:
        t = _tags(name)
        region = next((i for i, r in enumerate(order) if r in t), len(order))
        extras = ("Beta" in t or "Proto" in t or "Demo" in t or "Sample" in t, len(name))
        return (region, *extras)

    return min(same, key=rank)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Hearth-OS (living-room launcher)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def _url(system: str, kind: str, name: str = "") -> str:
    path = f"{SYSTEMS[system]}/{kind}/"
    if name:
        path += f"{name}.png"
    return f"{BASE}/{urllib.parse.quote(path)}"


def index(system: str, kind: str, fetch=_get) -> list[str]:
    """The names of every picture of this kind for a system (a directory
    listing, read at most every INDEX_DAYS)."""
    path = _cache() / f"{system}-{kind}.json"
    try:
        saved = json.loads(path.read_text())
        if time.time() - saved["at"] < INDEX_DAYS * 86400:
            return saved["names"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        page = fetch(_url(system, kind)).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        page = ""  # no pictures of this kind for this system: remember that too
    names = sorted({html.unescape(urllib.parse.unquote(m))[:-4]
                    for m in re.findall(r'href="([^"?/]+\.png)"', page)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": time.time(), "names": names}))
    return names


def _misses() -> dict:
    try:
        data = json.loads((_cache() / "misses.json").read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_misses(misses: dict) -> None:
    path = _cache() / "misses.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(misses))


def find(system: str, stem: str, fetch=_get) -> str | None:
    """Look for this ROM's picture and save it; the path, or None."""
    if system not in SYSTEMS:
        return None
    for kind in KINDS:
        name = best_match(stem, index(system, kind, fetch))
        if name is None:
            continue
        body = fetch(_url(system, kind, name))
        if not body.startswith(b"\x89PNG"):
            continue
        dest = art_dir(system) / f"{stem}.png"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(body)
        tmp.replace(dest)
        return str(dest)
    return None


def wanted(games) -> list[tuple[str, str]]:
    """(system, ROM file stem) for emulated games without a picture."""
    out = []
    for g in games:
        if g.art or not g.key.startswith("rom:") or g.system not in SYSTEMS:
            continue
        rom = g.key.split(":", 2)[2]
        out.append((g.system, Path(rom).stem if "." in rom else rom))
    return out


def run(games, limit: int = PER_RUN, fetch=_get, sleep=time.sleep) -> int:
    """Fetch pictures for up to `limit` games; how many were found."""
    misses, now, got, tried = _misses(), time.time(), 0, 0
    for system, stem in wanted(games):
        if tried >= limit:
            break
        miss_key = f"{system}/{stem}"
        if now - misses.get(miss_key, 0) < MISS_DAYS * 86400:
            continue
        tried += 1
        try:
            if find(system, stem, fetch):
                got += 1
                misses.pop(miss_key, None)
            else:
                misses[miss_key] = now
        except urllib.error.HTTPError:
            misses[miss_key] = now  # listed but not there: skip it for now
        except (urllib.error.URLError, OSError, ValueError) as e:
            log.info("game art: stopped at %s (%s)", miss_key, e)
            break  # offline or the service is down: try again next run
        sleep(PAUSE)
    _save_misses(misses)
    if got:
        log.info("game art: found %d pictures", got)
    return got


_running = threading.Lock()
_last_run = 0.0


def find_soon(games) -> None:
    """In the background, if it hasn't run lately and there's anything to find."""
    global _last_run
    if time.monotonic() - _last_run < RUN_EVERY and _last_run:
        return
    todo = wanted(games)
    if not todo or not _running.acquire(blocking=False):
        return
    _last_run = time.monotonic()

    def work():
        try:
            run(games)
        except Exception:
            log.exception("game art")
        finally:
            _running.release()

    threading.Thread(target=work, daemon=True, name="artfind").start()
