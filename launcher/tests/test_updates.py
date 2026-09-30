from fakes import FakeActions, FakePactl

from hearth import ctl, session, updates
from hearth.audio import Audio
from hearth.model import Nav
from hearth.quickmenu import Context, QuickMenu, build_tabs
from hearth.updates import parse_status

RPM_OSTREE = {
    "deployments": [
        {"staged": True, "booted": False, "version": "2026.09.26-abc1234", "timestamp": 1790000000},
        {"booted": True, "version": "2026.09.20-def5678",
         "container-image-reference": "ostree-unverified-registry:ghcr.io/me/hearth-os:latest"},
        {"booted": False, "version": "2026.09.13-0011223"},
    ]
}


def test_parse_status():
    s = parse_status(RPM_OSTREE)
    assert s.image == "ghcr.io/me/hearth-os:latest"
    assert s.booted == "2026.09.20-def5678" and s.staged == "2026.09.26-abc1234"
    assert s.rollback == "2026.09.13-0011223" and s.update_ready


def test_parse_status_without_versions_uses_dates():
    s = parse_status({"deployments": [{"booted": True, "timestamp": 1790000000}]})
    assert s.booted == "2026-09-21" and not s.update_ready and s.rollback is None


def system_tab(update):
    audio = Audio(FakePactl())
    state = {"foreground": None, "background": {}, "focus": "home", "update": update}
    menu = QuickMenu(build_tabs(Context(audio, audio.snapshot(), state, FakeActions())))
    menu.handle(Nav.TAB_PREV)
    return menu


def test_update_entry_states():
    def item(menu):
        return next(i for i in menu.current.items if i.key == "update")

    assert item(system_tab(None)).label == "Check for updates"
    assert item(system_tab({"status": "running"})).kind == "info"
    ready = system_tab({"status": "ready", "version": "2026.09.26"})
    assert item(ready).label == "Restart to finish update" and item(ready).confirm
    assert item(system_tab({"status": "failed"})).label.startswith("Update failed")


def test_check_for_updates_runs_action():
    menu = system_tab(None)
    while menu.selected.key != "update":
        menu.handle(Nav.DOWN)
    actions = menu.current.items[0].on_select.__self__
    menu.handle(Nav.SELECT)
    assert ("update",) in actions.calls


def test_enable_disable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    ctl.main(["disable"])
    assert ctl.disabled_flag().exists()
    ctl.main(["enable"])
    assert not ctl.disabled_flag().exists()


def test_dev_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert ctl.main(["dev", str(tmp_path)]) == 1  # not a checkout
    (tmp_path / "hearth").mkdir()
    (tmp_path / "hearth/__init__.py").touch()
    assert ctl.main(["dev", str(tmp_path)]) == 0
    assert ctl.dev_path_file().read_text() == str(tmp_path)
    ctl.main(["dev", "--off"])
    assert not ctl.dev_path_file().exists()


def test_requests_queue():
    ctl.main(["menu"])
    ctl.main(["home"])
    assert session.read()["requests"] == ["menu", "home"]


def test_channels():
    from hearth import updates

    live = "docker://ghcr.io/you/hearth-os:latest"
    assert updates.channel_of(live) == "live"
    assert updates.channel_of("ghcr.io/you/hearth-os:staging") == "staging"
    assert updates.channel_of("ghcr.io/you/hearth-os:abc123") == "abc123"
    assert updates.channel_of("localhost:5000/hearth-os") == "live"  # no tag means latest
    assert updates.channel_of(None) is None
    assert updates.channel_image(live, "staging") == "ghcr.io/you/hearth-os:staging"
    assert updates.channel_image("ghcr.io/you/hearth-os:staging", "live") == "ghcr.io/you/hearth-os:latest"


def test_channel_command(monkeypatch, capsys):
    from hearth import ctl, updates

    monkeypatch.setattr(updates, "os_status", lambda: updates.OsStatus(image="docker://ghcr.io/you/hearth-os:latest"))
    calls = []
    assert ctl.cmd_channel(None) == 0
    assert "Update channel: live" in capsys.readouterr().out
    assert ctl.cmd_channel("live", run=calls.append) == 0 and calls == []  # already there
    assert ctl.cmd_channel("staging", run=lambda cmd: calls.append(cmd) or 0) == 0
    assert calls == [["sudo", "bootc", "switch", "ghcr.io/you/hearth-os:staging"]]
    assert ctl.cmd_channel("staging", run=lambda cmd: 1) == 1  # the switch failed


def test_update_output_is_never_thrown_away(monkeypatch, tmp_path):
    """hearthctl update shows the updater's output; the menus log it."""
    import subprocess

    seen = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, stdout=None, stderr=None: (
        seen.append(stdout), subprocess.CompletedProcess(cmd, 1))[1])
    assert updates.run_helper("apply", show=True) is False
    assert seen[-1] is None  # straight to the terminal
    log = tmp_path / "hearth.log"
    updates.run_helper("apply", log)
    assert seen[-1].name == str(log)


def test_an_update_already_running_is_busy_not_failed(monkeypatch):
    import subprocess

    running = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0 if "uupd" in cmd else 1)  # noqa: E731
    assert updates.in_progress(run=running)
    assert not updates.in_progress(run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
    monkeypatch.setattr(updates, "in_progress", lambda: True)
    assert updates.apply() == "busy"  # never starts a second one
    monkeypatch.setattr(updates, "in_progress", lambda: False)
    for code, result in ((0, "ok"), (updates.BUSY, "busy"), (1, "failed")):
        monkeypatch.setattr(updates, "run_helper", lambda *a, c=code, **k: c)
        assert updates.apply() == result


def test_check_staged_says_running_while_it_downloads(monkeypatch):
    import time
    import types

    from hearth import overlay

    monkeypatch.setattr(updates, "os_status", lambda: updates.OsStatus())
    monkeypatch.setattr(updates, "in_progress", lambda: True)
    followed = []
    fake = types.SimpleNamespace(run_update=lambda: followed.append(1))
    overlay.Overlay.check_staged(fake)
    assert session.read()["update"] == {"status": "running"}  # not "current"
    for _ in range(50):
        if followed:
            break
        time.sleep(0.01)
    assert followed  # and it follows the download to the end


def fake_bin(tmp_path, pgrep_rc: int):
    import os

    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    for name, body in (("pgrep", f"exit {pgrep_rc}"), ("uupd", "echo uupd ran"), ("bootc", "echo bootc $*"),
                       ("flatpak", "echo flatpak $*")):
        (bin_ / name).write_text(f"#!/usr/bin/bash\n{body}\n")
        os.chmod(bin_ / name, 0o755)
    return {"PATH": f"{bin_}:/usr/bin:/bin"}


def test_update_script_refuses_a_second_run(tmp_path):
    import subprocess

    from conftest import REPO

    script = str(REPO / "image/system_files/usr/libexec/hearth/hearth-update")
    busy = subprocess.run([script, "apply"], env=fake_bin(tmp_path, 0), capture_output=True, text=True)
    assert busy.returncode == updates.BUSY and "already running" in busy.stderr
    ok = subprocess.run([script, "apply"], env=fake_bin(tmp_path, 1), capture_output=True, text=True)
    assert ok.returncode == 0 and "uupd ran" in ok.stdout


def test_esde_update_keeps_the_installed_one_when_offline(tmp_path):
    import os
    import subprocess

    from conftest import REPO

    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "curl").write_text("#!/usr/bin/bash\nexit 6\n")  # can't resolve host
    os.chmod(bin_ / "curl", 0o755)
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state")}
    script = str(REPO / "image/system_files/usr/libexec/hearth/hearth-esde-update")
    assert subprocess.run([script], env=env, capture_output=True).returncode == 1  # nothing installed yet
    app = tmp_path / "Applications/ES-DE.AppImage"
    app.parent.mkdir()
    app.write_text("")
    app.chmod(0o755)
    r = subprocess.run([script], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "keeping the installed one" in r.stderr
