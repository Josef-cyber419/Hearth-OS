"""Desktop Mode: holding Guide goes back to Hearth."""

import threading

from hearth import desktopguide, homebutton


class FakeWatcher:
    """Fires once the test says Guide was held."""
    started = []

    def __init__(self, on_fire, gesture, hold_seconds):
        assert gesture is homebutton.HomeButton  # hold, not tap
        self.on_fire, self.hold = on_fire, hold_seconds
        FakeWatcher.started.append(self)

    def start(self):
        pass

    def stop(self):
        pass

    def join(self, timeout=None):
        pass


def test_hold_guide_fires(monkeypatch):
    monkeypatch.setattr(desktopguide, "RESCAN_SECONDS", 0.05)
    FakeWatcher.started = []
    threading.Timer(0.2, lambda: FakeWatcher.started[-1].on_fire()).start()
    assert desktopguide.wait_for_hold(lambda: ["/dev/input/event3"], watcher=FakeWatcher, hold=2.0)
    assert FakeWatcher.started[0].hold == 2.0


def test_new_controllers_restart_the_watcher(monkeypatch):
    monkeypatch.setattr(desktopguide, "RESCAN_SECONDS", 0.05)
    FakeWatcher.started = []
    devices = [["/dev/input/event3"]]
    threading.Timer(0.2, lambda: devices.append(["/dev/input/event3", "/dev/input/event9"])).start()
    threading.Timer(0.6, lambda: FakeWatcher.started[-1].on_fire()).start()
    assert desktopguide.wait_for_hold(lambda: devices[-1], watcher=FakeWatcher)
    assert len(FakeWatcher.started) >= 2  # rescanned when the pad appeared


def test_stops_when_asked(monkeypatch):
    monkeypatch.setattr(desktopguide, "RESCAN_SECONDS", 0.05)
    stop = threading.Event()
    threading.Timer(0.2, stop.set).start()
    assert not desktopguide.wait_for_hold(lambda: [], watcher=FakeWatcher, stop=stop)


def test_does_nothing_in_game_mode(monkeypatch):
    monkeypatch.setenv("GAMESCOPE_WAYLAND_DISPLAY", "gamescope-0")
    called = []
    monkeypatch.setattr(desktopguide.subprocess, "call", lambda argv: called.append(argv))
    assert desktopguide.main() == 0 and not called


def test_goes_to_game_mode_on_hold(monkeypatch):
    monkeypatch.delenv("GAMESCOPE_WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(desktopguide, "wait_for_hold", lambda *a, **k: True)
    monkeypatch.setattr(homebutton, "evdev", type("FakeEvdev", (), {"list_devices": staticmethod(lambda: [])}))
    called = []
    monkeypatch.setattr(desktopguide.subprocess, "call", lambda argv: called.append(argv) or 0)
    assert desktopguide.main() == 0
    assert called == [[desktopguide.GAME_MODE]]
