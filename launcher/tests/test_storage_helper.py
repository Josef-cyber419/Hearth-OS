"""hearth-storage, the root helper behind Settings → Storage, on a real (loop)
disk: format, mount at every boot, keep files, release, and never touch the
system's drive. Needs root, loop devices and sfdisk, so it's skipped
elsewhere (CI); the argument checks run everywhere."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).parents[2] / "image/system_files/usr/libexec/hearth/hearth-storage"


def run(*args, env=None):
    return subprocess.run([str(args[0]), *map(str, args[1:])], capture_output=True, text=True, env=env)


def test_refuses_bad_arguments_before_touching_anything():
    assert run(HELPER).returncode == 2
    assert run(HELPER, "format", "/dev/sdz").returncode == 2
    bad = run(HELPER, "format", "/dev/sdz", "no spaces!")
    assert bad.returncode == 1 and "Not a usable name" in bad.stderr
    assert "Not a drive" in run(HELPER, "format", "/dev/sda1", "games").stderr  # a partition, not a disk
    assert "Not a drive" in run(HELPER, "use", "/dev/sda", "games").stderr  # a disk, not a partition
    assert "Not a drive" in run(HELPER, "use", "/dev/mapper/root", "games").stderr
    assert "Not a drive" in run(HELPER, "release", "../etc/passwd").stderr


def _can_loop() -> bool:
    return (os.geteuid() == 0 and shutil.which("losetup") and shutil.which("sfdisk")
            and shutil.which("mkfs.ext4") and Path("/dev/loop-control").exists())


@pytest.fixture
def disk(tmp_path):
    if not _can_loop():
        pytest.skip("needs root, loop devices and sfdisk")
    image = tmp_path / "disk.img"
    image.write_bytes(b"")
    os.truncate(image, 64 * 1024 * 1024)
    dev = subprocess.run(["losetup", "-fP", "--show", str(image)], capture_output=True, text=True)
    if dev.returncode:
        pytest.skip(f"losetup: {dev.stderr.strip()}")
    dev = dev.stdout.strip()
    # The helper, allowed to use this loop disk (the real one only takes real drives).
    helper = tmp_path / "helper"
    text = HELPER.read_text()
    text = re.sub(r"^DISK_RE=.*$", f"DISK_RE='^{dev}$'", text, flags=re.M)
    text = re.sub(r"^PART_RE=.*$", f"PART_RE='^{dev}p[0-9]+$'", text, flags=re.M)
    helper.write_text(text)
    helper.chmod(0o755)
    # No udev in a container: make the partition's device node the way udev would.
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    name = Path(dev).name
    (bin_ / "udevadm").write_text(f"""#!/bin/sh
partx -u {dev} 2>/dev/null
for b in /sys/class/block/{name}p*; do
  [ -e "$b" ] || continue
  n=/dev/$(basename $b); [ -b $n ] || mknod $n b $(cut -d: -f1 $b/dev) $(cut -d: -f2 $b/dev)
done
""")
    (bin_ / "systemctl").write_text("#!/bin/sh\nexit 0\n")
    for f in bin_.iterdir():
        f.chmod(0o755)
    (tmp_path / "mnt").mkdir()
    (tmp_path / "fstab").write_text("# the system's own entries\n")
    env = dict(os.environ, PATH=f"{bin_}:{os.environ['PATH']}", HEARTH_FSTAB=str(tmp_path / "fstab"),
               HEARTH_MNT=str(tmp_path / "mnt"), SUDO_USER="nobody")
    yield dev, helper, env, tmp_path
    subprocess.run(["umount", "-R", str(tmp_path / "mnt/games")], capture_output=True)
    subprocess.run(["losetup", "-d", dev], capture_output=True)


def test_format_use_release(disk):
    dev, helper, env, tmp = disk
    games, fstab = tmp / "mnt/games", tmp / "fstab"
    r = run(helper, "format", dev, "games", env=env)
    assert r.returncode == 0, r.stderr
    assert subprocess.run(["findmnt", "-n", str(games)], capture_output=True).returncode == 0
    assert games.stat().st_uid == 65534  # the top folder is the user's
    lines = fstab.read_text().splitlines()
    assert lines[0] == "# the system's own entries"
    assert re.fullmatch(rf"UUID=\S+ {games} ext4 defaults,nofail,x-systemd.device-timeout=10s,x-hearth 0 0",
                        lines[1])
    (games / "kept.txt").write_text("hello")

    assert run(helper, "use", f"{dev}p1", "games", env=env).returncode == 0  # again: fine, one entry
    assert fstab.read_text().count("x-hearth") == 1

    r = run(helper, "release", f"{dev}p1", env=env)
    assert r.returncode == 0, r.stderr
    assert fstab.read_text() == "# the system's own entries\n"
    assert not games.exists()

    r = run(helper, "use", f"{dev}p1", "games", env=env)  # keeps what's on it
    assert r.returncode == 0, r.stderr
    assert (games / "kept.txt").read_text() == "hello"


def test_never_the_system_drive(disk):
    dev, helper, env, tmp = disk
    assert run(helper, "format", dev, "games", env=env).returncode == 0
    (tmp / "mnt/games/kept.txt").write_text("hello")
    fake = tmp / "sysbin"
    fake.mkdir()
    (fake / "findmnt").write_text(f"""#!/bin/sh
case "$*" in *"--mountpoint /sysroot"*) echo {dev}p1;; *"--mountpoint "*) exit 1;; *) exec {shutil.which('findmnt')} "$@";; esac
""")
    (fake / "findmnt").chmod(0o755)
    system = dict(env, PATH=f"{fake}:{env['PATH']}")
    for args in (("format", dev, "games"), ("use", f"{dev}p1", "other"), ("release", f"{dev}p1")):
        r = run(helper, *args, env=system)
        assert r.returncode == 1 and "the system runs from" in r.stderr
    assert (tmp / "mnt/games/kept.txt").read_text() == "hello"


def test_in_use_elsewhere_is_left_alone(disk):
    dev, helper, env, tmp = disk
    assert run(helper, "format", dev, "games", env=env).returncode == 0
    assert run(helper, "release", f"{dev}p1", env=env).returncode == 0
    other = tmp / "somewhere else"
    other.mkdir()
    subprocess.run(["mount", f"{dev}p1", str(other)], check=True)
    try:
        r = run(helper, "format", dev, "games", env=env)
        assert r.returncode == 1 and "in use at" in r.stderr and str(other) in r.stderr
    finally:
        subprocess.run(["umount", str(other)])
