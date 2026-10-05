import time

import pygame
import pytest
from fakes import FakeActions, FakePactl

from hearth import config as cfg
from hearth import style, ui
from hearth.audio import Audio
from hearth.model import Home, Nav
from hearth.quickmenu import Context, QuickMenu, build_tabs
from hearth.quickmenu_view import QuickMenuView


@pytest.fixture
def surface():
    pygame.display.init()
    pygame.font.init()
    yield pygame.display.set_mode((1280, 720))
    pygame.quit()


def test_bundled_fonts_load(surface):
    for family, weight in style.Type.FILES:
        path = style.FONT_DIR / style.Type.FILES[(family, weight)]
        assert path.exists()
        assert style.Type(1.0)(20, family, weight).render("Hearth 12:34", True, (255, 255, 255)).get_width() > 0


def test_unknown_livery_falls_back():
    assert style.livery("nope") is style.LIVERIES["gulf"]


@pytest.mark.parametrize("livery", sorted(style.LIVERIES))
def test_every_livery_renders(surface, shipped_config, livery):
    config = cfg.load(shipped_config)
    screen = ui.HomeScreen(surface, Home(config), config.title, livery=livery, intro="boot")
    screen.running = {"discord"}
    for nav in [None, Nav.RIGHT, Nav.DOWN, Nav.MENU]:
        if nav:
            screen.handle(nav)
        for _ in range(3):
            screen.draw()
    ui.draw_loading(surface, config.rows[0].apps[1], livery)

    pactl, actions = FakePactl(), FakeActions()
    audio = Audio(pactl)
    state = {"foreground": {"id": "game", "name": "Game"}, "background": {}, "focus": "foreground"}
    menu = QuickMenu(build_tabs(Context(audio, audio.snapshot(), state, actions, True)))
    view = QuickMenuView((1280, 720), livery)
    layer = pygame.Surface((1280, 720), pygame.SRCALPHA)
    for tab in range(len(menu.tabs)):
        menu.tab = tab
        for t in (0.0, 0.5, 1.0):
            view.draw(layer, menu, "Game", True, t)


def test_boot_intro_ends_and_input_skips_it(surface, shipped_config):
    config = cfg.load(shipped_config)
    screen = ui.HomeScreen(surface, Home(config), config.title, intro="boot")
    screen.draw()
    assert screen.intro == "boot"
    screen.handle(Nav.RIGHT)
    assert screen.intro is None
    screen = ui.HomeScreen(surface, Home(config), config.title, intro="return")
    screen._intro_t0 -= 5
    screen.draw()
    assert screen.intro is None


def test_launch_transition(surface, shipped_config):
    config = cfg.load(shipped_config)
    screen = ui.HomeScreen(surface, Home(config), config.title)
    screen.draw()
    start = time.monotonic()
    screen.play_launch(screen.home.selected)
    assert ui.LAUNCH_SECONDS <= time.monotonic() - start < ui.LAUNCH_SECONDS + 1


def test_reduced_motion_is_still(surface, shipped_config):
    config = cfg.load(shipped_config)
    screen = ui.HomeScreen(surface, Home(config), config.title, motion="reduced", intro="boot")
    assert screen.intro is None
    screen.draw()
    start = time.monotonic()
    screen.play_launch(screen.home.selected)
    assert time.monotonic() - start < 0.1
    screen.handle(Nav.RIGHT)
    screen.draw()
    assert screen.smooth.values["ind_x"] == screen.theme.margin + screen.theme.tile_w + screen.theme.gap


def test_smoothing_is_frame_rate_independent():
    a = b = 0.0
    for _ in range(6):
        a = style.approach(a, 100, 1 / 60)
    for _ in range(3):
        b = style.approach(b, 100, 1 / 30)
    assert abs(a - b) < 0.5


def test_quick_menu_items_fully_shown_once_open(surface):
    view = QuickMenuView((1280, 720))
    assert all(view._stagger(1.0, i) == 1.0 for i in range(20))
    assert view._stagger(0.0, 0) == 0.0


def test_button_names_follow_the_last_input():
    style.set_prompts("auto")
    style.note_input("playstation")
    assert style.glyph_for("A") == "cross"
    style.note_input("keyboard")
    assert style.glyph_for("A") == "ENTER" and style.glyph_for("B") == "ESC"
    style.note_input("wii")
    assert style.glyph_for("START") == "+"
    style.set_prompts("nintendo")  # a fixed choice wins
    assert style.glyph_for("A") == "B"
    style.set_prompts("auto")
    style.note_input("xbox")


def test_controller_family_from_its_name():
    assert style.controller_family("DualSense Wireless Controller") == "playstation"
    assert style.controller_family("Sony Interactive Entertainment Wireless Controller") == "playstation"
    assert style.controller_family("Nintendo Switch Pro Controller") == "nintendo"
    assert style.controller_family("Xbox Wireless Controller") == "xbox"
    assert style.controller_family("") == "xbox"


def test_keys_switch_hints_unless_a_wii_remote_sent_them(monkeypatch):
    import pygame

    from hearth import input as input_

    mapper = input_.InputMapper()
    style.set_prompts("auto")
    monkeypatch.setattr(input_, "wii_recently", lambda: False)
    mapper.translate(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert style.prompt_style() == "keyboard"
    monkeypatch.setattr(input_, "wii_recently", lambda: True)
    mapper.translate(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
    assert style.prompt_style() == "wii"
    style.note_input("xbox")


def test_arrows_become_chevrons_barlow_can_draw():
    assert style.plain("Settings → Home ← back") == "Settings › Home ‹ back"


def test_clip_cuts_with_an_ellipsis_instead_of_squeezing(surface):
    f = style.Type(1.0)(27, "text", "semibold")
    long = "Built-in Audio Analog Stereo (Family 17h/19h HD Audio Controller)"
    whole = style.clip(f, long, 5000, (255, 255, 255))
    assert whole.get_width() == f.size(long)[0]
    cut = style.clip(f, long, 300, (255, 255, 255))
    assert cut.get_width() <= 300 and cut.get_height() == whole.get_height()  # same size type, less of it
    assert style.clip(f, long, 4, (255, 255, 255)).get_width() <= f.size("…")[0]
    assert style.clip(f, "Settings → Audio", 5000, (255, 255, 255)).get_width() == f.size("Settings › Audio")[0]


def test_wrap_gives_two_lines_and_an_ellipsis_at_the_end(surface):
    f = style.Type(1.0)(19, "text", "medium")
    text = "Hidden tiles → Settings → Home screen brings them back for the person who hid them, whenever they like"
    lines = style.wrap(f, text, 320)
    assert len(lines) == 2 and all(f.size(line)[0] <= 320 for line in lines)
    assert lines[1].endswith("…") and "›" in " ".join(lines) and "→" not in " ".join(lines)
    assert style.wrap(f, "Short", 320) == ["Short"]
    assert len(style.wrap(f, text, 320, lines=3)) == 3
