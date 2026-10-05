"""Drives added after install, for Steam games and ROMs (Settings → Storage).

Finding drives is unprivileged (lsblk). Erasing, mounting and releasing go
through /usr/libexec/hearth/hearth-storage via a narrow sudoers rule, because
a TV remote can't answer a password prompt; the helper checks everything
again and never touches the drive the system runs from.

A drive Hearth sets up is mounted at /var/mnt/<name> at every boot. From
there it can hold a Steam library (<drive>/SteamLibrary, added to Steam's
libraryfolders.vdf) and the ROMs folder (~/ROMs becomes a link to
<drive>/ROMs; emulators already have access to /var/mnt).
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

HELPER = "/usr/libexec/hearth/hearth-storage"
FSTAB = Path("/etc/fstab")
TAG = "x-hearth"  # the mount option marking fstab entries Hearth made
SYSTEM_MOUNTS = {"/", "/sysroot", "/boot", "/boot/efi", "/usr", "/etc", "/var", "/home", "/var/home", "[SWAP]"}
LINUX_FS = {"ext4", "btrfs", "xfs"}  # permissions and links: what Steam and emulators need
MIN_SIZE = 4e9  # smaller than this isn't a games drive (and keeps card readers and such out)
STEAM_FOLDER = "SteamLibrary"
ROMS_FOLDER = "ROMs"

Runner = Callable[[list[str]], str | None]


def _lsblk(args: list[str]) -> str | None:
    try:
        p = subprocess.run(["lsblk", *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def gb(size: float) -> str:
    return f"{size / 1e12:.1f} TB" if size >= 1e12 else f"{size / 1e9:.0f} GB"


@dataclass(frozen=True)
class Part:
    path: str
    size: int
    fstype: str = ""
    label: str = ""
    uuid: str = ""
    mounts: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """Can be used as it is (keeping its files)."""
        return self.fstype in LINUX_FS and bool(self.uuid)


@dataclass(frozen=True)
class Drive:
    path: str
    model: str
    size: int
    transport: str = ""
    removable: bool = False
    system: bool = False
    parts: tuple[Part, ...] = ()
    mounted_at: str | None = None  # where Hearth mounts it (its fstab entry)
    mounted_part: Part | None = None

    @property
    def name(self) -> str:
        """What to call it on screen: "Samsung SSD 870 EVO (256 GB)"."""
        kind = " USB" if self.transport == "usb" else ""
        return f"{self.model or 'Drive'}{kind} ({gb(self.size)})"

    @property
    def usable_part(self) -> Part | None:
        return next((p for p in self.parts if p.usable), None)

    @property
    def contents(self) -> str:
        """What's on it now, for the "this erases" warning."""
        shown = [p for p in self.parts if p.size >= 100e6] or list(self.parts)  # not Windows' tiny hidden ones
        if not shown:
            return "empty"
        return ", ".join(f"{p.label or p.fstype or 'unformatted'} ({gb(p.size)})" for p in shown)

    @property
    def ready(self) -> bool:
        return bool(self.mounted_at) and os.path.ismount(self.mounted_at)


def hearth_mounts(fstab: Path = FSTAB) -> dict[str, str]:
    """{UUID: mount point} of the drives Hearth set up."""
    out = {}
    try:
        lines = fstab.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        fields = line.split()
        if len(fields) >= 4 and fields[0].startswith("UUID=") and TAG in fields[3].split(","):
            out[fields[0][5:]] = fields[1]
    return out


def _mounts(dev: dict) -> tuple[str, ...]:
    points = dev.get("mountpoints") or ([dev["mountpoint"]] if dev.get("mountpoint") else [])
    return tuple(p for p in points if p)


def _all_mounts(dev: dict) -> set[str]:
    found = set(_mounts(dev))
    for child in dev.get("children") or ():
        found |= _all_mounts(child)
    return found


MOUNTS = Path("/proc/self/mounts")


def _nest(devices: list[dict]) -> list[dict]:
    """lsblk's tree. Newer lsblk (util-linux 2.41) prints a flat list unless
    NAME is among the columns, so partitions are hung back under their disk
    by PKNAME either way (field report #60: the system drive read as empty
    and was offered for erasing)."""
    by_name = {d.get("name"): d for d in devices if d.get("name")}
    by_name.update({d.get("path"): d for d in devices if d.get("path")})  # PKNAME is "sda", the path "/dev/sda"
    for d in devices:
        d.setdefault("children", [])
    top = []
    for d in devices:
        parent = by_name.get(d.get("pkname")) if d.get("pkname") else None
        if parent is not None and parent is not d:
            if d not in parent["children"]:
                parent["children"].append(d)
        elif d.get("type") != "part" or not d.get("pkname"):
            top.append(d)
    return top


def system_devices(mounts: Path = MOUNTS) -> set[str]:
    """Device paths mounted where the system lives (/, /var, /boot...)."""
    out = set()
    try:
        lines = mounts.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        fields = line.split()
        if len(fields) >= 2 and fields[0].startswith("/dev/") and fields[1] in SYSTEM_MOUNTS:
            out.add(fields[0])
    return out


def drives(run: Runner = _lsblk, fstab: Path = FSTAB, include_system: bool = False,
           mounts: Path = MOUNTS) -> list[Drive]:
    """Whole drives, the system's own marked (and left out unless asked for)."""
    out = run(["-J", "-b", "-o", "NAME,PKNAME,PATH,TYPE,SIZE,MODEL,TRAN,RM,RO,FSTYPE,LABEL,UUID,MOUNTPOINTS"])
    try:
        devices = _nest(json.loads(out or "{}").get("blockdevices", []))
    except (ValueError, AttributeError, TypeError):
        return []
    ours = hearth_mounts(fstab)
    held = system_devices(mounts)  # what the system is really mounted from, whatever lsblk says
    found = []
    for dev in devices:
        path = dev.get("path") or ""
        if dev.get("type") != "disk" or dev.get("ro") or path.startswith(("/dev/zram", "/dev/loop")):
            continue
        size = int(dev.get("size") or 0)
        if size < MIN_SIZE:
            continue
        paths = {path} | {c.get("path") for c in dev.get("children") or () if c.get("path")}
        system = bool(_all_mounts(dev) & SYSTEM_MOUNTS) or bool(paths & held)
        if system and not include_system:
            continue
        parts = tuple(Part(c.get("path", ""), int(c.get("size") or 0), c.get("fstype") or "", c.get("label") or "",
                           c.get("uuid") or "", _mounts(c))
                      for c in dev.get("children") or () if c.get("type") == "part")
        whole = Part(path, size, dev.get("fstype") or "", dev.get("label") or "", dev.get("uuid") or "", _mounts(dev))
        if not parts and whole.fstype:  # a filesystem straight on the disk, no partition table
            parts = (whole,)
        mine = next((p for p in parts if p.uuid in ours), None)
        found.append(Drive(path, (dev.get("model") or "").strip(), size, dev.get("tran") or "", bool(dev.get("rm")),
                           system, parts, ours.get(mine.uuid) if mine else None, mine))
    return found


def free_name(drive: Drive, base: Path = Path("/var/mnt"), fstab: Path = FSTAB) -> str:
    """A name for its mount point: its label if that suits, else games, games2..."""
    taken = {Path(p).name for p in hearth_mounts(fstab).values()}
    try:
        taken |= {p.name for p in base.iterdir()}
    except OSError:
        pass
    label = next((p.label for p in drive.parts if p.label), "")
    label = re.sub(r"[^A-Za-z0-9_-]", "", label.replace(" ", "-"))[:16]
    if label and label[0].isalnum() and label not in taken:
        return label
    n = 1
    while (name := "games" if n == 1 else f"games{n}") in taken:
        n += 1
    return name


# -- the privileged helper -----------------------------------------------------


WRONG_PASSWORD = "Wrong password"


def helper(*args: str, password: str | None = None) -> tuple[bool, str]:
    """Run hearth-storage as root. (ok, the last thing it said).

    Erasing a drive needs the account's password: sudoers only lets the
    other actions through without one. -k makes sudo ask even if it was
    given recently, so the password is checked every time."""
    if password is None:
        cmd, stdin = ["sudo", "-n", HELPER, *args], None
    else:
        cmd, stdin = ["sudo", "-k", "-S", "-p", "", HELPER, *args], password + "\n"
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if password is not None and p.returncode != 0 and re.search(r"incorrect password|Sorry, try again", p.stderr):
        return False, WRONG_PASSWORD
    said = (p.stdout + p.stderr).strip().splitlines()
    return p.returncode == 0, said[-1] if said else ("Done" if p.returncode == 0 else "Failed")


def erase(drive: Drive, name: str, password: str) -> tuple[bool, str]:
    return helper("format", drive.path, name, password=password)


def use(part: Part, name: str) -> tuple[bool, str]:
    return helper("use", part.path, name)


def release(part: Part) -> tuple[bool, str]:
    return helper("release", part.path)


# -- Steam libraries -----------------------------------------------------------


def steam_root() -> Path | None:
    from .library import steam_roots

    roots = steam_roots()
    return roots[0] if roots else None


def steam_running(home: Path | None = None) -> bool:
    """Steam rewrites its library list when it exits, so it must be closed to change it."""
    home = home or Path.home()
    try:
        pid = int((home / ".steam/steam.pid").read_text().strip())
        comm = Path(f"/proc/{pid}/comm").read_text().strip()
    except (OSError, ValueError):
        return False
    return comm.startswith("steam")


def dump_vdf(data: dict, indent: int = 0) -> str:
    """Valve KeyValues text, laid out the way Steam writes it."""
    out = []
    tabs = "\t" * indent
    for key, value in data.items():
        k = str(key).replace("\\", "\\\\").replace('"', '\\"')
        if isinstance(value, dict):
            out.append(f'{tabs}"{k}"\n{tabs}{{\n{dump_vdf(value, indent + 1)}{tabs}}}\n')
        else:
            v = str(value).replace("\\", "\\\\").replace('"', '\\"')
            out.append(f'{tabs}"{k}"\t\t"{v}"\n')
    return "".join(out)


def _libraries_file(root: Path) -> Path:
    return root / "steamapps/libraryfolders.vdf"


def _read_libraries(root: Path) -> dict:
    from .library import parse_vdf

    try:
        data = parse_vdf(_libraries_file(root).read_text(errors="replace"))
    except OSError:
        return {}
    key = next((k for k in data if k.lower() == "libraryfolders"), None)
    return data[key] if key else {}


def steam_libraries(root: Path | None) -> list[Path]:
    if root is None:
        return []
    return [Path(v["path"]) for v in _read_libraries(root).values() if isinstance(v, dict) and v.get("path")]


def has_steam_library(mount: str, root: Path | None = None) -> bool:
    root = root or steam_root()
    target = Path(mount) / STEAM_FOLDER
    return any(p == target for p in steam_libraries(root))


def _write_libraries(root: Path, folders: dict) -> None:
    path = _libraries_file(root)
    tmp = path.with_name(path.name + ".hearth-tmp")
    tmp.write_text(dump_vdf({"libraryfolders": folders}))
    os.replace(tmp, path)


def add_steam_library(mount: str, root: Path | None = None, home: Path | None = None) -> str:
    """Make <drive>/SteamLibrary a Steam library folder (Steam must be closed)."""
    root = root or steam_root()
    if root is None or not _libraries_file(root).exists():
        return "Open Steam once first, then try again"
    if steam_running(home):
        return "Close Steam first (Quick Menu → Close Steam), then try again"
    target = Path(mount) / STEAM_FOLDER
    folders = _read_libraries(root)
    if any(isinstance(v, dict) and Path(v.get("path", "")) == target for v in folders.values()):
        return "Steam already uses it"
    content_id = str(random.getrandbits(63))
    (target / "steamapps").mkdir(parents=True, exist_ok=True)
    (target / "libraryfolder.vdf").write_text(dump_vdf({"libraryfolder": {"contentid": content_id, "label": ""}}))
    index = max((int(k) for k in folders if str(k).isdigit()), default=-1) + 1
    folders[str(index)] = {"path": str(target), "label": "", "contentid": content_id, "totalsize": "0",
                           "update_clean_bytes_tally": "0", "time_last_update_verified": "0", "apps": {}}
    _write_libraries(root, folders)
    return "Done: Steam can install games on it (choose it when installing)"


def remove_steam_library(mount: str, root: Path | None = None, home: Path | None = None) -> str:
    """Stop Steam using it: only when no games are installed there."""
    root = root or steam_root()
    target = Path(mount) / STEAM_FOLDER
    games = list((target / "steamapps").glob("appmanifest_*.acf"))
    if games:
        return f"{len(games)} game(s) are installed there: move or uninstall them in Steam first"
    if root is None:
        return "Steam isn't set up"
    if steam_running(home):
        return "Close Steam first (Quick Menu → Close Steam), then try again"
    folders = _read_libraries(root)
    kept = {k: v for k, v in folders.items() if not (isinstance(v, dict) and Path(v.get("path", "")) == target)}
    if kept == folders:
        return "Steam wasn't using it"
    _write_libraries(root, {str(i): v for i, v in enumerate(kept.values())})
    return "Done: Steam no longer uses it"


def steam_games_on(mount: str) -> int:
    return len(list((Path(mount) / STEAM_FOLDER / "steamapps").glob("appmanifest_*.acf")))


# -- ROMs ----------------------------------------------------------------------


def roms_link(home: Path | None = None) -> Path:
    return (home or Path.home()) / "ROMs"


def roms_on(mount: str, home: Path | None = None) -> bool:
    link = roms_link(home)
    return link.is_symlink() and Path(os.path.realpath(link)) == Path(os.path.realpath(Path(mount) / ROMS_FOLDER))


def _size(path: Path) -> int:
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                pass
    return total


def _free_at(path: Path) -> int:
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def _move_into(src: Path, dst: Path, done: list[int], total: int, progress: Callable[[str], None] | None) -> list[str]:
    """Move src's contents into dst file by file, merging folders. Returns
    what was left behind (a name already taken on the other side)."""
    left = []
    dst.mkdir(parents=True, exist_ok=True)
    for entry in sorted(src.iterdir()):
        target = dst / entry.name
        if entry.is_dir() and not entry.is_symlink():
            if target.exists() and not target.is_dir():
                left.append(str(entry))
                continue
            left += _move_into(entry, target, done, total, progress)
            try:
                entry.rmdir()
            except OSError:
                pass
            continue
        if target.exists() or target.is_symlink():
            left.append(str(entry))
            continue
        size = entry.lstat().st_size
        shutil.move(str(entry), str(target))
        done[0] += size
        if progress:
            progress(f"Moving ROMs… {gb(done[0])} of {gb(total)}")
    return left


def move_roms(to: Path, home: Path | None = None, progress: Callable[[str], None] | None = None) -> str:
    """Put the ROMs at `to`, moving what's there, and point ~/ROMs at it; or,
    with `to` being ~/ROMs itself, bring them back into a real ~/ROMs folder."""
    link = roms_link(home)
    back_home = to == link
    current = Path(os.path.realpath(link)) if link.is_symlink() else link
    if back_home and not link.is_symlink():
        return "The ROMs are on this PC's drive already"
    if not back_home and link.is_symlink() and current == Path(os.path.realpath(to)):
        return "The ROMs are there already"
    total = _size(current) if current.exists() else 0
    free = _free_at(link.parent if back_home else to)
    if total > free:
        return f"Not enough space: the ROMs take {gb(total)}, there's {gb(free)} free"
    dest = link.with_name("ROMs.hearth-moving") if back_home else to
    left = _move_into(current, dest, [0], total, progress) if current.exists() else []
    if left:
        return f"Stopped: {len(left)} item(s) have the same name there already ({Path(left[0]).name}…)"
    if link.is_symlink():
        link.unlink()
    elif link.exists():
        link.rmdir()  # empty now: everything moved
    if back_home:
        dest.rename(link)
        return f"Done: the ROMs are back on this PC's drive ({gb(total)})"
    dest.mkdir(parents=True, exist_ok=True)
    link.symlink_to(to)
    return f"Done: the ROMs are on the new drive ({gb(total)}); ES-DE finds them as before"


def in_use(drive: Drive, home: Path | None = None, root: Path | None = None) -> list[str]:
    """What Hearth has put on a drive that still needs it (stops it being released)."""
    if not drive.mounted_at:
        return []
    reasons = []
    if roms_on(drive.mounted_at, home):
        reasons.append("the ROMs")
    if has_steam_library(drive.mounted_at, root):
        reasons.append("a Steam library")
    return reasons


def system_space(home: Path | None = None) -> tuple[int, int]:
    try:
        usage = shutil.disk_usage(home or Path.home())
        return usage.free, usage.total
    except OSError:
        return 0, 0
