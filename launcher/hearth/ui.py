"""The 10-foot home screen: rows of tiles, a clock, and a confirm dialog.

The look is heritage motorsport: tiles painted like period race cars (deep
enamel, twin stripes, a number roundel), condensed signwriter type, and a
livery of your choice (see style.py). Everything moves on eased, frame-rate
independent curves; `motion = "reduced"` keeps it still.
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
import time
from pathlib import Path
from typing import Callable

import pygame

from . import events, style
from .config import App
from .input import InputMapper
from .model import Home, Nav
from .style import Livery, Smooth, Type, ease_in_out, ease_out, enamel, mix, parse_color

log = logging.getLogger("hearth")

RUNNING = (86, 214, 128)
BOOT_SECONDS = 1.6
RETURN_SECONDS = 0.55
LAUNCH_SECONDS = 0.42
CONFIRM_SECONDS = 0.18
POINTER_SECONDS = 2.5  # the pointer hides this long after it last moved
# The backdrop follows the focused tile (its artwork, blurred, or its colour)
# once focus rests this long, then fades across over BACKDROP_FADE seconds.
BACKDROP_DELAY = 0.22
BACKDROP_FADE = 0.45
BACKDROPS_KEPT = 3  # full-screen backdrops cached
BATTERY_SECONDS = 20.0  # how often the status bar re-reads controller batteries
NETWORK_SECONDS = 5.0  # and the network connection
GAMES_SECONDS = 30.0  # how long a read of the game library is reused
# The ambient screen saver: each game's art for this long, cross-fading over
# SLIDE_FADE, drifting slowly across (Ken Burns), dimmed to be kind to OLEDs.
SLIDE_SECONDS = 20.0
SLIDE_FADE = 2.5
SLIDE_DIM = 150  # of 255: how much darker the art is shown
SLIDE_MAX = 60  # pictures in one showing (picked at random from the library)
SAVER_CAPTURES = 20  # your newest screenshots join them
# Resting the pointer near the top or bottom edge scrolls the rows.
EDGE_ZONE = 0.12  # fraction of the screen's height at each edge
# Once nothing has moved for SETTLE_SECONDS (no input, no animation), the home
# screen stops redrawing 60 times a second: an unchanging
# picture shouldn't cost CPU. It redraws when what it shows changes (the clock,
# batteries, network, a message). Input is still read 30 times a second.
SETTLE_SECONDS = 3.0
SETTLED_FPS = 2  # how often a settled screen checks whether anything changed
SETTLED_REDRAW = 10.0  # and redraws anyway, just in case
EDGE_FIRST = 0.35  # seconds at the edge before the first step
EDGE_REPEAT = 0.55  # then one row this often
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


_art: dict[str, pygame.Surface | None] = {}


def load_art(path: str | None) -> pygame.Surface | None:
    """A game's artwork, loaded once."""
    if not path:
        return None
    if path not in _art:
        if len(_art) > 200:
            _art.clear()
        try:
            _art[path] = pygame.image.load(path)
        except (pygame.error, OSError, FileNotFoundError):
            _art[path] = None
    return _art[path]


def _wrap(font: pygame.font.Font, text: str, width: int) -> list[str]:
    """Words into lines that fit `width`."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and font.size(trial)[0] > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def _soft_glow(size: tuple[int, int], color, at: tuple[float, float], reach: float, alpha: int) -> pygame.Surface:
    """A soft round glow of `color`, strongest at `at` (fractions of the
    screen) and gone `reach` screen-heights away. Worked out on a tiny
    image and scaled up in steps, so it has no edge at all."""
    w, h = size
    gw, gh = 64, 36
    small = pygame.Surface((gw, gh), pygame.SRCALPHA)
    cx, cy, r = at[0] * gw, at[1] * gh, reach * gh
    for y in range(gh):
        for x in range(gw):
            d = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5 / r
            if d < 1:
                small.set_at((x, y), (*color, int(alpha * (1 - d) ** 2)))
    mid = pygame.transform.smoothscale(small, (w // 4, h // 4))
    return pygame.transform.smoothscale(mid, (w, h))


PLAY = object()  # the Options card's "Play" entry


def played_for(seconds: float) -> str:
    """Play time as a person would say it."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "Less than a minute" if seconds > 0 else "Not yet"
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if hours < 10 and rest else f"{hours} h"


def played_when(timestamp: float, now: float | None = None) -> str:
    if not timestamp:
        return "Never"
    now = time.time() if now is None else now
    days = int((time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
                - time.mktime(time.localtime(timestamp)[:3] + (0, 0, 0, 0, 0, -1))) // 86400)
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 7:
        return f"{days} days ago"
    return time.strftime("%d %b %Y", time.localtime(timestamp)).lstrip("0")


def _soft_oval(size: tuple[int, int], alpha: int) -> pygame.Surface:
    """A dark oval filling `size`, fading to nothing at its edge."""
    w, h = size
    gw = 48
    gh = max(8, int(gw * h / max(1, w)))
    small = pygame.Surface((gw, gh), pygame.SRCALPHA)
    for y in range(gh):
        for x in range(gw):
            d = (((x + 0.5) / gw * 2 - 1) ** 2 + ((y + 0.5) / gh * 2 - 1) ** 2) ** 0.5
            if d < 1:
                small.set_at((x, y), (0, 0, 0, int(alpha * (1 - d * d) ** 1.5)))
    return pygame.transform.smoothscale(pygame.transform.smoothscale(small, (max(1, w // 4), max(1, h // 4))), size)


def _star(surf: pygame.Surface, color, center, r: float) -> None:
    import math

    cx, cy = center
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    pygame.draw.polygon(surf, color, pts)


def cover(img: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
    """Scale an image to fill `size`, cropping the overflow evenly."""
    w, h = size
    scale = max(w / img.get_width(), h / img.get_height())
    scaled = pygame.transform.smoothscale(img, (max(w, int(img.get_width() * scale) + 1),
                                                max(h, int(img.get_height() * scale) + 1)))
    out = pygame.Surface(size, pygame.SRCALPHA)
    out.blit(scaled, ((w - scaled.get_width()) // 2, (h - scaled.get_height()) // 2))
    return out


def _badge(surf: pygame.Surface, text: str, th: Theme, pad: int) -> None:
    """A small label in the tile's top corner (a game's platform, an episode)."""
    lv, w = th.lv, surf.get_width()
    badge = style.fit(style.tracked(th.type(16, "cond", "semibold"), text.upper(), lv.text, 0.18), w - pad * 3)
    chip = badge.get_rect().inflate(int(16 * th.u), int(6 * th.u))
    chip.topright = (w - pad, pad)
    style.blend_rect(surf, chip, (*lv.ink, 190), chip.h // 2)
    surf.blit(badge, badge.get_rect(center=chip.center))


def _progress(surf: pygame.Surface, app: App, th: Theme) -> None:
    """How far into a film or episode you are: a thin bar along the foot."""
    if app.progress is None:
        return
    w, h = surf.get_size()
    bar_h = max(3, int(6 * th.u))
    style.blend_rect(surf, pygame.Rect(0, h - bar_h, w, bar_h), (*th.lv.ink, 200))
    surf.fill(th.lv.accent, (0, h - bar_h, max(bar_h, int(w * min(1.0, app.progress))), bar_h))


def paint_game(size: tuple[int, int], app: App, th: Theme, lit: bool, art: pygame.Surface,
               details: bool = True) -> pygame.Surface:
    """A game tile: its artwork edge to edge, the title over a shaded foot."""
    lv, (w, h) = th.lv, size
    surf = cover(art, size)
    if not lit:
        style.blend_rect(surf, surf.get_rect(), (*lv.ink, 95))
    if details:
        foot = style.gradient((w, int(h * 0.6)), (*lv.ink, 0), (*lv.ink, 235), vertical=True)
        surf.blit(foot, (0, h - foot.get_height()))
        pad = int(h * 0.1)
        if app.platform:
            _badge(surf, app.platform, th, pad)
        name = style.tracked(th.font_tile, app.name.upper(), lv.text if lit else mix(lv.text, lv.ink, 0.2), 0.05)
        surf.blit(style.fit(name, w - pad * 2), (pad, h - pad - name.get_height() + int(h * 0.03)))
    if lit:
        style.stripes(surf, 0, 0, h, max(3, int(h * 0.05)), (lv.accent, lv.second))
    _progress(surf, app, th)
    style.rounded(surf, th.radius)
    if lit:
        pygame.draw.rect(surf, (*lv.text, 225), surf.get_rect(), width=max(2, int(2 * th.u)),
                         border_radius=th.radius)
    return surf


def paint_tile(size: tuple[int, int], app: App, th: Theme, lit: bool, icon: pygame.Surface | None = None,
               details: bool = True) -> pygame.Surface:
    """A tile as a little race car: enamel body, twin stripes, a roundel.
    Games with artwork show that instead."""
    art = load_art(app.art)
    if art is not None:
        return paint_game(size, app, th, lit, art, details)
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
        if app.progress is not None and app.platform:  # Watch next without a picture: say which episode
            _badge(surf, app.platform, th, pad)
    _progress(surf, app, th)
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
    art = load_art(app.art)
    if art is not None:
        # The game's artwork, softly blurred behind its name.
        small = cover(art, (max(1, w // 64), max(1, h // 64)))
        surf = pygame.transform.smoothscale(pygame.transform.smoothscale(small, (w // 8, h // 8)), size)
        style.blend_rect(surf, surf.get_rect(), (*lv.ink, 170))
    else:
        style.stripes(surf, int(w * 0.70), 0, h, max(3, int(th.tile_h * 1.06 * 0.085)), (lv.text, lv.accent),
                      alpha=60)
    cy = int(h * 0.42)
    radius = h * 0.115
    if art is not None:
        card_size = (int(th.tile_w * 1.5), int(th.tile_h * 1.5))
        card = paint_game(card_size, app, th, True, art, details=False)
        rect = card.get_rect(center=(w // 2, cy))
        surf.blit(style.soft_shadow(card_size, th.radius, th.gap, 160), (rect.x - th.gap, rect.y - th.gap + th.gap // 2))
        surf.blit(card, rect)
        y = rect.bottom + th.gap
        if app.platform:
            plat = style.tracked(th.font_date, app.platform.upper(), lv.dim, 0.3)
            surf.blit(plat, plat.get_rect(midtop=(w // 2, y)))
            y += plat.get_height() + th.gap // 3
    else:
        style.circle(surf, (0, 0, 0, 60), (w // 2, cy + int(radius * 0.12)), radius * 1.04)
        style.roundel(surf, (w // 2, cy), radius, app.name[:1].upper(),
                      th.type(radius * 1.45 / th.u, "cond", "bold"), lv.text, mix(body, (0, 0, 0), 0.35))
        y = int(cy + radius + th.gap * 1.2)
    name = style.fit(style.tracked(th.font_title, app.name.upper(), lv.text, 0.1), w - 2 * th.margin)
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
        self.confirm_caption = "ARE YOU SURE?"
        # Asked before opening a tile: a question to confirm first, or None
        # (e.g. starting a game would close the oldest Quick Resume game).
        self.ask: Callable[[App], str | None] | None = None
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
        self._edge: tuple[Nav, float] | None = None  # scrolling at an edge: (direction, next step)
        self._pointer_at = 0.0
        self.options: tuple[App, list, int] | None = None
        self.rebuild: Callable[[], object] | None = None  # fresh contents after a change
        self.back_exits = False  # the Library: B leaves it
        self.exit = False
        self.saver = False  # the screen saver is showing
        self.saver_style = "ambient"  # or "clock" (Settings → Home screen)
        self._slides: list[tuple[str, str | None, str]] = []  # (title, platform, art) for ambient
        self._slide_cache: dict[int, pygame.Surface] = {}
        self._saver_t0 = 0.0
        self.hints = (("A", "Open"), ("X", "Favorite"), ("Y", "Options"), ("VIEW", "Search"), ("GUIDE", "Quick Menu"))
        self.search = None  # the search screen, while it's open (search.Search)
        self.pin = None  # asking for the household PIN (family.PinEntry)
        self.gallery = None  # the Captures screen, while it's open (gallery.Gallery)
        self.whats_new: tuple[str, list[str]] | None = None  # (version, notes) to show once after an update
        self._thumbs: dict = {}  # screenshot path -> thumbnail (loaded one per frame)
        self._full: dict = {}  # screenshot path -> full-screen image (the last few)
        self._games: tuple[float, list] | None = None  # (read at, library.all_games())
        self._details = None  # the game the Options card is about (library.Game), if it's a game
        self._search_t0 = 0.0
        self.favorites: set[str] = self._load_favorites()
        self._backdrops: dict[str, pygame.Surface] = {}  # full screen, the last few
        self._blurs: dict[str, pygame.Surface | None] = {}  # each tile's art, blurred small
        self._backdrop: tuple[str, pygame.Surface] | None = None  # showing now
        self._backdrop_prev: pygame.Surface | None = None  # fading out
        self._backdrop_t0 = 0.0
        self._batteries: list = []
        self._batteries_at = -1e9
        self.settled = False  # nothing moving: drawn a couple of times a second (see run)
        self.busy_until = 0.0  # something is animating until then
        self._link = None  # netstate.Link: how the PC is connected, by the clock
        self._link_at = -1e9
        self._moving_rect: pygame.Rect | None = None
        # Moving a tile (Options → Move): (row, the tile's id, where it started).
        self.moving: tuple[int, str, list[str]] | None = None

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
        key = (app.id, lit, app.progress, app.platform)  # Watch next tiles change as you watch
        if key not in self._tiles:
            icon = self._icon(app, (int(size[1] * 0.5), int(size[1] * 0.5)))
            self._tiles[key] = paint_tile(size, app, th, lit, icon)
        return self._tiles[key]

    # -- input -----------------------------------------------------------------

    # -- the Options popup (Y): favourite, move, hide ---------------------------

    def games(self) -> list:
        """The game library, read at most every GAMES_SECONDS (search, details
        and the screen saver share it; a big ROM folder takes a moment to read)."""
        from . import library

        now = time.monotonic()
        if self._games is None or now - self._games[0] > GAMES_SECONDS:
            self._games = (now, library.all_games())
        return self._games[1]

    @staticmethod
    def _load_favorites() -> set[str]:
        from . import layout

        try:
            return set(layout.favorites())
        except Exception:  # a broken settings file mustn't break the home screen
            return set()

    def toggle_favorite(self) -> None:
        """X: star or unstar the tile you're on (the Favorites row)."""
        from . import layout

        app = self.home.selected
        if app is None or not layout.can_favorite(app.id) or self.rebuild is None:
            return
        on = layout.toggle_favorite(app.id)
        events.record("home_favorite", tile=app.id, on=on)
        self.reload(self.rebuild(), app.id, keep_row=True)
        self.message = f"{app.name}: added to Favorites" if on else f"{app.name}: removed from Favorites"

    def open_options(self) -> None:
        from . import layout, library, settings

        app = self.home.selected
        if app is None:
            return
        row = self.home.config.rows[self.home.row].title
        key = library.key_of(app.id)
        choices: list[tuple[str, Callable[[], None]]] = []
        self._details = None
        if key:
            try:
                self._details = library.details(key, self.games())
            except Exception:  # details are a nicety: never block the options over them
                log.exception("game details")
            choices.append(("Play", PLAY))
        if app.command[0] == "hearth:resume":
            from . import hub

            choices.append((f"Close {app.name}", lambda: hub.close_paused(app.command[1])))
        else:
            if self.rebuild is not None:
                if app.id in self.favorites:
                    choices.append(("Remove from Favorites", lambda: layout.set_favorite(app.id, False)))
                else:
                    choices.append(("Add to Favorites", lambda: layout.set_favorite(app.id, True)))
                # The Library sorts its platform rows itself; only its Favorites row moves.
                movable = layout.can_move(row) and (not self.back_exits or row == layout.FAVORITES)
                if movable and len(self.home.config.rows[self.home.row].apps) > 1:
                    choices.append(("Move", self.start_move))
            if key and row == "Continue":
                choices.append(("Remove from Continue", lambda: settings.toggle_in("hide_recent", key, True)))
            if not key and row != layout.FAVORITES and app.id not in ("settings", "library"):
                choices.append(("Hide this tile", lambda: settings.set_hidden(app.id, True)))
                choices.append(("Bring hidden tiles back: Settings → Home screen", lambda: None))
        if not choices:
            return
        choices.append(("Cancel", lambda: None))
        self.options = (app, choices, 0)
        self._confirm_t0 = time.monotonic()

    def _options_handle(self, nav: Nav) -> App | None:
        app, choices, index = self.options
        if nav in (Nav.UP, Nav.DOWN):
            self.options = (app, choices, (index + (1 if nav is Nav.DOWN else -1)) % len(choices))
        elif nav is Nav.SELECT:
            label, act = choices[index]
            self.options = None
            if act is PLAY:
                return self._open(app)
            act()
            events.record("home_option", tile=app.id, choice=label)
            if self.rebuild is not None and self.moving is None:
                self.reload(self.rebuild(), app.id, keep_row=True)
        elif nav in (Nav.BACK, Nav.OPTIONS, Nav.MENU):
            self.options = None
        return None

    def reload(self, config, keep_id: str | None = None, keep_row: bool = False) -> None:
        """New contents (after a favourite, say), keeping the place as best it
        can: the same tile in the same row if it's still there."""
        row_title = self.home.config.rows[self.home.row].title if self.home.config.rows else None
        home = Home(config)
        titles = [r.title for r in config.rows]
        if keep_row and keep_id and row_title in titles:
            r = titles.index(row_title)
            ids = [a.id for a in config.rows[r].apps]
            home.row = r
            if keep_id in ids:
                home.cols[r] = ids.index(keep_id)
            else:  # it left this row (e.g. unstarred in Favorites): stay near where it was
                home.cols[r] = min(self.home.col, len(ids) - 1)
        elif keep_id and home.select_id(keep_id):
            pass
        elif row_title in titles:
            home.row = titles.index(row_title)
        home.clamp()
        self.home = home
        self._tiles.clear()
        self.favorites = self._load_favorites()

    # -- moving a tile (Options → Move) ------------------------------------------

    def start_move(self) -> None:
        app = self.home.selected
        if app is None:
            return
        ids = [a.id for a in self.home.config.rows[self.home.row].apps]
        self.moving = (self.home.row, app.id, ids)

    def _move_handle(self, nav: Nav) -> None:
        from dataclasses import replace

        from . import layout

        r, tile_id, before = self.moving
        rows = list(self.home.config.rows)
        apps = list(rows[r].apps)
        c = self.home.cols[r]
        if nav in (Nav.LEFT, Nav.RIGHT):
            to = c + (1 if nav is Nav.RIGHT else -1)
            if 0 <= to < len(apps):
                apps[c], apps[to] = apps[to], apps[c]
                rows[r] = replace(rows[r], apps=tuple(apps))
                self.home.config = replace(self.home.config, rows=tuple(rows))
                self.home.cols[r] = to
            return
        if nav in (Nav.SELECT, Nav.OPTIONS, Nav.BACK, Nav.MENU):
            self.moving = None
            if nav is Nav.BACK:  # put it back
                rank = {k: i for i, k in enumerate(before)}
                apps.sort(key=lambda a: rank.get(a.id, len(rank)))
                rows[r] = replace(rows[r], apps=tuple(apps))
                self.home.config = replace(self.home.config, rows=tuple(rows))
                self.home.cols[r] = [a.id for a in apps].index(tile_id)
                return
            ids = [a.id for a in apps]
            layout.save_order(rows[r].title, ids)
            events.record("home_move", row=rows[r].title, tile=tile_id, at=ids.index(tile_id))
            if self.rebuild is not None:
                self.reload(self.rebuild(), tile_id, keep_row=True)

    # -- input -------------------------------------------------------------------

    def handle(self, nav: Nav) -> App | None:
        """Apply a navigation action; returns the app to launch, if any."""
        self.intro = None  # any input skips the entrance animation
        self.message = None
        if self.whats_new is not None:
            if nav in (Nav.SELECT, Nav.BACK, Nav.MENU):
                from . import whatsnew

                whatsnew.mark_seen(self.whats_new[0])
                events.record("whats_new_seen", version=self.whats_new[0])
                self.whats_new = None
            return None
        if self.pin is not None:
            result = self.pin.handle(nav)
            if result == "ok":
                return self.pin_done()
            if result == "cancel":
                self.pin = None
            return None
        if self.gallery is not None:
            if self.gallery.handle(nav) == "close":
                self.gallery = None
                if self.rebuild is not None:  # the Captures tile hides once they're all deleted
                    self.reload(self.rebuild(), "captures")
            return None
        if self.search is not None:
            result = self.search.handle(nav)
            if result == "close":
                self.search = None
            elif result is not None:
                self.search = None
                events.record("search_open", tile=result.id)
                return self._open(result)
            return None
        if self.options is not None:
            return self._options_handle(nav)
        if nav is Nav.SEARCH and self.confirming is None:
            self.open_search()
            return None
        if self.moving is not None:
            self._move_handle(nav)
            return None
        if nav is Nav.OPTIONS:
            self.open_options()
            return None
        if nav is Nav.FAVORITE:
            if self.confirming is None:
                self.toggle_favorite()
            return None
        if nav is Nav.BACK and self.back_exits and self.confirming is None:
            self.exit = True
            return None
        if self.confirming is not None:
            app, self.confirming = self.confirming, None
            return app if nav is Nav.SELECT else None
        if nav is Nav.SELECT:
            return self._open(self.home.selected)
        if nav is Nav.MENU:
            # Jump to the power/system row (the last one), like a TV's menu key.
            if self.home.config.rows:
                self.home.row = len(self.home.config.rows) - 1
            return None
        self.home.move(nav)
        return None

    def _open(self, app: App | None, pin_ok: bool = False) -> App | None:
        """Open a tile: ask first if it needs it (the PIN, if household limits
        say so; "are you sure?"); the Search tile opens here."""
        if app is None:
            return None
        if not pin_ok:
            from . import family

            reason = family.needs_pin(app.id)
            if reason:
                self.pin = family.PinEntry(reason, app)
                self._confirm_t0 = time.monotonic()
                events.record("pin_asked", tile=app.id, reason=reason)
                return None
        if app.command and app.command[0] == "hearth:search":
            self.open_search()
            return None
        if app.command and app.command[0] == "hearth:captures":
            self.open_gallery()
            return None
        question = self.ask(app) if self.ask else None
        if app.confirm or question:
            self.confirming = app
            self.confirm_caption = question or "ARE YOU SURE?"
            self._confirm_t0 = time.monotonic()
            return None
        return app

    # -- sounds (optional: Settings → Home screen → Sounds) ----------------------

    def sound_state(self) -> tuple:
        sr = self.search
        return (self.home.row, self.home.col, self.options[2] if self.options else None, self.options is not None,
                (sr.zone, sr.row, sr.col, sr.pick, sr.query) if sr else None, self.confirming is not None)

    def play_sound(self, nav: Nav, before: tuple, opened: App | None) -> None:
        from . import sounds

        after = self.sound_state()
        if opened is not None:
            sounds.play("select")
        elif nav is Nav.FAVORITE and before[4] is None and after[4] is None:
            sounds.play("favorite")
        elif (before[3] and not after[3]) or (before[4] is not None and after[4] is None) or \
                (before[5] and not after[5]) or nav is Nav.BACK:
            sounds.play("back")
        elif (not before[3] and after[3]) or (before[4] is None and after[4] is not None) or \
                (not before[5] and after[5]):
            sounds.play("select")
        elif before != after:
            sounds.play("move")

    # -- search --------------------------------------------------------------------

    def search_catalog(self) -> list[App]:
        """Everything search can find: every tile on the screen, plus every
        game in the Library."""
        from . import library

        seen: dict[str, App] = {}
        for row in self.home.config.rows:
            for app in row.apps:
                if not app.id.startswith("resume:") and app.command[:1] != ("hearth:search",):
                    seen.setdefault(app.id, app)
        try:
            for game in self.games():
                app = library.as_app(game)
                seen.setdefault(app.id, app)
        except Exception:  # a broken library file mustn't stop search
            log.exception("search: reading the game library")
        return list(seen.values())

    def open_search(self) -> None:
        from .search import Search

        self.search = Search(self.search_catalog())
        self._search_t0 = time.monotonic()
        events.record("search")

    def open_gallery(self) -> None:
        from . import captures
        from .gallery import Gallery

        self.gallery = Gallery(captures.all_captures())
        self._gallery_t0 = time.monotonic()
        events.record("captures_open", count=len(self.gallery.items))

    def type_text(self, text: str) -> App | None:
        """A real keyboard typing into search, or number keys into the PIN."""
        if self.pin is not None:
            return self.pin_done() if self.pin.type(text) == "ok" else None
        if self.search is not None:
            self.search.type(text)
        return None

    def pin_done(self) -> App | None:
        """The right PIN: open what it was for (and, if it was the time
        limit or bedtime, allow a little more)."""
        from . import family

        entry, self.pin = self.pin, None
        if entry.reason != "This one is locked":
            family.grant_extra()
        events.record("pin_ok", tile=entry.target.id if entry.target else None)
        return self._open(entry.target, pin_ok=True)

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
        self.busy(POINTER_SECONDS)  # the pointer shows, then fades
        if self.confirming is None:
            hit = self._tile_at(pos)
            if hit:
                self.home.row, self.home.cols[hit[0]] = hit
                self.intro = None

    def edge_scroll(self, now: float) -> None:
        """With the pointer resting near the top or bottom, step through the rows."""
        if (self._pointer is None or self.confirming is not None or self.options is not None
                or now - self._pointer_at > POINTER_SECONDS):
            self._edge = None
            return
        y, h = self._pointer[1], self.theme.height
        direction = Nav.UP if y < h * EDGE_ZONE else Nav.DOWN if y > h * (1 - EDGE_ZONE) else None
        if direction is None:
            self._edge = None
            return
        if self._edge is None or self._edge[0] is not direction:
            self._edge = (direction, now + EDGE_FIRST)
            return
        if now >= self._edge[1]:
            before = self.home.row
            self.home.move(direction)
            if self.home.row != before:
                self._pointer_at = now  # keep the pointer showing while it scrolls
                self.intro = None
            self._edge = (direction, now + EDGE_REPEAT)

    def click(self, pos: tuple[int, int]) -> App | None:
        """A click on a tile opens it (or answers the confirm dialog)."""
        if self.confirming is not None:
            return self.handle(Nav.SELECT)
        hit = self._tile_at(pos)
        if hit is None:
            return None
        self.home.row, self.home.cols[hit[0]] = hit
        return self.handle(Nav.SELECT)

    def busy(self, seconds: float = 0.5) -> None:
        """Something is animating: draw every frame for a while longer."""
        self.busy_until = max(self.busy_until, time.monotonic() + seconds)

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
        self._draw_backdrop(now)

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
        if self.moving is not None and self._moving_rect is not None:
            self._draw_moving(self._moving_rect)
        self._moving_rect = None
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
        if self.options is not None:
            self._draw_options()
        if self.search is not None:
            self._draw_search()
        if self.gallery is not None:
            self._draw_gallery()
        if self.whats_new is not None:
            self._draw_whats_new()
        if self.pin is not None:
            self._draw_pin()
        self._draw_pointer()

    # -- the backdrop: the focused tile's art or colour, softly ------------------

    def _make_backdrop(self, app: App) -> pygame.Surface:
        th, lv = self.theme, self.theme.lv
        w, h = th.width, th.height
        out = self.background.copy()
        if app.id not in self._blurs:
            art = load_art(app.art)
            # Blurred right out (down to a few dozen pixels, then up in steps
            # so there are no edges), so it's light and colour, not a picture.
            # Kept at a tenth of the screen's size: a full-size one is 8 MB.
            self._blurs[app.id] = None if art is None else pygame.transform.smoothscale(
                cover(art, (32, 18)), (w // 10, h // 10))
        mid = self._blurs[app.id]
        if mid is not None:
            blur = pygame.transform.smoothscale(pygame.transform.smoothscale(mid, (w // 3, h // 3)), (w, h))
            blur.set_alpha(95)
            out.blit(blur, (0, 0))
        else:
            out.blit(_soft_glow((w, h), style.parse_color(app.color), (1.0, 0.0), 0.95, 95), (0, 0))
        # Keep the rows readable: darken towards the bottom and the left.
        out.blit(style.gradient((w, h), (*lv.ink, 30), (*lv.ink, 190), vertical=True), (0, 0))
        out.blit(style.gradient((w, h), (*lv.ink, 120), (*lv.ink, 0), vertical=False), (0, 0))
        return out.convert() if pygame.display.get_surface() else out

    def _draw_backdrop(self, now: float) -> None:
        s = self.surface
        app = self.home.selected
        rested = now - self._focus_since >= BACKDROP_DELAY
        if app is not None and rested and (self._backdrop is None or self._backdrop[0] != app.id):
            if app.id not in self._backdrops:
                # Only the last few full-screen ones are kept (8 MB each at
                # 1080p); the rest are rebuilt from their small blur.
                while len(self._backdrops) >= BACKDROPS_KEPT:
                    self._backdrops.pop(next(iter(self._backdrops)))
                self._backdrops[app.id] = self._make_backdrop(app)
            else:
                self._backdrops[app.id] = self._backdrops.pop(app.id)  # most recently used last
            self._backdrop_prev = self._backdrop[1] if self._backdrop else self.background
            self._backdrop = (app.id, self._backdrops[app.id])
            self._backdrop_t0 = now
        if self._backdrop is None:
            s.blit(self.background, (0, 0))
            return
        p = 1.0 if self.reduced else min(1.0, (now - self._backdrop_t0) / BACKDROP_FADE)
        img = self._backdrop[1]
        if p >= 1.0 or self._backdrop_prev is None:
            s.blit(img, (0, 0))
            return
        self.busy()
        s.blit(self._backdrop_prev, (0, 0))
        img.set_alpha(int(255 * ease_in_out(p)))
        s.blit(img, (0, 0))
        img.set_alpha(None)

    def _draw_moving(self, rect: pygame.Rect) -> None:
        """The tile being moved: outlined, with arrows either side."""
        th, s = self.theme, self.surface
        pygame.draw.rect(s, th.lv.accent, rect.inflate(int(8 * th.u), int(8 * th.u)),
                         width=max(2, int(4 * th.u)), border_radius=th.radius + int(4 * th.u))
        for side in (-1, 1):
            cx = rect.centerx + side * (rect.w // 2 + int(24 * th.u))
            tip, back = cx + side * int(12 * th.u), cx - side * int(8 * th.u)
            pts = [(tip, rect.centery), (back, rect.centery - int(18 * th.u)), (back, rect.centery + int(18 * th.u))]
            style.circle(s, (0, 0, 0), (cx, rect.centery), 26 * th.u)
            pygame.draw.polygon(s, th.lv.accent, pts)

    # -- the status bar: controller batteries -----------------------------------

    def refresh_status(self) -> None:
        """Re-read controller batteries and the network now and then."""
        from . import battery, netstate

        now = time.monotonic()
        if now - self._batteries_at > BATTERY_SECONDS:
            self._batteries_at = now
            self._batteries = battery.controllers()
        if now - self._link_at > NETWORK_SECONDS:
            self._link_at = now
            try:
                self._link = netstate.link()
            except OSError:
                self._link = None

    def looks(self) -> tuple:
        """What a settled screen shows that can change without input: redraw
        only when this does."""
        self.refresh_status()
        caret = int(time.monotonic() * 2) % 2 if self.search is not None else 0
        return (style.clock_text(self.clock), time.strftime("%d"), repr(self._batteries), self._link,
                self.message, self.badge, caret, tuple(sorted(self.running)), id(self.home))

    def _draw_batteries(self, layer: pygame.Surface, right: int, cy: int) -> int:
        """Batteries of connected controllers, right to left from `right`.
        Returns the x where they end."""
        th, lv = self.theme, self.theme.lv
        x = right
        f = th.font_date
        for b in reversed(self._batteries):
            color = lv.accent if b.low else lv.dim
            label = style.tracked(f, "CHARGING" if b.charging and b.percent is None else
                                  f"{b.percent}%" if b.percent is not None else "", color, 0.14)
            x -= label.get_width()
            layer.blit(label, (x, cy - label.get_height() // 2))
            bw, bh = int(34 * th.u), int(16 * th.u)
            body = pygame.Rect(x - bw - int(10 * th.u), cy - bh // 2, bw, bh)
            pygame.draw.rect(layer, color, body, width=max(1, int(2 * th.u)), border_radius=max(1, int(3 * th.u)))
            layer.fill(color, (body.right, body.centery - bh // 4, max(2, int(3 * th.u)), bh // 2))
            inner = body.inflate(-int(6 * th.u), -int(6 * th.u))
            fill = (b.percent or 0) / 100
            if fill > 0:
                layer.fill(color, (inner.x, inner.y, max(1, int(inner.w * fill)), inner.h))
            x = body.x - int(26 * th.u)
        return x

    def _draw_network(self, layer: pygame.Surface, right: int, cy: int) -> int:
        """Wi-Fi bars, a wired plug, or "offline", ending at `right`. Returns
        the x where it starts."""
        th, lv = self.theme, self.theme.lv
        u = th.u
        link = self._link
        if link is None:
            return right
        if link.kind == "none":
            label = style.tracked(th.font_date, "OFFLINE", lv.accent, 0.14)
            layer.blit(label, (right - label.get_width(), cy - label.get_height() // 2))
            return right - label.get_width() - int(26 * u)
        if link.kind == "wired":
            # A plug: a box with two prongs, and its lead.
            w, h = int(18 * u), int(14 * u)
            body = pygame.Rect(right - w, cy - h // 2 + int(2 * u), w, h)
            pygame.draw.rect(layer, lv.dim, body, border_radius=max(1, int(3 * u)))
            for dx in (0.3, 0.7):
                layer.fill(lv.dim, (body.x + int(w * dx) - max(1, int(u)), body.y - int(6 * u),
                                    max(2, int(3 * u)), int(6 * u)))
            layer.fill(lv.dim, (body.centerx - max(1, int(u)), body.bottom, max(2, int(3 * u)), int(5 * u)))
            return body.x - int(26 * u)
        # Wi-Fi: four bars, the ones beyond the signal faint.
        bw, gap, tall = max(2, int(5 * u)), max(1, int(3 * u)), int(20 * u)
        x = right - 4 * bw - 3 * gap
        for i in range(4):
            h = int(tall * (i + 1) / 4)
            color = lv.dim if i < link.bars else style.mix(lv.dim, lv.panel, 0.7)
            layer.fill(color, (x + i * (bw + gap), cy + tall // 2 - h, bw, h))
        return x - int(26 * u)

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
        self.refresh_status()
        net_x = self._draw_network(layer, date_rect.x - int(28 * th.u), date_rect.centery)
        status_right = self._draw_batteries(layer, net_x, date_rect.centery)
        if self.badge:
            text = style.tracked(th.font_date, self.badge.upper(), lv.accent, 0.14)
            chip = text.get_rect().inflate(int(30 * th.u), int(14 * th.u))
            chip.midright = (status_right, date_rect.centery)
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
                self._draw_tile(app, pygame.Rect(x, ty, th.tile_w, th.tile_h), f, focused, appear,
                                in_favorites=row.title == "Favorites")
                visible = pygame.Rect(x, ty, th.tile_w, th.tile_h).clip(
                    pygame.Rect(0, th.header_h, th.width, th.height - th.header_h - th.footer_h))
                if visible.w > th.tile_w // 3 and visible.h > th.tile_h // 3:
                    self._hits.append((visible, r, c))
        return focus_rect

    def _draw_tile(self, app: App, rest: pygame.Rect, f: float, focused: bool, appear: float,
                   in_favorites: bool = False) -> None:
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
        if focused and not self.reduced and not self.settled and f >= 0.99:
            since = time.monotonic() - self._focus_since - 0.5
            phase = (since % 5.0) / 1.1 if since > 0 else 0
            glint = style.sheen(rect.size, phase)
            if glint is not None:
                s.blit(style.rounded(glint, th.radius), rect.topleft)

        if app.id in self.favorites and not in_favorites:  # starred (not needed in Favorites itself)
            star_c = (rect.x + int(24 * th.u), rect.y + int(24 * th.u))
            style.circle(s, (0, 0, 0), star_c, 14 * th.u)
            _star(s, th.lv.accent, star_c, 10 * th.u)
        if self.moving is not None and focused:
            self._moving_rect = rect  # drawn over the row once it's all there (_draw_moving)
        if app.id in self.running:
            dot = (rect.right - int(26 * th.u), rect.y + int(26 * th.u))
            style.circle(s, (0, 0, 0), dot, 10 * th.u)
            style.circle(s, RUNNING, dot, 7 * th.u)
        if app.command and app.command[0] == "hearth:resume" and app.platform and load_art(app.art) is None:
            # Quick Resume: "‖ PAUSED · 5 MIN" (tiles with artwork show it in their own badge).
            text = style.tracked(th.type(16, "cond", "semibold"), app.platform.upper(), th.lv.text, 0.18)
            pad, bar = int(10 * th.u), max(2, int(4 * th.u))
            pill = pygame.Surface((text.get_width() + pad * 3 + bar * 3, text.get_height() + pad), pygame.SRCALPHA)
            pill.fill((0, 0, 0, 150))
            for i in (0, 2):
                pygame.draw.rect(pill, (*th.lv.accent, 255), (pad + i * bar, pad // 2 + 2, bar, text.get_height() - 4))
            pill.blit(text, (pad * 2 + bar * 3, pad // 2))
            style.rounded(pill, pill.get_height() // 2)
            s.blit(pill, (rect.right - pill.get_width() - int(14 * th.u), rect.y + int(14 * th.u)))

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
        if self.moving is not None:
            x = th.margin
            for button, label in (("D-PAD", "Move"), ("A", "Done"), ("B", "Cancel")):
                x = style.button_hint(s, x, cy, button, label, th.type, lv)
            return
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
        for button, label in self.hints:
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

    def _draw_options(self) -> None:
        th, s, lv = self.theme, self.surface, self.theme.lv
        app, choices, index = self.options
        p = 1.0 if self.reduced else ease_out((time.monotonic() - self._confirm_t0) / CONFIRM_SECONDS)
        shade = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, int(170 * p)))
        s.blit(shade, (0, 0))
        row_h = int(64 * th.u)
        game = self._details
        # A game's card is wider, with its art and what you've played of it.
        facts = []
        if game is not None:
            facts = [("PLATFORM", game.platform), ("LAST PLAYED", played_when(game.last_played)),
                     ("PLAY TIME", played_for(game.playtime))]
            if game.plays:
                facts.append(("STARTED", f"{game.plays} time{'s' if game.plays != 1 else ''}"))
        fact_h = int(34 * th.u)
        art_w = int(th.width * 0.22) if game is not None else 0
        list_h = int(140 * th.u) + row_h * len(choices) + (fact_h * len(facts) + int(24 * th.u) if facts else 0)
        box = pygame.Rect(0, 0, int(th.width * (0.62 if game is not None else 0.4)), max(list_h, int(art_w * 1.2)))
        card = pygame.Surface(box.size, pygame.SRCALPHA)
        card.blit(style.gradient(box.size, style.lighten(lv.panel, 0.05), lv.panel, vertical=True), (0, 0))
        if game is not None:
            art = load_art(game.art)
            panel = pygame.Rect(0, 0, art_w, box.h)
            if art is not None:
                card.blit(cover(art, panel.size), (0, 0))
            else:
                card.fill(style.parse_color(app.color), panel)
                initial = th.font_number.render(app.name[:1].upper(), True, lv.text)
                card.blit(initial, initial.get_rect(center=panel.center))
            card.blit(style.gradient((int(art_w * 0.4), box.h), (*lv.panel, 0), (*lv.panel, 255), vertical=False),
                      (art_w - int(art_w * 0.4), 0))
        stripe_x = art_w + int(34 * th.u)
        stripe_w = style.stripes(card, stripe_x, 0, box.h, max(4, int(12 * th.u)), (lv.accent, lv.second))
        style.rounded(card, th.radius)
        x = stripe_x + stripe_w + int(36 * th.u)
        cap = style.tracked(th.font_date, "GAME" if game is not None else "OPTIONS", lv.dim, 0.3)
        card.blit(cap, (x, int(30 * th.u)))
        title = style.fit(style.tracked(th.font_row, app.name.upper(), lv.text, 0.08), box.w - x - int(30 * th.u))
        card.blit(title, (x, int(30 * th.u) + cap.get_height() + int(4 * th.u)))
        y = int(110 * th.u)
        if facts:
            f_key, f_val = th.font_date, th.type(24, "text", "medium")
            for i, (k, v) in enumerate(facts):
                ky = y + i * fact_h
                card.blit(style.tracked(f_key, k, lv.dim, 0.2), (x, ky + int(4 * th.u)))
                card.blit(f_val.render(v, True, lv.text), (x + int(190 * th.u), ky))
            y += fact_h * len(facts) + int(24 * th.u)
        f = th.type(26, "text", "semibold")
        for i, (label, _) in enumerate(choices):
            rect = pygame.Rect(x - int(16 * th.u), y + i * row_h, box.w - x - int(14 * th.u), row_h - int(8 * th.u))
            if i == index:
                style.blend_rect(card, rect, (*lv.text, 22), int(8 * th.u))
                card.fill(lv.accent, (rect.x, rect.y + int(12 * th.u), max(2, int(4 * th.u)), rect.h - int(24 * th.u)))
            text = style.fit(f.render(label, True, lv.text if i == index else lv.dim), rect.w - int(40 * th.u))
            card.blit(text, (rect.x + int(22 * th.u), rect.centery - text.get_height() // 2))
        scale = 0.96 + 0.04 * p
        if scale < 1:
            card = pygame.transform.smoothscale(card, (int(box.w * scale), int(box.h * scale)))
        card.set_alpha(int(255 * p))
        s.blit(card, card.get_rect(center=(th.width // 2, th.height // 2)))

    def _draw_search(self) -> None:
        from .search import ACTIONS, KEY_ROWS

        th, s, lv = self.theme, self.surface, self.theme.lv
        sr = self.search
        p = 1.0 if self.reduced else ease_out((time.monotonic() - self._search_t0) / CONFIRM_SECONDS)
        # Its own screen: the home screen fades out behind it.
        self.background.set_alpha(int(255 * p))
        s.blit(self.background, (0, 0))
        self.background.set_alpha(None)
        u, m = th.u, th.margin
        y = th.header_h - int(40 * u)
        cap = style.tracked(th.font_date, "SEARCH", lv.dim, 0.3)
        s.blit(cap, (m, y))
        y += cap.get_height() + int(10 * u)
        # The search box, with a caret.
        box = pygame.Rect(m, y, th.width - 2 * m, int(78 * u))
        style.blend_rect(s, box, (*lv.text, 16), int(10 * u))
        style.stripes(s, box.x, box.y, box.h, max(3, int(8 * u)), (lv.accent, lv.second))
        f_query = th.type(38, "text", "semibold")
        shown = sr.query or "Games and apps"
        text = f_query.render(shown, True, lv.text if sr.query else lv.dim)
        tx = box.x + int(40 * u)
        s.blit(text, (tx, box.centery - text.get_height() // 2))
        if int(time.monotonic() * 2) % 2 == 0 or not sr.query:
            cx = tx + (text.get_width() if sr.query else 0) + int(4 * u)
            s.fill(lv.accent, (cx, box.y + int(18 * u), max(2, int(3 * u)), box.h - int(36 * u)))
        count = ("TYPE TO SEARCH" if not sr.query else "NOTHING FOUND" if not sr.results
                 else f"{len(sr.results)} RESULT{'S' if len(sr.results) != 1 else ''}")
        ctext = style.tracked(th.font_date, count, lv.dim, 0.22)
        s.blit(ctext, ctext.get_rect(midright=(box.right - int(30 * u), box.centery)))

        # The keyboard.
        y = box.bottom + int(28 * u)
        key = int(62 * u)
        gap = int(10 * u)
        f_key = th.type(28, "cond", "semibold")
        for r, keys in enumerate([*KEY_ROWS, ACTIONS]):
            actions = r == len(KEY_ROWS)
            kw = key * 3 + gap * 2 if actions else key
            for c, k in enumerate(keys):
                rect = pygame.Rect(m + c * (kw + gap), y + r * (key + gap), kw, key)
                focus = sr.zone == "keys" and sr.row == r and sr.col == c
                if focus:
                    pygame.draw.rect(s, lv.accent, rect, border_radius=int(10 * u))
                else:
                    style.blend_rect(s, rect, (*lv.text, 20), int(10 * u))
                label = k.upper() if not actions else k.upper()
                glyph = style.tracked(f_key, label, lv.ink if focus else lv.text, 0.1 if actions else 0)
                s.blit(glyph, glyph.get_rect(center=rect.center))
        kb_bottom = y + (len(KEY_ROWS) + 1) * (key + gap)

        # The results: tiles, like the home screen's.
        ry = kb_bottom + int(24 * u)
        label = style.tracked(th.font_row, "RESULTS", lv.text if sr.zone == "results" else lv.dim, 0.3)
        s.blit(label, (m, ry))
        ty = ry + label.get_height() + int(18 * u)
        step = th.tile_w + th.gap
        first = max(0, sr.pick - max(1, (th.width - 2 * m) // step) + 1) if sr.zone == "results" else 0
        for i, app in enumerate(sr.results[first:first + 8]):
            idx = first + i
            x = m + i * step
            if x > th.width:
                break
            focused = sr.zone == "results" and idx == sr.pick
            self._draw_tile(app, pygame.Rect(x, ty, th.tile_w, th.tile_h), 1.0 if focused else 0.0, focused, 1.0)

        # Hints.
        cy = th.height - th.footer_h // 2
        x = m
        for button, text_ in (("A", "Open" if sr.zone == "results" else "Type"), ("X", "Delete"),
                              ("B", "Close")):
            x = style.button_hint(s, x, cy, button, text_, th.type, lv)

    # -- what's new (once, after an update) ---------------------------------------

    def _draw_pin(self) -> None:
        """The PIN pad: a combination lock, one digit at a time."""
        th, s, lv, pin = self.theme, self.surface, self.theme.lv, self.pin
        u = th.u
        p = 1.0 if self.reduced else ease_out((time.monotonic() - self._confirm_t0) / CONFIRM_SECONDS)
        shade = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, int(200 * p)))
        s.blit(shade, (0, 0))
        box = pygame.Rect(0, 0, int(th.width * 0.36), int(th.height * 0.44))
        box.center = (th.width // 2, th.height // 2 + int((1 - p) * 30 * u))
        card = pygame.Surface(box.size, pygame.SRCALPHA)
        card.blit(style.gradient(box.size, style.lighten(lv.panel, 0.05), lv.panel, vertical=True), (0, 0))
        stripe_w = style.stripes(card, int(28 * u), 0, box.h, max(4, int(12 * u)), (lv.accent, lv.second))
        style.rounded(card, th.radius)
        x = int(28 * u) + stripe_w + int(34 * u)
        y = int(40 * u)
        caption = style.tracked(th.font_date, pin.reason.upper(), lv.dim, 0.24)
        card.blit(caption, (x, y))
        y += caption.get_height() + int(6 * u)
        title = style.tracked(th.font_title, "ENTER THE PIN", lv.text, 0.06)
        card.blit(style.fit(title, box.w - x - int(30 * u)), (x, y))
        y += title.get_height() + int(34 * u)
        f_digit = th.type(72, "cond", "bold")
        cell = int(92 * u)
        gap = int(18 * u)
        for i, d in enumerate(pin.digits):
            r = pygame.Rect(x + i * (cell + gap), y, cell, int(cell * 1.2))
            here = i == pin.pos
            pygame.draw.rect(card, style.lighten(lv.panel, 0.12 if here else 0.05), r, border_radius=int(10 * u))
            if here:
                pygame.draw.rect(card, lv.accent, r, width=max(2, int(3 * u)), border_radius=int(10 * u))
                w = int(11 * u)
                for base, tip in ((r.y - int(10 * u), r.y - int(22 * u)), (r.bottom + int(10 * u),
                                                                             r.bottom + int(22 * u))):
                    pygame.draw.polygon(card, lv.accent, [(r.centerx - w, base), (r.centerx + w, base),
                                                          (r.centerx, tip)])  # Up/Down change it
                glyph = f_digit.render(str(d), True, lv.text)
            else:
                glyph = f_digit.render("•", True, lv.dim)  # only the digit you're on shows
            card.blit(glyph, glyph.get_rect(center=r.center))
        y += int(cell * 1.2) + int(40 * u)
        if pin.message:
            card.blit(th.type(24, "text", "semibold").render(pin.message, True, lv.accent), (x, y))
        hint_y = box.h - int(40 * u)
        hx = style.button_hint(card, x, hint_y, "A", "OK", th.type, lv)
        style.button_hint(card, hx + int(30 * u), hint_y, "B", "CANCEL", th.type, lv)
        s.blit(card, box)

    def _draw_whats_new(self) -> None:
        th, s, lv = self.theme, self.surface, self.theme.lv
        u = th.u
        version, notes = self.whats_new
        shade = pygame.Surface(s.get_size(), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 190))
        s.blit(shade, (0, 0))
        box_w = int(th.width * 0.62)
        pad = int(46 * u)
        f_head = th.type(24, "text", "semibold")
        f_body = th.type(24, "text", "regular")
        text_w = box_w - 2 * pad - int(30 * u)
        blocks = []
        for note in notes:
            head, sep, rest = note.partition(": ")
            short = bool(sep) and len(head) < 40
            body = rest[:1].upper() + rest[1:] if short else note
            blocks.append((head if short else "", _wrap(f_body, body, text_w)))
        line_h = f_body.get_linesize()
        caption = style.tracked(th.font_date, "UPDATED", lv.dim, 0.3)
        title = style.tracked(th.font_title, f"WHAT'S NEW IN {version}", lv.text, 0.06)
        top_h = pad + caption.get_height() + title.get_height() + int(26 * u)
        max_h = int(th.height * 0.82)
        body_h, shown = 0, []
        for head, lines in blocks:
            h = (line_h if head else 0) + line_h * len(lines) + int(14 * u)
            if top_h + body_h + h + pad + int(60 * u) > max_h:
                break
            shown.append((head, lines))
            body_h += h
        more = len(shown) < len(blocks)
        box_h = top_h + body_h + (line_h if more else 0) + pad + int(60 * u)
        box = pygame.Rect(0, 0, box_w, box_h)
        box.center = (th.width // 2, th.height // 2)
        card = pygame.Surface(box.size, pygame.SRCALPHA)
        card.blit(style.gradient(box.size, style.lighten(lv.panel, 0.05), lv.panel, vertical=True), (0, 0))
        stripe_w = style.stripes(card, int(28 * u), 0, box.h, max(4, int(12 * u)), (lv.accent, lv.second))
        style.rounded(card, th.radius)
        x = int(28 * u) + stripe_w + int(34 * u)
        y = pad
        card.blit(caption, (x, y))
        y += caption.get_height() + int(4 * u)
        card.blit(style.fit(title, box_w - x - pad), (x, y))
        y += title.get_height() + int(26 * u)
        for head, lines in shown:
            if head:
                card.blit(f_head.render(head, True, lv.accent), (x, y))
                y += line_h
            for line in lines:
                card.blit(f_body.render(line, True, lv.text), (x, y))
                y += line_h
            y += int(14 * u)
        if more:
            card.blit(f_body.render("…and more: see CHANGELOG.md", True, lv.dim), (x, y))
        style.button_hint(card, x, box.h - pad, "A", "OK", th.type, lv)
        s.blit(card, box)

    # -- captures (screenshots) --------------------------------------------------

    def _thumb(self, path, size: tuple[int, int], load: bool) -> tuple[pygame.Surface | None, bool]:
        """(the thumbnail if it's ready, whether this call had to load it)."""
        key = (path, size)
        if key in self._thumbs:
            return self._thumbs[key], False
        if not load:
            return None, False
        if len(self._thumbs) > 64:
            self._thumbs.clear()
        try:
            self._thumbs[key] = cover(pygame.image.load(str(path)), size)
        except (pygame.error, OSError):
            self._thumbs[key] = None
        return self._thumbs[key], True

    def _full_image(self, path, size: tuple[int, int]) -> pygame.Surface | None:
        if path not in self._full:
            if len(self._full) > 2:
                self._full.pop(next(iter(self._full)))
            try:
                img = pygame.image.load(str(path))
                scale = min(size[0] / img.get_width(), size[1] / img.get_height())
                self._full[path] = pygame.transform.smoothscale(
                    img, (max(1, int(img.get_width() * scale)), max(1, int(img.get_height() * scale))))
            except (pygame.error, OSError):
                self._full[path] = None
        return self._full[path]

    def _draw_gallery(self) -> None:
        from .gallery import COLS

        th, s, lv = self.theme, self.surface, self.theme.lv
        g = self.gallery
        u, m = th.u, th.margin
        p = 1.0 if self.reduced else ease_out((time.monotonic() - self._gallery_t0) / CONFIRM_SECONDS)
        self.background.set_alpha(int(255 * p))
        s.blit(self.background, (0, 0))
        self.background.set_alpha(None)
        cap = g.current
        if g.full and cap is not None:
            s.fill((0, 0, 0))
            img = self._full_image(cap.path, (th.width, th.height))
            if img is not None:
                s.blit(img, img.get_rect(center=(th.width // 2, th.height // 2)))
            # A caption band along the bottom.
            band = pygame.Surface((th.width, th.footer_h + int(70 * u)), pygame.SRCALPHA)
            band.fill((0, 0, 0, 170))
            s.blit(band, (0, th.height - band.get_height()))
            title = style.fit(style.tracked(th.font_row, cap.title.upper(), lv.text, 0.2), th.width // 2)
            when = style.tracked(th.font_date, f"{cap.when.upper()}  ·  {g.pick + 1} OF {len(g.items)}", lv.dim, 0.2)
            ty = th.height - band.get_height() + int(22 * u)
            s.blit(title, (m, ty))
            s.blit(when, (m, ty + title.get_height() + int(6 * u)))
        else:
            y = th.header_h - int(40 * u)
            head = style.tracked(th.font_date, "CAPTURES", lv.dim, 0.3)
            s.blit(head, (m, y))
            count = style.tracked(th.font_date, f"{len(g.items)} SCREENSHOT{'S' if len(g.items) != 1 else ''}",
                                  lv.dim, 0.22)
            s.blit(count, count.get_rect(topright=(th.width - m, y)))
            if not g.items:
                msg = style.tracked(th.font_row, "NO SCREENSHOTS YET", lv.text, 0.2)
                s.blit(msg, msg.get_rect(center=(th.width // 2, th.height // 2 - int(20 * u))))
                how = th.font_date.render("Take one from the Quick Menu (Guide) → System → Take a screenshot",
                                          True, lv.dim)
                s.blit(how, how.get_rect(center=(th.width // 2, th.height // 2 + int(30 * u))))
            gap = int(24 * u)
            tw = (th.width - 2 * m - gap * (COLS - 1)) // COLS
            tsize = (tw, tw * 9 // 16)
            label_h = th.font_date.get_height() + int(12 * u)
            row_h = tsize[1] + label_h + gap
            top = y + head.get_height() + int(24 * u)
            rows_shown = max(1, (th.height - th.footer_h - top) // row_h)
            first_row = max(0, g.pick // COLS - rows_shown + 1)
            loaded = False
            for i, c in enumerate(g.items[first_row * COLS:(first_row + rows_shown) * COLS]):
                idx = first_row * COLS + i
                r, col = divmod(i, COLS)
                rect = pygame.Rect(m + col * (tw + gap), top + r * row_h, *tsize)
                thumb, just_loaded = self._thumb(c.path, tsize, load=not loaded)
                loaded = loaded or just_loaded  # one new picture per frame keeps it smooth
                if just_loaded:
                    self.busy()
                if thumb is not None:
                    s.blit(thumb, rect)
                else:
                    style.blend_rect(s, rect, (*lv.text, 18), int(8 * u))
                focused = idx == g.pick
                if focused:
                    pygame.draw.rect(s, lv.text, rect.inflate(int(8 * u), int(8 * u)), max(2, int(4 * u)),
                                     border_radius=int(8 * u))
                label = style.fit(th.font_date.render(f"{c.title} · {c.when}", True, lv.text if focused else lv.dim),
                                  tw)
                s.blit(label, (rect.x, rect.bottom + int(8 * u)))
        # Hints.
        cy = th.height - th.footer_h // 2
        x = m
        if g.confirming:
            hints = (("A", "Delete it"), ("B", "Keep it"))
            ask = style.tracked(th.font_row, "DELETE THIS SCREENSHOT?", lv.accent, 0.2)
            s.blit(ask, ask.get_rect(midright=(th.width - m, cy)))
        elif g.full:
            hints = (("D-PAD", "Previous / next"), ("X", "Delete"), ("B", "Back"))
        else:
            hints = (("A", "View"), ("X", "Delete"), ("B", "Close")) if g.items else (("B", "Close"),)
        for button, text_ in hints:
            x = style.button_hint(s, x, cy, button, text_, th.type, lv)
        if g.message and not g.confirming:
            note = style.tracked(th.font_date, g.message.upper(), lv.accent, 0.2)
            s.blit(note, note.get_rect(midright=(th.width - m, cy)))

    # -- the screen saver ------------------------------------------------------

    def start_saver(self) -> None:
        """The screen saver begins: gather the artwork to show (ambient)."""
        self.saver = True
        self._slides = []
        self._slide_cache = {}
        self._saver_t0 = time.monotonic()
        if self.saver_style != "ambient":
            return
        try:
            seen = set()
            for game in self.games():
                # Only checked here; each picture loads when its turn comes.
                if game.art and game.art not in seen and os.path.isfile(game.art):
                    seen.add(game.art)
                    self._slides.append((game.title, game.platform, game.art))
        except Exception:  # no art is fine: the clock saver then
            log.exception("screen saver art")
        try:
            from . import captures

            for cap in captures.all_captures()[:SAVER_CAPTURES]:  # your latest screenshots too
                self._slides.append((cap.title, "Screenshot", str(cap.path)))
        except Exception:
            log.exception("screen saver captures")
        import random

        random.Random(int(self._saver_t0)).shuffle(self._slides)
        del self._slides[SLIDE_MAX:]

    def _slide(self, i: int) -> pygame.Surface | None:
        """Slide i's art, dimmed, a little larger than the screen (room to
        drift). A picture that won't load is dropped from the show."""
        th = self.theme
        while self._slides:
            key = i % len(self._slides)
            if key in self._slide_cache:
                return self._slide_cache[key]
            art = load_art(self._slides[key][2])
            if art is None:
                del self._slides[key]
                self._slide_cache.clear()  # keyed by position, which just moved
                continue
            if len(self._slide_cache) >= 2:  # the one showing and the one fading in
                self._slide_cache.pop(next(iter(self._slide_cache)))
            img = cover(art, (int(th.width * 1.12), int(th.height * 1.12)))
            if pygame.display.get_surface():
                img = img.convert()  # quicker to blit every frame
            shade = pygame.Surface(img.get_size(), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 255 - SLIDE_DIM))
            img.blit(shade, (0, 0))
            self._slide_cache[key] = img
            return img
        return None

    def _draw_slide(self, i: int, age: float, alpha: int) -> None:
        th = self.theme
        img = self._slide(i)
        if img is None:
            return
        # Drift from one corner towards another over the slide's life.
        p = max(0.0, min(1.0, age / (SLIDE_SECONDS + SLIDE_FADE)))
        dx, dy = img.get_width() - th.width, img.get_height() - th.height
        corners = ((0, 0), (1, 1), (1, 0), (0, 1))
        (x0, y0), (x1, y1) = corners[i % 4], corners[(i + 1) % 4]
        x = int(dx * (x0 + (x1 - x0) * p))
        y = int(dy * (y0 + (y1 - y0) * p))
        if alpha < 255:
            img.set_alpha(alpha)
        self.surface.blit(img, (-x, -y))
        img.set_alpha(None)

    def draw_saver(self) -> None:
        """The screen saver: your games' art, slowly (ambient), or dark with
        just the time. The time drifts either way (kind to OLED TVs)."""
        th, s, lv = self.theme, self.surface, self.theme.lv
        s.fill((0, 0, 0))
        t = time.monotonic()
        slides = getattr(self, "_slides", [])
        caption = None
        if slides:
            age = t - self._saver_t0
            i, into = int(age // SLIDE_SECONDS), age % SLIDE_SECONDS
            if into < SLIDE_FADE and i > 0:
                self._draw_slide(i - 1, into + SLIDE_SECONDS, 255)
                self._draw_slide(i, into, int(255 * ease_in_out(into / SLIDE_FADE)))
            else:
                self._draw_slide(i, into, 255)
        if slides:  # (still: pictures that wouldn't load have been dropped)
            title, platform, _ = slides[i % len(slides)]
            caption = f"{title} · {platform}" if platform else title
        dim = 0.2 if slides else 0.45  # over art the time needs to stand out more
        clock = th.type(120, "cond", "semibold").render(style.clock_text(self.clock), True, mix(lv.text, (0, 0, 0), dim))
        date = style.tracked(th.font_date, time.strftime("%A %d %B").upper(), mix(lv.dim, (0, 0, 0), dim), 0.3)
        cap = style.fit(style.tracked(th.font_row, caption.upper(), mix(lv.text, (0, 0, 0), 0.35), 0.2),
                        th.width // 2) if caption else None
        w = max(clock.get_width(), date.get_width(), cap.get_width() if cap else 0)
        block_h = clock.get_height() + date.get_height() + (int(34 * th.u) + cap.get_height() if cap else 0)
        x = int((th.width - w) * (0.5 + 0.45 * math.sin(t / 97)))
        y = int((th.height - clock.get_height() * 2) * (0.5 + 0.45 * math.sin(t / 61 + 1.3)))
        if slides:
            # A soft dark pool behind the time and title, so they read over any picture.
            pool = (int(w * 1.7), int(block_h * 2.2))
            if getattr(self, "_saver_pool", (None,))[0] != pool:
                self._saver_pool = (pool, _soft_oval(pool, 190))
            img = self._saver_pool[1]
            s.blit(img, img.get_rect(center=(x + w // 2, y + block_h // 2)))
        s.blit(clock, (x, y))
        s.blit(date, (x + int(4 * th.u), y + clock.get_height()))
        style.stripes(s, x + int(4 * th.u), y + clock.get_height() + date.get_height() + int(14 * th.u),
                      int(90 * th.u), max(3, int(6 * th.u)), (mix(lv.accent, (0, 0, 0), 0.4), mix(lv.second, (0, 0, 0), 0.4)),
                      vertical=False)
        if cap:
            s.blit(cap, (x + int(4 * th.u), y + clock.get_height() + date.get_height() + int(34 * th.u)))

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
        caption = style.fit(style.tracked(th.font_date, self.confirm_caption, lv.dim, 0.3), box.w - x - int(30 * th.u))
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
    rebuild: Callable[[], object] | None = None,
    back_exits: bool = False,
    saver_after: float = 0,
    saver_style: str = "ambient",
    sleep_after: float = 0,
    swap_confirm: bool = False,
    offset: tuple[int, int] = (0, 0),
    hints: tuple | None = None,
    ask: Callable[[App], str | None] | None = None,
    whats_new: tuple[str, list[str]] | None = None,
) -> App | None:
    """Show the home screen until the user picks an app.

    Returns None only when quitting is allowed (dev mode) and requested.
    `input_blocked` is polled a few times a second; while it's true (the Quick
    Menu is open over the home screen), input is ignored. `intro` is "boot"
    for the power-on animation, "return" for coming back from an app.
    `stats` (events.FrameStats) collects frame times. `rebuild` gives fresh
    contents after a change in the Options popup; `back_exits` makes B leave
    (the Library). After `saver_after` seconds without input the screen saver
    shows; after `sleep_after` the PC sleeps (0 = never). `offset` is where
    this surface sits on the screen (a safe-area inset), for the pointer.
    `ask` may return a question to confirm before a tile opens. `whats_new`
    (version, notes) is shown once, after an update.
    """
    screen = HomeScreen(surface, home, title, livery=livery, motion=motion, intro=intro)
    screen.message = message
    screen.clock = clock
    screen.rebuild = rebuild
    screen.back_exits = back_exits
    screen.saver_style = saver_style
    screen.ask = ask
    screen.whats_new = whats_new
    if hints:
        screen.hints = hints
    screen.badge = badge
    screen.running = running or set()
    mapper = InputMapper()
    mapper.swap_confirm = swap_confirm
    mapper.open_devices()
    clock = pygame.time.Clock()
    frames = 0
    blocked = False
    idle_since = time.monotonic()
    last_draw = last_look = 0.0
    drawn_looks = None
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
            if event.type in (pygame.KEYDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN, pygame.CONTROLLERBUTTONDOWN,
                              pygame.JOYBUTTONDOWN, pygame.CONTROLLERAXISMOTION, pygame.JOYAXISMOTION):
                if not (event.type in (pygame.CONTROLLERAXISMOTION, pygame.JOYAXISMOTION)
                        and abs(getattr(event, "value", 0)) < 0.5 * (32767 if event.type ==
                                                                     pygame.CONTROLLERAXISMOTION else 1)):
                    idle_since = time.monotonic()
                    if screen.saver:  # waking up: this input only wakes the screen
                        screen.saver = False
                        from . import tv

                        tv.switch_here(tries=5)  # and the TV, if it drifted off to another input
                        mapper.reset()
                        continue
            if screen.pin is not None and not blocked and event.type == pygame.KEYDOWN \
                    and getattr(event, "unicode", "").isdigit():
                # Number keys (a keyboard, a TV remote's digits) type the PIN.
                chosen = screen.type_text(event.unicode) or chosen
                continue
            if screen.search is not None and not blocked and event.type == pygame.KEYDOWN:
                # A real keyboard types into search.
                if event.key == pygame.K_BACKSPACE:
                    screen.search.delete()
                    continue
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and screen.search.results \
                        and screen.search.zone == "keys":
                    chosen = screen._open(screen.search.results[screen.search.pick])
                    screen.search = None
                    continue
                ch = getattr(event, "unicode", "")
                if ch and (ch.isalnum() or ch in " '-:.") and event.key != pygame.K_SLASH:
                    screen.type_text(ch.lower())
                    continue
            pos = (event.pos[0] - offset[0], event.pos[1] - offset[1]) if hasattr(event, "pos") else None
            if not blocked and event.type == pygame.MOUSEMOTION:
                screen.point(pos)
            elif not blocked and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                chosen = screen.click(pos)
            nav = mapper.translate(event, now)
            if nav is not None and not blocked:
                navs.append(nav)
        repeat = mapper.repeat(now)
        if repeat is not None and not blocked:
            navs.append(repeat)
        for nav in navs:
            if nav is Nav.BACK and allow_quit and screen.confirming is None and home.row == 0 and home.col == 0:
                return None
            before = screen.sound_state()
            app = screen.handle(nav)
            screen.play_sound(nav, before, app)
            if screen.exit:
                return None
            if app is not None:
                chosen = app
                break
        if chosen is not None:
            if not chosen.background and not chosen.confirm and (not chosen.builtin
                                                                 or chosen.command[0] == "hearth:resume"):
                screen.play_launch(chosen)
            return chosen
        if blocked:
            idle_since = time.monotonic()
        idle = time.monotonic() - idle_since
        if sleep_after and idle > sleep_after:
            events.record("idle_sleep", minutes=round(idle / 60))
            subprocess.Popen(["systemctl", "suspend"])
            idle_since = time.monotonic()
        if saver_after and idle > saver_after and not screen.saver:
            screen.start_saver()
            events.record("screen_saver", style=screen.saver_style, slides=len(screen._slides))
        if screen.saver:
            screen.draw_saver()
            pygame.display.flip()
            clock.tick(24 if screen._slides else 10)
            continue
        mono = time.monotonic()
        screen.settled = (screen.intro is None and mono - idle_since > SETTLE_SECONDS
                          and mono > screen.busy_until)
        if screen.settled:
            due = mono - last_draw >= SETTLED_REDRAW
            if not due and mono - last_look >= 1 / SETTLED_FPS:
                last_look = mono
                due = screen.looks() != drawn_looks
            if not due:
                clock.tick(30)  # nothing new to show: just keep reading input
                continue
        last_draw = last_look = mono
        screen.edge_scroll(mono)
        screen.draw()
        pygame.display.flip()
        drawn_looks = screen.looks()
        if stats is not None and not screen.settled:
            stats.tick()
        clock.tick(30 if screen.settled else 60)
    return None


def draw_loading(surface: pygame.Surface, app: App, livery: str = "gulf") -> None:
    """A full-screen "Starting <app>…" card, shown until the app's window appears."""
    surface.blit(paint_loading(surface.get_size(), app, livery), (0, 0))
    pygame.display.flip()
