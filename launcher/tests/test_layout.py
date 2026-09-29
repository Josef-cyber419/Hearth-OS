"""Arranging the home screen: favourite any tile (X), move tiles (Options → Move)."""

import pygame
import pytest

from hearth import config as cfg
from hearth import layout, library, settings, ui
from hearth.model import Home, Nav

APPS = {"rows": [
    {"title": "Play", "apps": [{"id": "steam", "name": "Steam", "command": "true"},
                               {"id": "moonlight", "name": "Moonlight", "command": "true"}]},
    {"title": "Watch", "apps": [{"id": "kodi", "name": "Kodi", "command": "true"},
                                {"id": "youtube", "name": "YouTube", "command": "true"},
                                {"id": "plex", "name": "Plex", "command": "true"}]},
    {"title": "System", "apps": [{"id": "settings", "name": "Settings", "command": "hearth:settings"}]},
]}


@pytest.fixture
def screen(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    pygame.display.init()
    pygame.font.init()
    surface = pygame.display.set_mode((1280, 720))

    def build():
        return library.with_game_rows(cfg.parse(APPS), games=[])

    s = ui.HomeScreen(surface, Home(build()), "Hearth")
    s.rebuild = build
    yield s
    pygame.quit()


def titles(s):
    return [r.title for r in s.home.config.rows]


def row(s, title):
    return [a.id for a in next(r for r in s.home.config.rows if r.title == title).apps]


def go(s, *navs):
    for nav in navs:
        s.handle(nav)
        s.draw()


def test_x_stars_any_tile_into_a_favorites_row_on_top(screen):
    go(screen, Nav.DOWN, Nav.RIGHT)  # Watch → YouTube
    assert screen.home.selected.id == "youtube"
    go(screen, Nav.FAVORITE)
    assert titles(screen)[0] == "Favorites" and row(screen, "Favorites") == ["youtube"]
    assert screen.home.selected.id == "youtube" and titles(screen)[screen.home.row] == "Watch"  # didn't jump
    assert "youtube" in screen.favorites and "Favorites" in screen.message
    go(screen, Nav.RIGHT, Nav.FAVORITE)  # Plex too: after YouTube
    assert row(screen, "Favorites") == ["youtube", "plex"]
    go(screen, Nav.FAVORITE)  # again: unstar
    assert row(screen, "Favorites") == ["youtube"]


def test_options_can_add_move_and_hide(screen):
    go(screen, Nav.DOWN, Nav.OPTIONS)  # Kodi
    labels = [c[0] for c in screen.options[1]]
    assert labels[:3] == ["Add to Favorites", "Move", "Hide this tile"]
    go(screen, Nav.SELECT)
    assert layout.favorites() == ["kodi"]


def test_move_a_tile_and_it_stays_moved(screen):
    go(screen, Nav.DOWN, Nav.OPTIONS)  # Kodi, in Watch
    go(screen, Nav.DOWN, Nav.SELECT)  # Move
    assert screen.moving is not None
    go(screen, Nav.RIGHT, Nav.RIGHT)  # to the end
    assert row(screen, "Watch") == ["youtube", "plex", "kodi"] and screen.home.selected.id == "kodi"
    go(screen, Nav.SELECT)  # done
    assert screen.moving is None
    assert settings.load()["order"]["Watch"] == ["youtube", "plex", "kodi"]
    screen.reload(screen.rebuild())  # e.g. after a restart
    assert row(screen, "Watch") == ["youtube", "plex", "kodi"]


def test_b_puts_a_moving_tile_back(screen):
    go(screen, Nav.DOWN, Nav.OPTIONS, Nav.DOWN, Nav.SELECT, Nav.RIGHT, Nav.BACK)
    assert row(screen, "Watch") == ["kodi", "youtube", "plex"] and "order" not in settings.load()


def test_reorder_favorites(screen):
    for tile in ("steam", "kodi", "plex"):
        layout.set_favorite(tile, True)
    screen.reload(screen.rebuild())
    screen.home.row = 0  # Favorites
    go(screen, Nav.RIGHT, Nav.RIGHT, Nav.OPTIONS)  # Plex
    labels = [c[0] for c in screen.options[1]]
    assert labels[0] == "Remove from Favorites" and "Hide this tile" not in labels
    go(screen, Nav.DOWN, Nav.SELECT, Nav.LEFT, Nav.LEFT, Nav.SELECT)
    assert layout.favorites() == ["plex", "steam", "kodi"]


def test_new_tiles_follow_the_ones_you_arranged():
    apps = cfg.parse(APPS).rows[1].apps
    assert [a.id for a in layout.arrange(apps, ["plex", "gone"])] == ["plex", "kodi", "youtube"]


def test_rows_hearth_orders_itself_cant_be_rearranged():
    assert not layout.can_move("Continue") and not layout.can_move("Quick Resume")
    assert layout.can_move("Favorites") and layout.can_move("Watch")
    assert not layout.can_favorite("resume:kodi")


def test_controller_batteries(tmp_path):
    from hearth import battery

    def supply(name, **files):
        d = tmp_path / name
        d.mkdir()
        for k, v in files.items():
            (d / k).write_text(v + "\n")

    supply("BAT0", type="Battery", scope="System", capacity="90")  # the PC's own: not a controller
    supply("xpadneo-1", type="Battery", scope="Device", capacity="64", status="Discharging",
           model_name="Xbox Wireless Controller")
    supply("ps-controller-battery-2", type="Battery", scope="Device", capacity_level="Low", status="Discharging")
    supply("hidpp_battery_0", type="Battery", scope="Device", capacity="10", status="Charging")
    got = battery.controllers(tmp_path)
    assert [(b.name, b.percent, b.low) for b in got] == [
        ("hidpp_battery_0", 10, False),  # charging: not flagged
        ("ps-controller-battery-2", 20, True),
        ("Xbox Wireless Controller", 64, False)]
    assert battery.controllers(tmp_path / "missing") == []


def test_backdrop_follows_the_focused_tile(screen, monkeypatch):
    monkeypatch.setattr(ui, "BACKDROP_DELAY", 0.0)
    screen.draw()
    first = screen._backdrop[0]
    go(screen, Nav.RIGHT)
    assert screen._backdrop[0] != first and screen._backdrop[0] == screen.home.selected.id


def test_library_platform_rows_dont_offer_move(screen):
    screen.back_exits = True  # the Library screen
    go(screen, Nav.DOWN, Nav.OPTIONS)
    assert "Move" not in [c[0] for c in screen.options[1]]
