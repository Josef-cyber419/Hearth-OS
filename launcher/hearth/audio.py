"""Audio devices and per-app volume, through PipeWire's PulseAudio interface.

Uses `pactl -f json`, which ships with pipewire-pulse on Fedora/Bazzite.
All state is read fresh into a Snapshot; every change is a single pactl call.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

log = logging.getLogger("hearth")

Runner = Callable[[Sequence[str]], str]

# PipeWire accepts up to 150% like most desktop mixers; above 100% can clip.
MAX_PERCENT = 150


PACTL_TIMEOUT = 2.0
STALLED_SECONDS = 30.0  # after a timeout, don't ask again for this long
_stalled_until = 0.0


def run_pactl(args: Sequence[str]) -> str:
    """pactl's answer. If PipeWire stops answering (it can after a trip to
    Desktop Mode, field report #31), fail fast with RuntimeError rather than
    holding up the Quick Menu for seconds on every call."""
    global _stalled_until
    if time.monotonic() < _stalled_until:
        raise RuntimeError("audio isn't answering")
    try:
        result = subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=PACTL_TIMEOUT)
    except subprocess.TimeoutExpired:
        _stalled_until = time.monotonic() + STALLED_SECONDS
        raise RuntimeError("audio isn't answering") from None
    if result.returncode != 0:
        raise RuntimeError(f"pactl {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def _percent(volume: dict) -> int:
    """Average of the per-channel volumes, as a percentage."""
    values = []
    for channel in volume.values():
        if isinstance(channel, dict) and "value_percent" in channel:
            values.append(int(str(channel["value_percent"]).rstrip("%")))
    return round(sum(values) / len(values)) if values else 0


@dataclass(frozen=True)
class Device:
    name: str
    label: str
    percent: int
    muted: bool


@dataclass(frozen=True)
class Stream:
    index: int
    app: str
    percent: int
    muted: bool
    props: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def is_discord(self) -> bool:
        haystack = " ".join(
            str(self.props.get(k, ""))
            for k in ("application.name", "application.process.binary", "application.id",
                      "pipewire.access.portal.app_id", "application.icon_name")
        ).lower()
        return "discord" in haystack or self.props.get("application.name") == "WEBRTC VoiceEngine"


@dataclass(frozen=True)
class Snapshot:
    outputs: tuple[Device, ...] = ()
    inputs: tuple[Device, ...] = ()
    default_output: str | None = None
    default_input: str | None = None
    playback: tuple[Stream, ...] = ()  # apps playing sound
    recording: tuple[Stream, ...] = ()  # apps using a microphone

    def output(self) -> Device | None:
        return next((d for d in self.outputs if d.name == self.default_output), None)

    def input(self) -> Device | None:
        return next((d for d in self.inputs if d.name == self.default_input), None)

    def discord_playback(self) -> tuple[Stream, ...]:
        return tuple(s for s in self.playback if s.is_discord)

    def discord_recording(self) -> tuple[Stream, ...]:
        return tuple(s for s in self.recording if s.is_discord)


def _app_name(props: dict) -> str:
    name = props.get("application.name") or props.get("application.process.binary") or "Unknown app"
    if name == "WEBRTC VoiceEngine":  # Discord's voice engine
        return "Discord voice"
    return str(name)


class Audio:
    def __init__(self, runner: Runner = run_pactl) -> None:
        self._runner = runner

    def run(self, args: Sequence[str]) -> str:
        if args and args[0].startswith(("set-", "move-")):
            log.debug("audio: pactl %s", " ".join(args))
        return self._runner(args)

    def _list(self, kind: str) -> list[dict]:
        return json.loads(self.run(["-f", "json", "list", kind]) or "[]")

    def snapshot(self) -> Snapshot:
        outputs = tuple(
            Device(s["name"], s.get("description") or s["name"], _percent(s.get("volume", {})), bool(s.get("mute")))
            for s in self._list("sinks")
        )
        inputs = tuple(
            Device(s["name"], s.get("description") or s["name"], _percent(s.get("volume", {})), bool(s.get("mute")))
            for s in self._list("sources")
            # Monitors are loopbacks of outputs, not microphones.
            if not s["name"].endswith(".monitor") and s.get("properties", {}).get("device.class") != "monitor"
        )
        playback = tuple(
            Stream(s["index"], _app_name(p), _percent(s.get("volume", {})), bool(s.get("mute")), p)
            for s in self._list("sink-inputs")
            for p in [s.get("properties", {})]
        )
        recording = tuple(
            Stream(s["index"], _app_name(p), _percent(s.get("volume", {})), bool(s.get("mute")), p)
            for s in self._list("source-outputs")
            for p in [s.get("properties", {})]
            # Skip PipeWire's own peak meters and loopbacks.
            if p.get("application.name") not in ("PulseAudio Volume Control", "pw-loopback")
        )
        return Snapshot(
            outputs=outputs,
            inputs=inputs,
            default_output=self.run(["get-default-sink"]).strip() or None,
            default_input=self.run(["get-default-source"]).strip() or None,
            playback=playback,
            recording=recording,
        )

    # -- changes ---------------------------------------------------------------

    @staticmethod
    def _pct(percent: int) -> str:
        return f"{max(0, min(MAX_PERCENT, int(percent)))}%"

    def set_output(self, name: str, snapshot: Snapshot | None = None) -> None:
        """Make `name` the default output and move everything already playing to it."""
        self.run(["set-default-sink", name])
        for stream in (snapshot or self.snapshot()).playback:
            try:
                self.run(["move-sink-input", str(stream.index), name])
            except RuntimeError as e:  # some streams refuse to move; not fatal
                log.info("audio: %s", e)

    def set_input(self, name: str, snapshot: Snapshot | None = None) -> None:
        self.run(["set-default-source", name])
        for stream in (snapshot or self.snapshot()).recording:
            try:
                self.run(["move-source-output", str(stream.index), name])
            except RuntimeError as e:
                log.info("audio: %s", e)

    def set_output_volume(self, name: str, percent: int) -> None:
        self.run(["set-sink-volume", name, self._pct(percent)])

    def set_output_muted(self, name: str, muted: bool) -> None:
        self.run(["set-sink-mute", name, "1" if muted else "0"])

    def set_input_volume(self, name: str, percent: int) -> None:
        self.run(["set-source-volume", name, self._pct(percent)])

    def set_input_muted(self, name: str, muted: bool) -> None:
        self.run(["set-source-mute", name, "1" if muted else "0"])

    def set_stream_volume(self, stream: Stream, percent: int) -> None:
        self.run(["set-sink-input-volume", str(stream.index), self._pct(percent)])

    def set_stream_muted(self, stream: Stream, muted: bool) -> None:
        self.run(["set-sink-input-mute", str(stream.index), "1" if muted else "0"])

    def set_recording_muted(self, stream: Stream, muted: bool) -> None:
        self.run(["set-source-output-mute", str(stream.index), "1" if muted else "0"])


def reset_restored_discord_mutes(audio: Audio, snapshot: Snapshot, seen: set[int]) -> list[Stream]:
    """Unmute Discord call streams that start out muted.

    WirePlumber remembers each app's mute by name across sessions, so a
    "Deafen" from the Quick Menu would otherwise carry over, silently, to the
    next call. The Quick Menu's mute and deafen are meant to last one call.
    `seen` holds stream indexes already checked (updated in place); returns
    the streams that were unmuted.
    """
    cleared = []
    for stream in (*snapshot.discord_playback(), *snapshot.discord_recording()):
        if stream.index in seen:
            continue
        seen.add(stream.index)
        if stream.muted:
            if stream in snapshot.discord_playback():
                audio.set_stream_muted(stream, False)
            else:
                audio.set_recording_muted(stream, False)
            cleared.append(stream)
    return cleared
