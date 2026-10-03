"""Your own photos in the screen saver (Settings → Home screen).

A folder of pictures (~/Pictures, or a USB stick's Photos or DCIM folder)
is shown the way the games' art is: slowly, dimmed, kind to OLED TVs. Phone
photos are often stored sideways with a note saying which way up they go
(the EXIF orientation), so that is read and honoured here; pygame doesn't.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pygame

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
# Folder names a camera, phone or person uses for pictures, on a drive's top level.
PICTURE_FOLDERS = ("Pictures", "Photos", "DCIM", "Pictures/Photos", "Fotos", "Bilder")
MAX_FILES = 3000  # enough for any show; a huge library is sampled, not walked to the end
MAX_DEPTH = 4


def home_pictures(home: Path | None = None) -> Path:
    """~/Pictures (the folder the desktop uses, if it's been moved)."""
    from .captures import folder

    return folder(home).parent


def _mounted(media: Path = Path("/run/media"), var_mnt: Path = Path("/var/mnt")) -> list[Path]:
    """Where other drives are: USB sticks (/run/media/<user>/<label>) and the
    drives Settings → Storage set up (/var/mnt/<name>)."""
    out = []
    for base, deep in ((media, True), (var_mnt, False)):
        try:
            entries = sorted(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if deep:
                try:
                    out += sorted(p for p in entry.iterdir() if p.is_dir())
                except OSError:
                    pass
            elif entry.is_dir():
                out.append(entry)
    return out


def candidates(home: Path | None = None, mounts: list[Path] | None = None) -> list[tuple[str, str]]:
    """(name, path) for the folders worth offering: your Pictures, and any
    pictures folder on a drive that's plugged in."""
    out = [("Pictures", str(home_pictures(home)))]
    for mount in _mounted() if mounts is None else mounts:
        for name in PICTURE_FOLDERS:
            folder = mount / name
            if folder.is_dir():
                out.append((f"{mount.name} / {name}", str(folder)))
    return out


def find(folder: str | Path, limit: int = MAX_FILES, depth: int = MAX_DEPTH, home: Path | None = None) -> list[Path]:
    """Every picture under a folder (a few levels deep), skipping hidden
    folders and Hearth's own screenshots, which the saver shows anyway."""
    from .captures import folder as captures_folder

    root = Path(folder).expanduser()
    skip = {captures_folder(home).resolve()}
    out: list[Path] = []
    todo = [(root, 0)]
    while todo and len(out) < limit:
        here, level = todo.pop(0)
        try:
            entries = sorted(os.scandir(here), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if level < depth and Path(entry.path).resolve() not in skip:
                        todo.append((Path(entry.path), level + 1))
                elif entry.is_file() and os.path.splitext(entry.name)[1].lower() in EXTENSIONS:
                    out.append(Path(entry.path))
                    if len(out) >= limit:
                        break
            except OSError:
                continue
    return out


def exif_orientation(path: str | Path) -> int:
    """The EXIF orientation of a JPEG (1 = as stored, 6 = turn right, 8 =
    turn left, 3 = upside down; 2, 4, 5, 7 are mirrored). 1 when there's none."""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return 1
            while True:
                marker, size = struct.unpack(">2sH", f.read(4))
                if marker[0] != 0xFF or marker[1] in (0xDA, 0xD9):  # image data: no EXIF before it
                    return 1
                if marker[1] != 0xE1:
                    f.seek(size - 2, 1)
                    continue
                app1 = f.read(size - 2)
                break
    except (OSError, struct.error):
        return 1
    if not app1.startswith(b"Exif\x00\x00"):
        return 1
    tiff = app1[6:]
    if len(tiff) < 8:
        return 1
    endian = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if endian is None:
        return 1
    try:
        (ifd,) = struct.unpack(endian + "I", tiff[4:8])
        (count,) = struct.unpack(endian + "H", tiff[ifd:ifd + 2])
        for i in range(count):
            at = ifd + 2 + i * 12
            tag, kind, _, value = struct.unpack(endian + "HHII", tiff[at:at + 12])
            if tag == 0x0112:
                if kind == 3:  # SHORT: the value sits in the first two bytes of the field
                    (value,) = struct.unpack(endian + "H", tiff[at + 8:at + 10])
                return value if 1 <= value <= 8 else 1
    except struct.error:
        pass
    return 1


def orient(img: pygame.Surface, orientation: int) -> pygame.Surface:
    """The picture the way up it should be seen."""
    if orientation in (2, 4, 5, 7):
        img = pygame.transform.flip(img, True, False)
    turn = {3: 180, 4: 180, 5: 90, 6: -90, 7: -90, 8: 90}.get(orientation, 0)
    return pygame.transform.rotate(img, turn) if turn else img


def load(path: str | Path) -> pygame.Surface | None:
    """A photo, the right way up; None if it won't load."""
    from .ui import as_truecolor

    try:
        img = pygame.image.load(str(path))
    except (pygame.error, OSError, ValueError):
        return None
    img = as_truecolor(img)
    if str(path).lower().endswith((".jpg", ".jpeg")):
        img = orient(img, exif_orientation(path))
    return img


def caption(path: Path, root: Path) -> str:
    """What to call a photo on screen: its folder ("Holiday 2025"), or
    nothing for one straight in the chosen folder (file names like
    IMG_2041 say nothing)."""
    try:
        rel = path.resolve().relative_to(Path(root).expanduser().resolve())
    except (ValueError, OSError):
        return ""
    return rel.parent.name if len(rel.parts) > 1 else ""
