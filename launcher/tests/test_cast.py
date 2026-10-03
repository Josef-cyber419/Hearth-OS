"""Casting from a phone: the AirPlay and Spotify receivers, and what Hearth
does when a phone's picture arrives."""

import hashlib
import io
import json
import os
import subprocess
import tarfile

import pytest
from conftest import REPO
from fakes import FakeActions, FakePactl

from hearth import cast, ctl, fieldcheck, session, settings, settings_app
from hearth import config as cfg
from hearth.audio import Audio
from hearth.quickmenu import Context, build_tabs

LIBEXEC = REPO / "image/system_files/usr/libexec/hearth"


def test_settings_and_the_name_a_phone_sees(monkeypatch):
    c = cfg.parse({"cast": {"airplay": False, "spotify": True, "name": "Living room"}})
    assert (c.cast_airplay, c.cast_spotify, c.cast_name) == (False, True, "Living room")
    assert cast.device_name(c) == "Living room"
    monkeypatch.setattr(cast.socket, "gethostname", lambda: "den.lan")
    assert cast.device_name(cfg.parse({})) == "den"
    monkeypatch.setattr(cast.socket, "gethostname", lambda: "localhost")
    assert cast.device_name(cfg.parse({})) == "Hearth"


def test_receivers_need_their_programs(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("shutil.which", lambda name: None)
    by_id = {app.id: app for _, app, _ in cast.receivers(cfg.parse({"cast": {"name": "TV"}}))}
    assert by_id[cast.AIRPLAY].command == ("/usr/libexec/hearth/hearth-airplay", "TV")
    assert by_id[cast.AIRPLAY].missing() and by_id[cast.SPOTIFY].missing()
    (tmp_path / "Applications").mkdir()
    (tmp_path / "Applications/spotifyd").write_bytes(b"x")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uxplay" if name == "uxplay" else None)
    assert all(app.available() for _, app, _ in cast.receivers(cfg.parse({})))
    assert all(cast.is_receiver(i) for i in cast.RECEIVER_IDS) and not cast.is_receiver("discord")


@pytest.fixture
def receivers_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Applications").mkdir()
    (tmp_path / "Applications/spotifyd").write_bytes(b"x")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/uxplay" if name == "uxplay" else None)
    started, stopped = [], []

    def start_background(app):
        started.append(app)
        session.update(lambda s: s["background"].__setitem__(app.id, {"name": app.name, "pid": 4242}))

    monkeypatch.setattr(session, "start_background", start_background)
    monkeypatch.setattr(session, "stop_entry", lambda info: stopped.append(info))
    monkeypatch.setattr(session, "background_alive", lambda info: True)
    return started, stopped


def test_ensure_starts_what_is_on_and_stops_what_is_off(receivers_ready):
    started, stopped = receivers_ready
    cast.ensure(cfg.parse({"cast": {"name": "TV"}}))
    assert [a.id for a in started] == [cast.AIRPLAY, cast.SPOTIFY]
    state = session.read()
    assert state["background"][cast.AIRPLAY]["name_arg"] == "TV"
    cast.ensure(cfg.parse({"cast": {"name": "TV"}}))
    assert len(started) == 2  # already running: left alone
    cast.ensure(cfg.parse({"cast": {"name": "TV", "spotify": False}}))
    assert len(stopped) == 1 and cast.SPOTIFY not in session.read()["background"]
    cast.ensure(cfg.parse({"cast": {"name": "Den", "spotify": False}}))  # renamed: AirPlay restarts
    assert len(stopped) == 2 and started[-1].command[1] == "Den"


def test_a_phones_picture_takes_the_screen_and_gives_it_back():
    s = {"foreground": {"id": "kodi", "name": "Kodi"}, "focus": "foreground",
         "background": {cast.AIRPLAY: {"name": "AirPlay"}}, "cast": None}
    cast.take_screen(s, cast.AIRPLAY)
    assert s["focus"] == cast.AIRPLAY and s["cast"]["back"] == "foreground" and cast.on_screen(s) == "AirPlay"
    cast.give_back(s, cast.AIRPLAY)
    assert s["focus"] == "foreground" and s["cast"] is None
    cast.take_screen(s, cast.AIRPLAY)
    s["foreground"] = None  # Kodi closed meanwhile
    cast.give_back(s, cast.AIRPLAY)
    assert s["focus"] == "home"
    cast.take_screen(s, "cast:nothing")  # not a running receiver: nothing happens
    assert s["focus"] == "home" and s["cast"] is None
    cast.take_screen(s, cast.AIRPLAY)
    s["focus"] = "home"  # the person held Guide to leave the cast
    cast.give_back(s, cast.AIRPLAY)
    assert s["focus"] == "home"


def test_the_overlays_window_bookkeeping():
    w = cast.Watch()
    assert w.seen(10, "discord") is None
    assert w.seen(11, cast.AIRPLAY) == "take" and w.seen(11, cast.AIRPLAY) is None
    assert w.prune({11, 10}) == []
    assert w.prune({10}) == [cast.AIRPLAY] and w.windows == {}


def test_quick_menu_offers_to_stop_casting():
    pactl, actions = FakePactl(), FakeActions()
    audio = Audio(pactl)
    state = {"foreground": None, "focus": cast.AIRPLAY, "background": {cast.AIRPLAY: {"name": "AirPlay"}},
             "cast": {"id": cast.AIRPLAY, "name": "AirPlay", "back": "home"}}
    tabs = build_tabs(Context(audio, audio.snapshot(), state, actions, True, casting=cast.on_screen(state)))
    system = next(t for t in tabs if t.key == "system")
    item = next(i for i in system.items if i.key == "stop-cast")
    assert "AirPlay" in item.label
    item.on_select()
    assert ("stop_cast",) in actions.calls
    tabs = build_tabs(Context(audio, audio.snapshot(), {**state, "focus": "home"}, actions, True))
    assert not any(i.key == "stop-cast" for i in next(t for t in tabs if t.key == "system").items)


def test_stop_and_restart_drop_the_phone(receivers_ready):
    started, stopped = receivers_ready
    config = cfg.parse({})
    cast.ensure(config)
    session.update(lambda s: cast.take_screen(s, cast.AIRPLAY))
    assert session.read()["focus"] == cast.AIRPLAY
    cast.restart(cast.AIRPLAY, config)
    state = session.read()
    assert len(stopped) == 1 and state["focus"] == "home" and state["cast"] is None
    assert cast.AIRPLAY in state["background"] and started[-1].id == cast.AIRPLAY


def test_settings_page(shipped_config, receivers_ready):
    app = settings_app.SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("casting")
    app.refresh()
    items = {i.key: i for i in app.menu.current.items}
    assert items["cast-airplay"].value is True and "Starts with the home screen" in items["cast-airplay"].detail
    cast.ensure(cfg.load(shipped_config))
    app._load_cast()  # what load_for("casting") does in the background
    app.refresh()
    items = {i.key: i for i in app.menu.current.items}
    assert "Ready: look for" in items["cast-airplay"].detail
    items["cast-spotify"].on_change(False)
    assert cfg.load(shipped_config).cast_spotify is False and settings.load()["cast"] == {"spotify": False}
    items["cast-name"].on_select()
    assert app.keyboard is not None and app.keyboard.text == cast.device_name(cfg.load(shipped_config))
    app.keyboard.text = "  Lounge TV "
    done, app.keyboard = app._keyboard_done, None
    done("  Lounge TV ")
    assert cfg.load(shipped_config).cast_name == "Lounge TV"
    assert "cast-youtube" in items


def test_status_and_check(receivers_ready, capsys, monkeypatch):
    settings.put("cast", "name", "TV")
    cast.ensure(cfg.load())
    session.update(lambda s: cast.take_screen(s, cast.AIRPLAY))
    ctl.cmd_status()
    assert "Casting: AirPlay (on screen)" in capsys.readouterr().out
    monkeypatch.setattr(fieldcheck, "_run", lambda cmd, timeout=15: (0, "") if cmd[0] == "systemctl" or
                        cmd[-1] == "avdec_h264" else (1, ""))
    results = {r.name: r for r in fieldcheck.casting()}
    assert results["AirPlay receiver"].status == "ok" and '"TV"' in results["AirPlay receiver"].detail
    assert results["Spotify receiver"].status == "ok"
    assert results["AirPlay discovery (avahi)"].status == "ok" and results["AirPlay video decoder"].detail == "avdec_h264"
    session.update(lambda s: s["background"].clear())
    results = {r.name: r for r in fieldcheck.casting()}
    assert results["AirPlay receiver"].status == "warn"


# -- the spotifyd installer ---------------------------------------------------------


@pytest.fixture
def github(tmp_path):
    """A fake GitHub: curl serves files from tmp_path/served by URL."""
    served, bin_dir, home = tmp_path / "served", tmp_path / "bin", tmp_path / "home"
    for d in (served, bin_dir, home):
        d.mkdir()
    (bin_dir / "curl").write_text(
        '#!/usr/bin/bash\nout=; url=\nwhile (($#)); do case $1 in -o) out=$2; shift;; -H) shift;; -*) ;; '
        '*) url=$1;; esac; shift; done\n'
        f'f={served}/$(echo "$url" | tr "/:" "__")\n[[ -f $f ]] || exit 22\n'
        '[[ -n $out ]] && cp "$f" "$out" || cat "$f"\n')
    (bin_dir / "curl").chmod(0o755)

    def serve(url, data):
        (served / url.replace("/", "_").replace(":", "_")).write_bytes(data)

    def release(tag, binary=b"\x7fELF spotifyd", digest=None):
        base = f"https://github.com/Spotifyd/spotifyd/releases/download/{tag}"
        name = "spotifyd-linux-x86_64-full.tar.gz"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("spotifyd")
            info.size, info.mode = len(binary), 0o755
            tar.addfile(info, io.BytesIO(binary))
        data = buf.getvalue()
        serve(f"{base}/{name}", data)
        serve(f"{base}/{name}.sha512", f"{digest or hashlib.sha512(data).hexdigest()}  {name}\n".encode())
        serve("https://api.github.com/repos/Spotifyd/spotifyd/releases/latest", json.dumps(
            {"tag_name": tag, "assets": [{"name": n, "browser_download_url": f"{base}/{n}"}
                                         for n in (name, name + ".sha512", "spotifyd-macos-aarch64-default.tar.gz")]}
        ).encode())

    def run():
        return subprocess.run(["bash", str(LIBEXEC / "hearth-spotify-update")], capture_output=True, text=True,
                              env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home),
                                   "XDG_STATE_HOME": str(home / ".state")})

    return {"home": home, "release": release, "run": run}


def test_spotifyd_installs_and_updates(github):
    app = github["home"] / "Applications/spotifyd"
    github["release"]("v0.4.1")
    r = github["run"]()
    assert r.returncode == 0, r.stderr
    assert app.read_bytes() == b"\x7fELF spotifyd" and os.access(app, os.X_OK)
    assert "Installed" not in github["run"]().stdout  # already current
    github["release"]("v0.5.0", binary=b"\x7fELF newer")
    github["run"]()
    assert app.read_bytes() == b"\x7fELF newer"


def test_spotifyd_download_that_fails_its_checksum_is_refused(github):
    github["release"]("v0.4.1", digest="0" * 128)
    assert github["run"]().returncode != 0
    assert not (github["home"] / "Applications/spotifyd").exists()


def test_no_spotifyd_release_is_not_an_error(github):
    assert github["run"]().returncode == 0


def test_receiver_scripts_and_timer_are_in_the_image():
    assert (LIBEXEC / "hearth-airplay").read_text().startswith("#!/usr/bin/bash")
    assert "uxplay" in (REPO / "image/build.sh").read_text()
    assert "hearth-spotify-update.timer" in (REPO / "image/build.sh").read_text()
    assert (REPO / "image/system_files/usr/lib/systemd/user/hearth-spotify-update.timer").exists()
