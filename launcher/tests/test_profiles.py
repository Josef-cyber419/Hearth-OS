import time

import pytest

from hearth import family, layout, profiles, settings, steamlogin
from hearth.model import Nav


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


def two_people():
    profiles.start("Joseph", "1234", family_rules={"pin": "x$y", "daily_minutes": 60})
    return profiles.add("Sam")


# -- one person: nothing changes ----------------------------------------------------------


def test_one_person_is_seamless(tmp_path):
    assert profiles.people() == [] and not profiles.active()
    assert profiles.current() is None and profiles.is_admin()
    assert profiles.current_id() == profiles.OWNER
    assert profiles.state_dir(tmp_path) == tmp_path
    assert family.needs_pin("settings") is None


# -- adding people ---------------------------------------------------------------------------


def test_adding_a_person_makes_the_first_the_admin():
    sam = two_people()
    joseph = profiles.get(profiles.OWNER)
    assert profiles.active() and joseph.admin and joseph.name == "Joseph" and not sam.admin
    assert profiles.check_pin(profiles.OWNER, "1234") and not profiles.check_pin(profiles.OWNER, "4321")
    assert profiles.check_admin_pin("1234")
    assert sam.rules == {"daily_minutes": 60}  # the household limits from before, without the old PIN
    assert profiles.current_id() == profiles.OWNER and sam.id == "sam"
    assert profiles.add("Sam").id == "sam-2"


def test_an_admin_needs_a_pin_and_someone_must_be_admin():
    sam = two_people()
    with pytest.raises(ValueError):
        profiles.update(sam.id, admin=True)  # no PIN yet
    profiles.set_pin(sam.id, "5555")
    profiles.update(sam.id, admin=True)
    profiles.update(profiles.OWNER, admin=False)
    with pytest.raises(ValueError):
        profiles.update(sam.id, admin=False)
    with pytest.raises(ValueError):
        profiles.set_pin(sam.id, None)


def test_removing_the_last_other_person_goes_back_to_one(home):
    sam = two_people()
    profiles.switch(sam.id, home)
    profiles.remove(sam.id)
    assert not profiles.active() and profiles.current_id() == profiles.OWNER
    with pytest.raises(ValueError):
        profiles.remove(profiles.OWNER)


# -- each person's own ------------------------------------------------------------------------


def test_favorites_and_hidden_tiles_are_each_persons_own(home):
    layout.set_favorite("kodi", True)
    settings.set_hidden("plex", True)
    settings.put("theme", "livery", "martini")
    sam = two_people()
    profiles.switch(sam.id, home)
    mine = settings.load()
    assert "favorites" not in mine and "hide" not in mine
    assert mine["theme"]["livery"] == "martini"  # the look is the household's
    settings.toggle_in("favorites", "steam", True)
    assert settings.load()["favorites"] == ["steam"]
    settings.put("theme", "livery", "brg")  # household settings still save for everyone
    profiles.switch(profiles.OWNER, home)
    back = settings.load()
    assert back["favorites"] == ["kodi"] and back["hide"] == ["plex"] and back["theme"]["livery"] == "brg"


def test_play_state_is_each_persons_own(home):
    from hearth import library

    sam = two_people()
    library.record_play("rom:n64:Mario.z64")
    profiles.switch(sam.id, home)
    assert library.played() == {}
    assert "people/sam" in str(library._played_path())


# -- limits -----------------------------------------------------------------------------------


def test_limits_follow_the_person_and_an_admins_pin_lets_them_past(home):
    sam = two_people()
    profiles.set_rule(sam.id, "locked", ["kodi"])
    assert not family.rules().active  # the admin has no limits
    profiles.switch(sam.id, home)
    r = family.rules()
    assert r.active and r.daily_minutes == 60 and r.locked == {"kodi"}
    assert family.needs_pin("kodi") == "This one is locked"
    assert family.needs_pin("settings") == "Needs an admin's PIN"
    assert family.needs_pin("desktop") == "Needs an admin's PIN"
    assert family.check_pin("1234") and not family.check_pin("0000")
    family.add_played(3600)
    assert family.needs_pin("steam") == family.TIME_UP
    assert family.played_today(pid=profiles.OWNER) == 0  # Joseph's own count


def test_the_picker_pin_is_the_persons_own(home):
    from hearth import family as fam

    sam = two_people()
    profiles.set_pin(sam.id, "2468")
    entry = fam.PinEntry("Sam's PIN", checker=lambda pin: profiles.check_pin(sam.id, pin))
    for d in "1234":
        entry.type(d)
    assert entry.message == "Not that one"  # the admin's PIN isn't Sam's
    assert [entry.type(d) for d in "2468"][-1] == "ok"


# -- apps' data and Steam -----------------------------------------------------------------------


def test_discord_data_swaps_with_the_person(home):
    live = home / ".var/app/com.discordapp.Discord"
    live.mkdir(parents=True)
    (live / "joseph.txt").write_text("j")
    sam = two_people()
    assert profiles.switch(sam.id, home) == []
    assert not live.exists()  # Sam starts signed out
    live.mkdir(parents=True)
    (live / "sam.txt").write_text("s")
    profiles.switch(profiles.OWNER, home)
    assert (live / "joseph.txt").exists() and not (live / "sam.txt").exists()
    profiles.switch(sam.id, home)
    assert (live / "sam.txt").exists()


LOGINUSERS = '''"users"
{
\t"76561197960265729"
\t{
\t\t"AccountName"\t\t"joe_steam"
\t\t"PersonaName"\t\t"Joe"
\t\t"RememberPassword"\t\t"1"
\t\t"MostRecent"\t\t"1"
\t}
\t"76561197960265730"
\t{
\t\t"AccountName"\t\t"sam_steam"
\t\t"PersonaName"\t\t"Sammy"
\t\t"MostRecent"\t\t"0"
\t}
}
'''
REGISTRY = '''"Registry"
{
\t"HKCU"
\t{
\t\t"Software"
\t\t{
\t\t\t"Valve"
\t\t\t{
\t\t\t\t"Steam"
\t\t\t\t{
\t\t\t\t\t"AutoLoginUser"\t\t"joe_steam"
\t\t\t\t\t"Language"\t\t"english"
\t\t\t\t}
\t\t\t}
\t\t}
\t}
}
'''


def steam_files(home):
    cfg = home / ".local/share/Steam/config"
    cfg.mkdir(parents=True)
    (cfg / "loginusers.vdf").write_text(LOGINUSERS)
    (home / ".steam").mkdir()
    (home / ".steam/registry.vdf").write_text(REGISTRY)


def test_steam_accounts_and_auto_login(home):
    steam_files(home)
    assert steamlogin.accounts(home) == [("joe_steam", "Joe"), ("sam_steam", "Sammy")]
    assert steamlogin.most_recent(home) == "joe_steam"
    assert steamlogin.account_id("sam_steam", home) == "2"
    steamlogin.set_auto_login("sam_steam", home)
    reg = (home / ".steam/registry.vdf").read_text()
    assert '"AutoLoginUser"\t\t"sam_steam"' in reg and '"Language"\t\t"english"' in reg
    assert steamlogin.most_recent(home) == "sam_steam"
    steamlogin.set_auto_login("", home)  # someone new: Steam asks
    assert steamlogin.most_recent(home) is None


def test_switching_signs_steam_in_to_the_persons_account(home):
    steam_files(home)
    sam = two_people()
    profiles.update(sam.id, steam="sam_steam")
    profiles.note_steam_account(home)  # Joseph was on joe_steam
    assert profiles.get(profiles.OWNER).steam == "joe_steam"
    profiles.switch(sam.id, home)
    assert steamlogin.most_recent(home) == "sam_steam"
    assert profiles.steam_account_id(home) == "2"
    profiles.switch(profiles.OWNER, home)
    assert steamlogin.most_recent(home) == "joe_steam"


# -- the picker and Settings ---------------------------------------------------------------------


def test_picker_has_a_tile_per_person():
    from hearth import hub

    two_people()
    tiles = hub.picker_config().rows[0].apps
    assert [(a.name, a.command) for a in tiles] == [("Joseph", ("hearth:person", "owner")),
                                                    ("Sam", ("hearth:person", "sam"))]


def test_switch_person_tile_only_with_people(shipped_config):
    import argparse

    from hearth import hub

    args = argparse.Namespace(config=shipped_config, show_all=False)
    ids = lambda: {a.id for r in hub.home_config(args).rows for a in r.apps}  # noqa: E731
    assert "people" not in ids()
    two_people()
    assert "people" in ids()


def type_into(app, text):
    app.keyboard.type(text)
    app.handle(Nav.MENU)  # Start = done


def test_settings_adds_the_first_person(shipped_config, monkeypatch):
    from hearth import settings_app
    from hearth.settings_app import SettingsApp

    settings.put("family", "daily_minutes", 90)
    app = SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("people")
    app.refresh()
    app.zone = "items"
    app.menu.select("people-start")
    app.handle(Nav.SELECT)
    type_into(app, "Joseph")
    type_into(app, "1234")
    type_into(app, "Sam")
    assert app.keyboard is None
    assert [p.name for p in profiles.people()] == ["Joseph", "Sam"]
    assert profiles.get("sam").rules == {"daily_minutes": 90} and "family" not in settings.load()
    keys = [i.key for i in app.menu.current.items]
    assert "person-steam" in keys and "person-remove" in keys


def test_family_page_edits_each_persons_limits(shipped_config):
    from hearth import settings_app
    from hearth.settings_app import SettingsApp

    two_people()
    app = SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("family")
    app.refresh()
    items = {i.key: i for i in app.menu.current.items}
    assert items["family-who"].options == ("Sam",)
    items["family-daily"].on_change(list(family.DAILY_CHOICES).index(120))
    items["lock-kodi"].on_change(True)
    assert profiles.get("sam").rules == {"daily_minutes": 120, "locked": ["kodi"]}


def test_pbkdf2_isnt_too_slow_for_the_picker():
    t = time.monotonic()
    profiles.pin_matches(profiles.hash_pin("1234"), "1234")
    assert time.monotonic() - t < 2


def test_hub_switch_closes_whats_personal_first(home, monkeypatch):
    from hearth import hub, session

    two_people()
    closed = []
    monkeypatch.setattr(hub, "close_paused", lambda app_id: (closed.append(app_id), session.update(
        lambda s: s.__setitem__("suspended", [e for e in s["suspended"] if e["id"] != app_id]))))
    monkeypatch.setattr(session, "stop_entry", lambda info: closed.append(info["name"]))
    session.update(lambda s: s.update(suspended=[{"id": "game:rom:n64:x", "name": "X"}],
                                      background={"discord": {"name": "Discord"}}))
    hub.switch_person("sam")
    assert profiles.current_id() == "sam"
    assert closed == ["game:rom:n64:x", "Discord"] and session.read()["background"] == {}
