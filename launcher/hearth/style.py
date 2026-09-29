"""Hearth's look: colour schemes after classic racing liveries, type, motion.

Shared by the home screen (ui.py) and the Quick Menu (quickmenu_view.py), so
the two always match. Pure drawing helpers; no app logic.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pygame
import pygame.gfxdraw

log = logging.getLogger(__name__)

RGB = tuple[int, int, int]
FONT_DIR = Path(__file__).parent / "fonts"
FALLBACK_FAMILIES = "barlowcondensed,cantarell,notosans,dejavusans,freesans"


@dataclass(frozen=True)
class Livery:
    name: str
    ink: RGB  # background
    panel: RGB  # cards, dialogs, the Quick Menu
    text: RGB  # warm white, like a race number
    dim: RGB
    accent: RGB  # the broad stripe: focus, values, highlights
    second: RGB  # the pinstripe beside it


LIVERIES = {
    "gulf": Livery("Gulf", ink=(11, 16, 22), panel=(20, 28, 37), text=(241, 235, 222), dim=(139, 151, 162),
                   accent=(243, 129, 42), second=(140, 196, 230)),
    "martini": Livery("Martini", ink=(10, 12, 18), panel=(19, 22, 33), text=(241, 237, 228), dim=(145, 150, 166),
                      accent=(218, 41, 47), second=(84, 160, 214)),
    "brg": Livery("British Racing Green", ink=(9, 17, 13), panel=(17, 31, 24), text=(238, 232, 212),
                  dim=(138, 156, 144), accent=(233, 196, 72), second=(214, 204, 174)),
    "rosso": Livery("Rosso", ink=(15, 10, 10), panel=(31, 20, 20), text=(242, 236, 228), dim=(162, 147, 143),
                    accent=(222, 28, 38), second=(246, 196, 0)),
    "silver": Livery("Silver Arrow", ink=(12, 13, 15), panel=(27, 29, 32), text=(236, 238, 240),
                     dim=(140, 146, 153), accent=(206, 211, 217), second=(0, 161, 150)),
}


def livery(name: str) -> Livery:
    if name not in LIVERIES:
        log.warning("unknown livery %r; using gulf (choices: %s)", name, ", ".join(LIVERIES))
    return LIVERIES.get(name, LIVERIES["gulf"])


# -- colour -------------------------------------------------------------------


def parse_color(hex_str: str, default: RGB = (58, 63, 88)) -> RGB:
    try:
        c = pygame.Color(hex_str)
        return (c.r, c.g, c.b)
    except (ValueError, TypeError):
        return default


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def lighten(c: RGB, t: float) -> RGB:
    return mix(c, (255, 255, 255), t)


def enamel(color: RGB, ink: RGB) -> RGB:
    """An app's brand colour as deep, slightly muted paint: every tile still
    reads as its app, but the row looks like one set rather than a mosaic."""
    grey = sum(color) // 3
    muted = mix(color, (grey, grey, grey), 0.18)
    return mix(muted, ink, 0.32)


# -- motion -------------------------------------------------------------------


def ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_in_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t**3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def approach(current: float, target: float, dt: float, rate: float = 14.0) -> float:
    """Frame-rate independent smoothing: the same feel at 30, 60 or 120 fps."""
    if abs(target - current) < 0.01:
        return target
    return current + (target - current) * (1 - math.exp(-rate * max(0.0, dt)))


class Smooth:
    """Values that glide to their targets (positions, fills, switch knobs)."""

    def __init__(self, rate: float = 14.0, instant: bool = False) -> None:
        self.rate = rate
        self.instant = instant
        self.values: dict[object, float] = {}

    def get(self, key: object, target: float, dt: float) -> float:
        if self.instant or key not in self.values:
            self.values[key] = target
        else:
            self.values[key] = approach(self.values[key], target, dt, self.rate)
        return self.values[key]


# -- type ---------------------------------------------------------------------


class Type:
    """Barlow (SIL Open Font License): a condensed grotesque in the spirit of
    period race numbers and timing boards. Falls back to system fonts."""

    FILES = {
        ("cond", "medium"): "BarlowCondensed-Medium.ttf",
        ("cond", "semibold"): "BarlowCondensed-SemiBold.ttf",
        ("cond", "bold"): "BarlowCondensed-Bold.ttf",
        ("text", "medium"): "Barlow-Medium.ttf",
        ("text", "semibold"): "Barlow-SemiBold.ttf",
    }

    def __init__(self, scale: float) -> None:
        # Fonts live only as long as the pygame session that loaded them, so
        # each screen keeps its own.
        self.scale = scale
        self._fonts: dict[tuple, pygame.font.Font] = {}

    def __call__(self, px: float, family: str = "cond", weight: str = "semibold") -> pygame.font.Font:
        key = (family, weight, max(8, int(px * self.scale)))
        if key not in self._fonts:
            path = FONT_DIR / self.FILES.get((family, weight), "BarlowCondensed-SemiBold.ttf")
            try:
                self._fonts[key] = pygame.font.Font(str(path), key[2])
            except (OSError, pygame.error):
                self._fonts[key] = pygame.font.SysFont(FALLBACK_FAMILIES, key[2], bold=weight != "medium")
        return self._fonts[key]


def tracked(font: pygame.font.Font, text: str, color, spacing: float = 0.12) -> pygame.Surface:
    """Text with letter spacing (in ems), the way signwriters spaced capitals."""
    return _tracked(font, text, tuple(color), round(spacing, 3))


@lru_cache(maxsize=512)
def _tracked(font: pygame.font.Font, text: str, color: tuple, spacing: float) -> pygame.Surface:
    if not text:
        return pygame.Surface((1, font.get_height()), pygame.SRCALPHA)
    gap = font.get_height() * spacing
    glyphs = [font.render(ch, True, color) for ch in text]
    width = int(sum(g.get_width() for g in glyphs) + gap * (len(glyphs) - 1))
    out = pygame.Surface((max(1, width), font.get_height()), pygame.SRCALPHA)
    x = 0.0
    for g in glyphs:
        out.blit(g, (int(x), 0))
        x += g.get_width() + gap
    return out


def clock_text(clock: str = "24h") -> str:
    if clock == "12h":
        return time.strftime("%I:%M").lstrip("0") + time.strftime(" %p").lower()
    return time.strftime("%H:%M")


def fit(surf: pygame.Surface, max_w: int) -> pygame.Surface:
    if surf.get_width() <= max_w or max_w <= 0:
        return surf
    return pygame.transform.smoothscale(surf, (max_w, max(1, int(surf.get_height() * max_w / surf.get_width()))))


# -- shapes -------------------------------------------------------------------


def circle(surf: pygame.Surface, color, center, radius: float) -> None:
    """Anti-aliased filled circle (translucent colours blend with what's below)."""
    x, y, r = int(center[0]), int(center[1]), max(1, int(radius))
    if len(color) == 4 and color[3] < 255 and surf.get_flags() & pygame.SRCALPHA:
        layer = pygame.Surface((r * 2 + 3, r * 2 + 3), pygame.SRCALPHA)
        circle(layer, color[:3], (r + 1, r + 1), r)
        layer.set_alpha(color[3])
        surf.blit(layer, (x - r - 1, y - r - 1))
        return
    pygame.gfxdraw.aacircle(surf, x, y, r, color)
    pygame.gfxdraw.filled_circle(surf, x, y, r, color)


def blend_rect(surf: pygame.Surface, rect: pygame.Rect, color, radius: int = 0, width: int = 0) -> None:
    """A (possibly translucent) rounded rect, blended with what's below."""
    if rect.w <= 0 or rect.h <= 0:
        return
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(layer, color, layer.get_rect(), width=width, border_radius=radius)
    surf.blit(layer, rect.topleft)


def gradient(size: tuple[int, int], c1, c2, vertical: bool = False) -> pygame.Surface:
    """A smooth two-colour gradient (colours may carry alpha)."""
    c1 = (*c1, 255) if len(c1) == 3 else c1
    c2 = (*c2, 255) if len(c2) == 3 else c2
    seed = pygame.Surface((1, 2) if vertical else (2, 1), pygame.SRCALPHA)
    seed.set_at((0, 0), c1)
    seed.set_at((0, 1) if vertical else (1, 0), c2)
    return pygame.transform.smoothscale(seed, (max(1, size[0]), max(1, size[1])))


def rounded(surf: pygame.Surface, radius: int) -> pygame.Surface:
    """Clip a surface to a rounded rectangle (in place) and return it."""
    mask = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return surf


def soft_shadow(size: tuple[int, int], radius: int, spread: int, alpha: int) -> pygame.Surface:
    """A blurred rounded rect, `spread` px larger on each side than `size`."""
    w, h = size[0] + spread * 2, size[1] + spread * 2
    layer = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(layer, (0, 0, 0, alpha), (spread, spread, size[0], size[1]), border_radius=radius)
    small = pygame.transform.smoothscale(layer, (max(1, w // 8), max(1, h // 8)))
    return pygame.transform.smoothscale(small, (w, h))


def stripes(surf: pygame.Surface, x: int, y: int, length: int, broad: int, colors, vertical: bool = True,
            alpha: int = 255) -> int:
    """Twin racing stripes: a broad band then a pinstripe, like a Le Mans car's
    nose. Returns the total width used."""
    gap = max(1, broad // 3)
    widths = (broad, max(1, broad // 3))
    pos = 0
    for color, w in zip(colors, widths):
        rect = pygame.Rect(x + pos, y, w, length) if vertical else pygame.Rect(x, y + pos, length, w)
        if alpha >= 255:
            surf.fill(color, rect)
        else:
            blend_rect(surf, rect, (*color, alpha))
        pos += w + gap
    return pos - gap


def checkered(surf: pygame.Surface, x: int, y: int, cell: int, cols: int, rows: int, color) -> None:
    """A small chequered flag."""
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                surf.fill(color, (x + c * cell, y + r * cell, cell, cell))
    pygame.draw.rect(surf, color, (x, y, cols * cell, rows * cell), width=max(1, cell // 4))


def roundel(surf: pygame.Surface, center, radius: float, text: str, font: pygame.font.Font, fill, ink) -> None:
    """A race-number roundel: a painted disc carrying the entry's number."""
    circle(surf, fill, center, radius)
    glyph = font.render(text, True, ink)
    # Optical centre: capitals sit a touch high in their line box.
    surf.blit(glyph, glyph.get_rect(center=(int(center[0]), int(center[1] + radius * 0.04))))


# Which controller's button names to show (Settings → Controllers).
# "auto" follows whatever was used last (see note_input).
_prompts = {"style": "auto", "swap": False, "last": "xbox"}
_POSITION = {"A": "south", "B": "east", "X": "west", "Y": "north"}  # the Xbox names, by position
_LABELS = {
    "xbox": {"south": "A", "east": "B", "west": "X", "north": "Y", "START": "MENU", "GUIDE": "GUIDE",
             "VIEW": "VIEW"},
    "playstation": {"south": "cross", "east": "circle", "west": "square", "north": "triangle",
                    "START": "OPTIONS", "GUIDE": "PS", "VIEW": "CREATE"},
    "nintendo": {"south": "B", "east": "A", "west": "Y", "north": "X", "START": "+", "GUIDE": "HOME", "VIEW": "−"},
    # The keys that do the same (input.KEYS), and a Wii Remote's buttons
    # (wiiinput.KEYS: A, B, − for options, + for the menu).
    "keyboard": {"south": "ENTER", "east": "ESC", "west": "F", "north": "F2", "START": "TAB", "GUIDE": "WIN",
                 "LB": "Q", "RB": "E", "VIEW": "/"},
    "wii": {"south": "A", "east": "B", "west": "1", "north": "−", "START": "+", "GUIDE": "HOME"},
}
# Controller names (as SDL reports them) that aren't Xbox-style.
_FAMILIES = (("playstation", ("playstation", "dualsense", "dualshock", "ps3", "ps4", "ps5", "sony")),
             ("nintendo", ("nintendo", "switch", "pro controller", "joy-con", "joycon")))


def set_prompts(style_name: str, confirm: str = "south") -> None:
    _prompts["style"] = style_name if style_name in _LABELS or style_name == "auto" else "auto"
    _prompts["swap"] = confirm == "east"


def controller_family(name: str) -> str:
    """"xbox", "playstation" or "nintendo", from a controller's name."""
    lower = (name or "").lower()
    for family, words in _FAMILIES:
        if any(w in lower for w in words):
            return family
    return "xbox"


def note_input(family: str) -> None:
    """Something was just used: "xbox", "playstation", "nintendo",
    "keyboard" or "wii". With automatic button names, hints follow it."""
    if family in _LABELS:
        _prompts["last"] = family


def prompt_style() -> str:
    return _prompts["last"] if _prompts["style"] == "auto" else _prompts["style"]


def glyph_for(button: str) -> str:
    """What's printed on the button that does what Xbox's `button` does here."""
    style_name = prompt_style()
    labels = _LABELS[style_name]
    position = _POSITION.get(button)
    if position is None:
        return labels.get(button, button)
    # Hearth's own Nintendo-style confirm swaps controller buttons, not keys.
    if _prompts["swap"] and button in ("A", "B") and style_name not in ("keyboard", "wii"):
        position = "east" if button == "A" else "south"
    return labels[position]


def _shape(surf: pygame.Surface, name: str, center, r: float, color) -> None:
    """PlayStation's face-button shapes."""
    cx, cy = center
    w = max(2, int(r / 4))
    if name == "cross":
        pygame.draw.line(surf, color, (cx - r * 0.5, cy - r * 0.5), (cx + r * 0.5, cy + r * 0.5), w)
        pygame.draw.line(surf, color, (cx - r * 0.5, cy + r * 0.5), (cx + r * 0.5, cy - r * 0.5), w)
    elif name == "circle":
        pygame.draw.circle(surf, color, (int(cx), int(cy)), int(r * 0.55), w)
    elif name == "square":
        pygame.draw.rect(surf, color, (cx - r * 0.48, cy - r * 0.48, r * 0.96, r * 0.96), w)
    elif name == "triangle":
        pygame.draw.polygon(surf, color, [(cx, cy - r * 0.6), (cx + r * 0.58, cy + r * 0.42),
                                          (cx - r * 0.58, cy + r * 0.42)], w)


def button_hint(surf: pygame.Surface, x: int, cy: int, button: str, label: str, t: Type, lv: Livery,
                size: float = 1.0) -> int:
    """A controller button glyph and its action, e.g. (A) OPEN, in the
    controller style chosen in Settings. Returns the x coordinate after it."""
    f_btn = t(18 * size, "cond", "bold")
    f_lbl = t(19 * size, "cond", "semibold")
    name = glyph_for(button)
    shape = name in ("cross", "circle", "square", "triangle")
    glyph = None if shape else f_btn.render(name, True, lv.ink)
    h = int(30 * size * t.scale)
    w = h if shape else max(h, glyph.get_width() + h // 2)
    chip = pygame.Rect(x, cy - h // 2, w, h)
    if w == h:
        circle(surf, lv.dim, chip.center, h / 2)
    else:
        pygame.draw.rect(surf, lv.dim, chip, border_radius=h // 2)
    if shape:
        _shape(surf, name, chip.center, h * 0.42, lv.ink)
    else:
        surf.blit(glyph, glyph.get_rect(center=(chip.centerx, chip.centery + 1)))
    text = tracked(f_lbl, label.upper(), lv.dim, 0.14)
    surf.blit(text, (chip.right + h // 3, cy - text.get_height() // 2))
    return chip.right + h // 3 + text.get_width() + h


def inset(surface: pygame.Surface, percent: int) -> tuple[pygame.Surface, tuple[int, int]]:
    """The part of the screen inside a safe area (for TVs that crop the
    edges), and where it sits. The border is black."""
    if percent <= 0:
        return surface, (0, 0)
    w, h = surface.get_size()
    dx, dy = int(w * percent / 100), int(h * percent / 100)
    surface.fill((0, 0, 0))
    rect = pygame.Rect(dx, dy, w - 2 * dx, h - 2 * dy)
    return surface.subsurface(rect), rect.topleft


def draw_pointer(surf: pygame.Surface, pos: tuple[int, int], scale: float, lv: Livery, alpha: float = 1.0) -> None:
    """The on-screen pointer for a Wii Remote (or mouse): a small roundel."""
    r = int(16 * scale)
    layer = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
    c = (r + 2, r + 2)
    circle(layer, (0, 0, 0), c, r)
    circle(layer, lv.text, c, r - max(2, int(3 * scale)))
    circle(layer, lv.accent, c, r * 0.45)
    layer.set_alpha(int(235 * alpha))
    surf.blit(layer, (pos[0] - c[0], pos[1] - c[1]))


def sheen(size: tuple[int, int], phase: float, strength: int = 46) -> pygame.Surface | None:
    """A diagonal highlight sweeping across polished paint; phase 0..1."""
    if not 0.0 < phase < 1.0:
        return None
    w, h = size
    band = max(8, w // 5)
    layer = pygame.Surface(size, pygame.SRCALPHA)
    cx = int(-band - h + (w + h + band * 2) * ease_in_out(phase))
    for i in range(band):
        a = int(strength * math.sin(math.pi * i / band))
        pygame.draw.line(layer, (255, 255, 255, a), (cx + i, h), (cx + i + h, 0))
    return layer
