"""Your own photos in the screen saver."""

import struct
import time

import pygame
import pytest

from hearth import library, photos, settings_app, ui
from hearth import config as cfg
from hearth.model import Home


def jpeg_with_orientation(path, orientation: int, little_endian: bool = True) -> None:
    """Just enough of a JPEG for the EXIF reader: SOI, an APP1 with one tag."""
    e = "<" if little_endian else ">"
    tiff = (b"II" if little_endian else b"MM") + struct.pack(e + "HI", 42, 8)
    tiff += struct.pack(e + "H", 1) + struct.pack(e + "HHI", 0x0112, 3, 1) + struct.pack(e + "H", orientation) + b"\0\0"
    tiff += struct.pack(e + "I", 0)
    app1 = b"Exif\x00\x00" + tiff
    path.write_bytes(b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9")


def test_exif_orientation_is_read_either_byte_order(tmp_path):
    jpeg_with_orientation(tmp_path / "a.jpg", 6)
    jpeg_with_orientation(tmp_path / "b.jpg", 8, little_endian=False)
    assert photos.exif_orientation(tmp_path / "a.jpg") == 6
    assert photos.exif_orientation(tmp_path / "b.jpg") == 8
    (tmp_path / "plain.jpg").write_bytes(b"\xff\xd8\xff\xdb\x00\x04\x00\x00\xff\xd9")
    assert photos.exif_orientation(tmp_path / "plain.jpg") == 1  # no EXIF
    assert photos.exif_orientation(tmp_path / "missing.jpg") == 1
    (tmp_path / "not.jpg").write_bytes(b"\x89PNG")
    assert photos.exif_orientation(tmp_path / "not.jpg") == 1


def test_orient_turns_a_sideways_photo_up():
    img = pygame.Surface((40, 20))
    assert photos.orient(img, 1).get_size() == (40, 20)
    assert photos.orient(img, 6).get_size() == (20, 40)
    assert photos.orient(img, 8).get_size() == (20, 40)
    assert photos.orient(img, 3).get_size() == (40, 20)
    img.fill((0, 0, 0))
    img.set_at((0, 0), (255, 0, 0))  # top left...
    assert photos.orient(img, 6).get_at((19, 0)) == (255, 0, 0, 255)  # ...ends top right after a right turn
    assert photos.orient(img, 2).get_at((39, 0)) == (255, 0, 0, 255)  # mirrored


def test_find_pictures_skips_hidden_folders_and_hearth_screenshots(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    pics = tmp_path / "Pictures"
    (pics / "Holiday 2025").mkdir(parents=True)
    (pics / ".thumbnails").mkdir()
    (pics / "Hearth").mkdir()
    for name in ("Holiday 2025/IMG_1.jpg", "Holiday 2025/IMG_2.JPEG", "cat.png", "notes.txt", ".thumbnails/x.jpg",
                 "Hearth/Elden Ring 2026.png", "Holiday 2025/clip.mp4"):
        (pics / name).write_bytes(b"x")
    found = sorted(p.relative_to(pics).as_posix() for p in photos.find(pics))
    assert found == ["Holiday 2025/IMG_1.jpg", "Holiday 2025/IMG_2.JPEG", "cat.png"]
    assert photos.find(pics, limit=2) and len(photos.find(pics, limit=2)) == 2
    assert photos.find(tmp_path / "nowhere") == []
    assert photos.caption(pics / "Holiday 2025/IMG_1.jpg", pics) == "Holiday 2025"
    assert photos.caption(pics / "cat.png", pics) == ""


def test_candidates_offer_pictures_and_plugged_in_drives(tmp_path):
    stick = tmp_path / "run/media/joseph/CAMERA"
    (stick / "DCIM").mkdir(parents=True)
    other = tmp_path / "var/mnt/games"
    other.mkdir(parents=True)
    out = photos.candidates(home=tmp_path / "home", mounts=[stick, other])
    assert out[0] == ("Pictures", str(tmp_path / "home/Pictures"))
    assert out[1:] == [("CAMERA / DCIM", str(stick / "DCIM"))]


def test_setting():
    c = cfg.parse({"home": {"screensaver": "both", "photos_folder": "/run/media/joseph/CAMERA/DCIM"}})
    assert c.screensaver == "both" and c.photos_folder == "/run/media/joseph/CAMERA/DCIM"
    assert cfg.parse({}).photos_folder == ""
    with pytest.raises(cfg.ConfigError):
        cfg.parse({"home": {"screensaver": "slideshow"}})


@pytest.fixture
def screen(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    pygame.display.init()
    pygame.font.init()
    surface = pygame.display.set_mode((1280, 720))
    pics = tmp_path / "Pictures/Trip"
    pics.mkdir(parents=True)
    for i, color in enumerate(((200, 40, 40), (40, 200, 40), (40, 40, 200))):
        img = pygame.Surface((400, 300))
        img.fill(color)
        pygame.image.save(img, str(pics / f"photo{i}.png"))
    art = tmp_path / "art.png"
    img = pygame.Surface((400, 300))
    img.fill((200, 200, 40))
    pygame.image.save(img, str(art))
    monkeypatch.setattr(library, "all_games", lambda: [library.Game("rom:a", "Red Game", "snes", ("true",), art=str(art))])
    yield ui.HomeScreen(surface, Home(cfg.Config(rows=())), "Hearth")
    pygame.quit()


def test_saver_shows_photos_alone_or_with_the_art(screen):
    screen.saver_style = "photos"
    screen.start_saver()
    assert len(screen._slides) == 3 and all(t == "Trip" for t, _, _ in screen._slides)
    assert all(p in screen._photo_paths for _, _, p in screen._slides)
    screen._saver_t0 = time.monotonic() - 1
    screen.draw_saver()
    r, g, b, _ = screen.surface.get_at((5, 700))
    assert max(r, g, b) > 0 and max(r, g, b) <= ui.SLIDE_DIM + 5  # a photo, dimmed
    screen.saver_style = "both"
    screen.start_saver()
    assert len(screen._slides) == 4 and "Red Game" in [t for t, _, _ in screen._slides]
    screen.saver_style = "ambient"
    screen.start_saver()
    assert [t for t, _, _ in screen._slides] == ["Red Game"]  # no photos unless asked


def test_a_chosen_folder_wins_and_a_bad_photo_is_dropped(screen, tmp_path):
    other = tmp_path / "USB/DCIM"
    other.mkdir(parents=True)
    (other / "broken.jpg").write_bytes(b"not a picture")
    img = pygame.Surface((300, 400))
    img.fill((40, 200, 200))
    pygame.image.save(img, str(other / "good.png"))
    screen.saver_style = "photos"
    screen.saver_photos = str(other)
    screen.start_saver()
    assert len(screen._slides) == 2
    screen._saver_t0 = time.monotonic() - 1
    screen.draw_saver()
    screen._saver_t0 = time.monotonic() - ui.SLIDE_SECONDS - ui.SLIDE_FADE - 1
    screen.draw_saver()
    assert [p for _, _, p in screen._slides] == [str(other / "good.png")]


def test_settings_offer_the_styles_and_folders(shipped_config, monkeypatch, tmp_path):
    monkeypatch.setattr(photos, "candidates", lambda: [("Pictures", str(tmp_path / "Pictures")),
                                                       ("CAMERA / DCIM", "/run/media/joseph/CAMERA/DCIM")])
    app = settings_app.SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("home")
    app._load_photo_folders()  # what load_for("home") does in the background
    app.refresh()
    items = {i.key: i for i in app.menu.current.items}
    assert items["saver-style"].options[1] == "Your photos" and items["photos-folder"].options[1] == "CAMERA / DCIM"
    items["saver-style"].on_change(2)
    items["photos-folder"].on_change(1)
    c = cfg.load(shipped_config)
    assert c.screensaver == "both" and c.photos_folder == "/run/media/joseph/CAMERA/DCIM"
    app.refresh()
    items = {i.key: i for i in app.menu.current.items}
    assert items["photos-folder"].value == 1
    items["photos-folder"].on_change(0)
    assert cfg.load(shipped_config).photos_folder == ""  # back to ~/Pictures, wherever that is
