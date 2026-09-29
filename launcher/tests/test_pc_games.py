"""PC games outside Steam: AppImages in ~/Games get tiles."""

import os
import subprocess

import pytest

from conftest import REPO
from hearth import config as cfg
from hearth import library

RUN_GAME = REPO / "image/system_files/usr/libexec/hearth/hearth-run-game"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "Games").mkdir()
    return tmp_path


def test_appimages_and_folders(home):
    games = home / "Games"
    (games / "Dusk-v1.2.0-x86_64.AppImage").write_bytes(b"")
    (games / "Dusk-v1.2.0-x86_64.png").write_bytes(b"")
    tp = games / "Twilight Princess"
    tp.mkdir()
    (tp / "dusk-linux.AppImage").write_bytes(b"")
    (tp / "cover.jpg").write_bytes(b"")
    (tp / "game.iso").write_bytes(b"")
    scripted = games / "Ship of Harkinian"
    scripted.mkdir()
    (scripted / "start.sh").write_text("exec ./soh.elf\n")
    (games / "empty folder").mkdir()
    (games / "notes.txt").write_text("")

    found = {g.title: g for g in library.port_games()}
    assert set(found) == {"Dusk", "Twilight Princess", "Ship of Harkinian"}
    assert found["Dusk"].art == str(games / "Dusk-v1.2.0-x86_64.png")
    assert found["Twilight Princess"].art == str(tp / "cover.jpg")
    # The disc goes to the game, so it skips its file picker (Dusklight).
    assert found["Twilight Princess"].command == (library.RUN_GAME, str(tp / "dusk-linux.AppImage"),
                                                  str(tp / "game.iso"))
    assert found["Ship of Harkinian"].command == (library.RUN_GAME, str(scripted / "start.sh"))  # no disc
    assert found["Dusk"].platform == "PC"


def test_compressed_disc_images_count(home):
    tp = home / "Games/Twilight Princess"
    tp.mkdir()
    (tp / "Dusklight-x86_64.AppImage").write_bytes(b"")
    (tp / "GZ2E01.RVZ").write_bytes(b"")
    assert library.port_games()[0].command[-1] == str(tp / "GZ2E01.RVZ")


def test_no_games_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert library.port_games() == []


def test_row_on_the_home_screen(home, shipped_config):
    (home / "Games/Twilight Princess.AppImage").write_bytes(b"")
    config = library.with_game_rows(cfg.load(shipped_config))
    row = next(r for r in config.rows if r.title == "PC games")
    app = row.apps[0]
    assert app.name == "Twilight Princess" and app.home_button and app.tag_windows
    assert library.key_of(app.id) == "pc:Twilight Princess.AppImage"  # can be pinned, shows in Continue
    library.record_play("pc:Twilight Princess.AppImage")
    assert [g.title for g in library.recent(library.all_games())] == ["Twilight Princess"]


def test_library_lists_them(home):
    (home / "Games/Dusk.AppImage").write_bytes(b"")
    assert "PC" in [r.title for r in library.library_config().rows]


def test_runner_starts_it_from_its_folder_even_without_execute_permission(tmp_path):
    folder = tmp_path / "Twilight Princess"
    folder.mkdir()
    game = folder / "dusk.AppImage"
    game.write_text(f"#!/usr/bin/bash\npwd > {tmp_path}/ran; echo \"$@\" >> {tmp_path}/ran; "
                    f"echo \"$SDL_VIDEODRIVER $SDL_VIDEO_DRIVER\" >> {tmp_path}/ran\n")
    game.chmod(0o644)  # as downloaded
    subprocess.run(["bash", str(RUN_GAME), str(game), "--fullscreen"], check=True, cwd=tmp_path,
                   env={**os.environ})
    assert (tmp_path / "ran").read_text().split("\n")[:3] == [str(folder), "--fullscreen", "x11 x11"]
    assert os.access(game, os.X_OK)
