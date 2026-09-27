"""ES-DE uses the emulators Hearth installs, and RetroArch gets its cores."""

import io
import xml.etree.ElementTree as ET
import zipfile

import pytest

from hearth import esde, library, settings


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(library, "flatpak_installed", lambda app: True)
    return tmp_path


def label(system):
    root = ET.parse(esde.gamelist(system)).getroot()
    return root.findtext("alternativeEmulator/label")


def test_selects_standalone_emulators(home):
    esde.setup(download=False)
    assert label("gc") == "Dolphin (Standalone)"
    assert label("ps2") == "PCSX2 (Standalone)"
    assert label("psx") == "DuckStation (Standalone)"
    assert label("n64") == "Rosalie's Mupen GUI (Standalone)"
    assert set(settings.load()["esde_emulators_set"]) == set(esde.STANDALONE)


def test_keeps_existing_games_and_the_users_choice(home):
    path = esde.gamelist("gc")
    path.parent.mkdir(parents=True)
    path.write_text('<?xml version="1.0"?>\n<gameList>\n\t<game><path>./Zelda.rvz</path>'
                    '<name>Zelda</name></game>\n</gameList>\n')
    chosen = esde.gamelist("ps2")
    chosen.parent.mkdir(parents=True)
    chosen.write_text('<?xml version="1.0"?>\n<alternativeEmulator>\n\t<label>LRPS2</label>\n'
                      '</alternativeEmulator>\n<gameList />\n')  # ES-DE's older layout
    before = chosen.read_text()

    esde.setup(download=False)
    root = ET.parse(path).getroot()
    assert root.findtext("alternativeEmulator/label") == "Dolphin (Standalone)"
    assert root.findtext("game/name") == "Zelda"
    assert chosen.read_text() == before  # set in ES-DE: left alone


def test_only_once_so_a_later_change_in_esde_sticks(home):
    esde.setup(download=False)
    esde.gamelist("gc").write_text('<?xml version="1.0"?>\n<gameList />\n')  # back to ES-DE's default
    esde.setup(download=False)
    assert label("gc") is None


def test_waits_for_the_emulator_to_be_installed(home, monkeypatch):
    monkeypatch.setattr(library, "flatpak_installed", lambda app: app != "net.pcsx2.PCSX2")
    esde.setup(download=False)
    assert not esde.gamelist("ps2").exists()
    monkeypatch.setattr(library, "flatpak_installed", lambda app: True)
    esde.setup(download=False)
    assert label("ps2") == "PCSX2 (Standalone)"


def fake_buildbot(fail=()):
    def fetch(url):
        core = url.rsplit("/", 1)[1].removesuffix(".so.zip")
        if core in fail:
            raise OSError("network down")
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            z.writestr(f"{core}.so", b"\x7fELF fake core")
        return data.getvalue()
    return fetch


def test_downloads_missing_cores(home):
    (esde.cores_dir()).mkdir(parents=True)
    (esde.cores_dir() / "snes9x_libretro.so").write_bytes(b"\x7fELF mine")
    failed = esde.download_cores(fetch=fake_buildbot(fail={"flycast_libretro"}))
    assert failed == ["flycast_libretro"]
    assert (esde.cores_dir() / "mesen_libretro.so").read_bytes().startswith(b"\x7fELF")
    assert (esde.cores_dir() / "snes9x_libretro.so").read_bytes() == b"\x7fELF mine"  # kept
    assert esde.missing_cores() == ["flycast_libretro"]  # retried next time
    # And Hearth's own launcher now finds the NES core.
    rom = home / "ROMs/nes/Mario.nes"
    assert library.launch_command("nes", rom)[-3:] == ("-L", str(esde.cores_dir() / "mesen_libretro.so"), str(rom))


def test_no_cores_without_retroarch(home, monkeypatch):
    monkeypatch.setattr(library, "flatpak_installed", lambda app: app != library.RA)
    assert esde.missing_cores() == []


def test_rejects_a_bad_download(home):
    def html(url):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            z.writestr("mesen_libretro.so", b"<html>not found</html>")
        return data.getvalue()
    with pytest.raises(ValueError):
        esde.download_core("mesen_libretro", fetch=html)
    assert not (esde.cores_dir() / "mesen_libretro.so").exists()
