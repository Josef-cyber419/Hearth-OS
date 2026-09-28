import sys

import pygame
import pytest

from hearth import config as cfg
from hearth import hub, ui
from hearth.model import Home, Nav


@pytest.fixture
def surface():
    pygame.display.init()
    pygame.font.init()
    yield pygame.display.set_mode((1920, 1080))
    pygame.quit()


def test_renders_shipped_config(surface, shipped_config):
    config = cfg.load(shipped_config)  # unfiltered: every tile drawn
    screen = ui.HomeScreen(surface, Home(config), config.title)
    for nav in [Nav.RIGHT] * 6 + [Nav.DOWN] * 3 + [Nav.LEFT]:
        screen.handle(nav)
        screen.draw()


def test_confirm_dialog(surface, shipped_config):
    config = cfg.load(shipped_config)
    home = Home(config)
    home.select_id("poweroff")
    screen = ui.HomeScreen(surface, home, config.title)
    assert screen.handle(Nav.SELECT) is None and screen.confirming.id == "poweroff"
    screen.draw()
    assert screen.handle(Nav.BACK) is None and screen.confirming is None
    screen.handle(Nav.SELECT)
    assert screen.handle(Nav.SELECT).id == "poweroff"


def test_menu_jumps_to_system_row(surface, shipped_config):
    config = cfg.load(shipped_config)
    screen = ui.HomeScreen(surface, Home(config), config.title)
    screen.handle(Nav.MENU)
    assert screen.home.config.rows[screen.home.row].title == "System"


def test_run_loop_returns_selected_app(surface, shipped_config):
    config = cfg.load(shipped_config)
    for key in (pygame.K_RIGHT, pygame.K_RETURN):
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key))
    app = ui.run(surface, Home(config), config.title, max_frames=10)
    assert app.id == config.rows[0].apps[1].id


def test_launch_reports_quick_failure():
    app = cfg.App(id="f", name="Fail", command=(sys.executable, "-c", "raise SystemExit(3)"))
    assert "exit code 3" in hub.launch(app)


def test_launch_reports_missing_program():
    app = cfg.App(id="m", name="Missing", command=("/nonexistent/program",))
    assert hub.launch(app).startswith("Couldn't start Missing")


def test_launch_success():
    app = cfg.App(id="ok", name="OK", command=(sys.executable, "-c", "pass"), home_button=False)
    assert hub.launch(app) is None


def test_home_button_closes_running_app(monkeypatch):
    class FiresImmediately:
        def __init__(self, on_home, *args, **options):
            self.on_home = on_home

        def start(self):
            self.on_home()

        def stop(self):
            pass

    monkeypatch.setattr(hub.homebutton, "Watcher", FiresImmediately)
    app = cfg.App(id="s", name="Sleepy", command=(sys.executable, "-c", "import time; time.sleep(30)"))
    assert hub.launch(app) is None  # closed quietly, no error shown


def test_launch_records_foreground_while_running(tmp_path):
    from hearth import session

    marker = tmp_path / "state-during-run"
    script = (
        "import json, os, pathlib;"
        f"p = pathlib.Path(os.environ['XDG_RUNTIME_DIR'], 'hearth', 'state.json');"
        f"pathlib.Path({str(marker)!r}).write_text(p.read_text())"
    )
    app = cfg.App(id="probe", name="Probe", command=(sys.executable, "-c", script), home_button=False)
    assert hub.launch(app) is None
    import json

    during = json.loads(marker.read_text())
    assert during["foreground"]["id"] == "probe" and during["focus"] == "foreground"
    assert session.read()["foreground"] is None and session.read()["focus"] == "home"


def test_pointer_at_the_bottom_or_top_scrolls_the_rows(surface, shipped_config):
    config = cfg.load(shipped_config)
    screen = ui.HomeScreen(surface, Home(config), config.title)
    rows = len(config.rows)
    assert rows >= 3
    screen._pointer, screen._pointer_at = (960, 1060), 100.0  # resting near the bottom
    screen.edge_scroll(100.0)
    screen.edge_scroll(100.0 + ui.EDGE_FIRST / 2)
    assert screen.home.row == 0  # not straight away
    t = 100.0 + ui.EDGE_FIRST
    screen.edge_scroll(t)
    assert screen.home.row == 1
    for _ in range(rows + 2):
        t += ui.EDGE_REPEAT
        screen.edge_scroll(t)
    assert screen.home.row == rows - 1  # stops at the last row

    screen._pointer, screen._pointer_at = (960, 20), t  # now near the top
    screen.edge_scroll(t)
    screen.edge_scroll(t + ui.EDGE_FIRST)
    assert screen.home.row == rows - 2

    screen._pointer = (960, 540)  # the middle: no scrolling
    before = screen.home.row
    for step in range(5):
        screen.edge_scroll(t + ui.EDGE_FIRST + step)
    assert screen.home.row == before


def test_edge_scroll_waits_for_dialogs_and_a_hidden_pointer(surface, shipped_config):
    config = cfg.load(shipped_config)
    screen = ui.HomeScreen(surface, Home(config), config.title)
    screen._pointer, screen._pointer_at = (960, 1060), 0.0
    t = ui.POINTER_SECONDS + 1  # pointer not moved for a while: hidden
    screen.edge_scroll(t)
    screen.edge_scroll(t + ui.EDGE_FIRST)
    assert screen.home.row == 0
    screen._pointer_at = 50.0
    screen.confirming = config.rows[0].apps[0]
    screen.edge_scroll(50.0)
    screen.edge_scroll(50.0 + ui.EDGE_FIRST)
    assert screen.home.row == 0
