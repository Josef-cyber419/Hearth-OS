"""hearth-flatpak-setup: installs every app in both lists, by its bare ID."""

import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO

SCRIPT = REPO / "image/system_files/usr/libexec/hearth/hearth-flatpak-setup"
LISTS = REPO / "image/system_files/usr/share/hearth"

pytestmark = pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")


def run_setup(tmp_path: Path, fail: str = "") -> tuple[list[str], str]:
    """Run the script with its paths moved into tmp_path and a fake flatpak."""
    share = tmp_path / "share"
    shutil.copytree(LISTS, share, dirs_exist_ok=True)
    script = SCRIPT.read_text().replace("/usr/share/hearth", str(share)).replace(
        "/var/lib/hearth", str(tmp_path / "state"))
    (tmp_path / "setup").write_text(script)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "flatpak.log"
    log.write_text("")
    (bin_dir / "flatpak").write_text(
        f'#!/usr/bin/bash\necho "$*" >> {log}\n'
        f'[[ $1 == install && -n "{fail}" && "${{@: -1}}" == "{fail}" ]] && exit 1\nexit 0\n')
    (bin_dir / "flatpak").chmod(0o755)
    subprocess.run(["bash", str(tmp_path / "setup")], check=True, capture_output=True,
                   env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path)})
    return log.read_text().splitlines(), (tmp_path / "state/flatpaks-attempted").read_text()


def listed(name: str) -> list[str]:
    return [line.strip() for line in (LISTS / name).read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")]


def test_installs_every_app_by_bare_id(tmp_path):
    calls, done = run_setup(tmp_path)
    installed = [c.split()[-1] for c in calls if c.startswith("install")]
    assert installed == listed("flatpaks.list") + listed("emulators.list")
    assert all(":" not in app and "/" not in app for app in installed)
    assert done.split() == installed


def test_emulators_get_access_to_games_and_other_drives(tmp_path):
    calls, _ = run_setup(tmp_path)
    overrides = [c for c in calls if c.startswith("override")]
    emulators = listed("emulators.list")
    assert [c.split()[-1] for c in overrides[:len(emulators)]] == emulators
    assert all("--filesystem=/var/mnt" in c and "--filesystem=~/ROMs" in c for c in overrides[:len(emulators)])
    # Game launchers install games, onto other drives too (not given the ROMs).
    launchers = overrides[len(emulators):]
    assert [c.split()[-1] for c in launchers] == ["com.heroicgameslauncher.hgl", "net.lutris.Lutris"]
    assert all("--filesystem=/var/mnt" in c and "ROMs" not in c for c in launchers)


def test_a_failed_install_is_retried_next_time(tmp_path):
    _, done = run_setup(tmp_path, fail="net.rpcs3.RPCS3")
    assert "net.rpcs3.RPCS3" not in done.split() and "net.pcsx2.PCSX2" in done.split()
    calls, done = run_setup(tmp_path)  # next boot: only the one that failed
    assert [c.split()[-1] for c in calls if c.startswith("install")] == ["net.rpcs3.RPCS3"]
    assert "net.rpcs3.RPCS3" in done.split()
