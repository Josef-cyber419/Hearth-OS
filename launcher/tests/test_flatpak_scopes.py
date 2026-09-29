"""Flatpak apps move into a scope of their own; Hearth still pauses, closes
and keeps track of them (Discord stayed only a few seconds before)."""

import os

from hearth import session, wiimote


def fake_proc(tmp_path, procs):
    """procs: pid -> (parent, name, cgroup path)."""
    root = tmp_path / "proc"
    for pid, (parent, name, cgroup) in procs.items():
        d = root / str(pid)
        d.mkdir(parents=True)
        (d / "stat").write_text(f"{pid} ({name}) S {parent} 0 0\n")
        (d / "comm").write_text(name + "\n")
        (d / "cgroup").write_text(f"0::{cgroup}\n")
    return root


HEARTH = "/user.slice/user-1000.slice/user@1000.service/app.slice/hearth-bg-discord_1.scope"
FLATPAK = "/user.slice/user-1000.slice/user@1000.service/app.slice/app-flatpak-com.discordapp.Discord-4242.scope"


def test_app_units_include_the_flatpak_scope(tmp_path):
    proc = fake_proc(tmp_path, {100: (1, "flatpak", FLATPAK), 101: (100, "bwrap", FLATPAK),
                                102: (101, "Discord", FLATPAK), 200: (1, "other", "/elsewhere/app-flatpak-x-1.scope")})
    units = session.app_units("hearth-bg-discord_1.scope", 100, proc)
    assert units == ["hearth-bg-discord_1.scope", "app-flatpak-com.discordapp.Discord-4242.scope"]


def test_app_units_without_flatpak(tmp_path):
    proc = fake_proc(tmp_path, {100: (1, "kodi", HEARTH)})
    assert session.app_units("hearth-bg-discord_1.scope", 100, proc) == ["hearth-bg-discord_1.scope"]


def test_background_app_alive_after_its_scope_emptied(monkeypatch):
    monkeypatch.setattr(session, "is_active", lambda unit: False)  # Flatpak moved everything out
    assert session.background_alive({"unit": "hearth-bg-discord_1.scope", "pid": os.getpid()})
    assert not session.background_alive({"unit": "hearth-bg-discord_1.scope", "pid": 2 ** 22 + 7})


def test_pause_and_resume_reach_the_flatpak_scope(monkeypatch):
    calls = []
    monkeypatch.setattr(session, "app_units", lambda unit, pid, proc=None: [unit, "app-flatpak-x-1.scope"])
    monkeypatch.setattr(session, "freeze", lambda u: calls.append(("freeze", u)) or u.startswith("app-"))
    monkeypatch.setattr(session, "thaw", lambda u: calls.append(("thaw", u)) or True)
    info = {"unit": "hearth-app-kodi_1.scope", "pid": 5}
    assert session.pause_entry(info)  # Hearth's (empty, gone) scope fails; the app's works
    assert session.resume_entry(info)
    assert calls == [("freeze", "hearth-app-kodi_1.scope"), ("freeze", "app-flatpak-x-1.scope"),
                     ("thaw", "hearth-app-kodi_1.scope"), ("thaw", "app-flatpak-x-1.scope")]


def test_paused_dolphin_gives_the_wii_remotes_back(tmp_path):
    scope = "/user.slice/app.slice/app-flatpak-org.DolphinEmu.dolphin-emu-77.scope"
    proc = fake_proc(tmp_path, {77: (1, "dolphin-emu", scope)})
    cgroups = tmp_path / "cgroup"
    group = cgroups / scope.lstrip("/")
    group.mkdir(parents=True)
    (group / "cgroup.events").write_text("populated 1\nfrozen 0\n")
    assert wiimote.dolphin_running(proc, cgroups)  # playing: Dolphin has them
    (group / "cgroup.events").write_text("populated 1\nfrozen 1\n")
    assert not wiimote.dolphin_running(proc, cgroups)  # paused (Quick Resume): Hearth takes them back
    (group / "cgroup.events").write_text("populated 1\nfrozen 0\n")
    (group.parent / "cgroup.events").write_text("frozen 1\n")  # a parent frozen counts too
    assert not wiimote.dolphin_running(proc, cgroups)
