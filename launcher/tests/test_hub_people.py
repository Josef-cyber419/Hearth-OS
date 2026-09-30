"""The hub with people: "Who's playing?" before the home screen."""

import argparse

import pygame
import pytest

from hearth import hub, profiles, session, ui
from hearth import config as cfg


@pytest.fixture
def two(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    profiles.start("Joseph", "1234")
    profiles.add("Sam")
    pygame.display.init()
    pygame.font.init()
    yield
    pygame.quit()


def run_step(shipped_config, state, choose, shown):
    """One hub step with ui.run replaced: `choose(home)` picks the tile."""
    def fake_run(surface, home, title, **kw):
        shown.append((title, [a.id for row in home.config.rows for a in row.apps]))
        return choose(home)

    ui.run = fake_run
    args = argparse.Namespace(config=shipped_config, show_all=False, windowed=True, dry_run=True)
    return hub.step(args, None, None, True, state)


def test_picker_first_then_home_as_that_person(shipped_config, two, monkeypatch):
    real_run = ui.run
    shown = []
    state = {"last_id": None, "message": None, "surface": None, "intro": "boot"}
    try:
        def pick_sam(home):
            return next(a for row in home.config.rows for a in row.apps if a.id == "person:sam")

        assert run_step(shipped_config, state, pick_sam, shown) is None
        assert shown[0][0] == "Who's playing?" and shown[0][1] == ["person:owner", "person:sam"]
        assert profiles.current_id() == "sam" and state["person_chosen"]
        # The next step is the home screen, with the Switch person tile.
        def pick_switch(home):
            return next(a for row in home.config.rows for a in row.apps if a.id == "people")

        assert run_step(shipped_config, state, pick_switch, shown) is None
        assert shown[1][0] == "Hearth" and "people" in shown[1][1]
        assert not state["person_chosen"]  # back to the picker next time
        assert session.read()["foreground"] is None
    finally:
        ui.run = real_run


def test_no_people_no_picker_no_switch_tile(shipped_config, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    args = argparse.Namespace(config=shipped_config, show_all=False)
    ids = [a.id for row in hub.home_config(args).rows for a in row.apps]
    assert "people" not in ids and not profiles.active()
    assert cfg.load(shipped_config, hide=False).app("people") is not None  # it's there, just hidden
