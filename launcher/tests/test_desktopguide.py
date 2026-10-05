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


def test_the_two_shortcuts_land_on_the_desktop_once(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / ".config/user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Skrivbord"\n')
    source = tmp_path / "applications"
    source.mkdir()
    for name in desktopguide.DESKTOP_ICONS:
        (source / name).write_text(f"[Desktop Entry]\nName={name}\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(desktopguide.subprocess, "call", lambda *a, **k: 0)
    added = desktopguide.desktop_icons(source=source)
    assert [p.name for p in added] == list(desktopguide.DESKTOP_ICONS)
    assert all(p.parent == home / "Skrivbord" for p in added)
    assert all(p.stat().st_mode & 0o111 for p in added)  # executable: a launcher the desktop trusts
    (home / "Skrivbord/hearth-steam-gamemode.desktop").unlink()  # deleted on purpose...
    assert desktopguide.desktop_icons(source=source) == []  # ...stays deleted
    assert (home / ".config/hearth/desktop-icons").exists()


def test_shortcuts_already_there_from_skel_are_left_alone(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    (home / "Desktop/hearth-gamemode.desktop").write_text("mine")
    source = tmp_path / "applications"
    source.mkdir()
    for name in desktopguide.DESKTOP_ICONS:
        (source / name).write_text("shipped")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setattr(desktopguide.subprocess, "call", lambda *a, **k: 0)
    assert [p.name for p in desktopguide.desktop_icons(source=source)] == ["hearth-steam-gamemode.desktop"]
    assert (home / "Desktop/hearth-gamemode.desktop").read_text() == "mine"
    assert desktopguide.desktop_icons(source=tmp_path / "nowhere") == []  # no source: nothing, no error


def test_the_shipped_shortcuts_point_at_the_switch_script():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "image/system_files"
    hearth = (root / "usr/share/applications/hearth-gamemode.desktop").read_text()
    steam = (root / "usr/share/applications/hearth-steam-gamemode.desktop").read_text()
    assert "Exec=/usr/libexec/hearth/hearth-gamemode\n" in hearth and "Icon=hearth\n" in hearth
    assert "Exec=/usr/libexec/hearth/hearth-gamemode --steam\n" in steam and "Icon=steam\n" in steam
    assert (root / "usr/share/icons/hicolor/scalable/apps/hearth.svg").exists()
    script = (root / "usr/libexec/hearth/hearth-gamemode").read_text()
    assert "--steam" in script and "steam-once" in script
    for session in ("steam", "ogui-steam"):
        hook = (root / "etc/gamescope-session-plus/sessions.d" / session).read_text()
        assert "steam-once" in hook and 'CLIENTCMD="/usr/bin/hearth"' in hook


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
    monkeypatch.setattr(desktopguide, "desktop_icons", lambda: [])
    monkeypatch.delenv("GAMESCOPE_WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(desktopguide, "wait_for_hold", lambda *a, **k: True)
    monkeypatch.setattr(homebutton, "evdev", type("FakeEvdev", (), {"list_devices": staticmethod(lambda: [])}))
    called = []
    monkeypatch.setattr(desktopguide.subprocess, "call", lambda argv: called.append(argv) or 0)
    assert desktopguide.main() == 0
    assert called == [[desktopguide.GAME_MODE]]


def test_back_to_hearth_after_steams_switch_to_desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(desktopguide, "desktop_icons", lambda: [])
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.delenv("GAMESCOPE_WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(homebutton, "evdev", None)  # even without controller support
    called = []
    monkeypatch.setattr(desktopguide.subprocess, "call", lambda argv: called.append(argv) or 0)
    m = desktopguide.steam_marker()
    m.parent.mkdir(parents=True)
    m.touch()
    assert desktopguide.main() == 0
    assert called == [[desktopguide.GAME_MODE]]
    assert not m.exists()  # used up: can't loop
    assert desktopguide.main() == 0 and len(called) == 1


def test_a_stale_marker_is_ignored(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    m = desktopguide.steam_marker()
    m.parent.mkdir(parents=True)
    m.touch()
    old = m.stat().st_mtime - desktopguide.STEAM_MARKER_SECONDS - 5
    os.utime(m, (old, old))
    assert not desktopguide.came_from_steam()
    assert not m.exists()
    assert not desktopguide.came_from_steam()  # none: nothing to do
