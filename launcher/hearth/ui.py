"""The 10-foot home screen: rows of tiles, a clock, and a confirm dialog.

The look is heritage motorsport: tiles painted like period race cars (deep
enamel, twin stripes, a number roundel), condensed signwriter type, and a
livery of your choice (see style.py). Everything moves on eased, frame-rate
independent curves; `motion = "reduced"` keeps it still.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import pygame

from . import style
from .config import App
from .input import InputMapper
from .model import Home, Nav
from .style import Livery, Smooth, Type, ease_in_out, ease_out, enamel, mix, parse_color

RUNNING = (86, 214, 128)
BOOT_SECONDS = 1.6
RETURN_SECONDS = 0.55
LAUNCH_SECONDS = 0.42
CONFIRM_SECONDS = 0.18
POINTER_SECONDS = 2.5  # the pointer hides this long after it last moved
SLANT = 0.45  # the lean of the big livery stripes, as a fraction of height


class Theme:
    """Sizes derived from screen height so 720p, 1080p and 4K all look right."""

    def __init__(self, size: tuple[int, int], livery: str = "gulf") -> None:
        w, h = size
        u = self.u = h / 1080
        self.lv: Livery = style.livery(livery)
        self.type = Type(u)
        self.width, self.height = w, h
        self.margin = int(104 * u)
        self.header_h = int(176 * u)
        self.footer_h = int(112 * u)
        self.tile_w = int(344 * u)
        self.tile_h = int(204 * u)
        self.gap = int(34 * u)
        self.row_title_h = int(62 * u)
        self.row_h = self.row_title_h + self.tile_h + int(66 * u)
        self.radius = max(4, int(12 * u))
        self.focus_scale = 1.06
        t = self.type
        self.font_brand = t(34, "cond", "semibold")
        self.font_clock = t(56, "cond", "semibold")
        self.font_date = t(20, "cond", "semibold")
        self.font_row = t(24, "cond", "semibold")
        self.font_tile = t(29, "cond", "semibold")
        self.font_number = t(66, "cond", "bold")
        self.font_title = t(64, "cond", "semibold")
        self.font_hint = t(26, "text", "medium")


def paint_tile(size: tuple[int, int], app: App, th: Theme, lit: bool, icon: pygame.Surface | None = None,
               details: bool = True) -> pygame.Surface:
    """A tile as a little race car: enamel body, twin stripes, a roundel."""
    lv, (w, h) = th.lv, size
    body = enamel(parse_color(app.color), lv.ink)
    if not lit:
        body = mix(body, lv.ink, 0.3)
    surf = style.gradient(size, style.lighten(body, 0.10), mix(body, (0, 0, 0), 0.22), vertical=True)
    # Twin stripes over the body, pinstripe in the livery's accent when focused.
    style.stripes(surf, int(w * 0.70), 0, h, max(3, int(h * 0.085)),
                  (lv.text, lv.accent if lit else lv.text), alpha=205 if lit else 60)
    # The polished top edge of the paint.
    style.blend_rect(surf, pygame.Rect(0, 0, w, max(1, h // 90)), (255, 255, 255, 40 if lit else 18))
    if details:
        center = (int(w * 0.225), int(h * 0.42))
        radius = h * 0.235
        if icon is not None:
            surf.blit(icon, icon.get_rect(center=center))
        else:
            style.roundel(surf, center, radius, app.name[:1].upper(), th.font_number,
                          lv.text if lit else mix(lv.text, lv.ink, 0.18), mix(body, (0, 0, 0), 0.35))
        pad = int(h * 0.1)
        name = style.tracked(th.font_tile, app.name.upper(), lv.text if lit else mix(lv.text, lv.ink, 0.25), 0.07)
        name = style.fit(name, int(w * 0.70) - pad * 2)
        surf.blit(name, (pad, h - pad - name.get_height() + int(h * 0.03)))
    style.rounded(surf, th.radius)
    if lit:
        pygame.draw.rect(surf, (*lv.text, 225), surf.get_rect(), width=max(2, int(2 * th.u)),
                         border_radius=th.radius)
    return surf


def paint_loading(size: tuple[int, int], app: App, livery: str = "gulf") -> pygame.Surface:
    """The "Starting <app>" card: the chosen tile, opened out to fill the screen."""
    th = Theme(size, livery)
    lv, (w, h) = th.lv, size
    body = enamel(parse_color(app.color), lv.ink)
    surf = style.gradient(size, mix(body, lv.ink, 0.30), mix(body, lv.ink, 0.78), vertical=True)
    style.stripes(surf, int(w * 0.70), 0, h, max(3, int(th.tile_h * 1.06 * 0.085)), (lv.text, lv.accent), alpha=60)
    cy = int(h * 0.42)
    radius = h * 0.115
    style.circle(surf, (0, 0, 0, 60), (w // 2, cy + int(radius * 0.12)), radius * 1.04)
    style.roundel(surf, (w // 2, cy), radius, app.name[:1].upper(), th.type(radius * 1.45 / th.u, "cond", "bold"),
                  lv.text, mix(body, (0, 0, 0), 0.35))
    name = style.tracked(th.font_title, app.name.upper(), lv.text, 0.1)
    y = int(cy + radius + th.gap * 1.2)
    surf.blit(name, name.get_rect(midtop=(w // 2, y)))
    y += name.get_height() + th.gap // 2
    if not app.confirm:
        sub = style.tracked(th.font_date, "STARTING", lv.dim, 0.4)
        surf.blit(sub, sub.get_rect(midtop=(w // 2, y)))
        bar_w = int(th.tile_w * 0.3)
        style.stripes(surf, w // 2 - bar_w // 2, y + sub.get_height() + th.gap // 2, bar_w,
                      max(2, int(5 * th.u)), (lv.accent, lv.second), vertical=False)
    return surf


class HomeScreen:
    def __init__(self, surface: pygame.Surface, home: Home, title: str, livery: str = "gulf",
                 motion: str = "full", intro: str | None = None) -> None:
        self.surface = surface
        self.home = home
        self.title = title
        self.livery = livery
        self.clock = "24h"
        self.theme = Theme(surface.get_size(), livery)
        self.reduced = motion == "reduced"
        self.smooth = Smooth(rate=13.0, instant=self.reduced)
        self.background = self._make_background()
        self._fade_bottom = self._make_fade()
        self.confirming: App | None = None
        self.message: str | None = None
        self.badge: str | None = None
        self.running: set[str] = set()  # background apps, marked on their tiles
        self._icons: dict[str, pygame.Surface | None] = {}
        self._tiles: dict[tuple, pygame.Surface] = {}
        self._shadow: pygame.Surface | None = None
        self._scroll_y = 0.0
        self._target_y = 0.0
        self._last = time.monotonic()
        self._dt = 0.0
        self.intro = None if self.reduced else intro
        self._intro_t0 = self._last
        self._confirm_t0 = 0.0
        self._focus_key: tuple[int, int] | None = None
        self._focus_since = self._last
        self._hits: list[tuple[pygame.Rect, int, int]] = []  # tiles on screen, for the pointer
        self._pointer: tuple[int, int] | None = None
        self._pointer_at = 0.0

    # -- caches ----------------------------------------------------------------

    def _make_background(self) -> pygame.Surface:
        th, lv = self.theme, self.theme.lv
        w, h = th.width, th.height
        bg = style.gradient((w, h), style.lighten(lv.ink, 0.035), mix(lv.ink, (0, 0, 0), 0.35), vertical=True)
        # A faint glow of the livery's stripe colour, top left, like light on paint.
        glow = pygame.Surface((w // 8, h // 8), pygame.SRCALPHA)
        style.circle(glow, (*lv.second, 16), (0, 0), h // 14)
        bg.blit(pygame.transform.smoothscale(glow, (w, h)), (0, 0))
        # The livery's stripes, huge and barely there, running across the corner.
        layer = pygame.Surface((w, h), pygame.SRCALPHA)
        broad = int(h * 0.09)
        for i, (color, bw, a) in enumerate(((lv.accent, broad, 10), (lv.second, broad // 3, 12))):
            x0 = int(w * 0.62) + i * int(broad * 1.35)
            pygame.draw.polygon(layer, (*color, a), [(x0, h), (x0 + bw, h), (x0 + bw + h * SLANT, 0), (x0 + h * SLANT, 0)])
        bg.blit(layer, (0, 0))
        return bg.convert() if pygame.display.get_surface() else bg

    def _make_fade(self) -> pygame.Surface:
        """The background's own pixels, fading in over the bottom of the rows."""
        th = self.theme
        h = int(70 * th.u)
        bottom = th.height - th.footer_h + th.gap // 2
        strip = pygame.Surface((th.width, h), pygame.SRCALPHA)
        strip.blit(self.background, (0, 0), pygame.Rect(0, bottom - h, th.width, h))
        strip.blit(style.gradient((th.width, h), (255, 255, 255, 0), (255, 255, 255, 255), vertical=True), (0, 0),
                   special_flags=pygame.BLEND_RGBA_MULT)
        return strip

    def _icon(self, app: App, size: tuple[int, int]) -> pygame.Surface | None:
        if not app.icon:
            return None
        key = f"{app.icon}@{size}"
        if key not in self._icons:
            try:
                img = pygame.image.load(str(Path(app.icon).expanduser())).convert_alpha()
                scale = min(size[0] / img.get_width(), size[1] / img.get_height())
                new = (int(img.get_width() * scale), int(img.get_height() * scale))
                self._icons[key] = pygame.transform.smoothscale(img, new)
            except (pygame.error, FileNotFoundError, ZeroDivisionError):
                self._icons[key] = None
        return self._icons[key]

    def _tile(self, app: App, lit: bool) -> pygame.Surface:
        th = self.theme
        size = (round(th.tile_w * th.focus_scale), round(th.tile_h * th.focus_scale)) if lit else (th.tile_w, th.tile_h)
        key = (app.id, lit)
        if key not in self._tiles:
            icon = self._icon(app, (int(size[1] * 0.5), int(size[1] * 0.5)))
            self._tiles[key] = paint_tile(size, app, th, lit, icon)
        return self._tiles[key]

    # -- input -----------------------------------------------------------------

    def handle(self, nav: Nav) -> App | None:
        """Apply a navigation action; returns the app to launch, if any."""
        self.intro = None  # any input skips the entrance animation
        self.message = None
        if self.confirming is not None:
            app, self.confirming = self.confirming, None
            return app if nav is Nav.SELECT else None
        if nav is Nav.SELECT:
            app = self.home.selected
            if app is not None and app.confirm:
                self.confirming = app
                self._confirm_t0 = time.monotonic()
                return None
            return app
        if nav is Nav.MENU:
            # Jump to the power/system row (the last one), like a TV's menu key.
            if self.home.config.rows:
                self.home.row = len(self.home.config.rows) - 1
            return None
        self.home.move(nav)
        return None

    # -- pointer (a Wii Remote, or a mouse) --------------------------------------

    def _tile_at(self, pos: tuple[int, int]) -> tuple[int, int] | None:
        for rect, r, c in self._hits:
            if rect.collidepoint(pos):
                return r, c
        return None

    def point(self, pos: tuple[int, int]) -> None:
        """Pointing at a tile highlights it."""
        if self._pointer is not None and abs(pos[0] - self._pointer[0]) + abs(pos[1] - self._pointer[1]) < 2:
            return  # ignore tremor
        self._pointer, self._pointer_at = pos, time.monotonic()
        if self.confirming is None:
            hit = self._tile_at(pos)
            if hit:
                self.home.row, self.home.cols[hit[0]] = hit
                self.intro = None

    def click(self, pos: tuple[int, int]) -> App | None:
        """A click on a tile opens it (or answers the confirm dialog)."""
        if self.confirming is not None:
            return self.handle(Nav.SELECT)
        hit = self._tile_at(pos)
        if hit is None:
            return None
        self.home.row, self.home.cols[hit[0]] = hit
        return self.handle(Nav.SELECT)

    def _draw_pointer(self) -> None:
        if self._pointer is None:
            return
        age = time.monotonic() - self._pointer_at
        if age > POINTER_SECONDS:
            return
        a = 1.0 if age < POINTER_SECONDS - 0.4 else (POINTER_SECONDS - age) / 0.4
        style.draw_pointer(self.surface, self._pointer, self.theme.u, self.theme.lv, a)

    # -- timing ----------------------------------------------------------------

    def _intro_progress(self) -> float:
        """Seconds into the entrance animation (ends it once it's over)."""
        if self.intro is None:
            return 1e9
        elapsed = time.monotonic() - self._intro_t0
        if elapsed > (BOOT_SECONDS if self.intro == "boot" else RETURN_SECONDS) + 0.5:
            self.intro = None
        return elapsed

    def _appear(self, delay: float, duration: float = 0.38) -> float:
        """0..1: how far an element is through its entrance."""
        if self.intro is None:
            return 1.0
        start = 0.55 if self.intro == "boot" else 0.0
        return ease_out((self._intro_progress() - start - delay) / duration)

    # -- drawing ---------------------------------------------------------------

    def draw(self) -> None:
        now = time.monotonic()
        self._dt, self._last = min(0.1, now - self._last), now
        th, s = self.theme, self.surface
        s.blit(self.background, (0, 0))

        # Scroll just enough to keep the focused row fully on screen.
        area = pygame.Rect(0, th.header_h, th.width, th.height - th.header_h - th.footer_h)
        row_top = self.home.row * th.row_h
        if row_top < self._target_y:
            self._target_y = row_top
        elif row_top + th.row_h > self._target_y + area.h:
            self._target_y = row_top + th.row_h - area.h
        self._scroll_y = self.smooth.get("scroll_y", self._target_y, self._dt)

        focus_key = (self.home.row, self.home.col)
        if focus_key != self._focus_key:
            self._focus_key, self._focus_since = focus_key, now

        s.set_clip(area.inflate(0, th.gap))
        self._hits = []
        indicator = None
        for r in range(len(self.home.config.rows)):
            y = int(area.y + r * th.row_h - self._scroll_y)
            if area.top - th.row_h < y < area.bottom:
                rect = self._draw_row(r, y)
                if rect is not None:
                    indicator = rect
        if indicator is not None:
            self._draw_indicator(indicator)
        s.set_clip(None)
        # Rows melt into the background at the edges instead of being cut off.
        s.blit(self._fade_bottom, (0, area.bottom - self._fade_bottom.get_height() + th.gap // 2))
        self._draw_header()

        if not self.home.config.rows:
            msg = style.tracked(th.font_row, "NO APPS AVAILABLE: CHECK APPS.TOML", th.lv.dim, 0.14)
            s.blit(msg, msg.get_rect(center=(th.width // 2, th.height // 2)))
        self._draw_hints()
        if self.intro == "boot":
            self._draw_boot_sweep()
        if self.confirming is not None:
            self._draw_confirm(self.confirming)
        self._draw_pointer()

    def _draw_header(self) -> None:
        th, s, lv = self.theme, self.surface, self.theme.lv
        a = self._appear(0.0, 0.5)
        if a <= 0:
            return
        layer = pygame.Surface((th.width, th.header_h), pygame.SRCALPHA)
        top = int(th.header_h * 0.32)
        cell = max(2, int(7 * th.u))
        style.checkered(layer, th.margin, top + int(9 * th.u), cell, 4, 3, lv.text)
        spacing = 0.32 + (0.5 * (1 - a) if self.intro == "boot" else 0)
        brand = style.tracked(th.font_brand, self.title.upper(), lv.text, spacing)
        layer.blit(brand, (th.margin + cell * 4 + int(20 * th.u), top))

        clock = th.font_clock.render(style.clock_text(self.clock), True, lv.text)
        clock_rect = clock.get_rect(topright=(th.width - th.margin, top - int(14 * th.u)))
        layer.blit(clock, clock_rect)
        date = style.tracked(th.font_date, time.strftime("%a %d %b").upper(), lv.dim, 0.22)
        date_rect = date.get_rect(bottomright=(clock_rect.x - int(22 * th.u), clock_rect.bottom - int(12 * th.u)))
        layer.blit(date, date_rect)
        if self.badge:
            text = style.tracked(th.font_date, self.badge.upper(), lv.accent, 0.14)
            chip = text.get_rect().inflate(int(30 * th.u), int(14 * th.u))
            chip.midright = (date_rect.x - int(28 * th.u), date_rect.centery)
            pygame.draw.rect(layer, lv.accent, chip, width=max(1, int(2 * th.u)), border_radius=chip.h // 2)
            layer.blit(text, text.get_rect(center=chip.center))

        # A hairline rule with the livery's stripes leading it.
        rule_y = th.header_h - int(26 * th.u)
        grow = a if self.intro == "boot" else 1.0
        rule_w = int((th.width - 2 * th.margin) * grow)
        style.blend_rect(layer, pygame.Rect(th.margin, rule_y, rule_w, max(1, int(th.u))), (*lv.text, 34))
        style.stripes(layer, th.margin, rule_y - int(2 * th.u), int(72 * th.u * grow), max(2, int(5 * th.u)),
                      (lv.accent, lv.second), vertical=False)
        if a < 1:
            layer.set_alpha(int(255 * a))
        s.blit(layer, (0, 0))

    def _draw_row(self, r: int, y: int) -> pygame.Rect | None:
        """Draw row r; returns the focused tile's resting rect if it's here."""
        th, s, lv = self.theme, self.surface, self.theme.lv
        row = self.home.config.rows[r]
        focused_row = r == self.home.row
        a = self._appear(0.06 * r, 0.4)
        if a > 0:
            number = style.tracked(th.font_row, f"{r + 1:02d}", lv.accent if focused_row else lv.dim, 0.1)
            label = style.tracked(th.font_row, row.title.upper(), lv.text if focused_row else lv.dim, 0.3)
            number.set_alpha(int(255 * a))
            label.set_alpha(int(255 * a))
            s.blit(number, (th.margin, y))
            s.blit(label, (th.margin + number.get_width() + int(18 * th.u), y))

        col = self.home.cols[r]
        step = th.tile_w + th.gap
        visible = max(1, (th.width - 2 * th.margin + th.gap) // step)
        first = min(max(0, col - visible + 1), max(0, len(row.apps) - visible))
        scroll_x = self.smooth.get(("scroll_x", r), first * step, self._dt)

        ty = y + th.row_title_h
        focus_rect = None
        for c, app in enumerate(row.apps):
            x = int(th.margin + c * step - scroll_x)
            focused = focused_row and c == col
            f = self.smooth.get(("focus", r, c), 1.0 if focused else 0.0, self._dt)
            if focused:
                focus_rect = pygame.Rect(x, ty, th.tile_w, th.tile_h)
            if x > th.width or x + th.tile_w * th.focus_scale < 0:
                continue
            appear = self._appear(0.06 * r + 0.045 * c, 0.42)
            if appear > 0:
                self._draw_tile(app, pygame.Rect(x, ty, th.tile_w, th.tile_h), f, focused, appear)
                visible = pygame.Rect(x, ty, th.tile_w, th.tile_h).clip(
                    pygame.Rect(0, th.header_h, th.width, th.height - th.header_h - th.footer_h))
                if visible.w > th.tile_w // 3 and visible.h > th.tile_h // 3:
                    self._hits.append((visible, r, c))
        return focus_rect

    def _draw_tile(self, app: App, rest: pygame.Rect, f: float, focused: bool, appear: float) -> None:
        th, s = self.theme, self.surface
        scale = 1 + (th.focus_scale - 1) * f
        rect = pygame.Rect(0, 0, round(rest.w * scale), round(rest.h * scale))
        rect.center = (rest.centerx, rest.centery - int(8 * th.u * f) + int((1 - appear) * th.gap * 1.3))
        alpha = int(255 * appear)

        if f > 0.01:
            if self._shadow is None:
                lit = self._tile(app, True)
                self._shadow = style.soft_shadow(lit.get_size(), th.radius, th.gap, 170)
            shadow = pygame.transform.smoothscale(self._shadow, (rect.w + th.gap * 2, rect.h + th.gap * 2)) \
                if f < 0.99 else self._shadow
            shadow.set_alpha(int(alpha * f))
            s.blit(shadow, (rect.x - th.gap, rect.y - th.gap + int(16 * th.u)))
            shadow.set_alpha(None)

        if f <= 0.01:
            img = self._tile(app, False)
        elif f >= 0.99:
            img = self._tile(app, True)
        else:
            # Mid-animation: paint both states at this exact size (text stays
            # crisp and in register) and cross-fade.
            icon = self._icon(app, (int(rect.h * 0.5), int(rect.h * 0.5)))
            img = paint_tile(rect.size, app, th, False, icon)
            lit = paint_tile(rect.size, app, th, True, icon)
            lit.set_alpha(int(255 * f))
            img.blit(lit, (0, 0))
        if alpha < 255:
            img.set_alpha(alpha)
        s.blit(img, rect.topleft)
        img.set_alpha(None)

        # Now and then, light runs across the focused tile's paint.
        if focused and not self.reduced and f >= 0.99:
            since = time.monotonic() - self._focus_since - 0.5
            phase = (since % 5.0) / 1.1 if since > 0 else 0
            glint = style.sheen(rect.size, phase)
            if glint is not None:
                s.blit(style.rounded(glint, th.radius), rect.topleft)

        if app.id in self.running:
            dot = (rect.right - int(26 * th.u), rect.y + int(26 * th.u))
            style.circle(s, (0, 0, 0), dot, 10 * th.u)
            style.circle(s, RUNNING, dot, 7 * th.u)

    def _draw_indicator(self, tile: pygame.Rect) -> None:
        """The livery stripe under the focused tile; it glides between tiles."""
        th = self.theme
        x = self.smooth.get("ind_x", tile.x, self._dt)
        y = self.smooth.get("ind_y", tile.bottom + int(th.tile_h * 0.03) + int(20 * th.u), self._dt)
        # It stretches a little while it travels, like a streak.
        length = int(th.tile_w * 0.28 + min(abs(tile.x - x), th.tile_w) * 0.35)
        a = self._appear(0.2, 0.4)
        if a > 0:
            layer = pygame.Surface((length, int(12 * th.u) + 2), pygame.SRCALPHA)
            style.stripes(layer, 0, 0, length, max(2, int(6 * th.u)), (th.lv.accent, th.lv.second), vertical=False)
            layer.set_alpha(int(255 * a))
            self.surface.blit(layer, (int(x), int(y)))

    def _draw_hints(self) -> None:
        th, s, lv = self.theme, self.surface, self.theme.lv
        cy = th.height - th.footer_h // 2
        if self.message:
            text = th.font_hint.render(self.message, True, lv.text)
            x = th.margin
            style.stripes(s, x, cy - text.get_height() // 2, text.get_height(), max(3, int(6 * th.u)),
                          (lv.accent, lv.second))
            s.blit(text, (x + int(26 * th.u), cy - text.get_height() // 2))
            return
        if self._appear(0.3, 0.4) < 1:
            return
        x = th.margin
        for button, label in (("A", "Open"), ("B", "Back"), ("START", "System"), ("GUIDE", "Quick Menu")):
            x = style.button_hint(s, x, cy, button, label, th.type, lv)

    def _draw_boot_sweep(self) -> None:
        """Power on: the livery's stripes sweep across the screen."""
        th, lv = self.theme, self.theme.lv
        p = ease_in_out(self._intro_progress() / 0.95)
        if p >= 1:
            return
        w, h = th.width, th.height
        slant = h * SLANT
        layer = pygame.Surface((w, h), pygame.SRCALPHA)
        broad = int(h * 0.16)
        bands = ((lv.accent, broad), (lv.second, broad // 3), (lv.text, broad // 8))
        total = sum(b for _, b in bands) + broad // 4 * 2 + slant
        x = -total + (w + total * 2) * p
        for color, bw in bands:
            pygame.draw.polygon(layer, color, [(x, h), (x + bw, h), (x + bw + slant, 0), (x + slant, 0)])
            x += bw + broad // 4
        self.surface.blit(layer, (0, 0))

    def _draw_confirm(self, app: App) -> None:
        th, s, lv = self.theme, self.surface, self.theme.lv
        p = 1.0 if self.reduced else ease_out((time.monotonic() - self._confirm_t0) / CONFIRM_SECONDS)
        shade = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, int(180 * p)))
        s.blit(shade, (0, 0))

        box = pygame.Rect(0, 0, int(th.width * 0.42), int(th.height * 0.27))
        card = pygame.Surface(box.size, pygame.SRCALPHA)
        card.blit(style.gradient(box.size, style.lighten(lv.panel, 0.05), lv.panel, vertical=True), (0, 0))
        stripe_w = style.stripes(card, int(34 * th.u), 0, box.h, max(4, int(12 * th.u)), (lv.accent, lv.second))
        style.rounded(card, th.radius)
        pygame.draw.rect(card, (*lv.text, 40), card.get_rect(), width=max(1, int(th.u)), border_radius=th.radius)
        x = int(34 * th.u) + stripe_w + int(40 * th.u)
        caption = style.tracked(th.font_date, "ARE YOU SURE?", lv.dim, 0.3)
        card.blit(caption, (x, int(box.h * 0.2)))
        title = style.fit(style.tracked(th.font_title, app.name.upper(), lv.text, 0.06), box.w - x - int(30 * th.u))
        card.blit(title, (x, int(box.h * 0.2) + caption.get_height() + int(4 * th.u)))
        hx = x
        for button, label in (("A", "Yes"), ("B", "Cancel")):
            hx = style.button_hint(card, hx, int(box.h * 0.78), button, label, th.type, lv)

        scale = 0.96 + 0.04 * p
        if scale < 1:
            card = pygame.transform.smoothscale(card, (int(box.w * scale), int(box.h * scale)))
        card.set_alpha(int(255 * p))
        s.blit(card, card.get_rect(center=(th.width // 2, th.height // 2)))

    # -- transitions -----------------------------------------------------------

    def play_launch(self, app: App) -> None:
        """The focused tile opens out to fill the screen, becoming the
        "Starting…" card."""
        th, s = self.theme, self.surface
        if self.reduced or self._focus_key is None:
            return
        # Find where the tile is on screen right now.
        r, c = self._focus_key
        area_y = th.header_h + r * th.row_h - self._scroll_y
        x = th.margin + c * (th.tile_w + th.gap) - self.smooth.values.get(("scroll_x", r), 0.0)
        start = pygame.Rect(0, 0, round(th.tile_w * th.focus_scale), round(th.tile_h * th.focus_scale))
        start.center = (int(x + th.tile_w / 2), int(area_y + th.row_title_h + th.tile_h / 2 - 8 * th.u))
        full = s.get_rect()
        backdrop = s.copy()
        card = paint_loading(s.get_size(), app, self.livery)
        clock = pygame.time.Clock()
        t0 = time.monotonic()
        while True:
            p = (time.monotonic() - t0) / LAUNCH_SECONDS
            e = ease_in_out(p)
            rect = pygame.Rect(
                int(start.x + (full.x - start.x) * e), int(start.y + (full.y - start.y) * e),
                int(start.w + (full.w - start.w) * e), int(start.h + (full.h - start.h) * e),
            )
            s.blit(backdrop, (0, 0))
            shade = pygame.Surface(full.size, pygame.SRCALPHA)
            shade.fill((0, 0, 0, int(160 * min(1.0, p * 2))))
            s.blit(shade, (0, 0))
            tile = paint_tile(rect.size, app, th, True, details=p < 0.25)
            s.blit(tile, rect.topleft)
            if p > 0.55:
                card.set_alpha(int(255 * min(1.0, (p - 0.55) / 0.45)))
                s.blit(card, (0, 0))
            pygame.display.flip()
            pygame.event.pump()
            if p >= 1:
                break
            clock.tick(60)
        card.set_alpha(None)
        s.blit(card, (0, 0))
        pygame.display.flip()


def run(
    surface: pygame.Surface,
    home: Home,
    title: str,
    message: str | None = None,
    allow_quit: bool = False,
    max_frames: int | None = None,
    input_blocked: Callable[[], bool] | None = None,
    badge: str | None = None,
    running: set[str] | None = None,
    livery: str = "gulf",
    motion: str = "full",
    intro: str | None = None,
    stats=None,
    clock: str = "24h",
) -> App | None:
    """Show the home screen until the user picks an app.

    Returns None only when quitting is allowed (dev mode) and requested.
    `input_blocked` is polled a few times a second; while it's true (the Quick
    Menu is open over the home screen), input is ignored. `intro` is "boot"
    for the power-on animation, "return" for coming back from an app.
    `stats` (events.FrameStats) collects frame times.
    """
    screen = HomeScreen(surface, home, title, livery=livery, motion=motion, intro=intro)
    screen.message = message
    screen.clock = clock
    screen.badge = badge
    screen.running = running or set()
    mapper = InputMapper()
    mapper.open_devices()
    clock = pygame.time.Clock()
    frames = 0
    blocked = False
    while max_frames is None or frames < max_frames:
        frames += 1
        if input_blocked and frames % 8 == 0:
            was_blocked, blocked = blocked, input_blocked()
            if blocked and not was_blocked:
                mapper.reset()
        now = pygame.time.get_ticks()
        navs: list[Nav] = []
        chosen = None
        for event in pygame.event.get():
            if event.type == pygame.QUIT and allow_quit:
                return None
            if not blocked and event.type == pygame.MOUSEMOTION:
                screen.point(event.pos)
            elif not blocked and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                chosen = screen.click(event.pos)
            nav = mapper.translate(event, now)
            if nav is not None and not blocked:
                navs.append(nav)
        repeat = mapper.repeat(now)
        if repeat is not None and not blocked:
            navs.append(repeat)
        for nav in navs:
            if nav is Nav.BACK and allow_quit and screen.confirming is None and home.row == 0 and home.col == 0:
                return None
            app = screen.handle(nav)
            if app is not None:
                chosen = app
                break
        if chosen is not None:
            if not chosen.background and not chosen.confirm and not chosen.builtin:
                screen.play_launch(chosen)
            return chosen
        screen.draw()
        pygame.display.flip()
        if stats is not None:
            stats.tick()
        clock.tick(60)
    return None


def draw_loading(surface: pygame.Surface, app: App, livery: str = "gulf") -> None:
    """A full-screen "Starting <app>…" card, shown until the app's window appears."""
    surface.blit(paint_loading(surface.get_size(), app, livery), (0, 0))
    pygame.display.flip()
