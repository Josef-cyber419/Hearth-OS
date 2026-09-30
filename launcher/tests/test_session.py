from hearth import session
from hearth.gamescope import HOME_APPID, appid_for


def test_state_update_and_defaults_isolated():
    session.update(lambda s: s["background"].__setitem__("discord", {"pid": 1}))
    assert session.read()["background"] == {"discord": {"pid": 1}}
    assert session.DEFAULT_STATE["background"] == {}


def test_real_ids_come_back_from_the_cgroup():
    # Field report #39: PC ports' windows were tagged with the tidied id, so
    # gamescope never showed them.
    app_id = "game:pc:Dusklight v2.0.2-linux.AppImage"
    unit = session.unit_name("app", app_id)
    cgroup = f"0::/user.slice/user@1000.service/app.slice/{unit}"
    state = {"foreground": {"id": app_id, "unit": unit}, "background": {}, "suspended": []}
    assert session.app_for_cgroup(cgroup, state) == ("app", app_id)
    moved = {"foreground": {"id": app_id, "unit": "other.scope"}, "background": {}, "suspended": []}
    assert session.app_for_cgroup(cgroup, moved) == ("app", app_id)  # by the tidied id
    paused = {"foreground": None, "background": {}, "suspended": [{"id": app_id, "unit": unit}]}
    assert session.app_for_cgroup(cgroup, paused) == ("app", app_id)


def test_unit_names_round_trip_through_cgroup():
    unit = session.unit_name("app", "hdmi-in_2")
    cgroup = f"0::/user.slice/user-1000.slice/user@1000.service/app.slice/{unit}\n"
    assert session.app_for_cgroup(cgroup) == ("app", "hdmi-in_2")
    assert session.app_for_cgroup("0::/user.slice/other.scope") is None


def test_focus_appid():
    fg = {"id": "kodi", "tag_windows": True}
    assert session.focus_appid({"focus": "home", "foreground": None, "background": {}}) == HOME_APPID
    assert session.focus_appid({"focus": "foreground", "foreground": fg, "background": {}}) == appid_for("kodi")
    both = {"focus": "discord", "foreground": fg, "background": {"discord": {}}}
    assert session.focus_appid(both) == appid_for("discord")
    steam = {"focus": "foreground", "foreground": {"id": "steam", "tag_windows": False}, "background": {}}
    assert session.focus_appid(steam) is None


def test_appids_are_distinct_and_in_range():
    ids = {appid_for(a) for a in ("steam", "kodi", "discord", "youtube", "emulation")}
    assert len(ids) == 5 and all(HOME_APPID < i < HOME_APPID + 0x10000 for i in ids)


def test_focus_order_falls_back_to_home():
    from hearth.gamescope import HOME_APPID, appid_for

    game = {"id": "kodi", "tag_windows": True}
    assert session.focus_order({"focus": "foreground", "foreground": game, "background": {}}) == \
        [appid_for("kodi"), HOME_APPID]
    discord_over_game = {"focus": "discord", "foreground": game, "background": {"discord": {}}}
    assert session.focus_order(discord_over_game) == [appid_for("discord"), appid_for("kodi"), HOME_APPID]
    steam = {"focus": "foreground", "foreground": {"id": "steam", "tag_windows": False}, "background": {}}
    assert session.focus_order(steam) is None
