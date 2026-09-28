from hearth import homebutton
from hearth.homebutton import BTN_MODE, KEY_HOMEPAGE, HomeButton


def test_guide_must_be_held():
    b = HomeButton(hold_seconds=1.5)
    assert not b.key(BTN_MODE, 1, now=10.0)
    assert not b.tick(11.0)
    assert b.tick(11.5)
    assert not b.tick(20.0)  # fires once per hold


def test_short_guide_press_does_nothing():
    b = HomeButton(hold_seconds=1.5)
    b.key(BTN_MODE, 1, now=0.0)
    b.key(BTN_MODE, 0, now=0.5)
    assert not b.tick(5.0)


def test_remote_home_key_is_instant():
    assert HomeButton().key(KEY_HOMEPAGE, 1, now=0.0)


def test_guide_tap_opens_quick_menu():
    from hearth.homebutton import KEY_MENU, GuideTap

    t = GuideTap(tap_max=0.4)
    assert not t.key(BTN_MODE, 1, now=0.0)
    assert t.key(BTN_MODE, 0, now=0.2)  # quick release: tap
    t.key(BTN_MODE, 1, now=1.0)
    assert not t.key(BTN_MODE, 0, now=2.0)  # that was a hold, not a tap
    assert t.key(KEY_MENU, 1, now=3.0)


def test_windows_key_tap_opens_quick_menu():
    tap = homebutton.GuideTap()
    assert not tap.key(homebutton.KEY_LEFTMETA, 1, 10.0)
    assert tap.key(homebutton.KEY_LEFTMETA, 0, 10.1)
    assert not tap.key(homebutton.KEY_RIGHTMETA, 1, 11.0)
    assert tap.key(homebutton.KEY_RIGHTMETA, 0, 11.2)


def test_windows_key_shortcut_or_long_press_does_not():
    tap = homebutton.GuideTap()
    tap.key(homebutton.KEY_LEFTMETA, 1, 10.0)
    assert not tap.key(30, 1, 10.05)  # Windows + A: a shortcut
    tap.key(30, 0, 10.1)
    assert not tap.key(homebutton.KEY_LEFTMETA, 0, 10.15)
    tap.key(homebutton.KEY_LEFTMETA, 1, 20.0)
    assert not tap.key(homebutton.KEY_LEFTMETA, 0, 21.0)  # held: not a tap


# -- the watcher, with controllers coming and going ----------------------------

import os  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402


class FakePad:
    """An input device: readable through a pipe, like a real event device."""

    def __init__(self, path, name="Xbox Wireless Controller", keys=(homebutton.BTN_MODE, 304)):
        self.path, self.name, self.keys = path, name, list(keys)
        self._r, self._w = os.pipe()
        self.queue, self.gone, self.closed = [], False, False

    def capabilities(self):
        return {homebutton.EV_KEY: self.keys}

    def fileno(self):
        return self._r

    def read(self):
        os.read(self._r, 4096)
        if self.gone:
            raise OSError(19, "No such device")
        events, self.queue = self.queue, []
        return events

    def send(self, code, value):
        self.queue.append(SimpleNamespace(type=homebutton.EV_KEY, code=code, value=value))
        os.write(self._w, b"x")

    def unplug(self):
        self.gone = True
        os.write(self._w, b"x")

    def close(self):
        self.closed = True


class FakeEvdev:
    def __init__(self):
        self.pads = {}

    def list_devices(self):
        return [p for p, d in self.pads.items() if not d.gone]

    def InputDevice(self, path):  # noqa: N802 - evdev's name
        pad = self.pads.get(path)
        if pad is None or pad.gone:
            raise OSError(2, "gone")
        return pad

    def plug(self, path, **kw):
        self.pads[path] = FakePad(path, **kw)
        return self.pads[path]


def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def tap(pad):
    pad.send(homebutton.BTN_MODE, 1)
    time.sleep(0.05)
    pad.send(homebutton.BTN_MODE, 0)


@pytest.fixture
def fake(monkeypatch):
    f = FakeEvdev()
    monkeypatch.setattr(homebutton, "evdev", f)
    monkeypatch.setattr(homebutton, "RESCAN_SECONDS", 0.1)
    return f


def start_tap_watcher():
    taps = []
    w = homebutton.Watcher(lambda: taps.append(time.monotonic()), homebutton.GuideTap, repeat=True)
    w.start()
    return w, taps


def test_controller_that_reconnects_keeps_working(fake):
    pad = fake.plug("/dev/input/event5")
    w, taps = start_tap_watcher()
    try:
        assert wait_for(lambda: w.devices() == ["Xbox Wireless Controller"])
        tap(pad)
        assert wait_for(lambda: len(taps) == 1)
        pad.unplug()  # asleep / Bluetooth dropped
        assert wait_for(lambda: w.devices() == [])
        again = fake.plug("/dev/input/event9")  # back, as a new device
        assert wait_for(lambda: w.devices() == ["Xbox Wireless Controller"])
        time.sleep(homebutton.DEBOUNCE_SECONDS)
        tap(again)
        assert wait_for(lambda: len(taps) == 2)
    finally:
        w.stop()
        w.join(2)


def test_controller_turned_on_after_hearth_started(fake):
    w, taps = start_tap_watcher()
    try:
        time.sleep(0.3)  # nothing to watch yet: keeps looking
        assert w.is_alive()
        pad = fake.plug("/dev/input/event3")
        assert wait_for(lambda: w.devices() == ["Xbox Wireless Controller"])
        tap(pad)
        assert wait_for(lambda: len(taps) == 1)
    finally:
        w.stop()
        w.join(2)


def test_same_tap_from_two_devices_counts_once(fake):
    pad = fake.plug("/dev/input/event5")
    virtual = fake.plug("/dev/input/event6", name="Microsoft X-Box 360 pad 0")  # Steam's copy
    w, taps = start_tap_watcher()
    try:
        assert wait_for(lambda: len(w.devices()) == 2)
        tap(pad)
        tap(virtual)  # the same press, reported again a moment later
        time.sleep(0.4)
        assert len(taps) == 1
        tap(pad)  # a real second tap, later
        assert wait_for(lambda: len(taps) == 2)
    finally:
        w.stop()
        w.join(2)


def test_devices_without_the_button_are_skipped(fake):
    fake.plug("/dev/input/event1", name="Mouse", keys=(272,))
    w, _ = start_tap_watcher()
    try:
        time.sleep(0.4)
        assert w.devices() == []
        assert fake.pads["/dev/input/event1"].closed
    finally:
        w.stop()
        w.join(2)


def test_hold_goes_home_once(fake):
    pad = fake.plug("/dev/input/event5")
    fired = threading.Event()
    w = homebutton.Watcher(fired.set, homebutton.HomeButton, hold_seconds=0.3)
    w.start()
    assert wait_for(lambda: w.devices())
    pad.send(homebutton.BTN_MODE, 1)
    assert fired.wait(2)
    w.join(2)
    assert not w.is_alive()  # a one-shot watcher stops after going home


def test_hearthctl_buttons_shows_presses_and_reconnects(fake):
    from hearth import ctl

    pad = fake.plug("/dev/input/event5")
    fake.plug("/dev/input/event1", name="Mouse", keys=(272,))
    lines = []

    def driver():
        assert wait_for(lambda: any("watching" in x or "+ Xbox" in x for x in lines))
        tap(pad)
        time.sleep(0.2)
        pad.unplug()
        time.sleep(0.3)
        tap(fake.plug("/dev/input/event9"))

    t = threading.Thread(target=driver)
    t.start()
    ctl.cmd_buttons(1.5, out=lines.append, evdev=fake)
    t.join()
    text = "\n".join(lines)
    assert "+ Xbox Wireless Controller (/dev/input/event5): Guide" in text
    assert "Mouse" not in text
    assert "Guide down" in text and "=> tap -> Quick Menu" in text
    assert "went away" in text
    assert "+ Xbox Wireless Controller (/dev/input/event9)" in text
