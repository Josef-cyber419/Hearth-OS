import pytest
from fakes import FakePactl

from hearth.audio import Audio


def test_snapshot_parses_devices_and_streams():
    snap = Audio(FakePactl()).snapshot()
    assert [d.label for d in snap.outputs] == ["LG TV (HDMI)", "Arctis Nova 7"]
    assert [d.label for d in snap.inputs] == ["Arctis Nova 7 mic"]  # monitor filtered out
    assert snap.output().percent == 65 and snap.input().percent == 80
    assert [s.app for s in snap.playback] == ["Elden Ring", "Discord voice", "Spotify"]
    assert snap.playback[2].muted
    assert [s.index for s in snap.discord_playback()] == [42]
    assert [s.index for s in snap.discord_recording()] == [51]


def test_switching_output_moves_playing_streams():
    pactl = FakePactl()
    audio = Audio(pactl)
    audio.set_output("bluez_output.headset", audio.snapshot())
    assert ["set-default-sink", "bluez_output.headset"] in pactl.calls
    moved = [c[1] for c in pactl.calls if c[0] == "move-sink-input"]
    assert moved == ["41", "42", "43"]


def test_volume_is_clamped():
    pactl = FakePactl()
    Audio(pactl).set_output_volume("x", 500)
    assert pactl.calls[-1] == ["set-sink-volume", "x", "150%"]


def test_restored_discord_mutes_are_cleared_once():
    from fakes import SINK_INPUTS, SOURCE_OUTPUTS

    from hearth.audio import reset_restored_discord_mutes

    pactl = FakePactl()
    SINK_INPUTS[1]["mute"] = True  # Discord voice, muted from a previous session
    SOURCE_OUTPUTS[0]["mute"] = True
    try:
        audio = Audio(pactl)
        seen: set[int] = set()
        cleared = reset_restored_discord_mutes(audio, audio.snapshot(), seen)
        assert [s.index for s in cleared] == [42, 51]
        assert ["set-sink-input-mute", "42", "0"] in pactl.calls
        assert ["set-source-output-mute", "51", "0"] in pactl.calls
        # Once seen, a stream is left alone (a mute during the call sticks).
        assert reset_restored_discord_mutes(audio, audio.snapshot(), seen) == []
        # Other apps' mutes (Spotify, index 43) are never touched.
        assert not any(c[:2] == ["set-sink-input-mute", "43"] for c in pactl.calls)
    finally:
        SINK_INPUTS[1]["mute"] = False
        SOURCE_OUTPUTS[0]["mute"] = False


def test_pactl_that_stops_answering_fails_fast(monkeypatch):
    # Field report #31: a hung PipeWire made every Guide press wait 5 s per
    # pactl call and then crash the Quick Menu (TimeoutExpired wasn't caught).
    import subprocess

    from hearth import audio

    calls = []

    def hang(cmd, **kw):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(audio, "_stalled_until", 0.0)
    monkeypatch.setattr(audio.subprocess, "run", hang)
    with pytest.raises(RuntimeError):
        audio.Audio().snapshot()
    with pytest.raises(RuntimeError):
        audio.Audio().snapshot()  # doesn't try again for a while
    assert len(calls) == 1
