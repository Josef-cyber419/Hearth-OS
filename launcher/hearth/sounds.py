"""Optional UI sounds, like a console's: a soft tick as focus moves, a
chime when something opens, a lower one going back.

Made here (short sine tones with a quick fade), so there are no sound files
to ship. Off by default: Settings → Home screen → Sounds. If audio isn't
available, they're silently skipped.
"""

from __future__ import annotations

import logging
import math
import struct

log = logging.getLogger("hearth")

RATE = 44100
VOLUME = 0.18  # of full scale: present, never loud

# name: [(frequency Hz, duration s), ...] played one after another
TONES = {
    "move": [(1760, 0.018)],
    "select": [(880, 0.045), (1320, 0.07)],
    "back": [(990, 0.045), (660, 0.06)],
    "favorite": [(1175, 0.04), (1568, 0.04), (2093, 0.06)],
}

_enabled = False
_sounds: dict[str, object] = {}
_failed = False


def tone(parts: list[tuple[float, float]], volume: float = VOLUME, rate: int = RATE) -> bytes:
    """16-bit mono PCM: each part a sine with a quick attack and a smooth fade."""
    out = bytearray()
    for freq, seconds in parts:
        n = int(rate * seconds)
        attack = max(1, int(rate * 0.003))
        for i in range(n):
            env = min(1.0, i / attack) * (1 - i / n) ** 2
            out += struct.pack("<h", int(32767 * volume * env * math.sin(2 * math.pi * freq * i / rate)))
    return bytes(out)


def enable(on: bool) -> None:
    global _enabled
    _enabled = bool(on)


def play(name: str) -> None:
    global _failed
    if not _enabled or _failed or name not in TONES:
        return
    try:
        import pygame

        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=RATE, size=-16, channels=1, buffer=512)
        if name not in _sounds:
            _sounds[name] = pygame.mixer.Sound(buffer=tone(TONES[name]))
        _sounds[name].play()
    except Exception as e:  # no audio device, no mixer: carry on silently
        _failed = True
        log.info("sounds: off (%s)", e)
