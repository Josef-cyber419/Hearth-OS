"""The Quick Menu comes back by itself if it dies, and doesn't leave the
home screen ignoring the controller or the game frozen."""

import sys
import time

from hearth import hub, session


def wait_for(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_crashed_quick_menu_restarts_while_on_the_home_screen(tmp_path, monkeypatch):
    monkeypatch.setattr(hub.OverlayProcess, "CHECK_SECONDS", 0.1)
    runs = tmp_path / "runs"
    overlay = hub.OverlayProcess(None)
    # A Quick Menu that crashes straight away (exit code 1), counting its starts.
    overlay.args = [sys.executable, "-c",
                    f"open({str(runs)!r}, 'a').write('x'); raise SystemExit(1)"]
    overlay.ensure()  # started once, by the hub, before the home screen
    # ...and nothing else calls ensure() while the home screen is up.
    try:
        assert wait_for(lambda: runs.exists() and len(runs.read_text()) >= 3)
    finally:
        overlay.stop()


def test_quick_menu_that_cant_run_here_is_not_restarted(tmp_path, monkeypatch):
    monkeypatch.setattr(hub.OverlayProcess, "CHECK_SECONDS", 0.1)
    runs = tmp_path / "runs"
    overlay = hub.OverlayProcess(None)
    overlay.args = [sys.executable, "-c", f"open({str(runs)!r}, 'a').write('x')"]  # exit 0: no gamescope
    overlay.ensure()
    try:
        time.sleep(0.6)
        assert runs.read_text() == "x"
    finally:
        overlay.stop()


def test_crash_while_open_unblocks_the_controller_and_the_game(monkeypatch):
    thawed = []
    monkeypatch.setattr(session, "thaw", lambda unit: thawed.append(unit) or True)
    session.update(lambda s: s.update(overlay_open=True, paused=True, focus="foreground",
                                      foreground={"id": "dolphin", "name": "Dolphin", "unit": "app-dolphin.scope"}))
    hub.recover_from_overlay_crash()
    state = session.read()
    assert not state["overlay_open"] and not state["paused"]
    assert thawed == ["app-dolphin.scope"]


def test_recovery_leaves_a_running_game_alone():
    thawed = []
    session.update(lambda s: s.update(overlay_open=False, paused=False,
                                      foreground={"id": "dolphin", "name": "Dolphin", "unit": "app-dolphin.scope"}))
    orig = session.thaw
    session.thaw = lambda unit: thawed.append(unit) or True
    try:
        hub.recover_from_overlay_crash()
    finally:
        session.thaw = orig
    assert thawed == []
