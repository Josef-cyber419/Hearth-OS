import json
import time

import pygame
import pytest

from hearth import bluetooth, network, session, settings, settings_app, storage, style, wiimote
from hearth import config as cfg
from hearth.model import Nav
from hearth.settings_app import Calibration, Keyboard, SettingsApp, SettingsView


# -- storage ---------------------------------------------------------------------


def test_settings_layer_over_apps_toml(shipped_config):
    assert cfg.load(shipped_config).livery == "gulf"
    settings.put("theme", "livery", "martini")
    settings.put("wii_remote", "sensor_bar", "above")
    settings.set_hidden("kodi", True)
    config = cfg.load(shipped_config)
    assert config.livery == "martini" and config.wii_bar == "above"
    assert config.app("kodi") is None and cfg.load(shipped_config, hide=False).app("kodi") is not None
    settings.put("theme", "livery", None)  # back to the default
    settings.set_hidden("kodi", False)
    config = cfg.load(shipped_config)
    assert config.livery == "gulf" and config.app("kodi") is not None


def test_bad_settings_never_take_the_home_screen_down(shipped_config):
    settings.put("wii_remote", "speed", 9000)
    config = cfg.load(shipped_config)
    assert config.app("settings") is not None and config.wii_speed == 100


def test_settings_tile_is_built_in(shipped_config):
    app = cfg.load(shipped_config).app("settings")
    assert app.builtin and app.available()


# -- network and bluetooth parsing -------------------------------------------------


class Fake:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def __call__(self, argv):
        self.calls.append(argv)
        for prefix, result in self.responses.items():
            if " ".join(argv).startswith(prefix):
                return result
        return (0, "", "")


def test_nmcli_fields_unescape():
    assert network.fields(r"*:My\:Net:80:WPA2") == ["*", "My:Net", "80", "WPA2"]


def test_network_status_prefers_ethernet():
    run = Fake({
        "nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device": (0, "wlp5s0:wifi:connected:Home\nenp3s0:ethernet:connected:Wired\n"
                                                             "lo:loopback:connected (externally):lo\n", ""),
        "nmcli -t -g IP4.ADDRESS device show enp3s0": (0, "192.168.1.9/24\n", ""),
    })
    s = network.status(run)
    assert (s.kind, s.device, s.address) == ("ethernet", "enp3s0", "192.168.1.9")
    assert s.describe() == "Ethernet · 192.168.1.9"
    assert network.status(Fake({"nmcli -t -f": (0, "wlp5s0:wifi:disconnected:\n", "")})).describe() == "Not connected"


def test_wifi_networks_deduped_and_sorted():
    run = Fake({
        "nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY": (0, " :Cafe:40:--\n*:Home:70:WPA2\n :Home:90:WPA2\n :Far:20:WPA2\n"
                                                    " ::60:WPA2\n", ""),
        "nmcli -t -f NAME,TYPE connection show": (0, "Home:802-11-wireless\nWired:802-3-ethernet\n", ""),
    })
    nets = network.networks(run=run)
    assert [n.ssid for n in nets] == ["Home", "Cafe", "Far"]  # the one in use first, hidden networks dropped
    assert nets[0].in_use and nets[0].saved and not nets[1].secure


def test_wifi_connect_messages():
    ok = Fake({"nmcli device wifi connect": (0, "Device 'wlp5s0' successfully activated", "")})
    assert network.connect("Home", "pw", run=ok) == (True, "Connected to Home")
    assert ok.calls[0][-2:] == ["password", "pw"]
    bad = Fake({"nmcli device wifi connect": (4, "", "Error: Connection activation failed: Secrets were required, "
                                                     "but not provided.")})
    assert network.connect("Home", "wrong", run=bad) == (False, "Wrong password?")
    saved = Fake({})
    network.connect("Home", saved=True, run=saved)
    assert saved.calls[0] == ["nmcli", "connection", "up", "id", "Home"]


INFO = """Device E4:17:D8:00:00:01 (public)
	Name: 8BitDo Ultimate 2
	Alias: 8BitDo Ultimate 2
	Icon: input-gaming
	Paired: yes
	Connected: no
"""


def test_bluetooth_devices():
    run = Fake({
        "bluetoothctl devices": (0, "Device E4:17:D8:00:00:01 8BitDo Ultimate 2\nDevice 11:22:33:44:55:66 11-22-33-44-55-66\n", ""),
        "bluetoothctl info E4:17:D8:00:00:01": (0, INFO, ""),
        "bluetoothctl info 11:22:33:44:55:66": (0, "Device 11:22:33:44:55:66\n\tPaired: no\n", ""),
    })
    devs = bluetooth.devices(run)
    assert devs[0].name == "8BitDo Ultimate 2" and devs[0].paired and not devs[0].connected
    assert devs[0].describe() == "Controller · Paired"
    assert bluetooth.powered(Fake({"bluetoothctl show": (0, "Controller 00:1A\n\tPowered: yes\n", "")})) is True
    assert bluetooth.powered(Fake({"bluetoothctl show": (1, "", "No default controller available")})) is None


def test_bluetooth_pair_trusts_and_connects():
    run = Fake({"bluetoothctl --timeout 25 pair": (0, "Pairing successful", ""),
                "bluetoothctl --timeout 15 connect": (0, "Connection successful", "")})
    assert bluetooth.pair("E4:17:D8:00:00:01", run) == (True, "Paired and connected")
    assert ["bluetoothctl", "trust", "E4:17:D8:00:00:01"] in run.calls


# -- keyboard and calibration ---------------------------------------------------------


def test_on_screen_keyboard():
    kb = Keyboard("Password", secret=True)
    assert kb.key_at(1, 0) == "q"
    kb.handle(Nav.SELECT)  # q
    kb.handle(Nav.TAB_NEXT)  # shift
    kb.handle(Nav.RIGHT)
    kb.handle(Nav.SELECT)  # W, then back to lower case
    kb.type("x!")
    assert kb.text == "qWx!" and kb.layer == "lower"
    kb.handle(Nav.BACK)
    assert kb.text == "qWx"
    for _ in range(3):  # to the bottom row: the special keys
        kb.handle(Nav.DOWN)
    assert kb.row == 4 and kb.special[kb.col] in kb.special
    assert kb.handle(Nav.MENU) == "done"
    assert Keyboard("x").handle(Nav.BACK) == "cancel"


def test_calibration_maps_targets_exactly():
    cal = Calibration()
    assert cal.capture(None) is None and "Can't see" in cal.message
    assert cal.capture((700.0, 200.0)) is None
    result = cal.capture((300.0, 560.0))
    aim = wiimote.Aim(calibration=result, smoothing=0)
    assert aim.to_screen(700, 200) == pytest.approx((0.1, 0.1))
    assert aim.to_screen(300, 560) == pytest.approx((0.9, 0.9))
    assert aim.to_screen(500, 380) == pytest.approx((0.5, 0.5))
    lazy = Calibration()
    lazy.capture((500.0, 380.0))
    assert lazy.capture((505.0, 383.0)) == "retry" and lazy.points == []


# -- the app ---------------------------------------------------------------------------


@pytest.fixture
def offline(monkeypatch):
    """No real nmcli or bluetoothctl: canned answers instead."""
    monkeypatch.setattr(network, "available", lambda: True)
    monkeypatch.setattr(network, "status", lambda run=None: network.Status(True, "wifi", "Home", "wlp5s0", "10.0.0.2"))
    monkeypatch.setattr(network, "wifi_enabled", lambda run=None: True)
    monkeypatch.setattr(network, "networks", lambda rescan=False, run=None: [
        network.Network("Home", 80, True, True, True), network.Network("Guest", 50, True)])
    connects = []
    monkeypatch.setattr(network, "connect", lambda ssid, password=None, saved=False, run=None: (
        connects.append((ssid, password)), (True, f"Connected to {ssid}"))[1])
    monkeypatch.setattr(bluetooth, "available", lambda: True)
    monkeypatch.setattr(bluetooth, "powered", lambda run=None: True)
    monkeypatch.setattr(bluetooth, "devices", lambda run=None: [
        bluetooth.Device("AA:00:00:00:00:01", "Pad", True, True, "input-gaming")])
    monkeypatch.setattr(network, "ip_config", lambda conn, run=None: network.IpConfig())
    monkeypatch.setattr(network, "gateway", lambda run=None: "10.0.0.1")
    monkeypatch.setattr(storage, "drives", lambda *a, **k: [
        storage.Drive("/dev/sda", "Samsung SSD 870 EVO", 256 * 10**9, "sata",
                      parts=(storage.Part("/dev/sda2", 255 * 10**9, "ntfs", "Games", "ABCD"),))])
    return connects


def wait_jobs(app):
    for _ in range(100):
        if not app.jobs._running:
            break
        time.sleep(0.02)
    app.tick()
    app.refresh()


def test_navigation_and_live_changes(shipped_config, offline):
    app = SettingsApp(shipped_config)
    assert app.zone == "nav" and app.menu.current.key == "appearance"
    app.handle(Nav.SELECT)
    assert app.zone == "items" and app.menu.selected.key == "livery"
    app.handle(Nav.RIGHT)  # next livery
    assert settings.load()["theme"]["livery"] == "martini" and app.config.livery == "martini"
    app.handle(Nav.BACK)
    assert app.zone == "nav"
    assert app.handle(Nav.BACK) == "exit"


def test_hiding_a_tile(shipped_config, offline):
    app = SettingsApp(shipped_config)
    app.handle(Nav.DOWN)  # Home screen
    app.handle(Nav.RIGHT)
    app.menu.select(next(i.key for i in app.menu.current.items if i.key.startswith("tile-")))
    first = app.menu.selected
    assert first.kind == "toggle" and first.value
    app.handle(Nav.SELECT)
    assert settings.load()["hide"] == [first.key.removeprefix("tile-")]
    assert "tile-settings" not in [i.key for i in app.menu.current.items]  # can't hide your way out
    assert "tile-library" not in [i.key for i in app.menu.current.items]


def test_wifi_password_flow(shipped_config, offline):
    app = SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("network")
    app.load_for("network")
    wait_jobs(app)
    app.zone = "items"
    app.menu.select("wifi-Guest")
    app.handle(Nav.SELECT)
    assert app.keyboard is not None and app.keyboard.secret
    app.keyboard.type("hunter22")
    app.handle(Nav.MENU)  # Start = done
    wait_jobs(app)
    assert offline == [("Guest", "hunter22")]
    assert app.jobs.messages["wifi-Guest"] == "Connected to Guest"


def test_calibration_flow_uses_the_overlays_aim(shipped_config, offline):
    app = SettingsApp(shipped_config)
    app.start_calibration()
    assert session.read()["wii_raw"] is True
    for raw in ((700, 200), (300, 560)):
        session.aim_path().write_text(json.dumps({"raw": raw, "t": time.time()}))
        app.handle(Nav.SELECT)
    assert app.calibrating is None and session.read()["wii_raw"] is False
    assert settings.load()["wii_remote"]["calibration"] == [700, 200, 300, 560]
    assert cfg.load(shipped_config).wii_calibration == (700.0, 200.0, 300.0, 560.0)


def test_livery_preview_is_live(shipped_config, offline):
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((640, 360))
        app = SettingsApp(shipped_config)
        view = SettingsView((640, 360))
        view.draw_settings(surface, app)
        app.handle(Nav.SELECT)
        app.handle(Nav.RIGHT)
        view.draw_settings(surface, app)
        assert view.lv is style.LIVERIES["martini"]
    finally:
        pygame.quit()


@pytest.mark.parametrize("livery", sorted(style.LIVERIES))
def test_every_page_renders(shipped_config, offline, livery):
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((1280, 720))
        settings.put("theme", "livery", livery)
        app = SettingsApp(shipped_config)
        view = SettingsView((1280, 720), livery)
        for i, (key, *_) in enumerate(settings_app.CATEGORIES):
            app.menu.tab = i
            app.load_for(key)
            wait_jobs(app)
            for zone in ("nav", "items"):
                app.zone = zone
                view.draw_settings(surface, app)
        hit = next(h for r, h in view.hits if h[0] == "item")
        app.point(hit)
        assert app.zone == "items"
        app.open_keyboard("Name", lambda t: None)
        view.draw_settings(surface, app)
        app.keyboard = None
        app.calibrating = Calibration()
        view.draw_settings(surface, app)
    finally:
        pygame.quit()


def test_run_loop_exits_on_back(shipped_config, offline):
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((1280, 720))
        for key in (pygame.K_DOWN, pygame.K_ESCAPE):
            pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0))
        assert settings_app.run(surface, shipped_config, max_frames=30, input_blocked=lambda: False) is None
    finally:
        pygame.quit()


# -- storage page --------------------------------------------------------------


@pytest.fixture
def drives(monkeypatch, tmp_path):
    """A new SATA SSD from Windows, and a drive Hearth set up, mounted at tmp_path/games."""
    games = tmp_path / "games"
    games.mkdir()
    new = storage.Drive("/dev/sda", "Samsung SSD 870 EVO", 256 * 10**9, "sata",
                        parts=(storage.Part("/dev/sda2", 255 * 10**9, "ntfs", "Games", "ABCD"),))
    part = storage.Part("/dev/sdb1", 2000 * 10**9, "ext4", "games", "u1", (str(games),))
    ready = storage.Drive("/dev/sdb", "Crucial MX500", 2000 * 10**9, "sata", parts=(part,),
                          mounted_at=str(games), mounted_part=part)
    monkeypatch.setattr(network, "ip_config", lambda conn, run=None: network.IpConfig())
    monkeypatch.setattr(network, "gateway", lambda run=None: "10.0.0.1")
    monkeypatch.setattr(storage, "drives", lambda *a, **k: [new, ready])
    monkeypatch.setattr(storage.Drive, "ready", property(lambda self: bool(self.mounted_at)))
    calls = []
    monkeypatch.setattr(storage, "helper", lambda *a, password=None: (
        calls.append(a if password is None else (*a, password)), (True, "Ready at /var/mnt/games"))[1])
    monkeypatch.setattr(storage, "free_name", lambda drive, *a: "games2")
    return calls, games


def open_storage(shipped_config):
    app = SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("storage")
    app.load_for("storage")
    wait_jobs(app)
    app.zone = "items"
    return app


def test_storage_lists_drives_and_what_can_be_done(shipped_config, offline, drives):
    app = open_storage(shipped_config)
    items = {i.key: i for i in app.menu.current.items}
    new = items["drive-/dev/sda"]
    assert new.kind == "info" and new.label == "Samsung SSD 870 EVO (256 GB)"
    assert "Not set up" in new.detail and "Games (255 GB)" in new.detail
    assert "drive-/dev/sda-use" not in items  # NTFS: can't be used as it is
    erase = items["drive-/dev/sda-erase"]
    assert erase.confirm and "Deletes everything on it: Games (255 GB)" in erase.detail
    ready = items["drive-/dev/sdb"]
    assert "Ready at" in ready.detail and "free" in ready.detail
    assert items["drive-/dev/sdb-steam"].kind == "toggle" and items["drive-/dev/sdb-roms"].kind == "toggle"
    assert "drive-/dev/sdb-erase" not in items  # not offered once it's in use


def test_erasing_takes_two_presses(shipped_config, offline, drives):
    calls, _ = drives
    app = open_storage(shipped_config)
    app.menu.select("drive-/dev/sda-erase")
    app.handle(Nav.SELECT)
    assert calls == [] and app.menu.confirming == "drive-/dev/sda-erase"
    app.handle(Nav.SELECT)
    # Then the account's password, which goes to sudo with the command.
    assert calls == [] and app.keyboard is not None and app.keyboard.secret
    app.keyboard.type("hunter22")
    app.handle(Nav.MENU)  # Start = done
    wait_jobs(app)
    assert calls == [("format", "/dev/sda", "games2", "hunter22")]
    assert app.jobs.messages["drive-/dev/sda"] == "Ready at /var/mnt/games"


def test_erase_needs_a_password(shipped_config, offline, drives):
    calls, _ = drives
    app = open_storage(shipped_config)
    app.menu.select("drive-/dev/sda-erase")
    app.handle(Nav.SELECT)
    app.handle(Nav.SELECT)
    app.keyboard.handle(Nav.BACK)  # backed out of the password
    wait_jobs(app)
    assert calls == []


def test_moving_away_cancels_the_erase(shipped_config, offline, drives):
    calls, _ = drives
    app = open_storage(shipped_config)
    app.menu.select("drive-/dev/sda-erase")
    app.handle(Nav.SELECT)
    app.handle(Nav.UP)
    app.menu.select("drive-/dev/sda-erase")
    app.handle(Nav.SELECT)
    wait_jobs(app)
    assert calls == [] and app.keyboard is None  # the first press didn't count any more


def test_roms_and_steam_toggles(shipped_config, offline, drives, monkeypatch):
    calls, games = drives
    moved, steam = [], []
    monkeypatch.setattr(storage, "move_roms", lambda to, progress=None: (moved.append(to), "Done: moved")[1])
    monkeypatch.setattr(storage, "add_steam_library", lambda mount: (steam.append(("add", mount)), "Done")[1])
    app = open_storage(shipped_config)
    app.menu.select("drive-/dev/sdb-roms")
    app.handle(Nav.SELECT)
    wait_jobs(app)
    assert moved == [games / "ROMs"] and app.jobs.messages["drive-/dev/sdb-roms"] == "Done: moved"
    app.menu.select("drive-/dev/sdb-steam")
    app.handle(Nav.SELECT)
    wait_jobs(app)
    assert steam == [("add", str(games))]


def test_stop_using_a_drive_still_in_use_is_refused(shipped_config, offline, drives, monkeypatch):
    calls, _ = drives
    monkeypatch.setattr(storage, "in_use", lambda drive: ["the ROMs"])
    app = open_storage(shipped_config)
    app.menu.select("drive-/dev/sdb-release")
    app.handle(Nav.SELECT)
    app.handle(Nav.SELECT)
    wait_jobs(app)
    assert calls == []
    assert app.jobs.messages["drive-/dev/sdb-release"] == "It still has the ROMs: turn those off first"
    monkeypatch.setattr(storage, "in_use", lambda drive: [])
    app.menu.select("drive-/dev/sdb-release")
    app.handle(Nav.SELECT)
    app.handle(Nav.SELECT)
    wait_jobs(app)
    assert calls == [("release", "/dev/sdb1")]


# -- IP address and DNS --------------------------------------------------------


def test_ip_config_and_validation():
    out = "manual\n192.168.1.50/24\n192.168.1.1\n1.1.1.1,1.0.0.1\nyes\n"
    ip = network.ip_config("Wired connection 1", lambda argv: (0, out, ""))
    assert ip == network.IpConfig("manual", "192.168.1.50/24", "192.168.1.1", ("1.1.1.1", "1.0.0.1"), True)
    assert ip.dns_choice == "Cloudflare"
    auto = network.ip_config("Home", lambda argv: (0, "auto\n\n\n\nno\n", ""))
    assert auto.method == "auto" and auto.dns == () and auto.dns_choice == "Automatic"
    assert network.IpConfig(dns=("192.168.1.2",)).dns_choice == "Custom"
    assert network.ip_config("Gone", lambda argv: (10, "", "no such connection")) is None

    assert network.validate("192.168.1.50", 24, "192.168.1.1") is None
    assert "isn't an IP address" in network.validate("192.168.1", 24, "192.168.1.1")
    assert "same network" in network.validate("192.168.1.50", 24, "10.0.0.1")
    assert "can't be used" in network.validate("192.168.1.0", 24, "192.168.1.1")
    assert "can't be the same" in network.validate("192.168.1.1", 24, "192.168.1.1")
    assert "usually 24" in network.validate("192.168.1.50", 31, "192.168.1.1")
    assert network.parse_dns("1.1.1.1, 8.8.8.8") == ("1.1.1.1", "8.8.8.8")
    assert network.parse_dns("2606:4700:4700::1111") == ("2606:4700:4700::1111",)
    assert "isn't an IP" in network.parse_dns("dns.google")
    assert "Type one or two" in network.parse_dns("  ")


def test_ip_changes_run_nmcli():
    calls = []
    run = lambda argv: (calls.append(argv), (0, "", ""))[1]  # noqa: E731
    assert network.set_manual("Home", "192.168.1.50", 24, "192.168.1.1", run) == (
        True, "Done: reconnected with the new settings")
    assert calls == [["nmcli", "connection", "modify", "id", "Home", "ipv4.method", "manual",
                      "ipv4.addresses", "192.168.1.50/24", "ipv4.gateway", "192.168.1.1"],
                     ["nmcli", "connection", "up", "id", "Home"]]
    calls.clear()
    network.set_automatic("Home", run)
    assert calls[0][5:] == ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", ""]
    calls.clear()
    network.set_dns("Home", ("1.1.1.1", "2606:4700:4700::1111"), run)
    assert calls[0][5:] == ["ipv4.dns", "1.1.1.1", "ipv4.ignore-auto-dns", "yes",
                            "ipv6.dns", "2606:4700:4700::1111", "ipv6.ignore-auto-dns", "yes"]
    calls.clear()
    network.set_dns("Home", None, run)
    assert calls[0][5:] == ["ipv4.dns", "", "ipv4.ignore-auto-dns", "no", "ipv6.dns", "", "ipv6.ignore-auto-dns", "no"]
    assert network.set_manual("Home", "192.168.1.50", 24, "10.0.0.1", run)[0] is False  # checked first
    failing = lambda argv: (4, "", "Error: failed to modify") if argv[2] == "modify" else (0, "", "")  # noqa: E731
    assert network.set_automatic("Home", failing) == (False, "Error: failed to modify")


@pytest.fixture
def nm(monkeypatch):
    applied = []
    monkeypatch.setattr(network, "set_manual", lambda conn, a, p, g: (applied.append(("manual", conn, a, p, g)),
                                                                       (True, "Done"))[1])
    monkeypatch.setattr(network, "set_automatic", lambda conn: (applied.append(("auto", conn)), (True, "Done"))[1])
    monkeypatch.setattr(network, "set_dns", lambda conn, servers: (applied.append(("dns", conn, servers)),
                                                                  (True, "Done"))[1])
    return applied


def open_network(shipped_config):
    app = SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("network")
    app.load_for("network")
    wait_jobs(app)
    app.zone = "items"
    return app


def test_static_ip_flow(shipped_config, offline, nm):
    app = open_network(shipped_config)
    keys = [i.key for i in app.menu.current.items]
    assert "ip-method" in keys and "ip-address" not in keys and "ip-apply" not in keys
    app.menu.select("ip-method")
    app.handle(Nav.RIGHT)  # Manual: only picks, nothing changes yet
    assert nm == []
    items = {i.key: i for i in app.menu.current.items}
    assert items["ip-address"].detail == "10.0.0.2" and items["ip-gateway"].detail == "10.0.0.1"
    assert items["ip-prefix"].value == 24 and "255.255.255.0" in items["ip-prefix"].detail
    app.menu.select("ip-address")
    app.handle(Nav.SELECT)
    assert app.keyboard.text == "10.0.0.2"
    for _ in range(len("2")):
        app.keyboard.handle(Nav.BACK)
    app.keyboard.type("50")
    app.handle(Nav.MENU)
    app.menu.select("ip-apply")
    app.handle(Nav.SELECT)
    assert nm == []  # one press asks
    app.handle(Nav.SELECT)
    wait_jobs(app)
    assert nm == [("manual", "Home", "10.0.0.50", 24, "10.0.0.1")]
    assert app.ip_edit is None and app.ip_method is None


def test_a_bad_static_address_is_caught_before_anything_changes(shipped_config, offline, nm):
    app = open_network(shipped_config)
    app.menu.select("ip-method")
    app.handle(Nav.RIGHT)
    app.ip_edit["gateway"] = "192.168.9.1"
    app.refresh()
    app.menu.select("ip-apply")
    app.handle(Nav.SELECT)
    app.handle(Nav.SELECT)
    wait_jobs(app)
    assert nm == [] and "same network" in app.jobs.messages["ip-apply"]


def test_dns_flow(shipped_config, offline, nm):
    app = open_network(shipped_config)
    assert "dns-apply" not in [i.key for i in app.menu.current.items]
    app.menu.select("dns")
    app.handle(Nav.RIGHT)  # Cloudflare
    app.handle(Nav.RIGHT)  # Google: picking only, no reconnects
    assert nm == []
    assert "8.8.8.8" in app.menu.selected.detail
    app.menu.select("dns-apply")
    app.handle(Nav.SELECT)
    wait_jobs(app)
    assert nm == [("dns", "Home", ("8.8.8.8", "8.8.4.4"))]
    app.menu.select("dns")
    app.handle(Nav.LEFT)  # Custom (wraps round)
    app.menu.select("dns-apply")
    app.handle(Nav.SELECT)
    app.keyboard.type("not-an-ip")
    app.handle(Nav.MENU)
    assert "isn't an IP" in app.jobs.messages["dns-apply"] and len(nm) == 1
    app.menu.select("dns-apply")
    app.handle(Nav.SELECT)
    app.keyboard.type("192.168.1.2")
    app.handle(Nav.MENU)
    wait_jobs(app)
    assert nm[-1] == ("dns", "Home", ("192.168.1.2",))


# -- audio ---------------------------------------------------------------------


def test_audio_page_picks_default_devices(shipped_config, offline, monkeypatch):
    from fakes import FakePactl

    from hearth import audio

    pactl = FakePactl()
    monkeypatch.setattr(audio, "run_pactl", pactl)
    monkeypatch.setattr(audio.Audio.__init__, "__defaults__", (pactl,))
    app = SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("audio")
    app.load_for("audio")
    wait_jobs(app)
    app.zone = "items"
    items = {i.key: i for i in app.menu.current.items}
    assert {"audio-output", "audio-volume", "audio-test", "audio-input", "audio-mic-level"} <= set(items)
    out = items["audio-output"]
    assert out.options[out.value] == "LG TV (HDMI)"  # the current default
    app.menu.select("audio-output")
    app.handle(Nav.RIGHT)
    wait_jobs(app)
    assert ["set-default-sink", "bluez_output.headset"] in pactl.calls
    assert any(c[0] == "move-sink-input" for c in pactl.calls)  # what's playing moves too
    app.menu.select("audio-input")
    app.handle(Nav.RIGHT)
    wait_jobs(app)
    assert any(c[0] == "set-default-source" for c in pactl.calls)


def test_audio_page_without_devices(shipped_config, offline, monkeypatch):
    from hearth import audio

    def broken(args):
        raise RuntimeError("pactl: connection refused")

    monkeypatch.setattr(audio.Audio.__init__, "__defaults__", (broken,))
    app = SettingsApp(shipped_config)
    app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("audio")
    app.load_for("audio")
    wait_jobs(app)
    assert [i.label for i in app.menu.current.items] == ["No audio devices found"]


def test_test_sound(monkeypatch, tmp_path):
    import subprocess

    played = []
    monkeypatch.setattr(settings_app.shutil, "which", lambda name: "/usr/bin/pw-play" if name == "pw-play" else None)
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: played.append(open(argv[1], "rb").read(4)))
    assert settings_app.play_test_sound().startswith("Heard it?")
    assert played == [b"RIFF"]  # a real WAV file
    monkeypatch.setattr(settings_app.shutil, "which", lambda name: None)
    assert "no player" in settings_app.play_test_sound()
