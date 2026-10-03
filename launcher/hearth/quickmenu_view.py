"""Drawing the Quick Menu: a panel that slides in over the game.

Styled like the home screen (see style.py): the livery's stripes down the
panel's edge, signwriter type, a selection bar that glides between rows,
gauge-style sliders. Renders onto a transparent (SRCALPHA) surface; the
overlay window shows the running game through the transparent parts.
"""

from __future__ import annotations

import math
import time
import zlib

import pygame

from . import style
from .quickmenu import Item, QuickMenu
from .style import Smooth, Type, ease_out, mix

AVATAR_COLORS = [(88, 101, 242), (35, 165, 90), (237, 66, 69), (250, 166, 26), (155, 89, 182), (26, 188, 156)]


class Icons:
    @staticmethod
    def draw(surf: pygame.Surface, name: str, center: tuple[int, int], size: int, color, bg=(0, 0, 0)) -> None:
        cx, cy = center
        s = size / 2
        w = max(2, int(size / 12))
        if name == "speaker":
            body = [(cx - s * 0.9, cy - s * 0.3), (cx - s * 0.45, cy - s * 0.3), (cx, cy - s * 0.75),
                    (cx, cy + s * 0.75), (cx - s * 0.45, cy + s * 0.3), (cx - s * 0.9, cy + s * 0.3)]
            pygame.draw.polygon(surf, color, body)
            for r in (0.45, 0.8):
                box = pygame.Rect(0, 0, s * r * 2, s * r * 2)
                box.center = (cx, cy)
                pygame.draw.arc(surf, color, box, -math.pi / 3.2, math.pi / 3.2, w)
        elif name == "sliders":
            for i, knob in enumerate((0.35, -0.3, 0.1)):
                y = cy + (i - 1) * s * 0.6
                pygame.draw.line(surf, color, (cx - s * 0.85, y), (cx + s * 0.85, y), w)
                style.circle(surf, color, (cx + knob * s * 1.6, y), max(3, int(s * 0.22)))
        elif name == "chat":
            box = pygame.Rect(0, 0, s * 1.8, s * 1.3)
            box.center = (cx, cy - s * 0.1)
            pygame.draw.rect(surf, color, box, border_radius=int(s * 0.4))
            pygame.draw.polygon(surf, color, [(cx - s * 0.5, box.bottom - 2), (cx - s * 0.1, box.bottom - 2),
                                              (cx - s * 0.6, box.bottom + s * 0.4)])
            for dx in (-0.45, 0, 0.45):
                style.circle(surf, bg, (cx + dx * s, box.centery), max(2, int(s * 0.13)))
        elif name == "battery":
            body = pygame.Rect(0, 0, s * 1.6, s * 0.9)
            body.center = (cx - s * 0.1, cy)
            pygame.draw.rect(surf, color, body, w, border_radius=max(1, int(s * 0.15)))
            surf.fill(color, (body.right, cy - s * 0.2, max(2, int(s * 0.18)), s * 0.4))
            surf.fill(color, (body.x + w * 2, body.y + w * 2, int(body.w * 0.2), body.h - w * 4))
        elif name == "download":
            pygame.draw.line(surf, color, (cx, cy - s * 0.85), (cx, cy + s * 0.3), w + 1)
            pygame.draw.polygon(surf, color, [(cx - s * 0.5, cy - s * 0.05), (cx + s * 0.5, cy - s * 0.05),
                                              (cx, cy + s * 0.5)])
            pygame.draw.line(surf, color, (cx - s * 0.85, cy + s * 0.85), (cx + s * 0.85, cy + s * 0.85), w + 1)
        elif name == "camera":
            body = pygame.Rect(0, 0, s * 1.8, s * 1.25)
            body.center = (cx, cy + s * 0.12)
            pygame.draw.rect(surf, color, body, border_radius=max(2, int(s * 0.25)))
            surf.fill(color, (cx - s * 0.4, body.y - s * 0.3, s * 0.8, s * 0.4))
            style.circle(surf, bg, body.center, max(3, int(s * 0.42)))
            style.circle(surf, color, body.center, max(2, int(s * 0.24)))
        elif name == "clock":
            pygame.draw.circle(surf, color, (cx, cy), s * 0.9, w + 1)
            pygame.draw.line(surf, color, (cx, cy), (cx, cy - s * 0.55), w + 1)
            pygame.draw.line(surf, color, (cx, cy), (cx + s * 0.4, cy + s * 0.2), w + 1)
        elif name == "info":
            style.circle(surf, color, (cx, cy), s * 0.9)
            surf.fill(bg, (cx - w // 2, cy - s * 0.1, max(2, w), s * 0.6))
            style.circle(surf, bg, (cx, cy - s * 0.4), max(2, int(s * 0.12)))
        elif name == "gauge":  # a rev counter
            box = pygame.Rect(0, 0, s * 1.8, s * 1.8)
            box.center = (cx, cy + s * 0.25)
            pygame.draw.arc(surf, color, box, 0, math.pi, w + 1)
            angle = math.pi * 0.28
            pygame.draw.line(surf, color, (cx, cy + s * 0.25),
                             (cx + math.cos(angle) * s * 0.75, cy + s * 0.25 - math.sin(angle) * s * 0.75), w + 1)
            style.circle(surf, color, (cx, cy + s * 0.25), max(2, int(s * 0.16)))
        elif name == "power":
            box = pygame.Rect(0, 0, s * 1.6, s * 1.6)
            box.center = (cx, cy + s * 0.08)
            pygame.draw.arc(surf, color, box, math.pi * 0.62, math.pi * 2.38, w + 1)
            pygame.draw.line(surf, color, (cx, cy - s * 0.9), (cx, cy - s * 0.05), w + 1)


class QuickMenuView:
    def __init__(self, size: tuple[int, int], livery: str = "gulf", motion: str = "full",
                 clock: str = "24h") -> None:
        self.size = size
        w, h = size
        self.u = h / 1080
        self.type = Type(self.u)
        self._make_fonts()
        self.panel_w = int(640 * self.u)
        self.margin = int(28 * self.u)
        self.pad = int(58 * self.u)
        self.pad_r = int(40 * self.u)
        self.radius = max(4, int(16 * self.u))
        self._scroll = 0.0
        self._last = time.monotonic()
        self._dt = 0.0
        self._backdrop = self._make_backdrop()
        self._shadow: pygame.Surface | None = None
        # Where each option and tab is on screen (for a mouse or pointer).
        self.item_hits: list[tuple[pygame.Rect, str]] = []
        self.tab_hits: list[tuple[pygame.Rect, int]] = []
        self._origin = (0, 0)  # the panel's top left on screen
        self.set_theme(livery, motion, clock)

    def set_theme(self, livery: str, motion: str = "full", clock: str = "24h") -> None:
        self.clock = clock
        self.lv = style.livery(livery)
        self.reduced = motion == "reduced"
        self.smooth = Smooth(rate=16.0, instant=self.reduced)
        self._make_fonts()  # the text size may have changed too (Settings → Accessibility)

    def _make_fonts(self) -> None:
        t = self.type
        self.f_caption = t(17, "cond", "semibold")
        self.f_title = t(48, "cond", "semibold")
        self.f_clock = t(32, "cond", "semibold")
        self.f_tab = t(18, "cond", "semibold")
        self.f_label = t(27, "text", "semibold")
        self.f_detail = t(19, "text", "medium")
        self.f_value = t(28, "cond", "semibold")
        self.f_avatar = t(26, "cond", "bold")
        # Rows grow with the text (most of the way: the padding needn't).
        self.row_scale = 1 + (style.TEXT_SCALE - 1) * 0.8

    def _make_backdrop(self) -> pygame.Surface:
        """Darken the game towards the right, where the panel sits."""
        return style.gradient(self.size, (0, 0, 0, 70), (0, 0, 0, 190))

    def px(self, v: float) -> int:
        return int(v * self.u)

    def hit(self, pos: tuple[int, int]) -> tuple[str, object] | None:
        """What's at a screen position: ("tab", index), ("item", key) or None."""
        x, y = pos[0] - self._origin[0], pos[1] - self._origin[1]
        for rect, index in self.tab_hits:
            if rect.collidepoint(x, y):
                return "tab", index
        for rect, key in self.item_hits:
            if rect.collidepoint(x, y):
                return "item", key
        return None

    def draw(self, surf: pygame.Surface, menu: QuickMenu, title: str, paused: bool, t: float = 1.0,
             pointer: tuple[int, int] | None = None) -> None:
        now = time.monotonic()
        self._dt, self._last = min(0.1, now - self._last), now
        surf.fill((0, 0, 0, 0))
        t = max(0.0, min(1.0, t))
        e = ease_out(t)
        backdrop = self._backdrop.copy()
        backdrop.set_alpha(int(255 * e))
        surf.blit(backdrop, (0, 0))

        w, h = self.size
        panel = pygame.Rect(0, self.margin, self.panel_w, h - 2 * self.margin)
        panel.right = int(w - self.margin + (1 - e) * (self.panel_w + self.margin * 2))

        layer = pygame.Surface(panel.size, pygame.SRCALPHA)
        self._draw_panel(layer, menu, title, paused, 1.0 if self.reduced else t)
        layer.set_alpha(int(255 * e))
        if self._shadow is None:
            self._shadow = style.soft_shadow(panel.size, self.radius, self.px(40), 170)
        self._shadow.set_alpha(int(255 * e))
        surf.blit(self._shadow, (panel.x - self.px(40), panel.y - self.px(40) + self.px(10)))
        surf.blit(layer, panel.topleft)
        self._origin = panel.topleft
        if pointer is not None and t >= 1.0:
            style.draw_pointer(surf, pointer, self.u, self.lv)

    def draw_toast(self, surf: pygame.Surface, toast, now: float) -> None:
        """A notice, top right: slides in, waits, slides out (toasts.SECONDS)."""
        from .toasts import SECONDS

        lv = self.lv
        age = now - (toast.shown_at or now)
        e = ease_out(min(1.0, age / 0.35)) * ease_out(min(1.0, max(0.0, SECONDS - age) / 0.35))
        w, h = self.px(560), self.px(118)
        card = pygame.Surface((w, h), pygame.SRCALPHA)
        card.blit(style.gradient((w, h), (*style.lighten(lv.panel, 0.06), 248), (*lv.panel, 244), vertical=True),
                  (0, 0))
        style.stripes(card, 0, 0, h, self.px(10), (lv.accent, lv.second))
        style.rounded(card, self.radius)
        icon = {"battery": "battery", "download": "download", "update": "download",
                "camera": "camera", "clock": "clock"}.get(toast.icon, "info")
        Icons.draw(card, icon, (self.px(64), h // 2), self.px(40), lv.accent, bg=lv.panel)
        x = self.px(108)
        title = style.fit(self.f_label.render(toast.title, True, lv.text), w - x - self.px(24))
        detail = style.fit(self.f_detail.render(toast.detail, True, lv.dim), w - x - self.px(24)) \
            if toast.detail else None
        th = title.get_height() + (detail.get_height() if detail else 0)
        y = (h - th) // 2
        card.blit(title, (x, y))
        if detail:
            card.blit(detail, (x, y + title.get_height()))
        card.set_alpha(int(255 * e))
        sw = surf.get_width()
        shadow = style.soft_shadow((w, h), self.radius, self.px(24), 150)
        shadow.set_alpha(int(255 * e))
        pos = (int(sw - self.margin - w + (1 - e) * self.px(80)), self.margin + self.px(20))
        surf.blit(shadow, (pos[0] - self.px(24), pos[1] - self.px(24) + self.px(6)))
        surf.blit(card, pos)

    def _stagger(self, t: float, i: int) -> float:
        """Content settles in, top to bottom, as the panel arrives, and is
        fully there once it has (however long the list)."""
        delay = min(0.55, 0.2 + 0.06 * i)
        return ease_out((t - delay) / (1 - delay))

    def _draw_panel(self, s: pygame.Surface, menu: QuickMenu, title: str, paused: bool, t: float) -> None:
        lv, r = self.lv, s.get_rect()
        s.blit(style.gradient(r.size, (*style.lighten(lv.panel, 0.05), 246), (*lv.panel, 242), vertical=True), (0, 0))
        style.stripes(s, 0, 0, r.h, self.px(12), (lv.accent, lv.second))
        style.rounded(s, self.radius)
        pygame.draw.rect(s, (*lv.text, 34), r, width=max(1, self.px(1.5)), border_radius=self.radius)

        pad = self.pad
        head = pygame.Surface((r.w, self.px(150)), pygame.SRCALPHA)
        y = self.px(44)
        cap = style.tracked(self.f_caption, "NOW PLAYING" if title != "Home" else "HEARTH", lv.dim, 0.35)
        head.blit(cap, (pad, y))
        clock = self.f_clock.render(style.clock_text(self.clock), True, lv.text)
        head.blit(clock, (r.w - self.pad_r - clock.get_width(), y - self.px(10)))
        y += cap.get_height() + self.px(4)
        chip_w = self.px(140) if paused else 0
        name = style.fit(style.tracked(self.f_title, title.upper(), lv.text, 0.04), r.w - pad - self.pad_r - chip_w)
        head.blit(name, (pad, y))
        if paused:
            self._paused_chip(head, r.w - self.pad_r, y + name.get_height() // 2)
        self._blit_in(s, head, (0, 0), self._stagger(t, 0))
        y += name.get_height() + self.px(22)
        style.blend_rect(s, pygame.Rect(pad, y, r.w - pad - self.pad_r, max(1, self.px(1))), (*lv.text, 30))

        y = self._draw_tabs(s, menu, y + self.px(18), t)
        footer_h = self.px(76)
        self._draw_items(s, menu, pygame.Rect(0, y + self.px(18), r.w, r.h - y - self.px(18) - footer_h), t,
                         highlight=0.35 if menu.on_tabs else 1.0)
        style.blend_rect(s, pygame.Rect(pad, r.h - footer_h, r.w - pad - self.pad_r, max(1, self.px(1))),
                         (*lv.text, 22))
        self._draw_footer(s, pygame.Rect(0, r.h - footer_h, r.w, footer_h))

    def _blit_in(self, s: pygame.Surface, layer: pygame.Surface, pos: tuple[int, int], a: float) -> None:
        if a <= 0:
            return
        if a < 1:
            layer.set_alpha(int(255 * a))
        s.blit(layer, (pos[0], pos[1] + int((1 - a) * self.px(18))))

    def _paused_chip(self, s: pygame.Surface, right: int, cy: int) -> None:
        lv = self.lv
        text = style.tracked(self.f_caption, "PAUSED", lv.accent, 0.3)
        bar_w, bar_h = max(2, self.px(4)), text.get_height() - self.px(6)
        chip = pygame.Rect(0, 0, text.get_width() + bar_w * 3 + self.px(48), text.get_height() + self.px(14))
        chip.midright = (right, cy)
        pygame.draw.rect(s, lv.accent, chip, width=max(1, self.px(2)), border_radius=chip.h // 2)
        x = chip.x + self.px(16)
        for dx in (0, bar_w * 2):
            s.fill(lv.accent, (x + dx, chip.centery - bar_h // 2, bar_w, bar_h))
        s.blit(text, (x + bar_w * 3 + self.px(12), chip.centery - text.get_height() // 2))

    def _draw_tabs(self, s: pygame.Surface, menu: QuickMenu, y: int, t: float) -> int:
        lv, pad = self.lv, self.pad
        n = max(1, len(menu.tabs))
        tab_w = (s.get_width() - pad - self.pad_r) / n
        tab_h = self.px(78)
        layer = pygame.Surface((s.get_width(), tab_h + self.px(12)), pygame.SRCALPHA)
        self.tab_hits = []
        for i, tab in enumerate(menu.tabs):
            x = int(pad + i * tab_w)
            active = i == menu.tab
            self.tab_hits.append((pygame.Rect(x, y, int(tab_w), tab_h), i))
            if active and menu.on_tabs:  # on the tab row: show which tab Left/Right is on
                style.blend_rect(layer, pygame.Rect(x + self.px(6), 0, int(tab_w) - self.px(12), tab_h),
                                 (*lv.text, 22), self.px(8))
            glow = self.smooth.get(("tab", i), 1.0 if active else 0.0, self._dt)
            color = mix(lv.dim, lv.text, glow)
            Icons.draw(layer, tab.icon, (int(x + tab_w / 2), self.px(22)), self.px(28), color, bg=lv.panel)
            label = style.tracked(self.f_tab, tab.title.upper(), color, 0.22)
            layer.blit(label, label.get_rect(midtop=(int(x + tab_w / 2), self.px(44))))
        # The livery stripe under the active tab glides to the next one.
        target = pad + menu.tab * tab_w + tab_w * 0.22
        x = self.smooth.get("tab_x", target, self._dt)
        length = int(tab_w * 0.56 + min(abs(target - x), tab_w) * 0.4)
        style.stripes(layer, int(x - (length - tab_w * 0.56) / 2), tab_h, length, max(2, self.px(5)),
                      (lv.accent, lv.second), vertical=False)
        self._blit_in(s, layer, (0, y), self._stagger(t, 1))
        return y + tab_h + self.px(12)

    def _draw_items(self, s: pygame.Surface, menu: QuickMenu, area: pygame.Rect, t: float,
                    highlight: float = 1.0) -> None:
        lv, pad = self.lv, self.pad
        row_h, gap = self.px(98 * self.row_scale), self.px(6)
        items = menu.current.items
        sel = menu.selected
        idx = items.index(sel) if sel in items else 0
        # Keep the selected row in view.
        target = max(0, (idx + 1) * (row_h + gap) - area.h)
        target = min(target, idx * (row_h + gap))
        self._scroll = self.smooth.get(("scroll", menu.tab), target, self._dt)
        clip = s.get_clip()
        s.set_clip(area)
        left, width = pad - self.px(18), s.get_width() - pad - self.pad_r + self.px(30)

        # The selection bar glides between rows (and tabs) rather than jumping.
        if sel in items:
            bar_y = self.smooth.get("bar_y", area.y + idx * (row_h + gap) - self._scroll, self._dt)
            bar = pygame.Rect(left, int(bar_y), width, row_h)
            style.blend_rect(s, bar, (*lv.text, int(16 * highlight)), self.px(8))
            style.blend_rect(s, pygame.Rect(bar.x, bar.y + self.px(14), max(2, self.px(4)), bar.h - self.px(28)),
                             (*lv.accent, int(255 * highlight)))

        self.item_hits = []
        for i, item in enumerate(items):
            rect = pygame.Rect(left, area.y + i * (row_h + gap) - int(self._scroll), width, row_h)
            if rect.bottom < area.top or rect.top > area.bottom:
                continue
            if item.selectable:
                self.item_hits.append((rect, item.key))
            a = self._stagger(t, 2 + i)
            if a <= 0:
                continue
            row = pygame.Surface(rect.size, pygame.SRCALPHA)
            self._draw_item(row, item, row.get_rect(), item is sel, menu.confirming == item.key)
            self._blit_in(s, row, rect.topleft, a)
        s.set_clip(clip)

    def _draw_item(self, s: pygame.Surface, item: Item, rect: pygame.Rect, selected: bool, confirming: bool) -> None:
        lv = self.lv
        inner = rect.inflate(-self.px(40), 0)
        x = inner.x
        if item.avatar:
            color = AVATAR_COLORS[zlib.crc32(item.label.encode()) % len(AVATAR_COLORS)]
            c = (x + self.px(26), rect.centery - (self.px(10) if item.kind == "slider" else 0))
            style.circle(s, color, c, self.px(26))
            letter = self.f_avatar.render(item.avatar, True, lv.text)
            s.blit(letter, letter.get_rect(center=c))
            x += self.px(68)

        label_color = (lv.accent if item.alert else lv.dim) if item.kind == "info" else lv.text
        if confirming:
            label = style.fit(style.tracked(self.f_value, (item.confirm_label or "Press A again to confirm").upper(),
                                            lv.accent, 0.08), max(1, inner.right - x))
        else:
            label = self.f_label.render(item.label, True, label_color)
        detail = self.f_detail.render(item.detail, True, lv.dim) if item.detail and not confirming else None
        if item.kind == "meter":  # a live reading: value on the right, a bar under it
            top = rect.y + self.px(14)
            s.blit(label, (x, top))
            shown = self.smooth.get((item.key, "value"), max(0.0, min(100.0, item.value or 0)), self._dt)
            value = style.tracked(self.f_value, item.unit, lv.accent if item.alert else lv.text, 0.06)
            s.blit(value, (inner.right - value.get_width(), top - self.px(2)))
            if detail:
                room = inner.right - value.get_width() - self.px(20) - (x + label.get_width() + self.px(14))
                s.blit(style.fit(detail, max(1, room)), (x + label.get_width() + self.px(14), top + self.px(6)))
            self._gauge(s, pygame.Rect(x, rect.bottom - self.px(26), inner.right - x, max(2, self.px(5))),
                        shown, False, False)
            return
        if item.kind == "slider":
            top = rect.y + self.px(14)
            s.blit(label, (x, top))
            shown = self.smooth.get((item.key, "value"), item.fraction * 100, self._dt)
            text = "MUTED" if item.muted else item.shows(item.value)
            value = style.tracked(self.f_value, text, lv.dim if item.muted else (lv.accent if selected else lv.text),
                                  0.06)
            s.blit(value, (inner.right - value.get_width(), top - self.px(2)))
            if detail:
                s.blit(detail, (x + label.get_width() + self.px(14), top + self.px(6)))
            self._gauge(s, pygame.Rect(x, rect.bottom - self.px(26), inner.right - x, max(2, self.px(5))),
                        shown, item.muted, selected)
            return

        text_h = label.get_height() + (detail.get_height() if detail else 0)
        top = rect.centery - text_h // 2
        s.blit(label, (x, top))
        if detail:
            s.blit(detail, (x, top + label.get_height()))

        if item.kind == "toggle":
            self._switch(s, item.key, pygame.Rect(0, 0, self.px(78), self.px(40)), inner.right, rect.centery,
                         bool(item.value))
        elif item.kind == "choice" and item.options:
            self._choice(s, item, inner.right, rect.centery, selected, x + label.get_width() + self.px(20))
        elif item.kind == "action":
            chev = self.type(44, "cond", "medium").render("›", True, lv.accent if selected else lv.dim)
            s.blit(chev, chev.get_rect(midright=(inner.right, rect.centery - self.px(2))))

    def _gauge(self, s: pygame.Surface, track: pygame.Rect, value: float, muted: bool, selected: bool) -> None:
        """A slider drawn like a rev counter's bar: tick marks, a needle."""
        lv = self.lv
        for i in range(11):
            tx = track.x + int(track.w * i / 10)
            tall = i in (0, 5, 10)
            h = self.px(10 if tall else 5)
            style.blend_rect(s, pygame.Rect(tx, track.y - h - self.px(4), max(1, self.px(1.5)), h),
                             (*lv.text, 70 if tall else 40))
        style.blend_rect(s, track, (*lv.text, 36))
        fill_w = int(track.w * max(0.0, min(100.0, value)) / 100)
        if fill_w > 0:
            fill = pygame.Rect(track.x, track.y, fill_w, track.h)
            if muted:
                style.blend_rect(s, fill, (*lv.text, 60))
            else:
                s.blit(style.gradient(fill.size, lv.second, lv.accent), fill.topleft)
        if selected and not muted:
            needle = pygame.Rect(0, 0, max(2, self.px(4)), self.px(24))
            needle.center = (track.x + fill_w, track.centery)
            s.fill(lv.text, needle)

    def _switch(self, s: pygame.Surface, key: str, rect: pygame.Rect, right: int, cy: int, on: bool) -> None:
        lv = self.lv
        rect.midright = (right, cy)
        k = self.smooth.get((key, "switch"), 1.0 if on else 0.0, self._dt)
        track = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(track, (*lv.text, 60), track.get_rect(), width=max(1, self.px(2)), border_radius=rect.h // 2)
        if k > 0:
            fill = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(fill, lv.accent, fill.get_rect(), border_radius=rect.h // 2)
            fill.set_alpha(int(255 * k))
            track.blit(fill, (0, 0))
        s.blit(track, rect.topleft)
        r = rect.h // 2 - self.px(6)
        knob_x = rect.x + rect.h // 2 + (rect.w - rect.h) * k
        style.circle(s, mix(lv.dim, lv.text, k), (knob_x, rect.centery), r)

    def _choice(self, s: pygame.Surface, item: Item, right: int, cy: int, selected: bool, min_x: int) -> None:
        lv = self.lv
        arrow_color = lv.accent if selected else lv.dim
        text = item.options[item.value]
        value = self.f_value.render(text, True, lv.text)
        avail = right - min_x - self.px(70)
        if value.get_width() > avail > 0:
            while len(text) > 3 and self.f_value.size(text + "…")[0] > avail:
                text = text[:-1]
            value = self.f_value.render(text + "…", True, lv.text)
        a = self.px(9)
        rx = right - a
        pygame.draw.polygon(s, arrow_color, [(rx - a, cy - a), (rx + a // 2, cy), (rx - a, cy + a)])
        vx = rx - a - self.px(14) - value.get_width()
        s.blit(value, (vx, cy - value.get_height() // 2))
        lx = vx - self.px(16)
        pygame.draw.polygon(s, arrow_color, [(lx + a, cy - a), (lx - a // 2, cy), (lx + a, cy + a)])

    def _draw_footer(self, s: pygame.Surface, area: pygame.Rect) -> None:
        x = self.pad
        for button, text in (("LB RB", "Tabs"), ("A", "Select"), ("‹ ›", "Adjust"), ("B", "Close")):
            x = style.button_hint(s, x, area.centery, button, text, self.type, self.lv, size=0.9)
