from fakes import FakeActions, FakePactl

from hearth import ctl, session
from hearth.audio import Audio
from hearth.model import Nav
from hearth.quickmenu import Context, QuickMenu, build_tabs
from hearth.updates import parse_status

RPM_OSTREE = {
    "deployments": [
        {"staged": True, "booted": False, "version": "2026.09.26-abc1234", "timestamp": 1790000000},
        {"booted": True, "version": "2026.09.20-def5678",
         "container-image-reference": "ostree-unverified-registry:ghcr.io/me/hearth-os:latest"},
        {"booted": False, "version": "2026.09.13-0011223"},
    ]
}


def test_parse_status():
    s = parse_status(RPM_OSTREE)
    assert s.image == "ghcr.io/me/hearth-os:latest"
    assert s.booted == "2026.09.20-def5678" and s.staged == "2026.09.26-abc1234"
    assert s.rollback == "2026.09.13-0011223" and s.update_ready


def test_parse_status_without_versions_uses_dates():
    s = parse_status({"deployments": [{"booted": True, "timestamp": 1790000000}]})
    assert s.booted == "2026-09-21" and not s.update_ready and s.rollback is None


def system_tab(update):
    audio = Audio(FakePactl())
    state = {"foreground": None, "background": {}, "focus": "home", "update": update}
    menu = QuickMenu(build_tabs(Context(audio, audio.snapshot(), state, FakeActions())))
    menu.handle(Nav.TAB_PREV)
    return menu


def test_update_entry_states():
    def item(menu):
        return next(i for i in menu.current.items if i.key == "update")

    assert item(system_tab(None)).label == "Check for updates"
    assert item(system_tab({"status": "running"})).kind == "info"
    ready = system_tab({"status": "ready", "version": "2026.09.26"})
    assert item(ready).label == "Restart to finish update" and item(ready).confirm
    assert item(system_tab({"status": "failed"})).label.startswith("Update failed")


def test_check_for_updates_runs_action():
    menu = system_tab(None)
    while menu.selected.key != "update":
        menu.handle(Nav.DOWN)
    actions = menu.current.items[0].on_select.__self__
    menu.handle(Nav.SELECT)
    assert ("update",) in actions.calls


def test_enable_disable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    ctl.main(["disable"])
    assert ctl.disabled_flag().exists()
    ctl.main(["enable"])
    assert not ctl.disabled_flag().exists()


def test_dev_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert ctl.main(["dev", str(tmp_path)]) == 1  # not a checkout
    (tmp_path / "hearth").mkdir()
    (tmp_path / "hearth/__init__.py").touch()
    assert ctl.main(["dev", str(tmp_path)]) == 0
    assert ctl.dev_path_file().read_text() == str(tmp_path)
    ctl.main(["dev", "--off"])
    assert not ctl.dev_path_file().exists()


def test_requests_queue():
    ctl.main(["menu"])
    ctl.main(["home"])
    assert session.read()["requests"] == ["menu", "home"]
