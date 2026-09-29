"""Now playing: read and control media apps (MPRIS over busctl)."""

import json

from fakes import FakeActions, FakePactl
from hearth import media
from hearth.audio import Audio
from hearth.model import Nav
from hearth.quickmenu import Context, QuickMenu, build_tabs


def fake_bus(players, calls=None):
    """players: {bus name: (status, title, artists, identity)}"""

    def run(args):
        if calls is not None:
            calls.append(args)
        if args == ["list"]:
            return json.dumps([{"name": "org.freedesktop.Notifications"}] + [{"name": n} for n in players])
        if args[0] == "get-property":
            status, title, artists, identity = players[args[1]]
            prop = args[-1]
            if prop == "PlaybackStatus":
                return json.dumps({"type": "s", "data": status})
            if prop == "Identity":
                return json.dumps({"type": "s", "data": identity})
            return json.dumps({"type": "a{sv}", "data": {
                "xesam:title": {"type": "s", "data": title},
                "xesam:artist": {"type": "as", "data": artists}}})
        if args[0] == "call":
            return ""
        return None
    return run


BUS = {"org.mpris.MediaPlayer2.spotify": ("Paused", "Song A", ["Band"], "Spotify"),
       "org.mpris.MediaPlayer2.chromium.instance42": ("Playing", "Lo-fi beats", [], "VacuumTube")}


def test_players_playing_first():
    got = media.players(fake_bus(BUS))
    assert [p.name for p in got] == ["VacuumTube", "Spotify"]
    assert got[0].playing and got[0].summary == "Lo-fi beats"
    assert got[1].summary == "Song A · Band"


def test_no_bus_no_players():
    assert media.players(lambda args: None) == []


def test_control():
    calls = []
    assert media.control("org.mpris.MediaPlayer2.spotify", "Next", fake_bus(BUS, calls))
    assert calls[-1] == ["call", "org.mpris.MediaPlayer2.spotify", media.PATH, media.PLAYER, "Next"]
    assert not media.control("org.mpris.MediaPlayer2.spotify", "Quit", fake_bus(BUS, calls))


def test_now_playing_in_the_audio_tab():
    audio, actions = Audio(FakePactl()), FakeActions()
    ctx = Context(audio, audio.snapshot(), {"foreground": None, "background": {}, "focus": "home"}, actions,
                  media=media.players(fake_bus(BUS)))
    menu = QuickMenu(build_tabs(ctx))
    row = menu.current.items[0]
    assert row.key == "media" and menu.selected is row  # first thing in the Audio tab
    assert row.label == "Lo-fi beats" and "VacuumTube · Playing" in row.detail
    menu.handle(Nav.SELECT)
    menu.handle(Nav.RIGHT)
    menu.handle(Nav.LEFT)
    bus = "org.mpris.MediaPlayer2.chromium.instance42"
    assert actions.calls == [("media", bus, "PlayPause"), ("media", bus, "Next"), ("media", bus, "Previous")]


def test_watcher_reads_in_the_background():
    import threading

    calls, gate = [], threading.Event()
    bus = fake_bus(BUS, calls)

    def slow(args):  # a media app that takes its time to answer
        gate.wait(5)
        return bus(args)

    w = media.Watcher(slow, every=10)
    assert w.poll(now=0) == []  # returns at once, while the thread waits
    gate.set()
    w.wait()
    assert w.fresh and [p.name for p in w.poll(now=1)] == ["VacuumTube", "Spotify"]
    asked = len(calls)
    w.poll(now=5)
    w.wait()
    assert len(calls) == asked  # not asked again this soon
    w.fresh = False
    w.control("org.mpris.MediaPlayer2.spotify", "PlayPause")
    w.wait()
    assert ["call", "org.mpris.MediaPlayer2.spotify", media.PATH, media.PLAYER, "PlayPause"] in calls
    assert not w.fresh  # the same players: nothing new to show


def test_watcher_survives_a_bad_answer():
    lists = iter([None, "not json", json.dumps([{"name": "org.mpris.MediaPlayer2.x"}])])

    def run(args):  # nothing, then nonsense, then a player that answers nonsense
        return next(lists, None) if args == ["list"] else "not json"

    w = media.Watcher(run, every=0)
    for t in range(3):
        w.poll(now=t)
        w.wait()
    assert w.players == [media.Player("org.mpris.MediaPlayer2.x", "x", False, "", "")]
