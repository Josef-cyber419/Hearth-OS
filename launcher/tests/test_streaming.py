"""Streaming websites as TV apps (hearth-web)."""

import os
import subprocess

from conftest import REPO
from hearth import config as cfg
from hearth.overlay import pointer_app_in_front

HEARTH_WEB = REPO / "image/system_files/usr/libexec/hearth/hearth-web"


def test_opens_the_site_full_screen_in_its_own_chrome(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "args"
    (bin_dir / "flatpak").write_text(f'#!/usr/bin/bash\nprintf "%s\\n" "$@" > {log}\n')
    (bin_dir / "flatpak").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    subprocess.run(["bash", str(HEARTH_WEB), "netflix", "https://www.netflix.com"], env=env, check=True)
    args = log.read_text().split("\n")
    profile = tmp_path / ".var/app/com.google.Chrome/hearth/netflix"
    assert args[:2] == ["run", "com.google.Chrome"]
    assert f"--user-data-dir={profile}" in args and profile.is_dir()
    assert "--kiosk" in args and "--ozone-platform=x11" in args
    assert args[-2] == "https://www.netflix.com"


def test_tiles_need_chrome(shipped_config, monkeypatch):
    config = cfg.load(shipped_config, hide=False)
    tiles = {a.id: a for row in config.rows for a in row.apps}
    for key in ("twitch", "netflix", "prime-video", "paramount-plus", "peacock"):
        assert tiles[key].pointer and tiles[key].command[0].endswith("hearth-web")
        assert tiles[key].missing()  # hidden until Chrome is installed (first boot installs it)
    assert "com.google.Chrome" in (REPO / "image/system_files/usr/share/hearth/flatpaks.list").read_text()


def test_controller_is_a_mouse_in_a_streaming_site():
    state = {"focus": "foreground", "foreground": {"id": "netflix", "pointer": True}, "background": {}}
    assert pointer_app_in_front(state)
    state["foreground"] = {"id": "kodi"}
    assert not pointer_app_in_front(state)
    state.update(focus="discord", background={"discord": {"pointer": True}})
    assert pointer_app_in_front(state)
    state.update(focus="home", foreground=None)
    assert not pointer_app_in_front(state)
