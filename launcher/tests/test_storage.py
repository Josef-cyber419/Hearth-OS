"""Settings → Storage: finding added drives, and putting Steam games and ROMs on them."""

import json
import os
from pathlib import Path

import pytest

from hearth import library, storage

GB = 1_000_000_000


def lsblk(fstab_uuid="1111-aaaa"):
    """The PC: the system NVMe, a 256 GB SATA SSD from Windows, a USB stick
    Hearth set up, a card reader, zram."""
    return json.dumps({"blockdevices": [
        {"path": "/dev/nvme0n1", "type": "disk", "size": 1000 * GB, "model": "WD_BLACK SN770 1TB", "tran": "nvme",
         "rm": False, "ro": False, "children": [
             {"path": "/dev/nvme0n1p1", "type": "part", "size": 1 * GB, "fstype": "vfat",
              "mountpoints": ["/boot/efi"]},
             {"path": "/dev/nvme0n1p2", "type": "part", "size": 999 * GB, "fstype": "btrfs",
              "mountpoints": ["/sysroot", "/var", "/var/home"]}]},
        {"path": "/dev/sda", "type": "disk", "size": 256 * GB, "model": "Samsung SSD 870 EVO 250GB ",
         "tran": "sata", "rm": False, "ro": False, "children": [
             {"path": "/dev/sda1", "type": "part", "size": 16 * 1024 * 1024, "fstype": None, "mountpoints": [None]},
             {"path": "/dev/sda2", "type": "part", "size": 255 * GB, "fstype": "ntfs", "label": "Games",
              "uuid": "ABCD", "mountpoints": [None]}]},
        {"path": "/dev/sdb", "type": "disk", "size": 64 * GB, "model": "SanDisk Ultra", "tran": "usb", "rm": True,
         "ro": False, "children": [
             {"path": "/dev/sdb1", "type": "part", "size": 64 * GB, "fstype": "ext4", "label": "stick",
              "uuid": fstab_uuid, "mountpoints": ["/var/mnt/stick"]}]},
        {"path": "/dev/sdc", "type": "disk", "size": 2 * GB, "model": "Card Reader", "tran": "usb", "rm": True,
         "ro": False},
        {"path": "/dev/zram0", "type": "disk", "size": 8 * GB, "mountpoints": ["[SWAP]"]},
    ]})


@pytest.fixture
def fstab(tmp_path):
    f = tmp_path / "fstab"
    f.write_text("UUID=system / btrfs defaults 0 0\n"
                 "UUID=1111-aaaa /var/mnt/stick ext4 defaults,nofail,x-systemd.device-timeout=10s,x-hearth 0 0\n")
    return f


def test_finds_added_drives_not_the_system(fstab):
    found = storage.drives(lambda args: lsblk(), fstab)
    assert [d.path for d in found] == ["/dev/sda", "/dev/sdb"]  # no system drive, card reader or zram
    ssd, stick = found
    assert ssd.name == "Samsung SSD 870 EVO 250GB (256 GB)"
    assert ssd.usable_part is None  # NTFS: needs setting up (erasing) for Steam on Linux
    assert ssd.contents == "Games (255 GB)"  # not Windows' tiny hidden partition
    assert ssd.mounted_at is None
    assert stick.name == "SanDisk Ultra USB (64 GB)"
    assert stick.mounted_at == "/var/mnt/stick" and stick.mounted_part.path == "/dev/sdb1"
    system = storage.drives(lambda args: lsblk(), fstab, include_system=True)[0]
    assert system.system and system.path == "/dev/nvme0n1"


def test_a_drive_with_a_linux_filesystem_can_be_used_as_it_is(fstab):
    stick = storage.drives(lambda args: lsblk(fstab_uuid="other"), fstab)[1]
    assert stick.mounted_at is None and stick.usable_part.path == "/dev/sdb1"


def test_nothing_found_when_lsblk_fails(fstab):
    assert storage.drives(lambda args: None, fstab) == []
    assert storage.drives(lambda args: "not json", fstab) == []


def test_names(tmp_path, fstab):
    base = tmp_path / "mnt"
    base.mkdir()
    ssd = storage.drives(lambda args: lsblk(), fstab)[0]
    assert storage.free_name(ssd, base, fstab) == "Games"  # its label
    (base / "Games").mkdir()
    assert storage.free_name(ssd, base, fstab) == "games"
    (base / "games").mkdir()
    assert storage.free_name(ssd, base, fstab) == "games2"
    stick = storage.drives(lambda args: lsblk(), fstab)[1]
    assert storage.free_name(stick, base, fstab) == "games2"  # "stick" is taken (by itself, in fstab)


def test_helper_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(storage, "helper", lambda *a: calls.append(a) or (True, "Ready"))
    drive = storage.Drive("/dev/sda", "SSD", 256 * GB)
    part = storage.Part("/dev/sda1", 256 * GB, "ext4", uuid="u")
    storage.erase(drive, "games")
    storage.use(part, "games")
    storage.release(part)
    assert calls == [("format", "/dev/sda", "games"), ("use", "/dev/sda1", "games"), ("release", "/dev/sda1")]


# -- Steam ---------------------------------------------------------------------

LIBRARIES = '''"libraryfolders"
{
\t"0"
\t{
\t\t"path"\t\t"/home/me/.local/share/Steam"
\t\t"label"\t\t""
\t\t"contentid"\t\t"123"
\t\t"apps"
\t\t{
\t\t\t"228980"\t\t"123456"
\t\t}
\t}
}
'''


@pytest.fixture
def steam(tmp_path):
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps/libraryfolders.vdf").write_text(LIBRARIES)
    home = tmp_path / "home"
    home.mkdir()
    return root, home, tmp_path / "drive"


def test_add_and_remove_a_steam_library(steam):
    root, home, drive = steam
    drive.mkdir()
    assert not storage.has_steam_library(str(drive), root)
    assert storage.add_steam_library(str(drive), root, home).startswith("Done")
    assert storage.has_steam_library(str(drive), root)
    assert (drive / "SteamLibrary/steamapps").is_dir()
    data = library.parse_vdf((root / "steamapps/libraryfolders.vdf").read_text())["libraryfolders"]
    assert data["0"]["apps"] == {"228980": "123456"}  # the existing library is kept as it was
    assert data["1"]["path"] == str(drive / "SteamLibrary")
    own = library.parse_vdf((drive / "SteamLibrary/libraryfolder.vdf").read_text())["libraryfolder"]
    assert own["contentid"] == data["1"]["contentid"]
    assert storage.add_steam_library(str(drive), root, home) == "Steam already uses it"
    # Hearth's game library now looks there too.
    (drive / "SteamLibrary/steamapps/appmanifest_42.acf").write_text(
        '"AppState" { "appid" "42" "name" "Far Game" "StateFlags" "4" }')
    assert storage.steam_games_on(str(drive)) == 1
    assert "move or uninstall" in storage.remove_steam_library(str(drive), root, home)
    (drive / "SteamLibrary/steamapps/appmanifest_42.acf").unlink()
    assert storage.remove_steam_library(str(drive), root, home).startswith("Done")
    assert storage.steam_libraries(root) == [Path("/home/me/.local/share/Steam")]


def test_steam_must_be_closed(steam, monkeypatch):
    root, home, drive = steam
    (home / ".steam").mkdir()
    (home / ".steam/steam.pid").write_text(str(os.getpid()))
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: "steam\n" if str(self).endswith("/comm")
                        else real(self, *a, **k))
    assert "Close Steam first" in storage.add_steam_library(str(drive), root, home)
    assert not storage.has_steam_library(str(drive), root)


def test_steam_never_opened(tmp_path):
    assert "Open Steam once" in storage.add_steam_library(str(tmp_path), tmp_path / "nothing", tmp_path)


# -- ROMs ----------------------------------------------------------------------


def test_move_roms_to_a_drive_and_back(tmp_path):
    home, drive = tmp_path / "home", tmp_path / "drive"
    (home / "ROMs/snes").mkdir(parents=True)
    (home / "ROMs/snes/Mario.sfc").write_bytes(b"x" * 1000)
    (home / "ROMs/gc").mkdir()
    (home / "ROMs/gc/Wind Waker.rvz").write_bytes(b"y" * 2000)
    drive.mkdir()
    seen = []
    assert storage.move_roms(drive / "ROMs", home, seen.append).startswith("Done")
    link = home / "ROMs"
    assert link.is_symlink() and (link / "gc/Wind Waker.rvz").read_bytes() == b"y" * 2000
    assert (drive / "ROMs/snes/Mario.sfc").exists()
    assert storage.roms_on(str(drive), home)
    assert seen and seen[-1].startswith("Moving ROMs…")
    assert storage.move_roms(drive / "ROMs", home) == "The ROMs are there already"

    assert storage.move_roms(link, home).startswith("Done: the ROMs are back")
    assert not link.is_symlink() and (link / "snes/Mario.sfc").read_bytes() == b"x" * 1000
    assert not storage.roms_on(str(drive), home)
    assert list((drive / "ROMs").rglob("*.*")) == []
    assert storage.move_roms(link, home) == "The ROMs are on this PC's drive already"


def test_move_roms_stops_on_a_name_clash(tmp_path):
    home, drive = tmp_path / "home", tmp_path / "drive"
    (home / "ROMs/snes").mkdir(parents=True)
    (home / "ROMs/snes/Mario.sfc").write_bytes(b"new")
    (drive / "ROMs/snes").mkdir(parents=True)
    (drive / "ROMs/snes/Mario.sfc").write_bytes(b"old")
    assert storage.move_roms(drive / "ROMs", home).startswith("Stopped")
    assert (home / "ROMs/snes/Mario.sfc").read_bytes() == b"new"  # nothing lost
    assert (drive / "ROMs/snes/Mario.sfc").read_bytes() == b"old"
    assert not (home / "ROMs").is_symlink()


def test_move_roms_checks_space(tmp_path, monkeypatch):
    home, drive = tmp_path / "home", tmp_path / "drive"
    (home / "ROMs").mkdir(parents=True)
    (home / "ROMs/big.iso").write_bytes(b"z" * 5000)
    drive.mkdir()
    monkeypatch.setattr(storage, "_free_at", lambda path: 100)
    assert storage.move_roms(drive / "ROMs", home).startswith("Not enough space")
    assert (home / "ROMs/big.iso").exists()


def test_in_use(tmp_path, steam):
    root, home, drive = steam
    drive.mkdir()
    d = storage.Drive("/dev/sda", "SSD", 256 * GB, mounted_at=str(drive))
    assert storage.in_use(d, home, root) == []
    storage.add_steam_library(str(drive), root, home)
    (home / "ROMs").mkdir()
    storage.move_roms(drive / "ROMs", home)
    assert storage.in_use(d, home, root) == ["the ROMs", "a Steam library"]
