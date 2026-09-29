"""What's new: shown once on the home screen after an update."""

import pygame
import pytest

from conftest import REPO
from hearth import config as cfg
from hearth import ui, whatsnew
from hearth.model import Home, Nav

CHANGELOG = """# Changelog

Intro text.

## 0.21.0 (2026-09-30)

- **Captures**: take a screenshot from the Quick Menu, and see them all with
  the Captures tile.
- A `wifi` indicator by the clock, [docs](docs/x.md).

## 0.20.0 (2026-09-29)

- Older things.
"""


@pytest.fixture
def changelog(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG)
    return path


def test_notes_in_plain_words(changelog):
    assert whatsnew.notes("0.21.0", changelog) == [
        "Captures: take a screenshot from the Quick Menu, and see them all with the Captures tile.",
        "A wifi indicator by the clock, docs.",
    ]
    assert whatsnew.notes("0.20.0", changelog) == ["Older things."]
    assert whatsnew.notes("9.9.9", changelog) == []
    assert whatsnew.notes("0.21.0", changelog.parent / "missing.md") == []


def test_shown_once_per_version(changelog):
    version, notes = whatsnew.pending("0.21.0", changelog)
    assert version == "0.21.0" and len(notes) == 2
    whatsnew.mark_seen("0.21.0")
    assert whatsnew.pending("0.21.0", changelog) is None
    assert whatsnew.pending("0.20.0", changelog) is not None  # a different version: shown
    assert whatsnew.pending("0.21.0-dev.abc1234", changelog) is None  # test builds: never
    assert whatsnew.pending("dev", changelog) is None


def test_the_real_changelog_has_notes_for_this_version():
    version = (REPO / "VERSION").read_text().strip()
    assert whatsnew.notes(version, REPO / "CHANGELOG.md")


def test_home_screen_card(changelog):
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((1280, 720))
        tile = cfg.App(id="a", name="A", command=("true",))
        scr = ui.HomeScreen(surface, Home(cfg.Config(rows=(cfg.Row("Play", (tile,)),))), "Hearth")
        scr.whats_new = whatsnew.pending("0.21.0", changelog)
        scr.draw()
        assert scr.handle(Nav.RIGHT) is None and scr.whats_new is not None  # only A/B close it
        assert scr.handle(Nav.SELECT) is None  # closes the card; doesn't open the tile
        assert scr.whats_new is None and whatsnew.pending("0.21.0", changelog) is None
        assert scr.handle(Nav.SELECT) == tile
        long = ("0.21.0", [f"Item {i}: " + "words " * 40 for i in range(20)])
        scr.whats_new = long
        scr.draw()  # too much for the card: it ends with "…and more"
    finally:
        pygame.quit()
