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


def test_closing_asks_the_app_to_exit_before_stopping_its_scope(monkeypatch):
    # Field report #41: stopping the scope at once killed an AppImage's FUSE
    # helper with it, and the game died of SIGBUS. The helper is left alone.
    calls = []
    alive = {42: True, 43: True, 44: True}
    monkeypatch.setattr(session, "_processes", lambda proc: {42: (1, "AppRun"), 43: (42, "fusefs"), 44: (42, "dusk")})
    monkeypatch.setattr(session, "_descendants", lambda pid, procs: [43, 44])
    monkeypatch.setattr(session, "holds_fuse", lambda pid, proc: pid == 43)
    monkeypatch.setattr(session.os, "kill", lambda pid, sig: (calls.append(("kill", pid, sig)), alive.update({pid: False})))
    monkeypatch.setattr(session, "_pid_alive", lambda pid: alive[pid])
    monkeypatch.setattr(session, "_units", lambda info: [info["unit"]])
    monkeypatch.setattr(session, "thaw", lambda u: calls.append(("thaw", u)))
    monkeypatch.setattr(session, "stop", lambda u: calls.append(("stop", u)) or True)
    session.stop_entry({"pid": 42, "unit": "hearth-app-x_1.scope"})
    assert calls == [("thaw", "hearth-app-x_1.scope"), ("kill", 42, 15), ("kill", 44, 15), ("stop", "hearth-app-x_1.scope")]


def test_an_app_that_ignores_sigterm_gets_its_scope_stopped(monkeypatch):
    monkeypatch.setattr(session, "_processes", lambda proc: {42: (1, "x")})
    monkeypatch.setattr(session, "_descendants", lambda pid, procs: [])
    monkeypatch.setattr(session, "holds_fuse", lambda pid, proc: False)
    monkeypatch.setattr(session.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(session, "_pid_alive", lambda pid: True)
    assert session.ask_to_exit(42, wait=0.3, sleep=lambda s: None) is False


def test_holds_fuse_reads_the_open_files(tmp_path):
    fd = tmp_path / "7" / "fd"
    fd.mkdir(parents=True)
    (fd / "3").symlink_to("/dev/null")
    assert not session.holds_fuse(7, tmp_path)
    (fd / "4").symlink_to("/dev/fuse")
    assert session.holds_fuse(7, tmp_path)
    assert not session.holds_fuse(8, tmp_path)


def test_steam_games_get_a_window_time_when_gamescope_can_show_them():
    # Field report #45: Steam and its games were always "never showed a window".
    import types

    from hearth.overlay import Overlay

    shown = []
    gs = types.SimpleNamespace(root="root", get_cardinals=lambda win, name: shown)
    fake = types.SimpleNamespace(
        gs=gs, _first_window=set(), STEAM_APPID=769,
        state={"foreground": {"id": "game:steam:814380", "tag_windows": False, "started": 1.0}})
    Overlay._time_steam_window(fake)
    assert fake._first_window == set()  # not showable yet (#40's case)
    shown.append(814380)
    Overlay._time_steam_window(fake)
    assert fake._first_window == {("game:steam:814380", 1.0)}
