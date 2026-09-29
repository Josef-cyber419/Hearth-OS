"""Notices: said once, shown one after another."""

from hearth import toasts
from hearth.battery import Battery
from hearth.toasts import Notices


def titles(n):
    return [t.title for t in n.queue]


def test_low_battery_is_said_once_then_again_when_very_low():
    n = Notices()
    n.batteries([Battery("Xbox Wireless Controller", 50, False)])
    assert titles(n) == []
    n.batteries([Battery("Xbox Wireless Controller", 19, False)])
    n.batteries([Battery("Xbox Wireless Controller", 18, False)])
    assert titles(n) == ["Controller battery low"]
    n.batteries([Battery("Xbox Wireless Controller", 9, False)])
    assert titles(n)[-1] == "Controller battery very low"
    n.queue.clear()
    n.batteries([Battery("Xbox Wireless Controller", 9, True)])  # charging: forget it
    n.batteries([Battery("Xbox Wireless Controller", 15, False)])
    assert titles(n) == ["Controller battery low"]


def test_new_installs_but_not_what_was_already_there():
    n = Notices()
    n.tiles({"kodi": "Kodi", "steam": "Steam"})
    assert titles(n) == []
    n.tiles({"kodi": "Kodi", "steam": "Steam", "twitch": "Twitch"})
    assert titles(n) == ["Twitch is ready"]


def test_update_ready_once_per_version():
    n = Notices()
    n.update_ready("44.1")
    assert titles(n) == ["Update ready"]
    n.queue.clear()
    n.update_ready("44.1")
    assert titles(n) == []  # already said
    n.update_ready("44.2")
    assert titles(n) == ["Update ready"]


def test_one_after_another():
    n = Notices()
    n.post("A")
    n.post("B")
    n.post("A")  # not twice while waiting
    assert n.current(100.0).title == "A"
    assert n.current(100.0 + toasts.SECONDS - 0.1).title == "A"
    assert n.current(100.0 + toasts.SECONDS).title == "B"
    assert n.current(100.0 + 3 * toasts.SECONDS) is None


def test_notice_shows_without_taking_input():
    from hearth.gamescope import Gamescope

    calls = {}

    class Fake(Gamescope):
        def __init__(self):
            pass

        def _set_cardinals(self, win, name, values):
            calls[name] = values

        def set_click_through(self, win, through):
            calls["click_through"] = through

        class d:
            @staticmethod
            def sync():
                pass

    Fake().set_overlay_visible(None, True, 1.0, focus=False)
    assert calls["STEAM_INPUT_FOCUS"] == [0] and calls["click_through"] is True and calls["_NET_WM_WINDOW_OPACITY"][0] > 0
    Fake().set_overlay_visible(None, True)
    assert calls["STEAM_INPUT_FOCUS"] == [1] and calls["click_through"] is False
