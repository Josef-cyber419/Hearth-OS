import tarfile

import pytest
from fakes import FakeActions, FakePactl

from hearth import ctl, events, report
from hearth.audio import Audio
from hearth.quickmenu import Context, QuickMenu, build_tabs


def test_events_record_and_read():
    events.set_role("hub")
    events.record("app_start", id="kodi")
    events.record("app_exit", id="kodi", ended="exited", code=0, seconds=12.5)
    got = events.read()
    assert [e["event"] for e in got] == ["app_start", "app_exit"]
    assert got[1]["seconds"] == 12.5 and got[0]["by"] == "hub"
    assert "app_exit" in events.describe(got[1]) and "seconds=12.5" in events.describe(got[1])


def test_events_rotate(monkeypatch):
    monkeypatch.setattr(events, "MAX_BYTES", 500)
    for i in range(40):
        events.record("tick", i=i)
    assert events.path().with_name("events.jsonl.1").exists()
    assert events.path().stat().st_size <= 600
    assert events.read()[-1]["i"] == 39  # read spans both files, oldest first


def test_events_never_raise(monkeypatch, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("")
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))  # not a directory
    events.record("x")
    assert events.read() == []


def test_frame_stats():
    stats = events.FrameStats()
    assert stats.summary() is None
    stats.times = [16.7] * 95 + [50.0] * 5
    s = stats.summary()
    assert s["frames"] == 100 and s["hitches"] == 5 and s["worst_ms"] == 50.0
    assert 50 < s["fps"] < 60


def test_redaction(monkeypatch):
    monkeypatch.setattr(report.getpass, "getuser", lambda: "josef")
    monkeypatch.setattr(report.socket, "gethostname", lambda: "livingroom-pc")
    text = ("/home/josef/.config on livingroom-pc; controller AA:BB:CC:11:22:33; "
            "inet 192.168.1.20 and 127.0.0.1; fe80::1a2b:3c4d:5e6f:7a8b\nU: Uniq=xyz123\n"
            'device.serial = "Elgato_4K_X_A1B2C3"\nusb 1-2: SerialNumber: 0123ABCD\n')
    out = report.Redactor()(text)
    for secret in ("josef", "livingroom-pc", "AA:BB:CC", "192.168.1.20", "fe80::", "xyz123", "A1B2C3", "0123ABCD"):
        assert secret not in out
    assert "127.0.0.1" in out and "<user>" in out and "<mac>" in out


def test_report_bundle(tmp_path, monkeypatch):
    events.record("app_exit", id="steam", ended="failed", code=1, seconds=0.8)
    monkeypatch.setattr(report, "gpu_samples", lambda: "t=0.0s card0 busy=3%\n")
    monkeypatch.setattr(report, "doctor_text", lambda: "✓ Game Mode: starts Hearth\n")

    def fake_run(argv):
        if argv[0] == "lspci":
            return ("03:00.0 VGA compatible controller [0300]: AMD Navi 22 [Radeon RX 6750 XT] [1002:73df]\n"
                    "\tKernel driver in use: amdgpu\n")
        if argv[0] == "lscpu":
            return "Model name:            Intel(R) Core(TM) i7-4790K CPU @ 4.00GHz\n"
        return f"output of {' '.join(argv)} from 10.0.0.5\n"

    texts, blobs = report.collect(runner=fake_run)
    path = report.write(texts, blobs, tmp_path / "reports")
    with tarfile.open(path) as tar:
        names = tar.getnames()
        folder = names[0].split("/")[0]
        summary = tar.extractfile(f"{folder}/SUMMARY.txt").read().decode()
        pci = tar.extractfile(f"{folder}/hardware/pci.txt").read().decode()
        journal = tar.extractfile(f"{folder}/logs/journal-session.txt").read().decode()
    assert f"{folder}/hearth/events.jsonl" in names
    assert "RX 6750 XT" in summary and "amdgpu" in summary and "i7-4790K" in summary
    assert "ended=failed" in summary  # recent failures are on the first page
    assert "Game Mode: starts Hearth" in summary
    assert "10.0.0.5" not in journal and "RX 6750 XT" in pci


def test_old_reports_are_pruned(tmp_path):
    out = tmp_path / "reports"
    out.mkdir()
    for i in range(12):
        (out / f"hearth-report-2020010{i:02d}-000000.tar.gz").write_text("")
    report.write({"a.txt": "x"}, {}, out)
    assert len(list(out.glob("hearth-report-*.tar.gz"))) == report.KEEP


def test_hearthctl_events(capsys):
    assert ctl.main(["events"]) == 1
    events.record("menu_open", over="game")
    assert ctl.main(["events", "-n", "5"]) == 0
    assert "menu_open" in capsys.readouterr().out


def test_quick_menu_report_item():
    pactl, actions = FakePactl(), FakeActions()
    audio = Audio(pactl)

    def menu(report_state):
        state = {"foreground": None, "background": {}, "focus": "home", "report": report_state}
        m = QuickMenu(build_tabs(Context(audio, audio.snapshot(), state, actions, True)))
        system = next(t for t in m.tabs if t.key == "system")
        return next(i for i in system.items if i.key == "report")

    item = menu(None)
    assert item.kind == "action" and item.on_select() == "close" and actions.calls[-1] == ("report",)
    assert menu({"status": "running"}).kind == "info"
    assert "hearth-report-1.tar.gz" in menu({"status": "done", "file": "hearth-report-1.tar.gz"}).detail


@pytest.mark.parametrize("argv", [["uname", "-a"], ["definitely-not-a-command-xyz"]])
def test_run_never_raises(argv):
    assert isinstance(report.run(argv), str)


def test_redaction_keeps_times_and_loopback():
    text = "Sep 25 20:50:12 started; listening on ::1 and [::]; took 00:01:02"
    assert report.Redactor()(text) == text
