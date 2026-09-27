"""The Quick Menu: what's in it and how navigation changes it.

Tap Guide in any app (or on the home screen) to open it. Tabs:
  Audio   output/input device, volume, mic mute
  Mixer   per-app volume for everything playing sound
  Discord start/show Discord, mute your mic, deafen, voice volume
  System  resume, go home (Quick Resume), sleep, restart, power off

This module has no drawing code; quickmenu_view.py renders it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .audio import Audio, Snapshot
from .model import Nav

STEP = 5
CLOSE = "close"


@dataclass
class Item:
    key: str
    label: str
    kind: str  # "slider" | "toggle" | "choice" | "action" | "info"
    value: Any = None
    options: tuple[str, ...] = ()
    detail: str = ""
    muted: bool = False
    avatar: str | None = None
    confirm: bool = False
    on_change: Callable[[Any], None] | None = None
    on_select: Callable[[], str | None] | None = None
    on_mute: Callable[[bool], None] | None = None
    # Sliders: range, step, and how the value reads ("{}%", "{:.1f} s", ...).
    low: float = 0
    high: float = 100
    step: float = STEP
    unit: str = "{}%"

    def shows(self, value: float) -> str:
        return self.unit.format(round(value, 2) if isinstance(self.step, float) else round(value))

    @property
    def fraction(self) -> float:
        span = self.high - self.low
        return 0.0 if not span else max(0.0, min(1.0, ((self.value or 0) - self.low) / span))

    @property
    def selectable(self) -> bool:
        return self.kind != "info"


@dataclass
class Tab:
    key: str
    title: str
    icon: str
    items: list[Item] = field(default_factory=list)


class QuickMenu:
    def __init__(self, tabs: list[Tab]) -> None:
        self.tabs: list[Tab] = []
        self.tab = 0
        self._selected: dict[str, str] = {}
        self.confirming: str | None = None
        self.set_tabs(tabs)

    def set_tabs(self, tabs: list[Tab]) -> None:
        """Replace the contents (on refresh), keeping the selection by key."""
        current = self.tabs[self.tab].key if self.tabs else None
        self.tabs = tabs
        keys = [t.key for t in tabs]
        self.tab = keys.index(current) if current in keys else min(self.tab, max(0, len(tabs) - 1))
        for tab in tabs:
            if self._selected.get(tab.key) not in [i.key for i in tab.items if i.selectable]:
                first = next((i.key for i in tab.items if i.selectable), None)
                if first:
                    self._selected[tab.key] = first

    @property
    def current(self) -> Tab:
        return self.tabs[self.tab]

    @property
    def selected(self) -> Item | None:
        key = self._selected.get(self.current.key)
        return next((i for i in self.current.items if i.key == key), None)

    def select(self, key: str) -> None:
        """Select an item in the current tab (e.g. the one a pointer is on)."""
        if any(i.key == key and i.selectable for i in self.current.items):
            self._selected[self.current.key] = key

    def _move(self, delta: int) -> None:
        items = [i for i in self.current.items if i.selectable]
        if not items:
            return
        keys = [i.key for i in items]
        cur = self._selected.get(self.current.key)
        idx = keys.index(cur) if cur in keys else 0
        self._selected[self.current.key] = keys[max(0, min(len(keys) - 1, idx + delta))]

    def handle(self, nav: Nav) -> str | None:
        """Apply a controller action. Returns CLOSE when the menu should close."""
        confirming, self.confirming = self.confirming, None
        if nav in (Nav.BACK, Nav.MENU):
            return CLOSE
        if nav in (Nav.TAB_PREV, Nav.TAB_NEXT):
            self.tab = (self.tab + (1 if nav is Nav.TAB_NEXT else -1)) % len(self.tabs)
            return None
        if nav in (Nav.UP, Nav.DOWN):
            self._move(-1 if nav is Nav.UP else 1)
            return None
        item = self.selected
        if item is None:
            return None
        if item.kind == "slider":
            if nav in (Nav.LEFT, Nav.RIGHT):
                value = item.value + (item.step if nav is Nav.RIGHT else -item.step)
                item.value = max(item.low, min(item.high, round(value, 3)))
                if item.on_change:
                    item.on_change(item.value)
            elif nav is Nav.SELECT and item.on_mute:
                item.muted = not item.muted
                item.on_mute(item.muted)
        elif item.kind == "toggle":
            if nav in (Nav.SELECT, Nav.LEFT, Nav.RIGHT):
                item.value = not item.value
                if item.on_change:
                    item.on_change(item.value)
        elif item.kind == "choice" and item.options:
            if nav in (Nav.LEFT, Nav.RIGHT, Nav.SELECT):
                step = -1 if nav is Nav.LEFT else 1
                item.value = (item.value + step) % len(item.options)
                if item.on_change:
                    item.on_change(item.value)
        elif item.kind == "action" and nav is Nav.SELECT:
            if item.confirm and confirming != item.key:
                self.confirming = item.key
                return None
            if item.on_select:
                return item.on_select()
        return None


# -- building the tabs ---------------------------------------------------------


class Actions(Protocol):
    def resume(self) -> str | None: ...
    def go_home(self) -> str | None: ...
    def quick_resume(self) -> str | None: ...
    def start_background(self, app_id: str) -> str | None: ...
    def show(self, target: str) -> str | None: ...
    def stop_background(self, app_id: str) -> str | None: ...
    def power(self, action: str) -> str | None: ...
    def update(self) -> str | None: ...
    def report(self) -> str | None: ...
    def set_wii_mouse(self, on: bool) -> str | None: ...


@dataclass
class Context:
    audio: Audio
    snapshot: Snapshot
    state: dict
    actions: Actions
    discord_available: bool = True
    # Set while a Wii Remote is connected: {"mouse": bool, "app": name in front}
    wii: dict | None = None


def build_tabs(ctx: Context) -> list[Tab]:
    return [_audio_tab(ctx), _mixer_tab(ctx), _discord_tab(ctx), _system_tab(ctx)]


def _audio_tab(ctx: Context) -> Tab:
    a, snap = ctx.audio, ctx.snapshot
    tab = Tab("audio", "Audio", "speaker")
    out, mic = snap.output(), snap.input()
    if out:
        tab.items.append(Item(
            "volume", "Volume", "slider", value=min(100, out.percent), muted=out.muted, detail=out.label,
            on_change=lambda v, n=out.name: a.set_output_volume(n, v),
            on_mute=lambda m, n=out.name: a.set_output_muted(n, m),
        ))
    if snap.outputs:
        names = [d.name for d in snap.outputs]
        tab.items.append(Item(
            "output", "Output", "choice", options=tuple(d.label for d in snap.outputs),
            value=names.index(snap.default_output) if snap.default_output in names else 0,
            on_change=lambda i: a.set_output(names[i], snap),
        ))
    if snap.inputs:
        names_in = [d.name for d in snap.inputs]
        tab.items.append(Item(
            "input", "Microphone", "choice", options=tuple(d.label for d in snap.inputs),
            value=names_in.index(snap.default_input) if snap.default_input in names_in else 0,
            on_change=lambda i: a.set_input(names_in[i], snap),
        ))
    if mic:
        tab.items.append(Item(
            "mic-level", "Mic level", "slider", value=min(100, mic.percent), muted=mic.muted,
            on_change=lambda v, n=mic.name: a.set_input_volume(n, v),
            on_mute=lambda m, n=mic.name: a.set_input_muted(n, m),
        ))
        tab.items.append(Item(
            "mic-mute", "Mute microphone", "toggle", value=mic.muted,
            on_change=lambda m, n=mic.name: a.set_input_muted(n, m),
        ))
    if not tab.items:
        tab.items.append(Item("none", "No audio devices found", "info"))
    return tab


def _mixer_tab(ctx: Context) -> Tab:
    a = ctx.audio
    tab = Tab("mixer", "Mixer", "sliders")
    for s in ctx.snapshot.playback:
        tab.items.append(Item(
            f"stream-{s.index}", s.app, "slider", value=min(100, s.percent), muted=s.muted,
            avatar=s.app[:1].upper(),
            on_change=lambda v, s=s: a.set_stream_volume(s, v),
            on_mute=lambda m, s=s: a.set_stream_muted(s, m),
        ))
    if not tab.items:
        tab.items.append(Item("none", "Nothing is playing sound", "info",
                              detail="Apps show up here while they play audio"))
    return tab


def _discord_tab(ctx: Context) -> Tab:
    a, snap, state, act = ctx.audio, ctx.snapshot, ctx.state, ctx.actions
    tab = Tab("discord", "Discord", "chat")
    if not ctx.discord_available:
        tab.items.append(Item("none", "Discord isn't installed", "info",
                              detail="It installs automatically on first boot"))
        return tab
    if "discord" not in state.get("background", {}):
        tab.items.append(Item("start", "Start Discord", "action",
                              detail="Runs in the background while you play",
                              on_select=lambda: act.start_background("discord")))
        return tab

    if state.get("focus") == "discord":
        back = (state.get("foreground") or {}).get("name") or "Home"
        tab.items.append(Item("show", f"Back to {back}", "action",
                              on_select=lambda: act.show("foreground" if state.get("foreground") else "home")))
    else:
        tab.items.append(Item("show", "Show Discord", "action",
                              detail="Controller works as a mouse there",
                              on_select=lambda: act.show("discord")))

    voice_in, voice_out = snap.discord_recording(), snap.discord_playback()
    if voice_in:
        tab.items.append(Item(
            "mute", "Mute my mic", "toggle", value=all(s.muted for s in voice_in),
            on_change=lambda m: [a.set_recording_muted(s, m) for s in voice_in],
        ))
    if voice_out:
        tab.items.append(Item(
            "deafen", "Deafen", "toggle", value=all(s.muted for s in voice_out),
            on_change=lambda m: [a.set_stream_muted(s, m) for s in voice_out],
        ))
        tab.items.append(Item(
            "voice-volume", "Voice volume", "slider",
            value=min(100, round(sum(s.percent for s in voice_out) / len(voice_out))),
            on_change=lambda v: [a.set_stream_volume(s, v) for s in voice_out],
        ))
    if not voice_in and not voice_out:
        tab.items.append(Item("idle", "Not in a voice call", "info",
                              detail="Join a voice channel in Discord to get call controls here"))
    tab.items.append(Item("quit", "Quit Discord", "action", confirm=True,
                          on_select=lambda: act.stop_background("discord")))
    return tab


def _system_tab(ctx: Context) -> Tab:
    act, fg = ctx.actions, ctx.state.get("foreground")
    tab = Tab("system", "System", "power")
    tab.items.append(Item("resume", "Resume", "action", on_select=act.resume))
    if fg and fg.get("resumable"):
        tab.items.append(Item("quick-resume", "Home, keep " + fg["name"] + " paused", "action",
                              detail="Quick Resume: pick it up later right where you left off",
                              on_select=act.quick_resume))
    if fg:
        tab.items.append(Item("home", "Close " + fg["name"], "action", confirm=True,
                              detail="Return to the home screen", on_select=act.go_home))
    tab.items.append(_update_item(ctx))
    if ctx.wii is not None:
        tab.items.append(Item("wii-mouse", "Wii Remote pointer as mouse", "toggle", value=ctx.wii["mouse"],
                              detail=f"For {ctx.wii['app']}: point to move, A to click, 2 to right-click",
                              on_change=act.set_wii_mouse))
    tab.items.append(_report_item(ctx))
    tab.items.append(Item("sleep", "Sleep", "action", on_select=lambda: act.power("suspend")))
    tab.items.append(Item("restart", "Restart", "action", confirm=True, on_select=lambda: act.power("reboot")))
    tab.items.append(Item("poweroff", "Power off", "action", confirm=True, on_select=lambda: act.power("poweroff")))
    return tab


def _report_item(ctx: Context) -> Item:
    report = ctx.state.get("report") or {}
    status = report.get("status")
    if status == "running":
        return Item("report", "Saving a report…", "info", detail="Takes about half a minute; keep playing")
    detail = "Saves a screenshot and details for fixing a problem"
    if status == "done":
        detail = f"Saved {report.get('file')} in your hearth-reports folder"
    elif status == "failed":
        detail = "Couldn't save it; details: hearthctl logs"
    return Item("report", "Report a problem", "action", detail=detail, on_select=ctx.actions.report)


def _update_item(ctx: Context) -> Item:
    update = ctx.state.get("update") or {}
    status = update.get("status")
    if status == "running":
        return Item("update", "Updating…", "info", detail="Keep playing; it finishes in the background")
    if status == "ready":
        return Item("update", "Restart to finish update", "action", confirm=True,
                    detail=f"Version {update.get('version') or 'new'} is downloaded",
                    on_select=lambda: ctx.actions.power("reboot"))
    if status == "failed":
        return Item("update", "Update failed: try again", "action",
                    detail="Details: hearthctl logs", on_select=ctx.actions.update)
    detail = "Up to date" if status == "current" else "Updates also install automatically"
    return Item("update", "Check for updates", "action", detail=detail, on_select=ctx.actions.update)
