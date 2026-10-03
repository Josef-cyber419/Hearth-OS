"""The phone remote: pairing with the code on the TV, buttons and typing."""

import http.client
import json
import types

import pygame
import pytest

from hearth import ctl, drive, fieldcheck, remote, session, settings, settings_app
from hearth import config as cfg


class FakeKeys:
    def __init__(self):
        self.presses, self.typed = [], []

    def press(self, name):
        if name == "guide":
            session.update(lambda s: s["requests"].append("menu"))
            return None
        self.presses.append(name)
        return None if name in drive.BUTTONS else f"unknown button {name!r}"

    def type(self, text):
        self.typed.append(text)
        return None


class Client:
    def __init__(self, port):
        self.port, self.cookie = port, None

    def call(self, method, path, data=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        from urllib.parse import urlencode

        conn.request(method, path, urlencode(data) if data else None, headers)
        resp = conn.getresponse()
        body = resp.read()
        set_cookie = resp.getheader("Set-Cookie")
        if set_cookie:
            self.cookie = set_cookie.split(";")[0]
        conn.close()
        return resp.status, body


@pytest.fixture
def served(tmp_path):
    keys = FakeKeys()
    flags = {"enabled": True}
    r = remote.Remote(lambda: keys, lambda: flags["enabled"], port=0, phones=tmp_path / "phones.json")
    server = remote.serve(r)
    remote.wait_for(server)
    yield r, keys, flags, Client(server.server_address[1])
    server.shutdown()
    server.server_close()
    remote.active = None


def test_pairing_with_the_code_then_buttons_and_typing(served):
    r, keys, _, client = served
    status, body = client.call("GET", "/")
    assert status == 200 and b"Hearth remote" in body
    status, body = client.call("GET", "/me")
    assert status == 200 and json.loads(body) == {"paired": False, "front": "Home screen"}
    assert client.call("POST", "/press", {"b": "up"})[0] == 401  # not paired yet
    status, body = client.call("POST", "/pair", {"code": "000000"})
    assert status == 403 and r.failures == 1
    status, body = client.call("POST", "/pair", {"code": r.code})
    assert status == 200 and client.cookie.startswith("hearth=")
    assert json.loads(client.call("GET", "/me")[1])["paired"] is True
    assert client.call("POST", "/press", {"b": "up"})[0] == 200
    assert client.call("POST", "/press", {"b": "a"})[0] == 200
    assert keys.presses == ["up", "a"]
    assert client.call("POST", "/type", {"text": "my wifi pass\n"})[0] == 200
    assert keys.typed == ["my wifi pass\n"]
    client.call("POST", "/press", {"b": "guide"})
    assert session.read()["requests"] == ["menu"]  # the Quick Menu, through Hearth itself
    status, body = client.call("POST", "/press", {"b": "jump"})
    assert status == 409 and "unknown button" in json.loads(body)["error"]
    assert client.call("POST", "/nothing")[0] == 404


def test_five_wrong_codes_pause_pairing_and_phones_are_remembered(served, tmp_path, monkeypatch):
    r, keys, flags, client = served
    monkeypatch.setattr(remote.time, "sleep", lambda s: None)  # the wrong-code pause
    first = r.code
    for _ in range(remote.CODE_TRIES - 1):
        assert client.call("POST", "/pair", {"code": "111111"})[0] == 403
    status, body = client.call("POST", "/pair", {"code": "111111"})
    assert status == 429 and "wait" in json.loads(body)["error"]
    assert r.code == first and r.locked_for() > 0  # the code stays readable on the TV
    assert client.call("POST", "/pair", {"code": r.code})[0] == 429  # even the right one waits
    r.locked_until = 0.0
    client.call("POST", "/pair", {"code": r.code})
    assert len(r.tokens) == 1 and session.read()["remote"]["phones"] == 1
    again = remote.Remote(lambda: keys, port=0, phones=tmp_path / "phones.json")
    assert again.tokens == r.tokens  # survives a restart of Hearth
    r.forget_phones()
    assert client.call("POST", "/press", {"b": "up"})[0] == 401
    flags["enabled"] = False
    assert client.call("GET", "/me")[0] == 503


def test_pairing_lockout_is_timed(tmp_path):
    r = remote.Remote(lambda: None, port=0, phones=tmp_path / "p.json")
    for _ in range(remote.CODE_TRIES):
        assert r.pair("000000", now=100.0) is None
    assert r.locked_for(now=100.0) == remote.LOCKOUT_SECONDS and r.pair(r.code, now=130.0) is None
    assert r.locked_for(now=100.0 + remote.LOCKOUT_SECONDS) == 0
    assert r.pair(r.code, now=100.0 + remote.LOCKOUT_SECONDS) is not None


def test_the_page_presses_enter_and_backspace_properly():
    assert 'data-t="&#10;"' in remote.PAGE and 'data-b="backspace"' in remote.PAGE
    assert "backspace" in drive.BUTTONS


def test_what_the_tv_shows(served):
    r = served[0]
    session.update(lambda s: s.update(foreground={"id": "kodi", "name": "Kodi"}, focus="foreground"))
    assert r.in_front() == "Kodi"
    session.update(lambda s: s.update(background={"discord": {"name": "Discord"}}, focus="discord"))
    assert r.in_front() == "Discord"
    session.update(lambda s: s.update(foreground=None, focus="home", screen="settings"))
    assert r.in_front() == "Settings"


def test_no_game_mode_display_is_said_plainly(tmp_path):
    r = remote.Remote(lambda: None, port=0, phones=tmp_path / "p.json")
    assert r.press("up") == "The TV isn't in Game Mode"
    assert r.type("x") == "The TV isn't in Game Mode"
    assert r.info()["code"] == r.code and len(r.code) == 6


def test_typing_holds_shift_for_capitals_and_symbols(monkeypatch):
    from Xlib import XK
    from Xlib.ext import xtest

    sent = []
    monkeypatch.setattr(xtest, "fake_input", lambda d, kind, code=0, **kw: sent.append((kind, code)))
    keymap = {"a": 38, "h": 43, "i": 31, "space": 65, "1": 10, "exclam": 10, "Shift_L": 50, "Return": 36}
    plain = {38: "a", 43: "h", 31: "i", 65: "space", 10: "1", 50: "Shift_L", 36: "Return"}

    def keysym_to_keycode(keysym):
        for name, code in keymap.items():
            if XK.string_to_keysym(name) == keysym:
                return code
        if keysym in (XK.string_to_keysym("H"), XK.string_to_keysym("I")):  # shifted letters share the key
            return keymap[XK.keysym_to_string(keysym).lower()]
        return 0

    d = types.SimpleNamespace(keysym_to_keycode=keysym_to_keycode,
                              keycode_to_keysym=lambda code, index: XK.string_to_keysym(plain[code]),
                              sync=lambda: None)
    win = types.SimpleNamespace(id=7, set_input_focus=lambda *a: None)
    monkeypatch.setattr(drive, "target", lambda gs, state: win)
    keys = drive.Keys(types.SimpleNamespace(d=d), sleep=lambda s: None)
    assert keys.type("Hi a1!\n€") is None
    from Xlib import X

    taps = [(k, c) for k, c in sent]
    # H: shift down, h, shift up; i: plain; space; a; 1; !: shift + 1; Enter; € left out.
    assert taps[:3] == [(X.KeyPress, 50), (X.KeyPress, 43), (X.KeyRelease, 43)] and taps[3] == (X.KeyRelease, 50)
    assert (X.KeyPress, 31) in taps and (X.KeyPress, 65) in taps and (X.KeyPress, 36) in taps
    presses = [c for k, c in taps if k == X.KeyPress]
    assert presses.count(10) == 2 and presses.count(50) == 2  # "1" plain, "!" shifted


def test_settings_page_and_the_pairing_card(shipped_config, tmp_path):
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((1280, 720))
        app = settings_app.SettingsApp(shipped_config)
        app.menu.tab = [c[0] for c in settings_app.CATEGORIES].index("remote")
        app.refresh()
        items = {i.key: i for i in app.menu.current.items}
        assert items["remote-on"].value is True and "remote-none" in items  # no server in tests
        items["remote-on"].on_change(False)
        assert cfg.load(shipped_config).remote_enabled is False
        assert settings.load()["remote"] == {"enabled": False}
        remote.active = remote.Remote(lambda: None, port=0, phones=tmp_path / "p.json")
        app.refresh()
        items = {i.key: i for i in app.menu.current.items}
        assert remote.active.code in items["remote-show"].detail
        app.zone = "items"
        app.menu.select("remote-show")
        from hearth.model import Nav

        app.handle(Nav.SELECT)
        assert app.pairing
        view = settings_app.SettingsView(surface.get_size())
        view.draw_settings(surface, app)
        app.handle(Nav.BACK)
        assert not app.pairing
        old = remote.active.code
        app.menu.select("remote-new")
        app.handle(Nav.SELECT)
        assert remote.active.code != old
    finally:
        remote.active = None
        pygame.quit()


def test_status_and_check_mention_the_remote(served, capsys, monkeypatch):
    r = served[0]
    ctl.cmd_status()
    assert f"Phone remote: {r.url()} (code {r.code}" in capsys.readouterr().out
    monkeypatch.setattr(fieldcheck, "_run", lambda cmd, timeout=15: (0, "public") if "zone" in cmd[-1] else (0, "22/tcp"))
    results = {x.name: x for x in fieldcheck.phone_remote()}
    assert results["Phone remote"].status == "ok"
    assert results["Phone remote firewall"].status == "warn" and str(r.port) in results["Phone remote firewall"].detail
    monkeypatch.setattr(fieldcheck, "_run", lambda cmd, timeout=15: (0, "FedoraWorkstation"))
    assert [x.name for x in fieldcheck.phone_remote()] == ["Phone remote"]


def test_check_without_a_remote_is_informational():
    assert fieldcheck.phone_remote()[0].status == "info"
