"""Emblems: small drawings for tiles that have no artwork of their own.

In the home screen's motorsport look: Settings is a gearbox, Sleep a moon over
the paddock, Restart a lap of a circuit, Power Off an engine start button.
Drawn in code (no image files), four times over and scaled down so the edges
are smooth, in the livery's colours. Pick one per tile with `emblem = "gears"`
in apps.toml.
"""

from __future__ import annotations

import math
from typing import Callable

import pygame

from .style import RGB, Livery, mix

SS = 4  # drawn this many times larger, then scaled down (anti-aliasing)
CLEAR = (0, 0, 0, 0)

Pt = tuple[float, float]


class Pen:
    """Drawing on a square canvas in units of its size (0..1 across)."""

    def __init__(self, size: int, lv: Livery):
        self.n = size * SS
        self.surf = pygame.Surface((self.n, self.n), pygame.SRCALPHA)
        self.fg: RGB = lv.text
        self.accent: RGB = lv.accent
        self.second: RGB = lv.second
        self.shade: RGB = mix(lv.text, lv.ink, 0.45)

    def p(self, x: float, y: float) -> tuple[int, int]:
        return round(x * self.n), round(y * self.n)

    def d(self, v: float) -> int:
        return max(1, round(v * self.n))

    def disc(self, c: Pt, r: float, color) -> None:
        pygame.draw.circle(self.surf, color, self.p(*c), self.d(r))

    def ring(self, c: Pt, r: float, width: float, color) -> None:
        pygame.draw.circle(self.surf, color, self.p(*c), self.d(r), self.d(width))

    def poly(self, pts: list[Pt], color) -> None:
        pygame.draw.polygon(self.surf, color, [self.p(*q) for q in pts])

    def rect(self, x: float, y: float, w: float, h: float, color, radius: float = 0, width: float = 0) -> None:
        pygame.draw.rect(self.surf, color, (*self.p(x, y), self.d(w), self.d(h)),
                         width=self.d(width) if width else 0, border_radius=self.d(radius) if radius else 0)

    def line(self, a: Pt, b: Pt, width: float, color) -> None:
        """A thick line with round ends."""
        pygame.draw.line(self.surf, color, self.p(*a), self.p(*b), self.d(width))
        self.disc(a, width / 2, color)
        self.disc(b, width / 2, color)

    def arc(self, c: Pt, r: float, width: float, start: float, stop: float, color, steps: int = 64) -> None:
        """A thick arc from `start` to `stop` degrees (0 = right, clockwise on screen)."""
        outer, inner = r + width / 2, r - width / 2
        angles = [math.radians(start + (stop - start) * i / steps) for i in range(steps + 1)]
        pts = [(c[0] + outer * math.cos(a), c[1] + outer * math.sin(a)) for a in angles]
        pts += [(c[0] + inner * math.cos(a), c[1] + inner * math.sin(a)) for a in reversed(angles)]
        self.poly(pts, color)

    def done(self, size: int) -> pygame.Surface:
        return pygame.transform.smoothscale(self.surf, (size, size))


def gear_points(c: Pt, r: float, teeth: int, phase: float = 0.0, depth: float = 0.16) -> list[Pt]:
    """The outline of a spur gear: `teeth` flat-topped teeth around radius r."""
    pts = []
    root = r * (1 - depth)
    step = 2 * math.pi / teeth
    for i in range(teeth):
        a = phase + i * step
        for frac, rad in ((0.0, root), (0.18, r), (0.50, r), (0.68, root)):
            ang = a + frac * step
            pts.append((c[0] + rad * math.cos(ang), c[1] + rad * math.sin(ang)))
    return pts


def _gear(pen: Pen, c: Pt, r: float, teeth: int, phase: float, color, holes: int) -> None:
    pen.poly(gear_points(c, r, teeth, phase), color)
    # Lightening holes, like a race car's drilled gears, and the shaft.
    for i in range(holes):
        a = phase + i * 2 * math.pi / holes
        pen.disc((c[0] + r * 0.52 * math.cos(a), c[1] + r * 0.52 * math.sin(a)), r * 0.17, CLEAR)
    pen.disc(c, r * 0.22, CLEAR)
    pen.ring(c, r * 0.22, r * 0.07, color)


def gears(pen: Pen) -> None:
    """Settings: a gearbox, three drilled gears in mesh."""
    radii = (0.25, 0.17, 0.115)
    centres = [(0.0, 0.0)]
    for i, ang in enumerate((-35, 50)):
        dist = (radii[i] + radii[i + 1]) * 0.93
        x, y = centres[-1]
        centres.append((x + dist * math.cos(math.radians(ang)), y + dist * math.sin(math.radians(ang))))
    # Centre the set on the canvas.
    left = min(x - r for (x, _), r in zip(centres, radii))
    right = max(x + r for (x, _), r in zip(centres, radii))
    top = min(y - r for (_, y), r in zip(centres, radii))
    bottom = max(y + r for (_, y), r in zip(centres, radii))
    dx, dy = 0.5 - (left + right) / 2, 0.5 - (top + bottom) / 2
    c1, c2, c3 = ((x + dx, y + dy) for x, y in centres)
    _gear(pen, c1, radii[0], 14, 0.0, pen.fg, 5)
    _gear(pen, c2, radii[1], 10, math.pi / 10, pen.accent, 4)
    _gear(pen, c3, radii[2], 7, 0.2, pen.fg, 0)


def camera(pen: Pen) -> None:
    """Captures: a period camera with a big lens."""
    pen.rect(0.10, 0.30, 0.80, 0.50, pen.fg, radius=0.08)
    pen.rect(0.30, 0.20, 0.26, 0.14, pen.fg, radius=0.04)  # the viewfinder hump
    pen.rect(0.70, 0.23, 0.12, 0.07, pen.accent, radius=0.02)  # flash
    pen.disc((0.48, 0.555), 0.20, CLEAR)
    pen.ring((0.48, 0.555), 0.20, 0.035, pen.shade)
    pen.disc((0.48, 0.555), 0.145, pen.accent)
    pen.disc((0.48, 0.555), 0.085, pen.fg)
    pen.disc((0.435, 0.51), 0.03, pen.accent)  # glint
    pen.rect(0.10, 0.44, 0.12, 0.04, CLEAR)  # a grip line


def moon(pen: Pen) -> None:
    """Sleep: a crescent moon and a few stars."""
    pen.disc((0.46, 0.52), 0.30, pen.fg)
    pen.disc((0.60, 0.42), 0.26, CLEAR)
    for (x, y), r in (((0.72, 0.24), 0.07), ((0.82, 0.50), 0.045), ((0.63, 0.72), 0.035)):
        _star(pen, (x, y), r, pen.accent)


def _star(pen: Pen, c: Pt, r: float, color) -> None:
    pts = []
    for i in range(8):
        rad = r if i % 2 == 0 else r * 0.32
        a = math.radians(i * 45 - 90)
        pts.append((c[0] + rad * math.cos(a), c[1] + rad * math.sin(a)))
    pen.poly(pts, color)


def circuit(pen: Pen) -> None:
    """Restart: round the circuit again, past the chequered start line."""
    c, r, w = (0.5, 0.52), 0.30, 0.10
    pen.arc(c, r, w, -50, 225, pen.fg)
    # The arrowhead, carrying on past the end of the lap (clockwise on screen).
    a = math.radians(-50)
    tip = (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
    back = (math.sin(a), -math.cos(a))  # against the direction of travel
    out = (math.cos(a), math.sin(a))
    pen.poly([(tip[0] + out[0] * 0.12, tip[1] + out[1] * 0.12),
              (tip[0] - out[0] * 0.12, tip[1] - out[1] * 0.12),
              (tip[0] - back[0] * 0.15, tip[1] - back[1] * 0.15)], pen.fg)
    # The chequered start line across the track in the gap.
    a0 = math.radians(242)
    radial, along = (math.cos(a0), math.sin(a0)), (-math.sin(a0), math.cos(a0))
    cell = w * 0.62
    for i in range(2):
        for j in range(2):
            color = pen.accent if (i + j) % 2 == 0 else pen.fg
            rad = r + (i - 0.5) * cell
            cx = c[0] + radial[0] * rad + along[0] * (j - 0.5) * cell
            cy = c[1] + radial[1] * rad + along[1] * (j - 0.5) * cell
            h = cell / 2
            pen.poly([(cx + (radial[0] * sx + along[0] * sy) * h, cy + (radial[1] * sx + along[1] * sy) * h)
                      for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))], color)


def power(pen: Pen) -> None:
    """Power Off: an engine start/stop button."""
    c = (0.5, 0.5)
    pen.disc(c, 0.40, pen.shade)
    pen.ring(c, 0.40, 0.04, pen.fg)
    pen.disc(c, 0.31, pen.accent)
    pen.arc(c, 0.17, 0.065, -55, 235, pen.fg)
    pen.line((0.5, 0.26), (0.5, 0.47), 0.065, pen.fg)


def garage(pen: Pen) -> None:
    """Desktop Mode: the workshop, a screen with a spanner across it."""
    pen.rect(0.10, 0.18, 0.80, 0.52, pen.fg, radius=0.05)
    pen.rect(0.15, 0.23, 0.70, 0.42, CLEAR, radius=0.03)
    for i, (x, y) in enumerate(((0.19, 0.27), (0.37, 0.27), (0.19, 0.45))):
        pen.rect(x, y, 0.15, 0.14, pen.accent if i == 0 else pen.shade, radius=0.015)
    pen.rect(0.43, 0.70, 0.14, 0.08, pen.fg)
    pen.rect(0.28, 0.78, 0.44, 0.05, pen.fg, radius=0.02)
    _spanner(pen, (0.52, 0.58), (0.86, 0.30), pen.accent)


def _spanner(pen: Pen, a: Pt, b: Pt, color) -> None:
    pen.line(a, b, 0.07, color)
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    pen.disc(b, 0.085, color)
    pen.disc((b[0] + ux * 0.05, b[1] + uy * 0.05), 0.045, CLEAR)  # the open jaw
    pen.disc(a, 0.065, color)
    pen.disc(a, 0.03, CLEAR)


def shelf(pen: Pen) -> None:
    """Library: game cases on a shelf, one leaning."""
    base = 0.80
    for i, (x, w, h) in enumerate(((0.16, 0.13, 0.50), (0.31, 0.13, 0.56), (0.46, 0.13, 0.46))):
        color = pen.accent if i == 1 else pen.fg
        pen.rect(x, base - h, w, h, color, radius=0.02)
        pen.rect(x + 0.03, base - h + 0.06, w - 0.06, 0.03, CLEAR)
    # The leaning one.
    ang = math.radians(20)
    x0, w, h = 0.63, 0.13, 0.52
    cos, sin = math.cos(ang), math.sin(ang)
    pts = [(x0, base), (x0 + w * cos, base - w * sin), (x0 + w * cos + h * sin, base - w * sin - h * cos),
           (x0 + h * sin, base - h * cos)]
    pts = [(x + 0.02, y) for x, y in pts]
    pen.poly(pts, pen.fg)
    pen.rect(0.10, base, 0.80, 0.05, pen.shade, radius=0.02)


def lens(pen: Pen) -> None:
    """Search: a magnifying glass over a chequered flag."""
    c, r = (0.42, 0.42), 0.25
    cell = 0.07
    for i in range(-3, 3):
        for j in range(-3, 3):
            if (i + j) % 2 == 0:
                x, y = c[0] + i * cell, c[1] + j * cell
                pen.rect(x, y, cell, cell, pen.shade)
    # Keep the flag inside the glass only.
    mask = pygame.Surface(pen.surf.get_size(), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), pen.p(*c), pen.d(r))
    pen.surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    pen.ring(c, r, 0.07, pen.fg)
    pen.line((c[0] + r * 0.78, c[1] + r * 0.78), (0.84, 0.84), 0.11, pen.accent)


def pad(pen: Pen) -> None:
    """Emulation: a classic controller."""
    pen.disc((0.30, 0.52), 0.21, pen.fg)
    pen.disc((0.70, 0.52), 0.21, pen.fg)
    pen.rect(0.30, 0.34, 0.40, 0.33, pen.fg)
    pen.rect(0.18, 0.47, 0.18, 0.06, pen.shade, radius=0.01)  # d-pad
    pen.rect(0.24, 0.41, 0.06, 0.18, pen.shade, radius=0.01)
    pen.disc((0.66, 0.56), 0.045, pen.accent)
    pen.disc((0.76, 0.47), 0.045, pen.accent)
    pen.rect(0.43, 0.49, 0.06, 0.025, pen.shade, radius=0.01)
    pen.rect(0.52, 0.49, 0.06, 0.025, pen.shade, radius=0.01)


def plug(pen: Pen) -> None:
    """HDMI input: a cable and its plug."""
    pen.poly([(0.22, 0.24), (0.78, 0.24), (0.78, 0.36), (0.70, 0.44), (0.30, 0.44), (0.22, 0.36)], pen.fg)
    pen.rect(0.30, 0.29, 0.40, 0.05, pen.shade, radius=0.01)
    pen.rect(0.34, 0.44, 0.32, 0.18, pen.accent, radius=0.03)
    pen.rect(0.44, 0.62, 0.12, 0.08, pen.fg)
    pen.line((0.50, 0.70), (0.50, 0.86), 0.07, pen.fg)


EMBLEMS: dict[str, Callable[[Pen], None]] = {
    "gears": gears, "camera": camera, "moon": moon, "circuit": circuit, "power": power, "garage": garage,
    "shelf": shelf, "lens": lens, "pad": pad, "plug": plug,
}

# The built-in tiles' emblems, so a customised apps.toml gets them too.
BY_ID = {
    "settings": "gears", "captures": "camera", "sleep": "moon", "restart": "circuit", "poweroff": "power",
    "desktop": "garage", "library": "shelf", "search": "lens", "emulation": "pad", "hdmi-in": "plug",
}

_cache: dict[tuple, pygame.Surface] = {}


def for_app(app, size: int, lv: Livery) -> pygame.Surface | None:
    """A tile's emblem: the one it names, or its built-in one."""
    return draw(app.emblem or BY_ID.get(app.id), size, lv)


def draw(name: str | None, size: int, lv: Livery) -> pygame.Surface | None:
    """The named emblem, `size` pixels square, or None if there's no such one."""
    fn = EMBLEMS.get(name or "")
    if fn is None or size < 4:
        return None
    key = (name, size, lv.name)
    if key not in _cache:
        if len(_cache) > 64:
            _cache.clear()
        pen = Pen(size, lv)
        fn(pen)
        _cache[key] = pen.done(size)
    return _cache[key]
