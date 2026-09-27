import time
from pathlib import Path

import pygame
import pytest

from hearth import config as cfg
from hearth import emutune, library, network, settings, style, ui
from hearth.input import InputMapper
from hearth.model import Home, Nav

MANIFEST = '''"AppState"
{
	"appid"		"%s"
	"name"		"%s"
	"StateFlags"		"%s"
	"LastPlayed"		"%s"
}
'''


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def make_steam(home: Path) -> Path:
    root = home / ".local/share/Steam"
    apps = root / "steamapps"
    apps.mkdir(parents=True)
    other = home / "games/SteamLibrary"
    (other / "steamapps").mkdir(parents=True)
    (apps / "libraryfolders.vdf").write_text(f'''"libraryfolders"
{{
	"0" {{ "path" "{root}" }}
	"1" {{ "path" "{other}" }}
}}''')
    (apps / "appmanifest_620.acf").write_text(MANIFEST % ("620", "Portal 2", "4", "0"))
    (apps / "appmanifest_1493710.acf").write_text(MANIFEST % ("1493710", "Proton Experimental", "4", "0"))
    (apps / "appmanifest_999.acf").write_text(MANIFEST % ("999", "Half Downloaded", "1026", "0"))
    (other / "steamapps/appmanifest_1245620.acf").write_text(MANIFEST % ("1245620", "ELDEN RING", "4", "1700000000"))
    cfgdir = root / "userdata/1234/config"
    cfgdir.mkdir(parents=True)
    (cfgdir / "localconfig.vdf").write_text('''"UserLocalConfigStore"
{ "Software" { "Valve" { "Steam" { "apps" {
	"620" { "LastPlayed" "1750000000" "Playtime" "90" }
} } } } }''')
    art = root / "appcache/librarycache/620/abc123"
    art.mkdir(parents=True)
    pygame.image.save(pygame.Surface((46, 21)), str(art / "header.jpg"))
    return root


def test_vdf_parser():
    data = library.parse_vdf('"A" { "b" "1" "c" { "d" "say \\"hi\\"" } }')
    assert data == {"A": {"b": "1", "c": {"d": 'say "hi"'}}}


def test_steam_library(home):
    make_steam(home)
    games = {g.title: g for g in library.steam_games()}
    assert set(games) == {"Portal 2", "ELDEN RING"}  # no runtimes, nothing half-installed
    assert games["Portal 2"].last_played == 1750000000
    assert games["ELDEN RING"].last_played == 1700000000  # from the manifest in the second library
    assert games["Portal 2"].art.endswith("620/abc123/header.jpg")
    assert games["Portal 2"].command == (library.STEAM_LAUNCHER, "steam://rungameid/620")


def make_roms(home: Path, monkeypatch) -> None:
    monkeypatch.setattr(library, "flatpak_installed", lambda app: True)
    for system, files in {"psx": ["Crash (USA).cue", "Crash (USA).bin", "FF7 (Disc 1).chd", "FF7 (Disc 2).chd"],
                          "gc": ["Wind Waker.rvz"], "snes": ["Zelda.sfc"], "genesis": ["Sonic.bin"]}.items():
        (home / "ROMs" / system).mkdir(parents=True, exist_ok=True)
        for f in files:
            (home / "ROMs" / system / f).write_text("")
    (home / "ROMs/psx/systeminfo.txt").write_text("")
    cores = home / ".var/app/org.libretro.RetroArch/config/retroarch/cores"
    cores.mkdir(parents=True)
    (cores / "snes9x_libretro.so").write_text("")  # genesis_plus_gx isn't downloaded
    gl = home / "ES-DE/gamelists/gc"
    gl.mkdir(parents=True)
    (gl / "gamelist.xml").write_text('''<?xml version="1.0"?>
<gameList><game><path>./Wind Waker.rvz</path><name>The Legend of Zelda: The Wind Waker</name>
<favorite>true</favorite><lastplayed>20250102T201500</lastplayed></game></gameList>''')
    media = home / "ES-DE/downloaded_media/gc/screenshots"
    media.mkdir(parents=True)
    (media / "Wind Waker.png").write_text("")


def test_rom_library(home, monkeypatch):
    make_roms(home, monkeypatch)
    games = {g.title: g for g in library.rom_games()}
    assert set(games) == {"Crash", "FF7", "The Legend of Zelda: The Wind Waker", "Zelda"}  # no Sonic: no core
    ww = games["The Legend of Zelda: The Wind Waker"]
    assert ww.favorite and ww.last_played > 0 and ww.art.endswith("screenshots/Wind Waker.png")
    assert ww.command[:3] == ("flatpak", "run", "org.DolphinEmu.dolphin-emu") and ww.command[-3:-1] == ("-b", "-e")
    assert games["Crash"].command[-1].endswith("Crash (USA).cue")  # the .cue, not the .bin
    assert games["Zelda"].command[3:5] == ("-f", "-L") and games["Zelda"].platform == "SNES"


def test_pins_recent_and_home_rows(home, monkeypatch, shipped_config):
    make_steam(home)
    make_roms(home, monkeypatch)
    library.record_play("rom:snes:Zelda.sfc")
    games = library.all_games()
    assert games[0].key == "rom:snes:Zelda.sfc"  # played through Hearth just now
    assert [g.title for g in library.recent(games)] == ["Zelda", "Portal 2", "The Legend of Zelda: The Wind Waker",
                                                      "ELDEN RING"]
    settings.toggle_in("pins", "steam:1245620", True)
    assert [g.key for g in library.pinned(games, settings.load()["pins"])] == [
        "steam:1245620", "rom:gc:Wind Waker.rvz"]  # your pin, then ES-DE's favourite
    config = library.with_game_rows(cfg.load(shipped_config), games)
    assert [r.title for r in config.rows[:3]] == ["Continue", "Pinned", "Play"]
    steam_game = config.rows[1].apps[0]
    assert steam_game.id == "game:steam:1245620" and not steam_game.tag_windows and not steam_game.home_button
    settings.put("home", "recent", False)
    assert [r.title for r in library.with_game_rows(cfg.load(shipped_config), games).rows[:2]] == ["Pinned", "Play"]
    rows = [r.title for r in library.library_config(games).rows]
    assert rows[:3] == ["Pinned", "Recently played", "Steam"] and "GameCube" in rows


def test_options_pin_from_home(home, monkeypatch, shipped_config):
    make_steam(home)
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((1280, 720))

        def build():
            return library.with_game_rows(cfg.load(shipped_config))

        screen = ui.HomeScreen(surface, Home(build()), "Hearth")
        screen.rebuild = build
        assert screen.home.config.rows[0].title == "Continue"
        screen.handle(Nav.OPTIONS)
        assert [c[0] for c in screen.options[1]] == ["Pin to home", "Remove from Continue", "Cancel"]
        screen.draw()
        screen.handle(Nav.SELECT)
        assert settings.load()["pins"] == ["steam:620"]
        assert [r.title for r in screen.home.config.rows[:2]] == ["Continue", "Pinned"]
        screen.handle(Nav.OPTIONS)
        screen.handle(Nav.DOWN)
        screen.handle(Nav.SELECT)  # Remove from Continue
        assert settings.load()["hide_recent"] == [screen.home.selected.id.removeprefix("game:")] or \
            "steam:620" in settings.load()["hide_recent"]
        screen.draw()
    finally:
        pygame.quit()


def test_game_tiles_and_loading_card_render(home):
    make_steam(home)
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((1280, 720))
        app = library.as_app(next(g for g in library.steam_games() if g.art))
        th = ui.Theme((1280, 720))
        for lit in (True, False):
            ui.paint_tile((th.tile_w, th.tile_h), app, th, lit)
        ui.draw_loading(surface, app)
    finally:
        pygame.quit()


def test_screen_saver_and_waking(shipped_config):
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((640, 360))
        config = cfg.load(shipped_config)
        assert ui.run(surface, Home(config), "Hearth", max_frames=5, saver_after=0.01) is None
        screen = ui.HomeScreen(surface, Home(config), "Hearth")
        screen.draw_saver()
    finally:
        pygame.quit()


def test_ini_editing_keeps_everything_else():
    text = "; comment\n[Core]\nGFXBackend = OGL\nCPUThread = True\n\n[Display]\nFoo = 1\n"
    out = emutune.set_ini(text, {"Core": {"GFXBackend": "Vulkan", "New": "1"}, "Other": {"X": "2"}})
    assert "; comment" in out and "CPUThread = True" in out and "Foo = 1" in out
    assert "GFXBackend = Vulkan" in out and "GFXBackend = OGL" not in out
    assert out.index("New = 1") < out.index("[Display]")  # added to its own section
    assert "[Other]\nX = 2" in out
    cfgtext = emutune.set_cfg('video_driver = "gl"\naudio_driver = "pulse"\n', {"video_driver": "vulkan", "a": "b"})
    assert 'video_driver = "vulkan"' in cfgtext and 'audio_driver = "pulse"' in cfgtext and 'a = "b"' in cfgtext


def test_tuning_only_touches_existing_configs(home, monkeypatch):
    monkeypatch.setattr(library, "flatpak_installed", lambda app: app in ("net.pcsx2.PCSX2", "org.ppsspp.PPSSPP"))
    ini = home / ".var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text("[UI]\nSettingsVersion = 1\n[EmuCore/GS]\nRenderer = -1\nupscale_multiplier = 1\n")
    results = emutune.apply_all("4k")
    text = ini.read_text()
    assert "Renderer = 14" in text and "upscale_multiplier = 5" in text and "SettingsVersion = 1" in text
    assert "vuThread = true" in text
    assert ini.with_name("PCSX2.ini.hearth-backup").read_text().startswith("[UI]")
    assert results["PPSSPP (PSP)"] == "open it once first, then apply again"
    assert results["Dolphin (GameCube, Wii)"] == "not installed"
    assert emutune.auto("1440p", set()) == {"net.pcsx2.PCSX2"}
    assert "upscale_multiplier = 4" in ini.read_text()


def test_network_test_report():
    def run(argv):
        if argv[0] == "ip":
            return 0, "default via 192.168.1.1 dev enp3s0 proto dhcp\n", ""
        if argv[-1] == "192.168.1.1":
            return 0, "rtt min/avg/max/mdev = 0.4/0.6/0.9/0.1 ms\n", ""
        return 1, "", ""

    assert network.test(run, resolve=lambda name: True) == "Router 1 ms · no internet · names OK"
    assert network.test(lambda argv: (0, "", ""), resolve=lambda n: True).startswith("No router")


def test_button_names_follow_the_controller():
    try:
        style.set_prompts("xbox", "south")
        assert (style.glyph_for("A"), style.glyph_for("Y")) == ("A", "Y")
        style.set_prompts("nintendo", "east")
        assert (style.glyph_for("A"), style.glyph_for("B")) == ("A", "B")  # confirm on the right, as printed
        style.set_prompts("nintendo", "south")
        assert style.glyph_for("A") == "B"  # bottom button, printed "B" on a Nintendo pad
        style.set_prompts("playstation", "south")
        assert (style.glyph_for("A"), style.glyph_for("GUIDE")) == ("cross", "PS")
    finally:
        style.set_prompts("xbox", "south")


def test_confirm_button_swap():
    mapper = InputMapper()
    mapper.swap_confirm = True
    event = pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_B, instance_id=0)
    assert mapper.translate(event, 0) is Nav.SELECT


def test_new_settings_parse_and_validate():
    c = cfg.parse({"theme": {"safe_area": 4}, "home": {"screensaver_minutes": 0, "recent": False},
                   "controllers": {"confirm": "east", "prompts": "playstation"}, "emulation": {"resolution": "4k"}})
    assert (c.safe_area, c.screensaver_minutes, c.home_recent, c.confirm, c.prompts, c.emulation_resolution) == (
        4, 0, False, "east", "playstation", "4k")
    with pytest.raises(cfg.ConfigError):
        cfg.parse({"theme": {"safe_area": 40}})
    sub, offset = style.inset(pygame.Surface((1000, 500)), 5)
    assert sub.get_size() == (900, 450) and offset == (50, 25)
