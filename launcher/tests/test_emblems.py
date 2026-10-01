import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from pathlib import Path

import pygame
import pytest

from hearth import config, emblems, style, ui

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True, scope="module")
def _pygame():
    pygame.init()
    yield


@pytest.mark.parametrize("name", sorted(emblems.EMBLEMS))
def test_each_emblem_draws_something(name):
    surf = emblems.draw(name, 96, style.livery("gulf"))
    assert surf.get_size() == (96, 96)
    painted = sum(1 for x in range(0, 96, 3) for y in range(0, 96, 3) if surf.get_at((x, y)).a > 0)
    assert painted > 40  # not blank


def test_unknown_emblem_is_none():
    assert emblems.draw("nope", 96, style.livery("gulf")) is None
    assert emblems.draw(None, 96, style.livery("gulf")) is None


def test_system_tiles_have_emblems():
    cfg = config.load(REPO / "image/system_files/usr/share/hearth/apps.toml", hide=False)
    ids = {a.id for r in cfg.rows for a in r.apps}
    for app_id, name in emblems.BY_ID.items():
        assert app_id in ids, app_id
        assert name in emblems.EMBLEMS


def test_apps_toml_emblem_overrides_default():
    cfg = config.parse({"rows": [{"title": "X", "apps": [
        {"id": "settings", "name": "Settings", "command": "hearth:settings", "emblem": "moon"}]}]})
    app = cfg.rows[0].apps[0]
    assert app.emblem == "moon"
    lv = style.livery("gulf")
    assert emblems.for_app(app, 64, lv) is emblems.draw("moon", 64, lv)


def test_tile_paints_with_emblem():
    th = ui.Theme((1280, 720), "gulf")
    app = config.parse({"rows": [{"title": "X", "apps": [
        {"id": "sleep", "name": "Sleep", "command": "systemctl suspend"}]}]}).rows[0].apps[0]
    for lit in (False, True):
        assert ui.paint_tile((th.tile_w, th.tile_h), app, th, lit).get_size() == (th.tile_w, th.tile_h)


def test_flatpak_icon_found_for_tiles_that_run_the_flatpak(tmp_path, monkeypatch):
    apps_dir = tmp_path / "flatpak/app"
    icon = tmp_path / "flatpak/exports/share/icons/hicolor/256x256/apps/tv.kodi.Kodi.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"png")
    monkeypatch.setattr(config, "flatpak_dirs", lambda: [apps_dir])
    rows = config.parse({"rows": [{"title": "X", "apps": [
        {"id": "kodi", "name": "Kodi", "flatpak": "tv.kodi.Kodi"},
        {"id": "ea", "name": "EA", "flatpak": "tv.kodi.Kodi", "command": ["hearth-lutris-app", "ea"]},
    ]}]}).rows[0].apps
    assert config.flatpak_icon(rows[0]) == str(icon)
    assert config.flatpak_icon(rows[1]) is None  # needs it, doesn't run it: no borrowed icon
