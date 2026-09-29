"""Game details (Y on a game): play time, last played, Play."""

import sys
import time

import pygame

from hearth import config as cfg
from hearth import hub, library, ui
from hearth.model import Home, Nav


def test_play_time_and_when_in_words():
    assert ui.played_for(0) == "Not yet" and ui.played_for(20) == "Less than a minute"
    assert ui.played_for(45 * 60) == "45 min" and ui.played_for(5 * 3600 + 20 * 60) == "5 h 20 min"
    assert ui.played_for(40 * 3600 + 5 * 60) == "40 h"
    now = time.mktime((2026, 9, 29, 20, 0, 0, 0, 0, -1))
    assert ui.played_when(0, now) == "Never"
    assert ui.played_when(now - 3600, now) == "Today"
    assert ui.played_when(now - 86400, now) == "Yesterday"
    assert ui.played_when(now - 3 * 86400, now) == "3 days ago"
    assert "2026" in ui.played_when(now - 40 * 86400, now)


def test_hearth_counts_time_in_front(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    app = cfg.App(id="game:rom:snes:Zelda.sfc", name="Zelda",
                  command=(sys.executable, "-c", "import time; time.sleep(0.4)"))
    hub.launch(app)
    # Counted from when it's on screen, so a little under the 0.4 s it ran on
    # a slow machine; never more than it ran.
    first = library.playtimes()["rom:snes:Zelda.sfc"]
    assert 0 < first < 5
    library.add_playtime("rom:snes:Zelda.sfc", 60)
    assert library.playtimes()["rom:snes:Zelda.sfc"] == first + 60  # adds up
    steam = cfg.App(id="game:steam:620", name="Portal 2", command=(sys.executable, "-c", "pass"),
                    home_button=False, tag_windows=False)
    hub.launch(steam)
    assert "steam:620" not in library.playtimes()  # Steam counts its own


def test_steam_play_time(tmp_path):
    cfgdir = tmp_path / "userdata/1/config"
    cfgdir.mkdir(parents=True)
    (cfgdir / "localconfig.vdf").write_text(
        '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { '
        '"620" { "LastPlayed" "1700000000" "Playtime" "754" } } } } } }')
    assert library.steam_playtime(tmp_path) == {"620": 754.0}


def test_details_card_offers_play(tmp_path, monkeypatch, shipped_config):
    monkeypatch.setenv("HOME", str(tmp_path))
    game = library.Game("rom:wii:g.wbfs", "Super Mario Galaxy", "wii", ("true",), last_played=time.time(),
                        playtime=4000, plays=3)
    monkeypatch.setattr(library, "all_games", lambda: [game])
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((1280, 720))

        def build():
            return library.with_game_rows(cfg.load(shipped_config, hide=False), games=[game])

        s = ui.HomeScreen(surface, Home(build()), "Hearth")
        s.rebuild = build
        assert s.home.select_id("game:rom:wii:g.wbfs")
        s.handle(Nav.OPTIONS)
        assert s._details.playtime == 4000 and s.options[1][0][0] == "Play"
        s.draw()
        app = s.handle(Nav.SELECT)
        assert app.id == "game:rom:wii:g.wbfs"
    finally:
        pygame.quit()
