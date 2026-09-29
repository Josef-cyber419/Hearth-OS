"""Settings → Privacy: Hearth's promise, and turning off the TV's tracking."""

import time

from hearth import privacy, settings, settings_app, tv
from hearth.settings_app import SettingsApp


def test_tv_makes_as_they_name_themselves_over_cec():
    assert privacy.guide_for("LG").key == "lg"
    assert privacy.guide_for("Samsung").key == "samsung"
    assert privacy.guide_for("Sony Corporation").key == "sony"
    assert privacy.guide_for("Hisense").key == "hisense"
    assert privacy.guide_for("Toshiba") is None and privacy.guide_for(None) is None and privacy.guide_for("") is None
    assert privacy.guide_for("Algonquin") is None  # "lg" inside a word isn't LG


def test_every_guide_has_steps_short_enough_to_read():
    for g in privacy.GUIDES:
        assert 2 <= len(g.steps) <= 4 and g.look_for
        assert all(len(s) <= 120 for s in g.steps), g.key
    assert privacy.GUIDES[-1].key == "other"


def page(app):
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("privacy")
    app.load_for("privacy")
    for _ in range(100):
        if not app.jobs._running:
            break
        time.sleep(0.02)
    app.tick()
    app.refresh()
    return {i.key: i for i in app.menu.tabs[app.menu.tab].items}


def test_privacy_page_follows_the_tv_it_finds(shipped_config, monkeypatch):
    monkeypatch.setattr(tv, "vendor", lambda *a, **k: "Samsung")
    items = page(SettingsApp(shipped_config))
    assert items["tv-make"].options[items["tv-make"].value] == "Samsung"
    assert "Samsung" in items["tv-make"].detail
    assert "Viewing Information Services" in items["tv-step-2"].detail
    assert "No ads" in items["hearth"].detail


def test_picking_a_make_by_hand(shipped_config, monkeypatch):
    monkeypatch.setattr(tv, "vendor", lambda *a, **k: None)  # no CEC adapter
    app = SettingsApp(shipped_config)
    items = page(app)
    assert items["tv-make"].options[items["tv-make"].value] == "Other"
    assert "CEC adapter" in items["tv-make"].detail
    items["tv-make"].on_change([g.key for g in privacy.GUIDES].index("vizio"))
    assert settings.load()["privacy"]["tv"] == "vizio"
    items = page(app)
    assert items["tv-make"].options[items["tv-make"].value] == "Vizio"
    assert "Viewing Data" in items["tv-step-2"].detail
