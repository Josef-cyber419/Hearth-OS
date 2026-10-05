"""Search: games and apps, with the controller or a keyboard."""

import pygame
import pytest

from hearth import config as cfg
from hearth import library, search, ui
from hearth.model import Home, Nav
from hearth.search import Search, find, score

GAMES = [library.Game("rom:wii:g.wbfs", "Super Mario Galaxy", "wii", ("true",)),
         library.Game("rom:n64:mk.z64", "Mario Kart 64", "n64", ("true",)),
         library.Game("rom:gc:ww.rvz", "The Legend of Zelda: The Wind Waker", "gc", ("true",)),
         library.Game("steam:620", "Portal 2", "steam", ("true",))]
APPS = [library.as_app(g) for g in GAMES]


def names(apps):
    return [a.name for a in apps]


def test_matching_is_forgiving():
    assert score("super mario galaxy", "Super Mario Galaxy") == 100
    assert score("mario", "Mario Kart 64") > score("mario", "Super Mario Galaxy") > 0  # starts vs word start
    assert score("mar gal", "Super Mario Galaxy")  # every word you typed starts a word
    assert score("smg", "Super Mario Galaxy")  # initials
    assert score("wind", "The Legend of Zelda: The Wind Waker")
    assert score("xyz", "Portal 2") is None and score("", "Portal 2") is None
    assert names(find("wii", APPS)) == ["Super Mario Galaxy"]  # by platform
    assert names(find("mario", APPS)) == ["Mario Kart 64", "Super Mario Galaxy"]


def test_controller_typing_and_picking():
    s = Search(APPS)
    assert s.row == 1 and s.key_at(1, 0) == "q"
    s.col = 3  # r
    s.handle(Nav.SELECT)
    assert s.query == "r"
    s.handle(Nav.FAVORITE)  # X deletes
    s.type("zel")
    assert names(s.results) == ["The Legend of Zelda: The Wind Waker"]
    for _ in range(4):
        s.handle(Nav.DOWN)  # past the action keys into the results
    assert s.zone == "results"
    assert s.handle(Nav.SELECT).name.startswith("The Legend of Zelda")
    s.handle(Nav.UP)
    assert s.zone == "keys" and s.row == len(search.KEY_ROWS)  # back on the action keys
    s.col = 2
    s.handle(Nav.SELECT)  # clear
    assert s.query == "" and s.results == []
    assert s.handle(Nav.BACK) == "close"


def test_down_from_the_bottom_needs_results():
    s = Search(APPS)
    for _ in range(8):
        s.handle(Nav.DOWN)
    assert s.zone == "keys"  # nothing to go to yet


@pytest.fixture
def screen(tmp_path, monkeypatch, shipped_config):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(library, "all_games", lambda: GAMES)
    pygame.display.init()
    pygame.font.init()
    surface = pygame.display.set_mode((1280, 720))

    def build():
        return library.with_game_rows(cfg.load(shipped_config, hide=False), games=[])

    s = ui.HomeScreen(surface, Home(build()), "Hearth")
    s.rebuild = build
    yield s
    pygame.quit()


def test_search_from_the_home_screen_opens_a_game(screen):
    screen.handle(Nav.SEARCH)
    assert screen.search is not None
    ids = {a.id for a in screen.search.catalog}
    assert "kodi" in ids and "game:steam:620" in ids and "search" not in ids  # tiles and every game
    screen.type_text("portal")
    screen.draw()
    for _ in range(5):
        screen.handle(Nav.DOWN)
    app = screen.handle(Nav.SELECT)
    assert app.id == "game:steam:620" and screen.search is None


def test_search_tile_and_closing(screen):
    assert screen.home.select_id("search")
    assert screen.handle(Nav.SELECT) is None and screen.search is not None
    screen.draw()
    screen.handle(Nav.BACK)
    assert screen.search is None


def test_power_tiles_still_ask_from_search(screen):
    screen.handle(Nav.SEARCH)
    screen.type_text("power")
    screen.search.zone, screen.search.pick = "results", 0
    screen.handle(Nav.SELECT)
    assert screen.confirming is not None and screen.confirming.confirm


def test_a_real_keyboard_types_straight_in(screen):
    home = Home(screen.rebuild())
    events = [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SLASH, unicode="/", mod=0)]
    for ch in "portal":  # "a" and "o" would be navigation keys outside search
        events.append(pygame.event.Event(pygame.KEYDOWN, key=ord(ch), unicode=ch, mod=0))
    events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0))
    real_get = pygame.event.get
    queue = [[e] for e in events]
    pygame.event.get = lambda *a, **k: queue.pop(0) if queue else real_get()
    try:
        app = ui.run(screen.surface, home, "Hearth", max_frames=40)
    finally:
        pygame.event.get = real_get
    assert app is not None and app.id == "game:steam:620"


def test_the_delete_hint_names_backspace_with_a_keyboard(screen, monkeypatch):
    import time

    from hearth import search, style

    screen.search = search.Search(screen.search_catalog())
    screen._search_t0 = time.monotonic()
    hints = []
    real = style.button_hint
    monkeypatch.setattr(style, "button_hint", lambda s, x, cy, b, label, t, lv, size=1.0: hints.append(b) or
                        real(s, x, cy, b, label, t, lv, size))
    try:
        style.set_prompts("keyboard")
        screen._draw_search()
        assert "BACKSPACE" in hints and "X" not in hints
        hints.clear()
        style.set_prompts("xbox")
        screen._draw_search()
        assert "X" in hints and "BACKSPACE" not in hints
    finally:
        style.set_prompts("auto")
