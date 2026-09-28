"""Recommended emulator settings for this PC and TV.

Tuned for a strong 8-core CPU and a 12 GB RDNA2 GPU (like a Ryzen 7 5800X3D
with a Radeon RX 6750 XT): Vulkan everywhere, upscaling matched to the TV
(1080p, 1440p or 4K), 16x texture filtering, and asynchronous shader
compilation so games don't stutter the first time an effect appears.

Safe by design:
- Only the settings listed here are changed; everything else is left alone.
- Only config files the emulator has already written are touched (some
  emulators reset a settings file that lacks their own version marker), so
  each emulator is tuned after its first run.
- The first time a file is changed, a copy is kept next to it
  (<name>.hearth-backup).

Emulators whose config formats Hearth doesn't edit (Cemu, Eden, Azahar,
RPCS3, xemu) get their recommended values listed in docs/EMULATION.md.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import library

log = logging.getLogger("hearth")

TARGETS = {"1080p": 1080, "1440p": 1440, "4k": 2160}

# Internal resolution multipliers per target TV resolution.
SCALES = {
    "psx": {1080: 5, 1440: 6, 2160: 9},  # 240p x 9 = 2160p
    "ps2": {1080: 3, 1440: 4, 2160: 5},  # 448p x 5 = 2240p
    "gc": {1080: 3, 1440: 3, 2160: 5},  # 528p x 5 = 2640p
    "psp": {1080: 4, 1440: 6, 2160: 8},  # 272p x 8 = 2176p
}


def target_height(setting: str) -> int:
    """The TV's height for "auto" (from the display), else the chosen one."""
    if setting in TARGETS:
        return TARGETS[setting]
    height = 0
    try:
        import pygame

        if pygame.display.get_init():
            sizes = pygame.display.get_desktop_sizes() if hasattr(pygame.display, "get_desktop_sizes") else []
            height = sizes[0][1] if sizes else pygame.display.Info().current_h
    except Exception:
        height = 0
    if height >= 2000:
        return 2160
    if height >= 1400:
        return 1440
    return 1080


# -- editing config files, keeping everything else ---------------------------------


def set_ini(text: str, changes: dict[str, dict[str, str]]) -> str:
    """INI text with `changes` ({section: {key: value}}) applied; other lines,
    comments and ordering stay as they were."""
    lines = text.splitlines()
    pending = {s: dict(kv) for s, kv in changes.items()}
    section = None
    out: list[str] = []

    def flush(sec: str | None) -> None:
        # Keys this section didn't have yet go at its end.
        for key, value in pending.pop(sec, {}).items():
            out.append(f"{key} = {value}")

    for line in lines:
        m = re.match(r"^\s*\[(.+)\]\s*$", line)
        if m:
            flush(section)
            section = m.group(1)
            out.append(line)
            continue
        km = re.match(r"^(\s*)([^=;#\s][^=]*?)\s*=", line)
        if km and section in pending and km.group(2) in pending[section]:
            out.append(f"{km.group(1)}{km.group(2)} = {pending[section].pop(km.group(2))}")
            continue
        out.append(line)
    flush(section)
    for sec in list(pending):
        if pending[sec]:
            out += ["", f"[{sec}]"] + [f"{k} = {v}" for k, v in pending.pop(sec).items()]
    return "\n".join(out) + "\n"


def set_cfg(text: str, changes: dict[str, str]) -> str:
    """RetroArch's retroarch.cfg: key = "value" lines."""
    pending = dict(changes)
    out = []
    for line in text.splitlines():
        m = re.match(r'^\s*([A-Za-z0-9_]+)\s*=', line)
        if m and m.group(1) in pending:
            out.append(f'{m.group(1)} = "{pending.pop(m.group(1))}"')
        else:
            out.append(line)
    out += [f'{k} = "{v}"' for k, v in pending.items()]
    return "\n".join(out) + "\n"


# -- the emulators -------------------------------------------------------------------


@dataclass
class Tune:
    app: str  # Flatpak ID
    name: str
    files: list[tuple[str, str, Callable[[int], dict]]]  # (path under ~/.var/app/<app>, "ini"|"cfg", changes)
    summary: Callable[[int], str]
    # Raised when the settings change, so emulators tuned before get the new ones.
    version: int = 1

    @property
    def key(self) -> str:
        """How it's recorded in settings' "emulation_tuned" once applied."""
        return self.app if self.version == 1 else f"{self.app}@{self.version}"


def _dolphin_gfx(h: int) -> dict:
    return {"Settings": {"InternalResolution": str(SCALES["gc"][h]), "ShaderCompilationMode": "2",
                         "WaitForShadersBeforeStarting": "True"},
            "Enhancements": {"MaxAnisotropy": "4"}}


TUNES = [
    Tune("org.DolphinEmu.dolphin-emu", "Dolphin (GameCube, Wii)", [
        ("config/dolphin-emu/Dolphin.ini", "ini", lambda h: {
            "Core": {"GFXBackend": "Vulkan"}, "Display": {"Fullscreen": "True"},
            "Interface": {"ConfirmStop": "False"}}),
        ("config/dolphin-emu/GFX.ini", "ini", _dolphin_gfx),
    ], lambda h: f"Vulkan, {SCALES['gc'][h]}x resolution, stutter-free shaders, 16x filtering"),
    Tune("net.pcsx2.PCSX2", "PCSX2 (PlayStation 2)", [
        ("config/PCSX2/inis/PCSX2.ini", "ini", lambda h: {
            "EmuCore/GS": {"Renderer": "14", "upscale_multiplier": str(SCALES["ps2"][h]), "MaxAnisotropy": "16"},
            "EmuCore/Speedhacks": {"vuThread": "true"},
            "UI": {"StartFullscreen": "true", "ConfirmShutdown": "false", "HideMouseCursor": "true"}}),
    ], lambda h: f"Vulkan, {SCALES['ps2'][h]}x resolution, multi-threaded VU, 16x filtering"),
    Tune("org.duckstation.DuckStation", "DuckStation (PlayStation)", [
        ("data/duckstation/settings.ini", "ini", lambda h: {
            "GPU": {"Renderer": "Vulkan", "ResolutionScale": str(SCALES["psx"][h]), "PGXPEnable": "true"},
            "Main": {"StartFullscreen": "true", "ConfirmPowerOff": "false"}}),
    ], lambda h: f"Vulkan, {SCALES['psx'][h]}x resolution, PGXP (no wobbly polygons)"),
    Tune("org.ppsspp.PPSSPP", "PPSSPP (PSP)", [
        ("config/ppsspp/PSP/SYSTEM/ppsspp.ini", "ini", lambda h: {
            "Graphics": {"GraphicsBackend": "3 (VULKAN)", "InternalResolution": str(SCALES["psp"][h]),
                         "AnisotropyLevel": "4", "FullScreen": "True"}}),
    ], lambda h: f"Vulkan, {SCALES['psp'][h]}x resolution, 16x filtering"),
    Tune("org.libretro.RetroArch", "RetroArch (retro consoles)", [
        ("config/retroarch/retroarch.cfg", "cfg", lambda h: {
            "video_driver": "vulkan", "video_fullscreen": "true", "video_vsync": "true",
            "video_threaded": "false", "pause_nonactive": "false",
            # Guide belongs to Hearth (Quick Menu, hold for home). RetroArch's
            # controller profiles put its menu on Guide too; a button set here
            # overrides the profile, and no controller has a button 63. Its
            # menu moves to clicking both sticks (L3 + R3).
            "input_menu_toggle_btn": "63", "input_menu_toggle_gamepad_combo": "2"}),
    ], lambda h: "Vulkan, full screen, low-latency video; menu on L3 + R3 (Guide is Hearth's)", version=2),
]


def installed(tune: Tune) -> bool:
    return library.flatpak_installed(tune.app)


def config_path(tune: Tune, rel: str) -> Path:
    return library.home() / ".var/app" / tune.app / rel


def apply(tune: Tune, height: int) -> str:
    """Apply one emulator's settings. Returns what happened, for the Settings app."""
    if not installed(tune):
        return "not installed"
    missing = [rel for rel, _, _ in tune.files if not config_path(tune, rel).exists()]
    if missing:
        return "open it once first, then apply again"
    for rel, kind, changes in tune.files:
        path = config_path(tune, rel)
        backup = path.with_name(path.name + ".hearth-backup")
        if not backup.exists():
            shutil.copy2(path, backup)
        text = path.read_text(errors="replace")
        new = set_ini(text, changes(height)) if kind == "ini" else set_cfg(text, changes(height))
        if new != text:
            tmp = path.with_name(path.name + ".hearth-tmp")
            tmp.write_text(new)
            os.replace(tmp, path)  # the emulator's own settings: never half-written
    return tune.summary(height)


def apply_all(setting: str = "auto") -> dict[str, str]:
    height = target_height(setting)
    results = {}
    for tune in TUNES:
        try:
            results[tune.name] = apply(tune, height)
        except OSError as e:
            results[tune.name] = f"couldn't change its settings: {e}"
    log.info("emulator settings (%sp): %s", height, results)
    return results


def auto(setting: str, done: set[str]) -> set[str]:
    """Tune each emulator once, as soon as it has written its own config.
    Returns the updated set of tuned emulators."""
    height = target_height(setting)
    for tune in TUNES:
        if tune.key in done or not installed(tune):
            continue
        if all(config_path(tune, rel).exists() for rel, _, _ in tune.files):
            try:
                apply(tune, height)
                done.add(tune.key)
            except OSError as e:
                log.warning("tuning %s: %s", tune.name, e)
    return done
