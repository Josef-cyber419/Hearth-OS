"""hearthctl check (every safe check at once) and hearthctl press (buttons
to the TV over SSH)."""

import os

from hearth import drive, events, fieldcheck, gamescope


def test_one_broken_check_never_hides_the_rest():
    def boom():
        raise RuntimeError("no sensors")

    results = fieldcheck.run([("Temperatures", boom), ("Fine", lambda: [fieldcheck.Result("x", "ok", "good")])])
    text = fieldcheck.markdown(results)
    assert "check crashed: RuntimeError: no sensors" in text and "**x**: good" in text
    assert "1 failed, 0 to look at, 1 fine." in text
    assert "## Needs attention" in text


def test_failed_services_come_with_their_log(monkeypatch):
    def run(cmd, timeout=15):
        if cmd[:2] == ["systemctl", "--failed"]:
            return 0, ""
        if cmd[:3] == ["systemctl", "--user", "--failed"]:
            return 0, "hearth-esde-update.service loaded failed failed Update ES-DE"
        return 0, "2026-09-29T21:48:03 hearth-esde-update: couldn't reach gitlab.com"

    monkeypatch.setattr(fieldcheck, "_run", run)
    system, user = fieldcheck.failed_units()
    assert system.status == "ok"
    assert user.status == "fail" and user.detail == "hearth-esde-update.service"
    assert any("couldn't reach gitlab.com" in line for line in user.evidence)


def test_systemd_unreachable_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(fieldcheck, "_run", lambda cmd, timeout=15: (
        1, "System has not been booted with systemd as init system (PID 1). Can't operate.\nFailed to connect"))
    assert all(r.status == "info" and "\n" not in r.detail for r in fieldcheck.failed_units())


def test_apps_that_never_showed_a_window_are_caught():
    events.record("app_start", id="game:pc:Dusk.AppImage")
    events.record("app_exit", id="game:pc:Dusk.AppImage", code=0)
    events.record("app_start", id="kodi")
    events.record("app_window", id="kodi", seconds=3.1)
    events.record("app_start", id="steam")
    events.record("app_window", id="steam", seconds=22.0)
    results = {r.name: r for r in fieldcheck.app_history()}
    missing = results["Apps that never showed a window"]
    assert missing.status == "fail" and "Dusk" in missing.evidence[0] and len(missing.evidence) == 1
    assert "steam" in results["Slow to appear (over 15 s)"].evidence[0]


def test_saved_report(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    path = fieldcheck.save("# report")
    assert path.parent == tmp_path / "hearth/checks" and path.read_text() == "# report"


def test_over_ssh_the_display_comes_from_the_home_screen(tmp_path, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    proc = tmp_path / "proc"
    for pid, cmd, env in (("10", b"/usr/bin/bash\0", b"DISPLAY=:9\0"),
                          ("20", b"/usr/bin/python3\0-m\0hearth\0", b"DISPLAY=:1\0XAUTHORITY=/run/x\0HOME=/h\0"),
                          ("self", b"", b"")):
        d = proc / pid
        d.mkdir(parents=True)
        (d / "cmdline").write_bytes(cmd)
        (d / "environ").write_bytes(env)
    assert gamescope.adopt_session_display(proc=proc, uid=os.getuid())
    assert os.environ["DISPLAY"] == ":1" and os.environ["XAUTHORITY"] == "/run/x"
    monkeypatch.delenv("DISPLAY")
    (tmp_path / "no-hearth").mkdir()
    assert not gamescope.adopt_session_display(proc=tmp_path / "no-hearth", uid=os.getuid())


def test_press_names_the_buttons_it_knows():
    problems = drive.press(["up", "jump"])
    assert problems and "unknown button 'jump'" in problems[0] and "guide" in problems[0]
