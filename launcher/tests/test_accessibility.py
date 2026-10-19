"""Settings → Accessibility: bigger text and the high-contrast look, each person's own."""

import pygame
import pytest

from hearth import profiles, settings, settings_app, style, ui
from hearth import config as cfg
from hearth.model import Home
from hearth.quickmenu_view import QuickMenuView


@pytest.fixture(autouse=True)
def standard_text():
    style.set_text_scale("normal")
    yield
    style.set_text_scale("normal")


@pytest.fixture
def surface():
    pygame.display.init()
    pygame.font.init()
    yield pygame.display.set_mode((1280, 720))
    pygame.quit()


def test_settings_parse():
    c = cfg.parse({"accessibility": {"text_size": "larger", "contrast": True}})
    assert c.text_size == "larger" and c.contrast and c.scheme == "contrast"
    assert cfg.parse({}).text_size == "normal" and not cfg.parse({}).contrast
    assert cfg.parse({"theme": {"livery": "brg"}}).scheme == "brg"
    with pytest.raises(cfg.ConfigError):
        cfg.parse({"accessibility": {"text_size": "huge"}})


def test_text_scale_makes_every_font_bigger(surface):
    small = style.Type(1.0)(20).get_height()
    style.set_text_scale("larger")
    assert style.Type(1.0)(20).get_height() > small * 1.25
    style.set_text_scale("normal")
    assert style.Type(1.0)(20).get_height() == small


def test_bigger_text_gets_taller_header_and_rows(surface):
    before = ui.Theme((1920, 1080))
    style.set_text_scale("larger")
    after = ui.Theme((1920, 1080))
    assert after.header_h > before.header_h and after.row_title_h > before.row_title_h
    assert after.tile_w == before.tile_w  # the tiles themselves stay


def test_high_contrast_is_not_a_livery_to_pick():
    assert "contrast" not in style.liveries() and "gulf" in style.liveries()
    assert style.livery("contrast").contrast and not style.livery("gulf").contrast


def test_high_contrast_home_screen_draws_plain_black_behind_the_rows(surface, shipped_config):
    config = cfg.load(shipped_config)
    screen = ui.HomeScreen(surface, Home(config), config.title, livery="contrast")
    screen.draw()
    assert screen.theme.contrast
    backdrop = screen._make_backdrop(config.rows[0].apps[0])
    assert backdrop.get_at((10, 10))[:3] == (0, 0, 0)
    tile = ui.paint_tile((344, 204), config.rows[0].apps[0], screen.theme, True)
    assert tile.get_at((172, 2))[:3] == style.LIVERIES["contrast"].accent  # the thick yellow ring


def test_quick_menu_rows_grow_with_the_text(surface):
    view = QuickMenuView((1280, 720))
    assert view.row_scale == 1.0
    standard = view.f_label.get_height()
    style.set_text_scale("large")
    view.set_theme("gulf")
    assert view.row_scale > 1.0
    assert view.f_label.get_height() > standard


def test_settings_page_changes_text_size_and_contrast(shipped_config, surface):
    app = settings_app.SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("accessibility")
    app.refresh()
    items = {i.key: i for i in app.menu.current.items}
    assert items["text-size"].value == 0 and items["contrast"].value is False
    items["text-size"].on_change(2)
    items["contrast"].on_change(True)
    assert settings.load()["accessibility"] == {"text_size": "larger", "contrast": True}
    c = cfg.load(shipped_config)
    assert c.text_size == "larger" and c.contrast and c.scheme == "contrast"
    # Live preview: the Settings view follows the choice.
    view = settings_app.SettingsView(surface.get_size())
    view.draw_settings(surface, app)
    assert view.lv.contrast and style.TEXT_SCALE == style.TEXT_SIZES["larger"]


def test_each_person_has_their_own(shipped_config, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    profiles.start("Joseph", "1234")
    profiles.add("Sam")
    settings.put("accessibility", "text_size", "large")  # the owner's
    profiles.switch("sam", tmp_path / "home")
    assert cfg.load(shipped_config).text_size == "normal"
    settings.put("accessibility", "contrast", True)
    assert cfg.load(shipped_config).contrast and cfg.load(shipped_config).text_size == "normal"
    profiles.switch(profiles.OWNER, tmp_path / "home")
    c = cfg.load(shipped_config)
    assert c.text_size == "large" and not c.contrast


def test_larger_text_keeps_labels_clear_of_their_controls(surface, monkeypatch):
    """Long names on switches, choices, sliders and readings are cut or
    wrapped, never drawn under the control (field reports #59, #62, #63)."""
    from hearth import style as st
    from hearth.quickmenu import Item, QuickMenu, Tab

    style.set_text_scale("larger")
    view = QuickMenuView((1280, 720))
    view.set_theme("gulf")
    long = "Built-in Audio Analog Stereo (Family 17h/19h/1ah HD Audio Controller)"
    items = [
        Item("t", "Share your presence with Discord friends everywhere", "toggle", value=True,
             detail="Lets Discord show what you're playing to everyone on your friends list and in servers"),
        Item("c", "Where the sound goes when a game starts", "choice", value=0, options=("HDMI (TV)", "Headset")),
        Item("s", "Volume", "slider", value=70, detail=long),
        Item("m", "GPU", "meter", value=50, unit="81 °C", detail="Hot but not throttling, keep an eye on it"),
        Item("a", "Take a screenshot of whatever is on the TV right now", "action"),
    ]
    menu = QuickMenu([Tab("one", "Audio", "audio", items), Tab("two", "Performance", "perf", []),
                      Tab("three", "System", "system", []), Tab("four", "Discord", "discord", [])])
    rendered = []
    real = st.clip

    def clip(font, text, width, color):
        out = real(font, text, width, color)
        rendered.append((text, width, out.get_width()))
        return out

    monkeypatch.setattr(st, "clip", clip)
    layer = pygame.Surface((1280, 720), pygame.SRCALPHA)
    view.draw(layer, menu, "Game", paused=False, t=1.0)
    assert len(rendered) >= 5 and all(w <= room for _, room, w in rendered)
    assert any(text == long and w < st.Type(view.u)(19, "text", "medium").size(long)[0] for text, _, w in rendered)
    ends = []
    real_hint = st.button_hint

    def hint(surf, x, cy, button, label, t, lv, size=1.0):
        ends.append(real_hint(surf, x, cy, button, label, t, lv, size))
        return ends[-1]

    monkeypatch.setattr(st, "button_hint", hint)
    view.draw_hints(layer, 0, 40, 420, (("A", "Select"), ("Y", "Mute"), ("LB", "Tab"), ("RB", "Tab"), ("B", "Close")))
    assert ends[-1] <= 420  # shrunk until the last one fits


def test_every_settings_page_draws_at_larger_text(surface, shipped_config):
    style.set_text_scale("larger")
    app = settings_app.SettingsApp(shipped_config)
    view = settings_app.SettingsView(surface.get_size())
    for i, _ in enumerate(settings_app.CATEGORIES):
        app.menu.tab = i
        app.refresh()
        view.draw_settings(surface, app)
