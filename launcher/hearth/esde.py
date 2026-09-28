"""Make ES-DE work with the emulators Hearth installs.

For many consoles ES-DE's default emulator is a RetroArch core (e.g. the
Dolphin core for GameCube), even where Hearth installed the standalone
emulator (the one Hearth tunes, see emutune.py). And Flatpak RetroArch comes
without cores, so ES-DE says it can't find the emulator core. Two fixes:

- Where Hearth installed a standalone emulator, select it for that console,
  the same way ES-DE's own Other settings → Alternative emulators does (an
  <alternativeEmulator> entry at the top of the console's gamelist.xml). Done
  once per console, so a different choice made later in ES-DE sticks.
- For consoles only RetroArch covers, download the core ES-DE uses by
  default from libretro's buildbot (what RetroArch's own updater uses).
"""

from __future__ import annotations

import io
import logging
import os
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from . import library

log = logging.getLogger("hearth")

# console: (Flatpak, label of its entry in ES-DE's es_systems.xml)
STANDALONE = {
    "gc": ("org.DolphinEmu.dolphin-emu", "Dolphin (Standalone)"),
    "wii": ("org.DolphinEmu.dolphin-emu", "Dolphin (Standalone)"),
    "ps2": ("net.pcsx2.PCSX2", "PCSX2 (Standalone)"),
    "psx": ("org.duckstation.DuckStation", "DuckStation (Standalone)"),
    "psp": ("org.ppsspp.PPSSPP", "PPSSPP (Standalone)"),
    "nds": ("net.kuribo64.melonDS", "melonDS (Standalone)"),
    "n3ds": ("org.azahar_emu.Azahar", "Azahar (Standalone)"),
    "n64": ("com.github.Rosalie241.RMG", "Rosalie's Mupen GUI (Standalone)"),
    "arcade": ("org.mamedev.MAME", "MAME (Standalone)"),
    "mame": ("org.mamedev.MAME", "MAME (Standalone)"),
}

# ES-DE's default cores for the consoles that have no standalone emulator here.
CORES = {
    "mesen_libretro": "NES",
    "snes9x_libretro": "SNES",
    "gambatte_libretro": "Game Boy / Color",
    "mgba_libretro": "Game Boy Advance",
    "genesis_plus_gx_libretro": "Genesis / Mega Drive / Master System",
    "flycast_libretro": "Dreamcast",
    "mednafen_saturn_libretro": "Saturn",
}
BUILDBOT = "https://buildbot.libretro.com/nightly/linux/x86_64/latest/{core}.so.zip"


def cores_dir() -> Path:
    return library.home() / f".var/app/{library.RA}/config/retroarch/cores"


def gamelist(system: str) -> Path:
    return library.esde_dir() / "gamelists" / system / "gamelist.xml"


# ES-DE (3.4) reads the emulator choice from an <alternativeEmulator> element
# before <gameList>, at the top level of the file (not quite standard XML):
#
#   <?xml version="1.0"?>
#   <alternativeEmulator>
#   	<label>Dolphin (Standalone)</label>
#   </alternativeEmulator>
#   <gameList>...</gameList>
#
# Its development code also accepts it inside <gameList>, but releases don't.


def _split(text: str) -> tuple[str | None, str]:
    """(top-level <alternativeEmulator> block or None, the rest from <gameList> on)."""
    at = text.find("<gameList")
    head, rest = (text, "") if at < 0 else (text[:at], text[at:])
    start = head.find("<alternativeEmulator")
    if start < 0:
        return None, rest
    stop = head.find("</alternativeEmulator>", start)
    return (head[start:stop + len("</alternativeEmulator>")] if stop >= 0 else None), rest


def _write(path: Path, label: str, game_list: str) -> None:
    alt = ET.Element("alternativeEmulator")
    ET.SubElement(alt, "label").text = label
    ET.indent(alt, "\t")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".xml.hearth-tmp")
    tmp.write_text('<?xml version="1.0"?>\n' + ET.tostring(alt, encoding="unicode") + "\n"
                   + game_list.rstrip() + "\n")
    os.replace(tmp, path)


def _inner_alternative(game_list: str) -> tuple[str | None, str]:
    """An <alternativeEmulator> inside <gameList> (what an earlier Hearth wrote):
    (its label, the gameList without it). (None, unchanged) if there isn't one."""
    root = ET.fromstring(game_list)
    inner = root.find("alternativeEmulator")
    if root.tag != "gameList" or inner is None:
        return None, game_list
    label = inner.findtext("label")
    root.remove(inner)
    ET.indent(root, "\t")
    return label, ET.tostring(root, encoding="unicode")


def select_emulator(system: str, label: str) -> bool:
    """Set a console's emulator in its gamelist.xml, unless one is already
    chosen. Returns True if written."""
    path = gamelist(system)
    text = path.read_text(errors="replace") if path.exists() else ""
    top, game_list = _split(text)
    if top is not None:
        return False  # already chosen (in ES-DE, or by Hearth before)
    if not game_list.strip():
        game_list = "<gameList />"
    inner, game_list = _inner_alternative(game_list)
    _write(path, inner or label, game_list)
    return True


def fix_layout(system: str) -> bool:
    """Move an emulator choice an earlier Hearth wrote inside <gameList> to
    where ES-DE reads it. Returns True if the file changed."""
    path = gamelist(system)
    if not path.exists():
        return False
    top, game_list = _split(path.read_text(errors="replace"))
    if top is not None or not game_list.strip():
        return False
    inner, game_list = _inner_alternative(game_list)
    if inner is None:
        return False
    _write(path, inner, game_list)
    return True


def select_standalone(done: set[str]) -> set[str]:
    """Select Hearth's standalone emulators in ES-DE, once per console."""
    for system in STANDALONE:
        try:
            if fix_layout(system):
                log.info("ES-DE: moved %s's emulator choice to where ES-DE reads it", system)
        except (OSError, ET.ParseError) as e:
            log.warning("ES-DE: couldn't check %s's gamelist: %s", system, e)
    for system, (app, label) in STANDALONE.items():
        if system in done or not library.flatpak_installed(app):
            continue
        try:
            if select_emulator(system, label):
                log.info("ES-DE: %s now uses %s", system, label)
            done.add(system)
        except (OSError, ET.ParseError) as e:
            log.warning("ES-DE: couldn't set the emulator for %s: %s", system, e)
    return done


def missing_cores() -> list[str]:
    if not library.flatpak_installed(library.RA):
        return []
    return [core for core in CORES if not (cores_dir() / f"{core}.so").exists()]


def download_core(core: str, fetch=None) -> None:
    """Fetch one core into Flatpak RetroArch's cores folder."""
    fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=60).read())
    data = fetch(BUILDBOT.format(core=core))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        body = z.read(f"{core}.so")
    if not body.startswith(b"\x7fELF"):
        raise ValueError(f"{core}: not a Linux library")
    dest = cores_dir() / f"{core}.so"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".so.hearth-tmp")
    tmp.write_bytes(body)
    os.replace(tmp, dest)


def download_cores(fetch=None, report=None) -> list[str]:
    """Download missing cores; returns the ones that failed (retried next time)."""
    failed = []
    for core in missing_cores():
        try:
            download_core(core, fetch)
            log.info("RetroArch: downloaded %s (%s)", core, CORES[core])
            if report:
                report(f"Downloaded the {CORES[core]} core")
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
            log.warning("RetroArch: couldn't download %s: %s", core, e)
            failed.append(core)
            if report:
                report(f"Couldn't download the {CORES[core]} core ({e}); will retry")
    return failed


def setup(download: bool = True, report=None) -> None:
    """Everything above, remembering which consoles were already set."""
    from . import settings

    data = settings.load()
    done = set(data.get("esde_emulators_set", []))
    new = select_standalone(set(done))
    if new != done:
        data = settings.load()
        data["esde_emulators_set"] = sorted(new)
        settings.save(data)
        if report:
            report("ES-DE now uses the standalone emulators for: " + ", ".join(sorted(new - done)))
    if download:
        download_cores(report=report)
