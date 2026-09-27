"""Quick Resume: games paused in the background and brought back where they were.

Without systemd scopes (as here) Hearth pauses the app's process group with
SIGSTOP, so these tests use real processes."""

import sys
import time
from pathlib import Path

import pytest

from hearth import config as cfg
from hearth import hub, quickmenu, session



def game(app_id="g", name="Game", **options):
    command = (sys.executable, "-c", "import time\nfor _ in range(20): time.sleep(0.05)")
    return cfg.App(id=app_id, name=name, command=command, **options)


def config(**options):
    return cfg.Config(rows=(), **options)


class HoldOnce:
    """A Guide button held once, right after the app starts."""
    held = 0

    def __init__(self, on_home, *args, **options):
        self.on_home = on_home

    def start(self):
        if HoldOnce.held == 0:
            HoldOnce.held += 1
            self.on_home()

    def stop(self):
        pass


@pytest.fixture
def hold_once(monkeypatch):
    HoldOnce.held = 0
    monkeypatch.setattr(hub.homebutton, "Watcher", HoldOnce)
    yield
    for proc in hub.PROCS.values():
        proc.kill()
        proc.wait()
    hub.PROCS.clear()


def process_state(pid):
    return Path(f"/proc/{pid}/stat").read_text().split()[2]


def test_hold_guide_pauses_and_resume_carries_on(hold_once):
    c = config()
    assert hub.launch(game(), config=c) is None
    paused = session.read()["suspended"]
    assert [e["id"] for e in paused] == ["g"]
    assert session.read()["foreground"] is None and session.read()["focus"] == "home"
    pid = paused[0]["pid"]
    time.sleep(0.2)
    assert process_state(pid) == "T"  # stopped, not closed
    assert session.entry_alive(paused[0])

    row = hub.quick_resume_row(c)
    assert row.title == "Quick Resume" and row.apps[0].command == ("hearth:resume", "g")
    assert row.apps[0].platform.startswith("Paused")

    assert hub.resume("g", None, 1.5, c) is None  # runs to its end, no error
    assert session.read()["suspended"] == []
    assert hub.quick_resume_row(c) is None
    assert "g" not in hub.PROCS


def test_hold_guide_closes_when_set_to(hold_once):
    assert hub.launch(game(), config=config(guide_hold_action="close")) is None
    assert session.read()["suspended"] == []


def test_quick_resume_off_closes(hold_once):
    assert hub.launch(game(), config=config(quick_resume=0)) is None
    assert session.read()["suspended"] == []


def test_make_room_closes_the_oldest(hold_once):
    c = config(quick_resume=1)
    hub.launch(game("a", "Alpha"), config=c)
    HoldOnce.held = 0
    old = session.read()["suspended"][0]
    assert hub.eviction_question(game("b", "Beta"), c) == "THIS CLOSES PAUSED ALPHA"
    assert hub.eviction_question(game("a", "Alpha"), c) is None  # that one just resumes
    hub.make_room(c)
    assert session.read()["suspended"] == []
    assert not session.entry_alive(old)
    assert hub.eviction_question(game("b", "Beta"), c) is None


def test_steam_and_background_apps_arent_paused():
    c = config()
    assert hub.resumable(game(), c)
    assert not hub.resumable(game(tag_windows=False, home_button=False), c)  # Steam
    assert not hub.resumable(game(background=True), c)
    assert not hub.resumable(game(), config(quick_resume=0))
    assert not hub.resumable(game(), None)


def test_resume_of_a_game_that_closed_meanwhile():
    session.update(lambda s: s.__setitem__("suspended", [{"id": "x", "name": "X", "pid": 999999999}]))
    assert hub.resume("x", None, 1.5, config()) == "That game had already closed"
    assert session.read()["suspended"] == []


def test_settings_parse():
    c = cfg.parse({"rows": [], "home": {"quick_resume": 3}, "controllers": {"guide_hold": "close"}})
    assert c.quick_resume == 3 and c.guide_hold_action == "close"
    assert cfg.parse({"rows": []}).quick_resume == 2


def test_quick_menu_offers_quick_resume():
    class Acts:
        def __getattr__(self, name):
            return lambda *a: None

    def items(fg):
        ctx = quickmenu.Context(None, None, {"foreground": fg}, Acts())
        return [i.key for i in quickmenu._system_tab(ctx).items]

    assert "quick-resume" in items({"id": "g", "name": "Game", "resumable": True})
    assert "quick-resume" not in items({"id": "steam", "name": "Steam", "resumable": False})
