"""Twitch: VacuumStream, installed and kept up to date like ES-DE."""

import hashlib
import json
import os
import subprocess

import pytest

from conftest import REPO
from hearth import config as cfg
from hearth.overlay import pointer_app_in_front

LIBEXEC = REPO / "image/system_files/usr/libexec/hearth"


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

    def release(tag, image=b"\x7fELF twitch", sums=None):
        base = f"https://github.com/eliottness/VacuumStream/releases/download/{tag}"
        name = f"VacuumStream-{tag.lstrip('v')}-x86_64.AppImage"
        serve(f"{base}/{name}", image)
        digest = hashlib.sha256(image).hexdigest() if sums is None else sums
        serve(f"{base}/SHA256SUMS", f"{digest}  {name}\n".encode())
        serve("https://api.github.com/repos/eliottness/VacuumStream/releases/latest", json.dumps(
            {"tag_name": tag, "assets": [{"name": n, "browser_download_url": f"{base}/{n}"}
                                         for n in (name, "SHA256SUMS", "VacuumStream.flatpak")]}).encode())

    def run():
        return subprocess.run(["bash", str(LIBEXEC / "hearth-twitch-update")], capture_output=True, text=True,
                              env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home),
                                   "XDG_STATE_HOME": str(home / ".state")})

    return {"home": home, "release": release, "run": run}


def test_installs_and_updates(github):
    app = github["home"] / "Applications/VacuumStream.AppImage"
    github["release"]("v0.2.1")
    assert github["run"]().returncode == 0
    assert app.read_bytes() == b"\x7fELF twitch" and os.access(app, os.X_OK)
    assert "Installed" not in github["run"]().stdout  # already current
    github["release"]("v0.3.0", image=b"\x7fELF newer")
    github["run"]()
    assert app.read_bytes() == b"\x7fELF newer"


def test_rejects_a_download_that_fails_its_checksum(github):
    github["release"]("v0.2.1", sums="0" * 64)
    assert github["run"]().returncode != 0
    assert not (github["home"] / "Applications/VacuumStream.AppImage").exists()


def test_no_release_yet_is_not_an_error(github):
    assert github["run"]().returncode == 0


def test_twitch_tile_waits_for_the_app(shipped_config, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    twitch = cfg.load(shipped_config, hide=False).app("twitch")
    assert twitch.command == ("/usr/libexec/hearth/hearth-twitch",) and twitch.missing()
    (tmp_path / "Applications").mkdir()
    (tmp_path / "Applications/VacuumStream.AppImage").write_bytes(b"")
    assert twitch.available()
    assert "hearth-twitch-update.timer" in (REPO / "image/build.sh").read_text()


def test_controller_is_a_mouse_for_pointer_apps_in_front():
    state = {"focus": "foreground", "foreground": {"id": "browser", "pointer": True}, "background": {}}
    assert pointer_app_in_front(state)
    state["foreground"] = {"id": "kodi"}
    assert not pointer_app_in_front(state)
    state.update(focus="discord", background={"discord": {"pointer": True}})
    assert pointer_app_in_front(state)
    state.update(focus="home", foreground=None)
    assert not pointer_app_in_front(state)
