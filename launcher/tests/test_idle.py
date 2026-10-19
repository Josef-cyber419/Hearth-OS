"""Staying light when nothing moves: a settled home screen stops redrawing 60
times a second, and only a few full-screen backdrops are kept in memory."""

import pygame
import pytest

from hearth import config as cfg
from hearth import ui
from hearth.model import Home, Nav


@pytest.fixture
def surface():
    pygame.display.init()
    pygame.font.init()
    yield pygame.display.set_mode((1280, 720))
    pygame.quit()


def count_draws(monkeypatch):
    draws = []
    real = ui.HomeScreen.draw
    monkeypatch.setattr(ui.HomeScreen, "draw", lambda self: (draws.append(1), real(self))[1])
    return draws


def test_a_settled_screen_stops_redrawing(surface, shipped_config, monkeypatch):
    draws = count_draws(monkeypatch)
    monkeypatch.setattr(ui, "SETTLE_SECONDS", 0.0)
    # On a slow runner the first draw can come after BACKDROP_DELAY, which
    # starts the backdrop's fade and keeps the screen busy for half a second.
    monkeypatch.setattr(ui, "BACKDROP_DELAY", 1e9)
    config = cfg.load(shipped_config, hide=False)
    assert ui.run(surface, Home(config), config.title, max_frames=45) is None
    assert len(draws) <= 3  # once, then only when something shown changes


def test_an_active_screen_draws_every_frame(surface, shipped_config, monkeypatch):
    draws = count_draws(monkeypatch)
    config = cfg.load(shipped_config, hide=False)
    ui.run(surface, Home(config), config.title, max_frames=20)
    assert len(draws) == 20


def test_what_a_settled_screen_shows(surface, shipped_config):
    config = cfg.load(shipped_config, hide=False)
    screen = ui.HomeScreen(surface, Home(config), config.title)
    before = screen.looks()
    assert screen.looks() == before  # nothing changed
    screen.message = "Hades: added to Favorites"
    assert screen.looks() != before  # a message appeared: draw it


def test_only_a_few_full_screen_backdrops_are_kept(surface, shipped_config, monkeypatch):
    monkeypatch.setattr(ui, "BACKDROP_DELAY", 0.0)
    config = cfg.load(shipped_config, hide=False)
    screen = ui.HomeScreen(surface, Home(config), config.title)
    seen = set()
    for i in range(12):
        screen.handle(Nav.RIGHT if i % 4 else Nav.DOWN)
        screen._focus_since = -1e9
        screen.draw()
        seen.add(screen.home.selected.id)
    assert len(screen._backdrops) <= ui.BACKDROPS_KEPT < len(seen)
    assert len(screen._blurs) == len(seen)  # the small blurs stay, to rebuild them quickly


def test_no_sleep_or_saver_while_something_else_is_on(surface, shipped_config, monkeypatch):
    """Discord or a phone casting in front, or music playing: the home screen
    behind them mustn't put the PC to sleep (sleep_minutes) or start the saver."""
    suspends = []
    monkeypatch.setattr(ui.subprocess, "Popen", lambda argv: suspends.append(argv))
    monkeypatch.setattr(ui, "BUSY_SECONDS", 0.0)
    config = cfg.load(shipped_config, hide=False)
    ui.run(surface, Home(config), config.title, max_frames=40, sleep_after=0.05, saver_after=0.05,
           busy=lambda: "shown")
    assert suspends == []
    saved = []
    monkeypatch.setattr(ui.HomeScreen, "start_saver", lambda self: saved.append(1))
    ui.run(surface, Home(config), config.title, max_frames=40, sleep_after=0.05, saver_after=0.05,
           busy=lambda: "playing")
    assert suspends == [] and saved  # music: the saver still looks after the TV
    ui.run(surface, Home(config), config.title, max_frames=40, sleep_after=0.05, busy=lambda: None)
    assert suspends and all(s == ["systemctl", "suspend"] for s in suspends)  # (a real PC sleeps at the first)


def test_in_use_hears_sound_as_well_as_players(monkeypatch):
    from hearth import audio, hub, media, session

    session.update(lambda s: s.update(focus="home", foreground=None))
    monkeypatch.setattr(media, "players", lambda: [])
    monkeypatch.setattr(audio, "playing_now", lambda: False)
    assert hub.in_use() is None
    monkeypatch.setattr(audio, "playing_now", lambda: True)  # AirPlay audio: no player on the bus, sound going out
    assert hub.in_use() == "playing"
    session.update(lambda s: s.update(focus="discord"))
    assert hub.in_use() == "shown"


def test_playing_now_reads_pactl():
    from hearth import audio

    streams = '[{"index": 1, "corked": true, "mute": false}, {"index": 2, "corked": false, "mute": false}]'
    assert audio.playing_now(run=lambda args: streams) is True
    assert audio.playing_now(run=lambda args: '[{"index": 2, "corked": false, "mute": true}]') is False
    assert audio.playing_now(run=lambda args: "[]") is False

    def broken(args):
        raise RuntimeError("audio isn't answering")

    assert audio.playing_now(run=broken) is False


def test_the_remote_asks_the_config_now_and_then_not_per_request(monkeypatch):
    from hearth import hub
    from hearth import config as cfg

    loads = []

    class C:
        remote_enabled = True

    monkeypatch.setattr(cfg, "load", lambda *a, **k: loads.append(1) or C())
    hub._remote_enabled.clear()
    assert hub.remote_enabled() and hub.remote_enabled() and len(loads) == 1

    def broken(*a, **k):
        raise cfg.ConfigError("bad")

    monkeypatch.setattr(cfg, "load", broken)
    hub._remote_enabled.clear()
    assert hub.remote_enabled() is False  # a broken config: off, not a traceback per request
    hub._remote_enabled.clear()
