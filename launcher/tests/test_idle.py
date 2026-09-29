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
