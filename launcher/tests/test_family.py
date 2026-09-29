"""Household limits: daily game time, bedtime, locked tiles, all behind a PIN."""

from datetime import datetime

import pytest

from hearth import config as cfg
from hearth import family, settings, settings_app, ui
from hearth.model import Home, Nav


def at(hour: int, minute: int = 0) -> float:
    return datetime(2026, 9, 29, hour, minute).timestamp()


def test_nothing_applies_without_a_pin():
    settings.put("family", "daily_minutes", 30)
    assert not family.rules().active
    assert family.needs_pin("steam") is None


def test_pin_is_stored_hashed_and_checked():
    family.set_pin("2468")
    stored = settings.load()["family"]["pin"]
    assert "2468" not in stored and "$" in stored
    assert family.check_pin("2468") and not family.check_pin("1357")
    with pytest.raises(ValueError):
        family.set_pin("12")
    family.set_pin(None)
    assert "family" not in settings.load()


def test_daily_limit_bedtime_and_locks():
    family.set_pin("2468")
    settings.put("family", "daily_minutes", 60)
    settings.put("family", "bedtime", "21:00-07:00")
    settings.put("family", "locked", ["discord"])
    now = at(18)
    assert family.needs_pin("game:steam:620", now) is None
    assert family.needs_pin("youtube", now) is None  # films and TV apps aren't games
    assert family.needs_pin("discord", now) == "This one is locked"
    family.add_played(3600, now)
    assert family.needs_pin("game:steam:620", now) == "That's all the play time for today"
    assert family.needs_pin("steam", at(22)) == "It's bedtime" and family.needs_pin("steam", at(6, 59))
    assert family.needs_pin("youtube", at(22)) is None
    family.grant_extra(now)  # the PIN was entered
    assert family.needs_pin("steam", now + 60) is None
    assert family.needs_pin("steam", now + (family.EXTRA_MINUTES + 1) * 60)
    assert family.played_today(at(18) + 86400) == 0  # a new day


def test_watcher_counts_warns_and_closes():
    family.set_pin("2468")
    settings.put("family", "daily_minutes", 30)
    settings.put("family", "when_up", "close")
    w = family.Watcher()
    now = at(17)
    family.add_played(24 * 60, now)
    out = []
    for t in range(0, 7 * 60 + 90, 1):  # a game in front, one tick a second
        out += w.tick("game:rom:snes:mario.sfc", now + t)
    notices = [o for o in out if o[0] == "notice"]
    assert notices[0][1] == "5 min of play time left"
    assert notices[1][1] == "That's all the play time for today" and "save now" in notices[1][2]
    assert out.count(("close",)) == 1  # a minute after time's up, once
    assert w.tick("youtube", now + 9000) == []  # not a game: nothing counted, nothing said
    assert w.tick(None, now + 9001) == []


def test_watcher_does_nothing_when_off():
    assert family.Watcher().tick("steam") == []
    assert family.played_today() == 0


def test_pin_pad():
    family.set_pin("2468")
    pad = family.PinEntry("It's bedtime")
    for digit in "2468":
        for _ in range(int(digit)):
            pad.handle(Nav.UP)
        pad.handle(Nav.RIGHT)
    assert pad.handle(Nav.SELECT) == "ok"
    pad = family.PinEntry("It's bedtime")
    assert pad.handle(Nav.SELECT) is None and pad.message == "Not that one"
    assert pad.type("2") is None and pad.type("4") is None and pad.type("6") is None and pad.type("8") == "ok"
    assert family.PinEntry("x").handle(Nav.BACK) == "cancel"


def test_home_screen_asks_for_the_pin(shipped_config):
    import pygame

    pygame.display.init()
    pygame.font.init()
    surface = pygame.display.set_mode((1280, 720))
    try:
        family.set_pin("2468")
        settings.put("family", "locked", ["steam"])
        config = cfg.load(shipped_config, hide=False)
        screen = ui.HomeScreen(surface, Home(config), config.title)
        steam = config.app("steam")
        assert screen._open(steam) is None and screen.pin is not None
        screen.draw()  # the pad draws
        for ch in "246":
            assert screen.type_text(ch) is None
        assert screen.type_text("8") == steam and screen.pin is None
        assert family.needs_pin("steam") == "This one is locked"  # a lock stays locked (no extra time)
    finally:
        pygame.quit()


def test_settings_family_page(shipped_config, monkeypatch):
    app = settings_app.SettingsApp(shipped_config)
    typed = []
    monkeypatch.setattr(app, "open_keyboard", lambda title, done, secret=False, text="": typed.append((title, done)))

    def items():
        app.refresh()
        return {i.key: i for i in app.build()[[c[0] for c in settings_app.CATEGORIES].index("family")].items}

    items()["family-pin"].on_select()
    typed[-1][1]("2468")
    page = items()
    assert family.rules().active and "family-daily" in page  # set just now: open
    page["family-daily"].on_change(list(family.DAILY_CHOICES).index(90))
    page["lock-steam"].on_change(True)
    assert family.rules().daily_minutes == 90 and family.rules().locked == {"steam"}
    app2 = settings_app.SettingsApp(shipped_config)
    monkeypatch.setattr(app2, "open_keyboard", lambda title, done, secret=False, text="": typed.append((title, done)))
    app = app2
    page = items()
    assert list(page) == ["family-unlock"]  # a fresh visit: PIN first
    page["family-unlock"].on_select()
    typed[-1][1]("0000")
    assert list(items()) == ["family-unlock"]
    items()["family-unlock"].on_select()
    typed[-1][1]("2468")
    assert "family-bedtime" in items()
