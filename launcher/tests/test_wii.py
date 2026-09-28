import socket

import pygame
import pytest

from hearth import config as cfg
from hearth import ui, wiimote
from hearth.model import Home, Nav
from hearth.overlay import Overlay, focus_key
from hearth.wiiinput import HOLD_SECONDS, WiiInput
from hearth.wiimote import A, B, DOWN, HOME, TWO, UP, Dot


def report_33(buttons=0, dots=()):
    ir = bytearray(b"\xff" * 12)
    for i, (x, y, size) in enumerate(dots):
        ir[i * 3: i * 3 + 3] = bytes([x & 0xFF, y & 0xFF, ((y >> 8) & 3) << 6 | ((x >> 8) & 3) << 4 | size])
    return bytes([0x33, buttons >> 8, buttons & 0xFF, 0x80, 0x80, 0x80]) + bytes(ir)


def test_parse_buttons_and_ir():
    r = report_33(A | UP, [(300, 400, 3), (700, 390, 2)])
    assert wiimote.buttons_of(r) == A | UP
    assert wiimote.ir_dots(r) == [Dot(300, 400, 3), Dot(700, 390, 2)]
    assert wiimote.buttons_of(bytes([0x22, 0, 0, 0x12, 0])) == 0  # acks carry buttons too
    assert wiimote.buttons_of(b"\x3d" + bytes(21)) is None  # extension-only report


def test_aim():
    aim = wiimote.Aim(smoothing=0, offset=0)
    assert aim.update([Dot(412, 384, 2), Dot(612, 384, 2)]) == (0.5, 0.5)
    # Pointing right: the bar moves left in the camera's view.
    x, _ = aim.update([Dot(212, 384 - 138, 2), Dot(412, 384 - 138, 2)])
    assert x > 0.6
    # Pointing down: the bar moves up in the camera's view (its y grows upwards).
    _, y = aim.update([Dot(412, 384 + 138, 2), Dot(612, 384 + 138, 2)])
    assert y > 0.6
    _, y = aim.update([Dot(412, 384 - 138, 2), Dot(612, 384 - 138, 2)])
    assert y < 0.4
    x, _ = aim.update([Dot(212, 384 - 138, 2), Dot(412, 384 - 138, 2)])
    # One dot drops out of view: keep aiming from the remembered spacing.
    x1, _ = aim.update([Dot(412, 384, 2)])
    assert abs(x1 - x) < 0.01
    assert aim.update([]) is None


def test_bar_below_the_tv_aims_at_the_middle():
    aim = wiimote.Aim(smoothing=0)  # default: bar below the TV
    # Aiming at the middle of the screen, the bar is below the middle of the view.
    below = 384 - wiimote.BAR_OFFSET * wiimote.IR_HEIGHT
    assert aim.update([Dot(412, below, 2), Dot(612, below, 2)]) == (0.5, 0.5)
    aim.configure(bar="above")
    above = 384 + wiimote.BAR_OFFSET * wiimote.IR_HEIGHT
    x, y = aim.update([Dot(412, above, 2), Dot(612, above, 2)])
    assert abs(x - 0.5) < 1e-9 and abs(y - 0.5) < 1e-9


def test_find_only_dolphinbar_remotes(tmp_path):
    for name, hid in (("hidraw0", "0003:0000057E:00000306"), ("hidraw1", "0005:0000057E:00000306"),
                      ("hidraw2", "0003:0000046D:0000C52B")):
        (tmp_path / name / "device").mkdir(parents=True)
        (tmp_path / name / "device" / "uevent").write_text(f"DRIVER=hid-generic\nHID_ID={hid}\n")
    assert wiimote.find(tmp_path) == ["/dev/hidraw0"]


def test_dolphin_running(tmp_path):
    (tmp_path / "123").mkdir()
    (tmp_path / "123" / "comm").write_text("bash\n")
    assert not wiimote.dolphin_running(tmp_path)
    (tmp_path / "456").mkdir()
    (tmp_path / "456" / "comm").write_text("dolphin-emu\n")
    assert wiimote.dolphin_running(tmp_path)


class Slot:
    """A fake DolphinBar slot: a message socket standing in for /dev/hidrawN."""

    def __init__(self):
        self.host, self.dev = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.dev.setblocking(False)
        self.host.setblocking(False)  # like the real device, opened with O_NONBLOCK

    def sent(self):
        out = []
        while True:
            try:
                out.append(self.dev.recv(64))
            except BlockingIOError:
                return out


def test_remote_starts_on_status_report():
    slot = Slot()
    r = wiimote.Remote("/fake", fd=slot.host.detach(), aim=wiimote.Aim(offset=0))
    slot.dev.send(bytes([0x20, 0, 0, 0, 0, 0, 0x60]))
    r.read(now=1.0)
    assert r.connected
    sent = slot.sent()
    assert sent[0] == bytes([0x11, 0x11])  # player 1 LED + a rumble pulse
    assert bytes([0x13, 0x04]) in sent and bytes([0x1A, 0x04]) in sent
    assert sent[-1] == bytes([0x12, 0x04, 0x33])  # continuous buttons + IR
    slot.dev.send(report_33(A, [(412, 384, 2), (612, 384, 2)]))
    r.read(now=1.1)
    assert r.buttons == A and r.pointer == (0.5, 0.5)
    r.read(now=1.1 + wiimote.QUIET_SECONDS + 1)
    assert not r.connected and r.pointer is None


def test_remote_already_on_is_set_up_too():
    """A remote that was already on (or that Dolphin just let go of) sends
    button reports before any status report. It still gets its IR camera
    switched on, or the pointer never moves."""
    slot = Slot()
    r = wiimote.Remote("/fake", fd=slot.host.detach(), aim=wiimote.Aim(offset=0))
    slot.dev.send(bytes([0x30, 0x00, 0x08]))  # plain buttons report: A
    r.read(now=1.0)
    assert r.connected and r.buttons == A
    sent = slot.sent()
    assert bytes([0x13, 0x04]) in sent and sent[-1] == bytes([0x12, 0x04, 0x33])
    slot.dev.send(report_33(0, [(412, 384, 2), (612, 384, 2)]))
    r.read(now=1.1)
    assert r.pointer == (0.5, 0.5)


def test_remote_stuck_without_ir_reports_is_set_up_again():
    """If the remote keeps sending plain button reports (it missed the setup,
    or something else changed its mode), send the setup again."""
    slot = Slot()
    r = wiimote.Remote("/fake", fd=slot.host.detach(), aim=wiimote.Aim(offset=0))
    slot.dev.send(bytes([0x20, 0, 0, 0, 0, 0, 0x60]))
    r.read(now=1.0)
    slot.sent()
    for t in (1.5, 2.0, 2.5, 3.0, 3.5):
        slot.dev.send(bytes([0x30, 0x00, 0x00]))
        r.read(now=t)
    assert bytes([0x12, 0x04, 0x33]) in slot.sent()  # set up again
    # With IR reports arriving it's left alone.
    for t in (4.0, 4.5, 5.0, 5.5, 6.0, 6.5):
        slot.dev.send(report_33(0, []))
        r.read(now=t)
    assert slot.sent() == []


class Sink:
    def __init__(self):
        self.calls = []

    def key(self, name, down):
        self.calls.append(("key", name, down))

    def move(self, x, y):
        self.calls.append(("move", round(x, 2), round(y, 2)))

    def button(self, number, down):
        self.calls.append(("button", number, down))


@pytest.fixture
def rig(monkeypatch):
    slot = Slot()

    def fake_open(self):
        self.fd = slot.host.fileno()
        return True

    monkeypatch.setattr(wiimote.Remote, "open", fake_open)
    monkeypatch.setattr(wiimote.Remote, "close", lambda self: setattr(self, "connected", False))
    taps, holds, sink = [], [], Sink()
    dolphin = {"running": False}
    wii = WiiInput(sink, lambda: taps.append(1), lambda: holds.append(1), find=lambda: ["/fake"],
                   dolphin=lambda: dolphin["running"])
    clock = {"t": 100.0}

    def press(buttons, dots=(), menu=False, pointing=False, mouse=False, dt=0.05):
        clock["t"] += dt
        slot.dev.send(report_33(buttons, dots))
        return wii.poll(menu, pointing, mouse, now=clock["t"])

    slot.dev.send(bytes([0x20, 0, 0, 0, 0, 0, 0x60]))
    wii.poll(False, False, False, now=clock["t"])
    slot.sent()
    return wii, sink, press, taps, holds, dolphin


def test_buttons_become_keys_for_the_app(rig):
    wii, sink, press, *_ = rig
    assert wii.active
    press(A)
    press(0)
    press(B | DOWN)
    assert sink.calls == [("key", "Return", True), ("key", "Return", False),
                          ("key", "Down", True), ("key", "Escape", True)]


def test_mouse_mode_clicks_and_points(rig):
    wii, sink, press, *_ = rig
    press(A, [(412, 384, 2), (612, 384, 2)], mouse=True)
    press(0, [(412, 384, 2), (612, 384, 2)], mouse=True)
    press(TWO, mouse=True)
    press(0, mouse=True)
    assert ("move", 0.5, 0.79) in sink.calls  # the bar is below the TV by default
    assert [c for c in sink.calls if c[0] == "button"] == [("button", 1, True), ("button", 1, False),
                                                          ("button", 3, True), ("button", 3, False)]
    sink.calls.clear()
    press(0, [(412, 384, 2), (612, 384, 2)])  # neither mouse mode nor the home screen: no pointer
    assert sink.calls == []


def test_menu_navigation_with_repeat(rig):
    wii, sink, press, *_ = rig
    press(DOWN)  # held down while the menu opens: the app's key is let go
    assert press(DOWN, menu=True) == []
    assert ("key", "Down", False) in sink.calls
    assert press(0, menu=True) == []
    assert press(UP, menu=True) == [Nav.UP]
    assert press(UP, menu=True, dt=0.2) == []
    assert press(UP, menu=True, dt=0.25) == [Nav.UP]  # repeats after 0.4 s
    assert press(A, menu=True) == [Nav.SELECT]


def test_home_tap_and_hold(rig):
    wii, sink, press, taps, holds, _ = rig
    press(HOME)
    press(0)
    assert taps == [1] and holds == []
    press(HOME)
    press(HOME, dt=HOLD_SECONDS + 0.1)
    press(0)
    assert taps == [1] and holds == [1]


def test_dolphin_gets_the_remotes(rig):
    wii, sink, press, _, _, dolphin = rig
    dolphin["running"] = True
    assert press(A, dt=1.5) == [] and not wii.active and wii.remotes == {}
    assert sink.calls == []
    dolphin["running"] = False
    press(0, dt=1.5)
    assert "/fake" in wii.remotes


def test_wii_mouse_setting():
    o = Overlay.__new__(Overlay)
    o.config = cfg.parse({"rows": [{"apps": [
        {"id": "kodi", "name": "Kodi", "command": "kodi"},
        {"id": "discord", "name": "Discord", "command": "d", "background": True, "pointer": True}]}]})
    state = {"focus": "home", "foreground": None, "background": {}, "wii_mouse": {}}
    o.state = state
    assert not o.wii_mouse()
    state.update(focus="foreground", foreground={"id": "kodi"})
    assert focus_key(state) == "kodi" and not o.wii_mouse()
    state["wii_mouse"]["kodi"] = True
    assert o.wii_mouse()
    state.update(focus="discord", background={"discord": {"pointer": True}})
    assert o.wii_mouse()
    o.config = cfg.parse({"wii_remote": {"mouse": "never"}})
    assert not o.wii_mouse()
    with pytest.raises(cfg.ConfigError):
        cfg.parse({"wii_remote": {"mouse": "sometimes"}})


def test_pointing_at_tiles(shipped_config):
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((1280, 720))
        config = cfg.load(shipped_config)
        screen = ui.HomeScreen(surface, Home(config), config.title)
        screen.draw()
        rect, r, c = next(h for h in screen._hits if (h[1], h[2]) == (1, 2))
        screen.point(rect.center)
        assert (screen.home.row, screen.home.col) == (1, 2)
        screen.draw()
        assert screen.click(rect.center).id == config.rows[1].apps[2].id
        poweroff = next(h for h in screen._hits if config.rows[h[1]].apps[h[2]].id == "poweroff") \
            if any(config.rows[h[1]].apps[h[2]].id == "poweroff" for h in screen._hits) else None
        if poweroff:
            assert screen.click(poweroff[0].center) is None and screen.confirming.id == "poweroff"
            assert screen.click((5, 5)).id == "poweroff"  # a click anywhere confirms
    finally:
        pygame.quit()


def test_wii_support_switches_on_and_off_live():
    o = Overlay.__new__(Overlay)
    o.config = cfg.parse({"wii_remote": {"enabled": False}})
    o.gs, o.wii, o._wii_status = None, None, None

    class View:
        def set_theme(self, *a):
            pass

    class Pointer:
        speed = 1.0

    import queue

    class Mapper:
        swap_confirm = False

    o.view, o.pointer, o.events, o.mapper = View(), Pointer(), queue.Queue(), Mapper()
    o.apply_config()
    assert o.wii is None
    o.config = cfg.parse({"wii_remote": {"enabled": True, "hold": "sideways"}})
    o.apply_config()
    assert o.wii is not None and o.wii.sideways
    o.config = cfg.parse({"wii_remote": {"enabled": False}})
    o.apply_config()
    assert o.wii is None


def test_wii_test_command_shows_buttons_and_dots(monkeypatch):
    from hearth import ctl

    slot = Slot()
    fd = slot.host.detach()
    monkeypatch.setattr(wiimote, "find", lambda: ["/fake"])
    monkeypatch.setattr(wiimote.Remote, "open", lambda self: setattr(self, "fd", fd) or True)
    monkeypatch.setattr(wiimote.time, "sleep", lambda s: None)
    t = [0.0]
    script = {0.1: bytes([0x30, 0x00, 0x08]), 0.3: report_33(A, [(412, 384, 2), (612, 384, 2)])}

    def clock():
        t[0] = round(t[0] + 0.05, 2)
        if t[0] in script:
            slot.dev.send(script[t[0]])
        return t[0]

    lines = []
    assert ctl.cmd_wii_test(1.0, clock=clock, sleep=lambda s: None, out=lines.append) == 0
    text = "\n".join(lines)
    assert "remote 1: buttons [a]  camera: no IR reports (camera off)" in text
    assert "remote 1: buttons [a]  camera: sees 2 dot(s) aim 0.50," in text


def test_wii_test_without_dolphinbar(monkeypatch):
    from hearth import ctl

    monkeypatch.setattr(wiimote, "find", lambda: [])
    lines = []
    assert ctl.cmd_wii_test(1.0, out=lines.append) == 1 and "mode 4" in lines[0]
