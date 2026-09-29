"""Fake pactl output and a recording runner, for audio and Quick Menu tests."""

import json


def vol(pct):
    v = {"value": int(65536 * pct / 100), "value_percent": f"{pct}%", "db": "0 dB"}
    return {"front-left": v, "front-right": v}


SINKS = [
    {"index": 1, "name": "alsa_output.hdmi", "description": "LG TV (HDMI)", "mute": False, "volume": vol(65), "properties": {}},
    {"index": 2, "name": "bluez_output.headset", "description": "Arctis Nova 7", "mute": False, "volume": vol(40), "properties": {}},
]
SOURCES = [
    {"index": 1, "name": "alsa_output.hdmi.monitor", "description": "Monitor of LG TV", "mute": False, "volume": vol(100), "properties": {"device.class": "monitor"}},
    {"index": 3, "name": "bluez_input.headset", "description": "Arctis Nova 7 mic", "mute": False, "volume": vol(80), "properties": {}},
]
SINK_INPUTS = [
    {"index": 41, "sink": 1, "mute": False, "volume": vol(100), "properties": {"application.name": "Elden Ring", "application.process.binary": "eldenring.exe"}},
    {"index": 42, "sink": 1, "mute": False, "volume": vol(55), "properties": {"application.name": "WEBRTC VoiceEngine", "application.process.binary": "Discord"}},
    {"index": 43, "sink": 1, "mute": True, "volume": vol(70), "properties": {"application.name": "Spotify"}},
]
SOURCE_OUTPUTS = [
    {"index": 51, "source": 3, "mute": False, "volume": vol(100), "properties": {"application.name": "WEBRTC VoiceEngine", "application.process.binary": "Discord"}},
]


class FakePactl:
    def __init__(self):
        self.calls = []

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        lists = {"sinks": SINKS, "sources": SOURCES, "sink-inputs": SINK_INPUTS, "source-outputs": SOURCE_OUTPUTS}
        if args[:3] == ["-f", "json", "list"]:
            return json.dumps(lists[args[3]])
        if args == ["get-default-sink"]:
            return "alsa_output.hdmi\n"
        if args == ["get-default-source"]:
            return "bluez_input.headset\n"
        return ""


class FakeActions:
    def __init__(self):
        self.calls = []

    def _record(self, *call):
        self.calls.append(call)
        return "close"

    def resume(self):
        return self._record("resume")

    def go_home(self):
        return self._record("go_home")

    def start_background(self, app_id):
        return self._record("start", app_id)

    def show(self, target):
        return self._record("show", target)

    def stop_background(self, app_id):
        return self._record("stop", app_id)

    def power(self, action):
        return self._record("power", action)

    def update(self):
        return self._record("update")

    def report(self):
        return self._record("report")

    def set_wii_mouse(self, on):
        return self._record("wii_mouse", on)

    def media(self, bus, action):
        return self._record("media", bus, action)

    def screenshot(self):
        return self._record("screenshot")
