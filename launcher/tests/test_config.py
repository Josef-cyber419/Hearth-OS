import pytest

from hearth import config as cfg


def test_shipped_config_parses(shipped_config):
    config = cfg.load(shipped_config)
    ids = [a.id for row in config.rows for a in row.apps]
    assert "steam" in ids and "poweroff" in ids
    assert config.rows[-1].title == "System"  # Start/Menu jumps to the last row


def test_flatpak_shorthand_and_args():
    config = cfg.parse({"rows": [{"title": "R", "apps": [
        {"id": "kodi", "name": "Kodi", "flatpak": "tv.kodi.Kodi", "args": "--standalone"},
    ]}]})
    assert config.rows[0].apps[0].command == ("flatpak", "run", "tv.kodi.Kodi", "--standalone")


def test_string_command_is_split():
    app = cfg.parse({"rows": [{"apps": [{"id": "a", "name": "A", "command": "systemctl reboot"}]}]}).rows[0].apps[0]
    assert app.command == ("systemctl", "reboot")
    assert app.home_button is True and app.confirm is False


@pytest.mark.parametrize("raw, message", [
    ({"id": "a", "name": "A"}, "needs either"),
    ({"name": "A", "command": "x"}, "missing 'id'"),
    ({"id": "a", "name": "A", "command": []}, "non-empty"),
])
def test_invalid_apps(raw, message):
    with pytest.raises(cfg.ConfigError, match=message):
        cfg.parse({"rows": [{"apps": [raw]}]})


def test_duplicate_ids_rejected():
    app = {"id": "a", "name": "A", "command": "x"}
    with pytest.raises(cfg.ConfigError, match="duplicate"):
        cfg.parse({"rows": [{"apps": [app, app]}]})


def test_visible_hides_missing_apps_and_empty_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "flatpak_dirs", lambda: [tmp_path])
    (tmp_path / "tv.kodi.Kodi").mkdir()
    config = cfg.parse({"rows": [
        {"title": "A", "apps": [
            {"id": "sh", "name": "Shell", "command": "sh", "requires": "sh"},
            {"id": "nope", "name": "Nope", "command": "x", "requires": ["definitely-not-installed-xyz"]},
            {"id": "kodi", "name": "Kodi", "flatpak": "tv.kodi.Kodi"},
            {"id": "gone", "name": "Gone", "flatpak": "org.example.Missing"},
        ]},
        {"title": "Empty", "apps": [{"id": "e", "name": "E", "flatpak": "org.example.Missing2"}]},
    ]}).visible()
    assert [r.title for r in config.rows] == ["A"]
    assert [a.id for a in config.rows[0].apps] == ["sh", "kodi"]


def test_requires_files(tmp_path):
    raw = {"id": "a", "name": "A", "command": "sh", "requires_files": str(tmp_path / "marker")}
    config = cfg.parse({"rows": [{"apps": [raw]}]})
    assert config.visible().rows == ()
    (tmp_path / "marker").touch()
    assert len(config.visible().rows) == 1


def test_requires_files_glob_and_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    raw = {"id": "a", "name": "A", "command": "sh", "requires_files": "~/dev/usb-Elgato*-video-index0"}
    config = cfg.parse({"rows": [{"apps": [raw]}]})
    assert config.visible().rows == ()
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev/usb-Elgato_Game_Capture_4K_X-video-index0").touch()
    assert len(config.visible().rows) == 1


def test_user_config_overrides_system(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "hearth").mkdir()
    (tmp_path / "hearth/apps.toml").write_text('title = "Mine"\n')
    assert cfg.load().title == "Mine"


def test_bad_toml_is_config_error(tmp_path):
    p = tmp_path / "apps.toml"
    p.write_text("rows = [")
    with pytest.raises(cfg.ConfigError):
        cfg.load(p)


def test_user_changes_layer_over_defaults(tmp_path, monkeypatch, shipped_config):
    monkeypatch.setattr(cfg, "SYSTEM_CONFIG", shipped_config)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "hearth").mkdir()
    (tmp_path / "hearth/apps.toml").write_text("""
hide = ["plex"]
[quick_menu]
pause_game = false
[[rows]]
title = "Watch"
  [[rows.apps]]
  id = "kodi"
  color = "#000000"
  [[rows.apps]]
  id = "twitch"
  name = "Twitch"
  flatpak = "tv.twitch.Twitch"
[[rows]]
title = "Mine"
  [[rows.apps]]
  id = "shell"
  name = "Shell"
  command = "sh"
""")
    config = cfg.load()
    titles = [r.title for r in config.rows]
    assert titles[-2:] == ["Mine", "System"]  # new rows go before System
    watch = next(r for r in config.rows if r.title == "Watch")
    ids = [a.id for a in watch.apps]
    assert "plex" not in ids and ids[-1] == "twitch"
    kodi = config.app("kodi")
    assert kodi.color == "#000000" and kodi.command == ("flatpak", "run", "tv.kodi.Kodi")
    assert config.pause_game is False
    assert config.app("steam") is not None  # defaults still there


def test_replace_ignores_defaults(tmp_path, monkeypatch, shipped_config):
    monkeypatch.setattr(cfg, "SYSTEM_CONFIG", shipped_config)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "hearth").mkdir()
    (tmp_path / "hearth/apps.toml").write_text('replace = true\ntitle = "Mine"\n')
    config = cfg.load()
    assert config.title == "Mine" and config.rows == ()


def test_theme_defaults_and_user_override():
    config = cfg.parse({})
    assert (config.livery, config.motion) == ("gulf", "full")
    merged = cfg.merge({"theme": {"livery": "gulf", "motion": "full"}, "rows": []}, {"theme": {"livery": "Martini"}})
    config = cfg.parse(merged)
    assert (config.livery, config.motion) == ("martini", "full")
    assert config.visible().livery == "martini"  # filtering keeps the theme


def test_theme_motion_is_checked():
    with pytest.raises(cfg.ConfigError, match="motion"):
        cfg.parse({"theme": {"motion": "fast"}})
