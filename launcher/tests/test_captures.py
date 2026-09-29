"""Captures: screenshots from the Quick Menu, the Captures screen, and the
screen saver showing them."""

import time

import pygame
import pytest

from fakes import FakeActions, FakePactl
from hearth import captures, ctl, library, ui
from hearth import config as cfg
from hearth.audio import Audio
from hearth.gallery import COLS, Gallery
from hearth.model import Home, Nav
from hearth.quickmenu import Context, QuickMenu, build_tabs


def png(color=(200, 40, 40), size=(64, 36)) -> bytes:
    import io

    img = pygame.Surface(size)
    img.fill(color)
    buf = io.BytesIO()
    pygame.image.save(img, buf, "capture.png")
    return buf.getvalue()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_saved_named_by_game_and_time(home):
    when = time.mktime((2026, 9, 29, 20, 15, 30, 0, 0, -1))
    a = captures.save(b"one", "Super Mario Galaxy", home, when)
    b = captures.save(b"two", "Super Mario Galaxy", home, when)  # same second: kept, not overwritten
    c = captures.save(b"three", "Bad/Name:?", home, when + 60)
    assert a.name == "Super Mario Galaxy 2026-09-29 20.15.30.png" and a.parent == home / "Pictures/Hearth"
    assert b.name == "Super Mario Galaxy 2026-09-29 20.15.30 2.png" and a.read_bytes() == b"one"
    assert c.name == "BadName 2026-09-29 20.16.30.png"
    listed = captures.all_captures(home)
    assert [x.path for x in listed][0] == c  # newest first
    assert listed[0].title == "BadName" and listed[-1].title == "Super Mario Galaxy"
    assert listed[0].when == "29 Sep 2026, 20:16"


def test_pictures_folder_from_the_desktop(home):
    (home / ".config").mkdir()
    (home / ".config/user-dirs.dirs").write_text('XDG_PICTURES_DIR="$HOME/Bilder"\n')
    assert captures.folder(home) == home / "Bilder/Hearth"


def test_take_uses_the_screen(home, monkeypatch):
    from hearth import report

    monkeypatch.setattr(report, "screenshot", lambda: (b"PNGDATA", "gamescope"))
    path = captures.take("Hades", home)
    assert path.read_bytes() == b"PNGDATA" and path.name.startswith("Hades ")
    monkeypatch.setattr(report, "screenshot", lambda: None)
    assert captures.take("Hades", home) is None


def test_quick_menu_has_take_a_screenshot():
    audio, actions = Audio(FakePactl()), FakeActions()
    state = {"foreground": {"id": "kodi", "name": "Kodi"}, "background": {}, "focus": "foreground"}
    menu = QuickMenu(build_tabs(Context(audio, audio.snapshot(), state, actions)))
    menu.tab = [t.key for t in menu.tabs].index("system")
    menu.select("screenshot")
    assert menu.handle(Nav.SELECT) == "close"
    assert actions.calls == [("screenshot",)]


def test_hearthctl_screenshot(home, monkeypatch, capsys):
    monkeypatch.setattr(captures, "take", lambda title: home / f"{title}.png")
    assert ctl.main(["screenshot"]) == 0
    assert "Home.png" in capsys.readouterr().out  # nothing running: the home screen
    monkeypatch.setattr(captures, "take", lambda title: None)
    assert ctl.main(["screenshot"]) == 1


def caps(home, n):
    return [captures.save(b"x", f"Game {i}", home, 1_000_000 + i) for i in range(n)]


def test_gallery_grid_and_full_view(home):
    caps(home, 6)
    g = Gallery(captures.all_captures(home))
    assert g.current.title == "Game 5"
    g.handle(Nav.RIGHT)
    g.handle(Nav.DOWN)
    assert g.pick == 1 + COLS
    g.handle(Nav.DOWN)  # no row below: stays
    assert g.pick == 1 + COLS
    g.handle(Nav.UP)
    g.handle(Nav.LEFT)
    g.handle(Nav.LEFT)  # the edge
    assert g.pick == 0
    g.handle(Nav.SELECT)
    assert g.full
    g.handle(Nav.LEFT)  # full view wraps round
    assert g.pick == 5
    assert g.handle(Nav.BACK) is None and not g.full
    assert g.handle(Nav.BACK) == "close"


def test_gallery_deletes_after_asking(home):
    caps(home, 2)
    g = Gallery(captures.all_captures(home))
    g.handle(Nav.FAVORITE)  # X
    assert g.confirming and len(list((home / "Pictures/Hearth").glob("*.png"))) == 2
    g.handle(Nav.BACK)  # keep it
    assert not g.confirming and len(g.items) == 2
    g.handle(Nav.FAVORITE)
    g.handle(Nav.SELECT)
    assert len(g.items) == 1 and g.message == "Deleted"
    assert [p.name for p in (home / "Pictures/Hearth").glob("*.png")] == [g.items[0].path.name]
    g.handle(Nav.FAVORITE)
    g.handle(Nav.FAVORITE)  # X twice works too
    assert g.items == [] and g.handle(Nav.SELECT) == "close"


@pytest.fixture
def screen(home, monkeypatch):
    pygame.display.init()
    pygame.font.init()
    surface = pygame.display.set_mode((1280, 720))
    monkeypatch.setattr(library, "all_games", lambda: [])
    yield surface
    pygame.quit()


def test_captures_tile_opens_the_screen(screen, home):
    for i, color in enumerate(((200, 40, 40), (40, 200, 40), (40, 40, 200))):
        captures.save(png(color), f"Game {i}", home, 1_000_000 + i)
    tile = cfg.App(id="captures", name="Captures", command=("hearth:captures",))
    scr = ui.HomeScreen(screen, Home(cfg.Config(rows=(cfg.Row("System", (tile,)),))), "Hearth")
    assert scr.handle(Nav.SELECT) is None and scr.gallery is not None
    for _ in range(4):  # thumbnails arrive one per frame
        scr.draw()
    assert len(scr._thumbs) == 3
    scr.handle(Nav.SELECT)
    scr.draw()
    r, g, b, _ = screen.get_at((640, 300))
    assert b > r and b > g  # the newest (blue) screenshot, full screen
    scr.handle(Nav.BACK)
    scr.handle(Nav.BACK)
    assert scr.gallery is None


def test_empty_captures_screen_draws(screen, home):
    tile = cfg.App(id="captures", name="Captures", command=("hearth:captures",))
    scr = ui.HomeScreen(screen, Home(cfg.Config(rows=(cfg.Row("System", (tile,)),))), "Hearth")
    scr.handle(Nav.SELECT)
    scr.draw()
    assert scr.handle(Nav.BACK) is None and scr.gallery is None


def test_screen_saver_shows_screenshots(screen, home):
    captures.save(png(), "Hades", home, 1_000_000)
    scr = ui.HomeScreen(screen, Home(cfg.Config(rows=())), "Hearth")
    scr.start_saver()
    [(title, caption, path)] = scr._slides
    assert (title, caption) == ("Hades", "Screenshot") and path.startswith(str(captures.folder(home)))
    scr.draw_saver()
