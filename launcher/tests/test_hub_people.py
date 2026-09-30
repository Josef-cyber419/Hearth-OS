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


def test_asks_again_after_the_pc_slept(shipped_config, two, monkeypatch):
    real_run = ui.run
    shown = []
    state = {"last_id": None, "message": None, "surface": None, "intro": "boot"}
    try:
        pick_owner = lambda home: next(a for r in home.config.rows for a in r.apps if a.id == "person:owner")  # noqa: E731
        run_step(shipped_config, state, pick_owner, shown)
        assert state["person_chosen"] and "slept_at_pick" in state
        # The PC sleeps while the home screen is up: its own poll sees it and
        # hands back an INTERRUPTED app...
        clock = {"slept": state["slept_at_pick"]}
        monkeypatch.setattr(session, "slept", lambda: clock["slept"])
        assert hub.ask_again(state) is None

        def home_interrupted(home):
            clock["slept"] += hub.WAKE_SECONDS + 1
            assert hub.ask_again(state) == "wake"
            return cfg.App(id=ui.INTERRUPTED, name="", command=(ui.INTERRUPTED,))

        run_step(shipped_config, state, home_interrupted, shown)
        assert shown[-1][0] == "Hearth" and not state["person_chosen"]
        # ...and the next step is "Who's playing?" again, with a fresh sleep reading.
        run_step(shipped_config, state, pick_owner, shown)
        assert shown[-1][0] == "Who's playing?" and state["person_chosen"]
        assert hub.ask_again(state) is None
        clock["slept"] += 5  # a nap shorter than WAKE_SECONDS doesn't count
        assert hub.ask_again(state) is None
        # Asleep while a game was in front: the check at the start of a step catches it.
        clock["slept"] += hub.WAKE_SECONDS
        run_step(shipped_config, state, pick_owner, shown)
        assert shown[-1][0] == "Who's playing?"
    finally:
        ui.run = real_run


def test_quick_menu_switch_request_brings_the_picker_back(shipped_config, two):
    real_run = ui.run
    shown = []
    state = {"last_id": None, "message": None, "surface": None, "intro": "boot"}
    try:
        pick_owner = lambda home: next(a for r in home.config.rows for a in r.apps if a.id == "person:owner")  # noqa: E731
        run_step(shipped_config, state, pick_owner, shown)
        session.update(lambda s: s.__setitem__("switch_request", True))  # Quick Menu → Switch person
        assert hub.ask_again(state) == "switch"
        run_step(shipped_config, state, pick_owner, shown)
        assert shown[-1][0] == "Who's playing?" and not session.read()["switch_request"]
    finally:
        ui.run = real_run


def test_the_home_screen_stops_when_interrupted(shipped_config, two):
    from hearth.model import Home

    surface = pygame.display.set_mode((640, 360))
    home = Home(cfg.load(shipped_config))
    app = ui.run(surface, home, "Hearth", max_frames=40, interrupt=lambda: "wake")
    assert app is not None and app.command == (ui.INTERRUPTED,)
    assert ui.run(surface, home, "Hearth", max_frames=10, interrupt=lambda: None) is None


def test_a_persons_own_livery_colours_their_home_screen(shipped_config, two, tmp_path):
    profiles.update("sam", livery="rosso")
    assert cfg.load(shipped_config).livery == "gulf"  # the owner: the household's
    profiles.switch("sam", tmp_path / "home")
    assert cfg.load(shipped_config).livery == "rosso"
    profiles.update("sam", livery="nonsense")
    assert cfg.load(shipped_config).livery == "gulf"  # an unknown one is ignored


def test_settings_people_page_offers_a_colour_scheme(shipped_config, two):
    from hearth import settings_app, style
    from hearth.settings_app import SettingsApp

    app = SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("people")
    app.person_edit = "sam"
    app.refresh()
    items = {i.key: i for i in app.menu.current.items}
    assert items["person-livery"].options[0] == "Household's" and items["person-livery"].value == 0
    items["person-livery"].on_change(list(style.LIVERIES).index("brg") + 1)
    assert profiles.get("sam").livery == "brg"
