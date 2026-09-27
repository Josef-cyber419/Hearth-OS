"""hearth-steam: Steam's "Switch to Desktop" inside Hearth returns home.

Runs the real scripts with fake steam, systemctl and sudo on PATH."""

import os
import shutil
import subprocess
import time

import pytest

from conftest import REPO

LIBEXEC = REPO / "image/system_files/usr/libexec/hearth"
DROPIN = "systemd/user/graphical-session.target.d/50-hearth-steam.conf"

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")


@pytest.fixture
def env(tmp_path):
    bin_dir, sddm, run = tmp_path / "bin", tmp_path / "sddm.conf.d", tmp_path / "run"
    for d in (bin_dir, sddm, run):
        d.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"

    def fake(name, body):
        (bin_dir / name).write_text(f"#!/usr/bin/bash\necho \"{name} $*\" >> {log}\n{body}\n")
        (bin_dir / name).chmod(0o755)

    # Steam runs until "steam -shutdown" is called.
    fake("steam", f'if [[ $1 == -shutdown ]]; then touch {tmp_path}/quit; exit 0; fi\n'
                  f'while [[ ! -e {tmp_path}/quit ]]; do sleep 0.1; done')
    fake("systemctl", "exit 0")
    # sudo runs the helper (as us), with the test's sddm dir.
    helper = LIBEXEC / "hearth-session"
    fake("sudo", f'[[ $1 == -n ]] && shift\n[[ $1 == /usr/libexec/hearth/hearth-session ]] && shift && exec {helper} "$@"\nexit 1')
    return {"tmp": tmp_path, "sddm": sddm, "run": run, "log": log,
            "env": {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "XDG_RUNTIME_DIR": str(run),
                    "HEARTH_SDDM_DIR": str(sddm)}}


def start(env) -> subprocess.Popen:
    return subprocess.Popen(["bash", str(LIBEXEC / "hearth-steam")], env=env["env"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def wait_for(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_switch_to_desktop_returns_home(env):
    proc = start(env)
    dropin = env["run"] / DROPIN
    assert wait_for(dropin.exists)
    assert "RefuseManualStop=yes" in dropin.read_text()  # Steam's logout will be refused
    time.sleep(0.3)
    assert proc.poll() is None  # Steam is running

    # Steam asks SteamOS Manager for the desktop: it writes a one-time login.
    (env["sddm"] / "zzt-steamos-temp-login.conf").write_text("[Autologin]\nSession=plasma.desktop\n")
    proc.wait(timeout=10)

    assert not (env["sddm"] / "zzt-steamos-temp-login.conf").exists()  # no KDE at next login
    assert not dropin.exists()  # logouts work normally again
    calls = env["log"].read_text()
    assert "steam -shutdown" in calls and "systemctl --user daemon-reload" in calls


def test_steam_exiting_normally_cleans_up(env):
    proc = start(env)
    dropin = env["run"] / DROPIN
    assert wait_for(dropin.exists)
    (env["tmp"] / "quit").touch()
    proc.wait(timeout=10)
    assert not dropin.exists()


def test_a_game_mode_login_is_left_alone(env):
    game = env["sddm"] / "zzt-steamos-temp-login.conf"
    game.write_text("[Autologin]\nSession=gamescope-wayland.desktop\n")
    proc = start(env)
    assert wait_for((env["run"] / DROPIN).exists)
    time.sleep(1.2)
    assert proc.poll() is None and game.exists()  # not a desktop request
    (env["tmp"] / "quit").touch()
    proc.wait(timeout=10)


def test_stale_desktop_login_is_cleared_without_closing_steam(env):
    (env["sddm"] / "zzt-steamos-temp-login.conf").write_text("[Autologin]\nSession=plasma\n")
    proc = start(env)
    assert wait_for(lambda: not (env["sddm"] / "zzt-steamos-temp-login.conf").exists())
    time.sleep(1.2)
    assert proc.poll() is None  # Steam keeps running
    (env["tmp"] / "quit").touch()
    proc.wait(timeout=10)


def test_helper_only_removes_a_desktop_login(tmp_path):
    temp = tmp_path / "zzt-steamos-temp-login.conf"
    run = lambda *a: subprocess.run(["bash", str(LIBEXEC / "hearth-session"), *a],  # noqa: E731
                                    env={**os.environ, "HEARTH_SDDM_DIR": str(tmp_path)})
    temp.write_text("[Autologin]\nSession=gamescope-wayland.desktop\n")
    assert run("clear-desktop-login").returncode == 0 and temp.exists()
    temp.write_text("[Autologin]\nSession=plasma.desktop\n")
    assert run("clear-desktop-login").returncode == 0 and not temp.exists()
    assert run("anything-else").returncode == 2


def test_desktop_tile_clears_a_leftover_dropin(env):
    dropin = env["run"] / DROPIN
    dropin.parent.mkdir(parents=True)
    dropin.write_text("[Unit]\nRefuseManualStop=yes\n")
    fake_bin = env["tmp"] / "bin"
    (fake_bin / "steamosctl").write_text(f'#!/usr/bin/bash\necho "steamosctl $*" >> {env["log"]}\n')
    (fake_bin / "steamosctl").chmod(0o755)
    script = (LIBEXEC / "hearth-desktop").read_text().replace(
        "/usr/libexec/os-session-select /usr/bin/steamos-session-select", "/nonexistent")
    (env["tmp"] / "desktop").write_text(script)
    subprocess.run(["bash", str(env["tmp"] / "desktop")], env=env["env"], check=True)
    assert not dropin.exists()
    assert "steamosctl switch-to-desktop-mode" in env["log"].read_text()
