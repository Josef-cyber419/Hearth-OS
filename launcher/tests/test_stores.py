"""Epic and GOG games (Heroic) and Battle.net and other Lutris games in
Hearth's Library, and the Battle.net tile."""

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from conftest import REPO
from hearth import library


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path


def heroic(home: Path) -> Path:
    base = home / ".var/app/com.heroicgameslauncher.hgl/config"
    legendary = base / "heroic/legendaryConfig/legendary"
    legendary.mkdir(parents=True)
    (legendary / "installed.json").write_text(json.dumps({
        "Quail": {"app_name": "Quail", "title": "Hades", "install_path": "/home/me/Games/Heroic/Hades"},
        "QuailDLC": {"app_name": "QuailDLC", "title": "Hades Soundtrack", "is_dlc": True}}))
    gog = base / "heroic/gog_store"
    gog.mkdir(parents=True)
    (gog / "installed.json").write_text(json.dumps({"installed": [
        {"appName": "1207658924", "platform": "windows", "install_path": "/home/me/Games/Heroic/Witcher 3"},
        {"appName": "999", "platform": "windows", "install_path": "/home/me/Games/Heroic/Some Game"}]}))
    cache = base / "heroic/store_cache"
    cache.mkdir(parents=True)
    (cache / "gog_library.json").write_text(json.dumps({"games": [
        {"app_name": "1207658924", "title": "The Witcher 3: Wild Hunt"}]}))
    return base


def lutris(home: Path) -> Path:
    base = home / ".var/app/net.lutris.Lutris/data/lutris"
    base.mkdir(parents=True)
    con = sqlite3.connect(base / "pga.db")
    con.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT, slug TEXT, runner TEXT, installed INTEGER,"
                " lastplayed INTEGER, playtime REAL, hidden INTEGER, service TEXT)")
    con.executemany("INSERT INTO games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        (1, "Battle.net", "battlenet", "wine", 1, 1700000000, 1.0, 0, None),
        (2, "Diablo IV", "diablo-iv", "wine", 1, 1750000000, 12.5, 0, "battlenet"),
        (3, "Old Game", "old-game", "wine", 0, 0, 0.0, 0, None),
        (4, "Hidden Game", "hidden-game", "wine", 1, 0, 0.0, 1, None),
        (5, "Quake", "quake", "linux", 1, 0, 0.0, 0, None),
        (6, "EA app", "ea-app", "wine", 1, 0, 0.0, 0, None),
        (7, "Ubisoft Connect", "ubisoft-connect", "wine", 1, 0, 0.0, 0, None),
        (8, "Mass Effect Legendary Edition", "mass-effect-le", "wine", 1, 1740000000, 3.0, 0, "ea_app"),
        (9, "Far Cry 5", "far-cry-5", "wine", 1, 0, 0.0, 0, "ubisoft")])
    con.commit()
    con.close()
    (base / "coverart").mkdir()
    (base / "coverart/diablo-iv.jpg").write_bytes(b"jpg")
    return base


def test_heroic_epic_and_gog_games(home):
    heroic(home)
    games = {g.key: g for g in library.heroic_games()}
    assert set(games) == {"epic:Quail", "gog:1207658924", "gog:999"}  # no DLC
    hades = games["epic:Quail"]
    assert hades.title == "Hades" and hades.platform == "Epic Games"
    assert hades.command == ("flatpak", "run", "com.heroicgameslauncher.hgl",
                             "heroic://launch?appName=Quail&runner=legendary")
    assert games["gog:1207658924"].title == "The Witcher 3: Wild Hunt"
    assert games["gog:1207658924"].command[-1] == "heroic://launch?appName=1207658924&runner=gog"
    assert games["gog:999"].title == "Some Game"  # not in the library cache: its folder name
    assert games["gog:999"].platform == "GOG"


def test_heroic_names_are_quoted():
    assert library.heroic_url("a b&c", "legendary") == "heroic://launch?appName=a%20b%26c&runner=legendary"


def test_lutris_games(home):
    base = lutris(home)
    games = {g.key: g for g in library.lutris_games()}
    assert set(games) == {"lutris:diablo-iv", "lutris:quake", "lutris:mass-effect-le", "lutris:far-cry-5"}
    # not the store apps themselves, uninstalled or hidden
    d4 = games["lutris:diablo-iv"]
    assert d4.platform == "Battle.net" and d4.last_played == 1750000000 and d4.playtime == 12.5 * 3600
    assert d4.command == ("flatpak", "run", "net.lutris.Lutris", "lutris:rungameid/2")
    assert d4.art == str(base / "coverart/diablo-iv.jpg")
    assert games["lutris:quake"].platform == "PC"


def test_in_the_library_with_launchers_keeping_their_own_time(home):
    heroic(home)
    lutris(home)
    library.add_playtime("lutris:diablo-iv", 600)  # started from Hearth: Lutris counted it already
    library.add_playtime("epic:Quail", 600)  # Hearth counts Heroic's games
    games = {g.key: g for g in library.all_games()}
    assert games["lutris:diablo-iv"].playtime == 12.5 * 3600
    assert games["epic:Quail"].playtime == 600
    assert list(games)[0] == "lutris:diablo-iv"  # most recently played first
    assert library.as_app(games["epic:Quail"]).platform == "Epic Games"


def test_nothing_installed(home):
    assert library.heroic_games() == [] and library.lutris_games() == []
    broken = home / ".var/app/net.lutris.Lutris/data/lutris"
    broken.mkdir(parents=True)
    (broken / "pga.db").write_text("not a database")
    assert library.lutris_games() == []


def test_ea_and_ubisoft_games_under_their_store(home):
    lutris(home)
    by_key = {g.key: g for g in library.lutris_games()}
    assert (by_key["lutris:mass-effect-le"].system, by_key["lutris:mass-effect-le"].platform) == ("ea", "EA")
    assert (by_key["lutris:far-cry-5"].system, by_key["lutris:far-cry-5"].platform) == ("ubisoft", "Ubisoft")
    assert not {"lutris:ea-app", "lutris:ubisoft-connect", "lutris:battlenet"} & by_key.keys()  # own tiles
    assert library.STORES["ea"] == "EA" and library.STORES["ubisoft"] == "Ubisoft"


LUTRIS_APP = REPO / "image/system_files/usr/libexec/hearth/hearth-lutris-app"


@pytest.mark.parametrize("script,slug", [("hearth-battlenet", "battlenet"), ("hearth-lutris-app", "ea-app"),
                                         ("hearth-lutris-app", "ubisoft-connect")])
@pytest.mark.parametrize("installed", [True, False])
def test_store_app_tile_installs_then_runs(tmp_path, installed, script, slug):
    home = tmp_path
    base = lutris(home)
    if not installed:
        con = sqlite3.connect(base / "pga.db")
        con.execute("UPDATE games SET installed = 0 WHERE slug = ?", (slug,))
        con.commit()
        con.close()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "calls"
    (bin_ / "flatpak").write_text(f'#!/usr/bin/bash\necho "$*" >> {log}\nexit 0\n')
    (bin_ / "flatpak").chmod(0o755)
    args = [str(LUTRIS_APP.parent / script)] + ([slug] if script == "hearth-lutris-app" else [])
    subprocess.run(args, check=True, env={"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(home)})
    ran = log.read_text().splitlines()[-1]
    assert ran == (f"run net.lutris.Lutris lutris:rungame/{slug}" if installed
                   else f"run net.lutris.Lutris lutris:install/{slug}")


def test_store_app_refuses_odd_slugs(tmp_path):
    r = subprocess.run([str(LUTRIS_APP), "../../etc"], capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert r.returncode == 2


def test_tiles(shipped_config):
    from hearth import config as cfg

    config = cfg.load(shipped_config, hide=False)
    epic, bnet = config.app("epic"), config.app("battlenet")
    assert epic.flatpak == "com.heroicgameslauncher.hgl" and epic.command[:2] == ("flatpak", "run")
    for app, slug in ((bnet, "battlenet"), (config.app("ea"), "ea-app"), (config.app("ubisoft"), "ubisoft-connect")):
        assert app.command == ("/usr/libexec/hearth/hearth-lutris-app", slug)
        assert app.flatpak == "net.lutris.Lutris" and app.pointer
    assert bnet.pointer and not epic.pointer  # Heroic has its own controller navigation
