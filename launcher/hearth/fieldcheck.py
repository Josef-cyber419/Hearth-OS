"""`hearthctl check`: everything that can be checked on the real PC without
touching the screen, in one report.

Read-only and safe to run while someone is watching or playing. It runs
`hearthctl doctor`'s checks, then looks at what doctor doesn't: failed
services and errors since boot, crashes and apps that never showed a window,
how smoothly the home screen draws, memory and CPU, temperatures, disk,
network, devices, audio and the game library. The report is Markdown, saved
in ~/.local/state/hearth/checks/, ready to paste into a field report (see
CLAUDE.md and docs/FIELD_TESTS.md).
"""

from __future__ import annotations

import datetime
import os
import re
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import events, session, updates


@dataclass
class Result:
    name: str
    status: str  # "ok" | "warn" | "fail" | "info"
    detail: str
    evidence: list[str] = field(default_factory=list)  # log lines and the like


MARK = {"ok": "✅", "warn": "⚠️", "fail": "❌", "info": "·"}


def _run(cmd: list[str], timeout: float = 15) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


# -- the checks ------------------------------------------------------------------


def doctor() -> list[Result]:
    from . import ctl

    out = []
    for group in (ctl.check_updates, ctl.check_session, ctl.check_modules, ctl.check_config, ctl.check_audio,
                  ctl.check_input, ctl.check_wii, ctl.check_apps):
        try:
            for c in group():
                out.append(Result(c.name.strip(), c.status, c.detail + (f" (fix: {c.fix})" if c.fix else "")))
        except Exception as e:
            out.append(Result(group.__name__, "fail", f"check crashed: {e}"))
    return out


def version() -> list[Result]:
    s = updates.os_status()
    out = [Result("Hearth version", "info", updates.hearth_version()),
           Result("OS image", "info", f"{s.image or '?'} (booted {s.booted or '?'})")]
    if s.update_ready:
        out.append(Result("Update", "warn", f"{s.staged} is downloaded: restart to finish"))
    if updates.in_progress():
        out.append(Result("Update", "info", "an update is downloading now"))
    return out


def failed_units() -> list[Result]:
    out = []
    for scope, cmd in (("system", ["systemctl", "--failed", "--no-legend", "--plain"]),
                       ("user", ["systemctl", "--user", "--failed", "--no-legend", "--plain"])):
        code, text = _run(cmd)
        # Unit lines look like "hearth-esde-update.service loaded failed failed ...".
        units = [w[0] for w in (line.split() for line in text.splitlines())
                 if w and "." in w[0] and w[0].rsplit(".", 1)[1] in ("service", "timer", "mount", "socket", "scope")
                 # Ended logins (SSH) whose leftovers systemd had to kill: not a problem.
                 and not w[0].startswith("session-")]
        if code == 127 or (code != 0 and not units):
            first = (text.splitlines() or ["?"])[0][:100]
            out.append(Result(f"Failed {scope} services", "info", f"couldn't ask systemd: {first}"))
        elif units:
            evidence = []
            for unit in units[:5]:
                _, log = _run(["journalctl", *(["--user"] if scope == "user" else []), "-u", unit, "-b",
                               "-n", "8", "--no-pager", "-o", "short-iso"])
                evidence += [f"[{unit}]"] + log.splitlines()[-8:]
            out.append(Result(f"Failed {scope} services", "fail", ", ".join(units), evidence))
        else:
            out.append(Result(f"Failed {scope} services", "ok", "none"))
    return out


ERROR_WORDS = ("Traceback", "ERROR", "CRITICAL", "Exception")


def hearth_log(hours: float = 24) -> list[Result]:
    from . import logs

    path = logs.log_path()
    try:
        lines = path.read_text(errors="replace").splitlines()[-4000:]
    except OSError:
        return [Result("Hearth log", "info", f"no log at {path}")]
    bad = [line for line in lines if any(w in line for w in ERROR_WORDS)]
    if not bad:
        return [Result("Hearth log", "ok", "no errors in the last 4000 lines")]
    return [Result("Hearth log", "warn", f"{len(bad)} error line(s); latest shown", bad[-15:])]


def journal_errors() -> list[Result]:
    code, text = _run(["journalctl", "--user", "-b", "-p", "err", "--no-pager", "-o", "short-iso", "-n", "40"])
    if code == 127 or "No journal files" in text:
        return [Result("Errors since boot", "info", "journalctl not available")]
    lines = [line for line in text.splitlines()
             if line.strip() and not line.startswith(("-- ", "No journal files"))
             # A core dump's module list and stack, one line each: keep its headline only.
             and not re.search(r"systemd-coredump\[\d+\]:\s+(Module |#\d+ |Stack trace|ELF object)", line)]
    if not lines:
        return [Result("Errors since boot (your session)", "ok", "none")]
    return [Result("Errors since boot (your session)", "warn", f"{len(lines)} (latest 40 at most)", lines[-20:])]


def app_history(limit: int = 3000) -> list[Result]:
    """Crashes, launch failures, and apps that started but never showed a window."""
    evs = events.read(limit)
    out = []
    crashes = [e for e in evs if e.get("event") in ("crash", "launch_failed", "overlay_restart")]
    out.append(Result("Crashes and failed launches", "warn" if crashes else "ok",
                      f"{len(crashes)} in the event log" if crashes else "none",
                      [events.describe(e) for e in crashes[-10:]]))
    started: dict[str, dict] = {}
    no_window, slow = [], []
    # Only since this version started (the last session_start with another
    # version), so a check after an update is about the update.
    from . import updates

    now_version = updates.hearth_version()
    since, older = 0, False
    for i, e in enumerate(evs):
        if e.get("event") == "session_start":
            if e.get("version") != now_version:
                older = True
            elif older:  # the first start of this version after an older one
                since, older = i, False
    for e in evs[since:]:
        kind = e.get("event")
        if kind == "app_start":
            started[e.get("id", "?")] = e
        elif kind == "app_window":
            started.pop(e.get("id", "?"), None)
            if float(e.get("seconds") or 0) > 15:
                slow.append(events.describe(e))
        elif kind == "app_exit" and e.get("id") in started:
            no_window.append(events.describe(started.pop(e["id"])))
    if no_window:
        out.append(Result("Apps that never showed a window", "fail",
                          "started and closed without Hearth seeing their window (the loading screen stayed up)",
                          no_window[-10:]))
    else:
        out.append(Result("Apps that never showed a window", "ok", "none"))
    if slow:
        out.append(Result("Slow to appear (over 15 s)", "warn", f"{len(slow)}", slow[-10:]))
    frames = [e for e in evs if e.get("event") == "home_frames"]
    if frames:
        f = frames[-1]
        smooth = float(f.get("fps") or 0) >= 50 and int(f.get("hitches") or 0) <= 3
        out.append(Result("Home screen smoothness", "ok" if smooth else "warn",
                          f"{f.get('fps')} fps, p95 {f.get('p95_ms')} ms, {f.get('hitches')} hitches "
                          f"(last visit, {f.get('frames')} frames)"))
    return out


def resources() -> list[Result]:
    from . import footprint

    f = footprint.measure(3.0)
    h = f.hearth
    out = [Result("Memory in use", "info", f"{footprint.gib(f.used)} of {footprint.gib(f.total)}"),
           Result("Hearth itself", "ok" if h.cpu < 5 and h.memory < 600 * 2**20 else "warn",
                  f"{h.cpu:.1f}% of a core, {footprint.gib(h.memory)} ({h.processes} processes)")]
    top = [f"{u.name}: {footprint.gib(u.memory)}, {u.cpu:.1f}%" for u in f.programs[:8]]
    out.append(Result("Biggest programs", "info", f"processor {f.cpu / f.cores:.1f}% of {f.cores} cores", top))
    # / is the read-only image (always "0 of 0"); the drive it's on is /sysroot.
    for label, path in (("Disk: system drive", "/sysroot"), ("Disk: /var (apps, games, updates)", "/var"),
                        ("Disk: home", str(Path.home()))):
        try:
            u = shutil.disk_usage(path)
        except OSError:
            continue
        free = u.free / 2**30
        if not u.total:
            continue
        status = "fail" if free < 5 else "warn" if free < 20 else "ok"
        out.append(Result(label, status, f"{free:.0f} GB free of {u.total / 2**30:.0f} GB"))
    return out


def temperatures() -> list[Result]:
    try:
        from . import perf

        r = perf.Monitor().read()
    except Exception as e:
        return [Result("Temperatures", "info", f"couldn't read: {e}")]
    parts = []
    for label, attr in (("CPU", "cpu_temp"), ("GPU", "gpu_temp"), ("GPU hotspot", "gpu_hotspot")):
        v = getattr(r, attr, None)
        if v is not None:
            parts.append(f"{label} {v:.0f}°C")
    hot = any((getattr(r, a, None) or 0) >= 90 for a in ("cpu_temp", "gpu_temp", "gpu_hotspot"))
    return [Result("Temperatures (idle)", "warn" if hot else "ok" if parts else "info",
                   ", ".join(parts) or "no sensors found")]


def graphics() -> list[Result]:
    vendors = {"0x1002": "AMD", "0x8086": "Intel", "0x10de": "NVIDIA"}
    found = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
        try:
            vendor = (card / "device/vendor").read_text().strip()
            found.append(vendors.get(vendor, vendor))
        except OSError:
            continue
    if not found:
        return [Result("Graphics", "info", "no card found in /sys/class/drm")]
    bad = "NVIDIA" in found
    return [Result("Graphics", "fail" if bad else "ok", ", ".join(found) +
                   (" (NVIDIA isn't supported: see docs/COMPATIBILITY.md)" if bad else ""))]


def network() -> list[Result]:
    from . import netstate

    out = []
    try:
        link = netstate.link(wait=True)
        out.append(Result("Connection", "ok" if link.kind != "none" else "fail",
                          {"wired": "wired", "wifi": f"Wi-Fi ({link.bars}/4 bars)", "none": "offline"}[link.kind]))
    except OSError as e:
        out.append(Result("Connection", "info", str(e)))
    for host in ("ghcr.io", "github.com", "flathub.org"):
        t0 = time.monotonic()
        try:
            socket.create_connection((host, 443), timeout=5).close()
            out.append(Result(f"Reach {host}", "ok", f"{(time.monotonic() - t0) * 1000:.0f} ms"))
        except OSError as e:
            out.append(Result(f"Reach {host}", "fail", str(e)))
    return out


def phone_remote() -> list[Result]:
    """The phone remote's page answers, and the firewall lets phones reach it."""
    import urllib.error
    import urllib.request

    from . import session

    info = session.read().get("remote")
    if not info:
        return [Result("Phone remote", "info", "not running (starts with Hearth in Game Mode)")]
    out = []
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/me", timeout=3) as resp:
            body = resp.read(200).decode("utf-8", "replace")
        out.append(Result("Phone remote", "ok" if '"front"' in body else "warn", f"{info['url']} answers"))
    except urllib.error.HTTPError as e:
        if e.code == 503:
            return [Result("Phone remote", "info", "turned off in Settings → Phone remote")]
        out.append(Result("Phone remote", "fail", f"{info['url']} answers with an error: {e}"))
    except OSError as e:
        out.append(Result("Phone remote", "fail", f"{info['url']} doesn't answer: {e}"))
    rc, zone = _run(["firewall-cmd", "--get-default-zone"], timeout=5)
    if rc == 0 and zone and zone != "FedoraWorkstation":  # that zone opens every port above 1024
        rc, ports = _run(["firewall-cmd", "--list-ports"], timeout=5)
        if rc == 0 and f"{info['port']}/tcp" not in ports.split():
            out.append(Result("Phone remote firewall", "warn",
                              f"zone {zone} may block port {info['port']}: "
                              f"sudo firewall-cmd --add-port={info['port']}/tcp --permanent && sudo firewall-cmd --reload"))
    return out


def casting() -> list[Result]:
    """The receivers a phone would look for: installed, running, discoverable."""
    import shutil

    from . import cast
    from . import config as cfg

    out = []
    try:
        config = cfg.load()
        state = session.read()
    except Exception as e:  # noqa: BLE001
        return [Result("Casting", "info", f"couldn't read the settings: {e}")]
    marks = {"off": "info", "missing": "warn", "running": "ok", "stopped": "warn"}
    for receiver, how, words in cast.status(config, state["background"]):
        if how == "stopped":
            words = "on, but not running: hearthctl logs"
        out.append(Result(f"{receiver.name} receiver", marks[how], words))
    if config.cast_airplay and shutil.which("uxplay"):
        rc, _ = _run(["systemctl", "is-active", "--quiet", "avahi-daemon"], timeout=5)
        out.append(Result("AirPlay discovery (avahi)", "ok" if rc == 0 else "warn",
                          "avahi-daemon running" if rc == 0 else "avahi-daemon not running: phones won't see the PC"))
        decoder = next((d for d in ("avdec_h264", "vah264dec", "vaapih264dec")
                        if _run(["gst-inspect-1.0", d], timeout=10)[0] == 0), None)
        out.append(Result("AirPlay video decoder", "ok" if decoder else "warn",
                          decoder or "no GStreamer H.264 decoder: casting would be sound only"))
    return out


def devices() -> list[Result]:
    out = []
    try:
        from . import battery

        pads = battery.controllers()
        out.append(Result("Controllers with a battery", "info",
                          ", ".join(f"{b.name} {b.percent}%" for b in pads if b.percent is not None)
                          or "none connected"))
    except Exception as e:
        out.append(Result("Controllers", "info", f"couldn't read: {e}"))
    try:
        import evdev

        names = sorted({evdev.InputDevice(p).name for p in evdev.list_devices()})
        out.append(Result("Input devices", "info", f"{len(names)}", names))
    except Exception as e:
        out.append(Result("Input devices", "info", f"couldn't list: {e}"))
    from . import tv

    if tv.available():
        _, status = _run([tv.HELPER, "status"], timeout=10)
        out.append(Result("TV over HDMI-CEC", "ok" if status else "warn",
                          f"{tv.vendor() or 'make unknown'}, power: {status or 'no answer'}"))
    else:
        out.append(Result("TV over HDMI-CEC", "info", "no CEC adapter"))
    return out


def audio() -> list[Result]:
    try:
        from .audio import Audio

        snap = Audio().snapshot()
    except Exception as e:
        return [Result("Audio", "fail", f"couldn't read PipeWire: {e}")]
    out = snap.output()
    return [Result("Audio output", "ok" if out else "warn",
                   f"{out.label if out else 'no default output'}; {len(snap.outputs)} outputs, "
                   f"{len(snap.inputs)} inputs")]


def library() -> list[Result]:
    from . import library as lib
    from . import watchnext

    try:
        games = lib.all_games()
    except Exception as e:
        return [Result("Game library", "fail", f"couldn't read it: {e}")]
    counts: dict[str, int] = {}
    for g in games:
        counts[g.platform] = counts.get(g.platform, 0) + 1
    out = [Result("Game library", "info" if games else "warn",
                  ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])) or "no games")]
    acc = watchnext.accounts()
    fetched, items = watchnext.cached()
    out.append(Result("Watch next", "info",
                      f"Jellyfin {'on' if acc.get('jellyfin') else 'off'}, Plex {'on' if acc.get('plex') else 'off'}, "
                      f"{len(items)} in progress (fetched {_ago(fetched)})"))
    return out


def _ago(t: float) -> str:
    if not t:
        return "never"
    m = int((time.time() - t) / 60)
    return f"{m} min ago" if m < 120 else f"{m // 60} h ago"


def running() -> list[Result]:
    s = session.read()
    fg = (s.get("foreground") or {}).get("name")
    return [Result("In front", "info", f"{fg or 'home screen'}; focus {s.get('focus')}; "
                                      f"background: {', '.join(s['background']) or 'none'}; "
                                      f"paused: {', '.join(e['name'] for e in s['suspended']) or 'none'}")]


SECTIONS = [
    ("Version and updates", version),
    ("Setup (hearthctl doctor)", doctor),
    ("Services and errors", lambda: failed_units() + journal_errors() + hearth_log()),
    ("Apps", app_history),
    ("What's running", running),
    ("Resources", lambda: resources() + temperatures() + graphics()),
    ("Network", lambda: network() + phone_remote() + casting()),
    ("Devices", lambda: devices() + audio()),
    ("Library", library),
]


# -- the report --------------------------------------------------------------------


def run(sections=SECTIONS) -> list[tuple[str, list[Result]]]:
    from .gamescope import adopt_session_display

    adopt_session_display()
    out = []
    for title, check in sections:
        try:
            out.append((title, check()))
        except Exception as e:  # one broken check never hides the rest
            out.append((title, [Result(title, "fail", f"check crashed: {type(e).__name__}: {e}")]))
    return out


def markdown(results: list[tuple[str, list[Result]]]) -> str:
    flat = [r for _, rs in results for r in rs]
    counts = {k: sum(r.status == k for r in flat) for k in ("fail", "warn", "ok")}
    lines = [f"# Hearth check: {updates.hearth_version()}, {datetime.datetime.now():%Y-%m-%d %H:%M}", "",
             f"{counts['fail']} failed, {counts['warn']} to look at, {counts['ok']} fine.", ""]
    problems = [r for r in flat if r.status in ("fail", "warn")]
    if problems:
        lines += ["## Needs attention", ""]
        lines += [f"- {MARK[r.status]} **{r.name}**: {r.detail}" for r in problems]
        lines.append("")
    for title, rs in results:
        lines += [f"## {title}", ""]
        for r in rs:
            lines.append(f"- {MARK[r.status]} **{r.name}**: {r.detail}")
            if r.evidence:
                lines += ["", "  ```", *(f"  {e}" for e in r.evidence), "  ```", ""]
        lines.append("")
    return "\n".join(lines)


def save(text: str) -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "hearth" / "checks"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"check-{datetime.datetime.now():%Y%m%d-%H%M%S}.md"
    path.write_text(text)
    return path
