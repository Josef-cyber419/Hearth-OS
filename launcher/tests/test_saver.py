"""The ambient screen saver: your games' art, slowly."""

import time

import pygame
import pytest

from hearth import config as cfg
from hearth import library, ui
from hearth.model import Home


@pytest.fixture
def screen(tmp_path, monkeypatch):
    pygame.display.init()
    pygame.font.init()
    surface = pygame.display.set_mode((1280, 720))
    arts = []
    for i, color in enumerate(((200, 40, 40), (40, 40, 200))):
        img = pygame.Surface((400, 300))
        img.fill(color)
        path = tmp_path / f"art{i}.png"
        pygame.image.save(img, str(path))
        arts.append(str(path))
    games = [library.Game("rom:a", "Red Game", "snes", ("true",), art=arts[0]),
             library.Game("rom:b", "Blue Game", "n64", ("true",), art=arts[1]),
             library.Game("rom:c", "No Art", "gb", ("true",))]
    monkeypatch.setattr(library, "all_games", lambda: games)
    yield ui.HomeScreen(surface, Home(cfg.Config(rows=())), "Hearth")
    pygame.quit()


def test_shows_games_with_art(screen):
    screen.start_saver()
    assert sorted(t for t, _, _ in screen._slides) == ["Blue Game", "Red Game"]
    screen._saver_t0 = time.monotonic() - 1
    screen.draw_saver()
    first = screen.surface.get_at((640, 700))
    screen._saver_t0 = time.monotonic() - ui.SLIDE_SECONDS - ui.SLIDE_FADE - 1
    screen.draw_saver()
    assert screen.surface.get_at((640, 700)) != first  # moved on to the other game
    r, g, b, _ = screen.surface.get_at((5, 700))
    assert max(r, g, b) <= ui.SLIDE_DIM + 5  # dimmed: kind to OLED TVs


def test_clock_only_when_chosen_or_no_art(screen, monkeypatch):
    screen.saver_style = "clock"
    screen.start_saver()
    assert screen._slides == []
    screen.draw_saver()
    assert screen.surface.get_at((5, 5))[:3] == (0, 0, 0)
    monkeypatch.setattr(library, "all_games", lambda: [])
    screen.saver_style = "ambient"
    screen.start_saver()
    screen.draw_saver()  # no art at all: the dark clock saver
    assert screen._slides == []


def test_setting():
    assert cfg.parse({"home": {"screensaver": "clock"}}).screensaver == "clock"
    assert cfg.parse({}).screensaver == "ambient"


def test_art_that_wont_load_is_skipped(tmp_path, monkeypatch):
    pygame.display.init()
    pygame.font.init()
    surface = pygame.display.set_mode((1280, 720))
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a picture")
    good = tmp_path / "good.png"
    img = pygame.Surface((64, 64))
    img.fill((200, 40, 40))
    pygame.image.save(img, str(good))
    games = [library.Game("rom:a", "Broken", "snes", ("true",), art=str(broken)),
             library.Game("rom:b", "Missing", "snes", ("true",), art=str(tmp_path / "gone.png")),
             library.Game("rom:c", "Good", "snes", ("true",), art=str(good))]
    monkeypatch.setattr(library, "all_games", lambda: games)
    try:
        screen = ui.HomeScreen(surface, Home(cfg.Config(rows=())), "Hearth")
        screen.start_saver()
        assert sorted(t for t, _, _ in screen._slides) == ["Broken", "Good"]  # missing files never make the list
        for age in (1, ui.SLIDE_SECONDS + 1, 2 * ui.SLIDE_SECONDS + 1):
            screen._saver_t0 = time.monotonic() - age
            screen.draw_saver()
        assert [t for t, _, _ in screen._slides] == ["Good"]
        assert screen.surface.get_at((640, 700))[0] > screen.surface.get_at((640, 700))[2]  # the red art
    finally:
        pygame.quit()


def test_only_broken_art_falls_back_to_the_clock(tmp_path, monkeypatch):
    pygame.display.init()
    pygame.font.init()
    surface = pygame.display.set_mode((1280, 720))
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not a picture")
    monkeypatch.setattr(library, "all_games",
                        lambda: [library.Game("rom:a", "Broken", "snes", ("true",), art=str(broken))])
    try:
        screen = ui.HomeScreen(surface, Home(cfg.Config(rows=())), "Hearth")
        screen.start_saver()
        screen.draw_saver()  # mustn't fail with nothing left to show
        assert screen._slides == []
    finally:
        pygame.quit()
