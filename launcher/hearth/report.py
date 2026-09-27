"""`hearthctl report`: everything needed to understand a problem, in one file.

Collects hardware, drivers, displays, audio, controllers, apps, services,
this boot's and the previous boot's logs, Hearth's own logs and event
timeline, and (from the Quick Menu, or with --screenshot) what's on screen.
Personal details are masked: your user name, the PC's name, network and
Bluetooth addresses. Nothing is sent anywhere; you choose who gets the file.
"""

from __future__ import annotations

import contextlib
import getpass
import io
import os
import re
import shutil
import socket
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Callable

from . import config as cfg
from . import events, logs, session, updates

KEEP = 10  # older reports are deleted

# (file, command). Missing tools and permission errors are noted, not fatal.
COMMANDS: list[tuple[str, list[str]]] = [
    ("os/bootc-status.txt", ["bootc", "status"]),
    ("os/rpm-ostree-status.txt", ["rpm-ostree", "status", "-v"]),
    ("os/uname.txt", ["uname", "-a"]),
    ("os/uptime.txt", ["uptime"]),
    ("hardware/cpu.txt", ["lscpu"]),
    ("hardware/memory.txt", ["free", "-h"]),
    ("hardware/disks.txt", ["df", "-h", "-x", "tmpfs", "-x", "devtmpfs", "-x", "overlay"]),
    ("hardware/block-devices.txt", ["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL"]),
    ("hardware/pci.txt", ["lspci", "-nnk"]),
    ("hardware/usb.txt", ["lsusb"]),
    ("hardware/sensors.txt", ["sensors"]),
    ("graphics/vulkan.txt", ["vulkaninfo", "--summary"]),
    ("graphics/opengl.txt", ["glxinfo", "-B"]),
    ("audio/pactl-info.txt", ["pactl", "info"]),
    ("audio/outputs.txt", ["pactl", "list", "sinks"]),
    ("audio/inputs.txt", ["pactl", "list", "sources"]),
    ("audio/cards.txt", ["pactl", "list", "cards"]),
    ("audio/wpctl-status.txt", ["wpctl", "status"]),
    ("input/bluetooth-devices.txt", ["bluetoothctl", "devices"]),
    ("input/capture-devices.txt", ["v4l2-ctl", "--list-devices"]),
    ("apps/flatpaks.txt", ["flatpak", "list", "--app", "--columns=application,version,branch,installation"]),
    ("services/failed-system.txt", ["systemctl", "--failed", "--no-pager"]),
    ("services/failed-user.txt", ["systemctl", "--user", "--failed", "--no-pager"]),
    ("services/hearth-user-units.txt", ["systemctl", "--user", "list-units", "hearth*", "--all", "--no-pager"]),
    ("services/timers.txt", ["systemctl", "list-timers", "--all", "--no-pager"]),
    ("logs/journal-session.txt", ["journalctl", "--user", "-b", "--no-pager", "-n", "5000"]),
    ("logs/journal-warnings.txt", ["journalctl", "-b", "-p", "warning", "--no-pager", "-n", "2000"]),
    ("logs/journal-kernel.txt", ["journalctl", "-k", "-b", "--no-pager", "-n", "2000"]),
    # Freezes and hard crashes only show up after the restart that fixed them.
    ("logs/journal-previous-boot-errors.txt", ["journalctl", "-b", "-1", "-p", "err", "--no-pager", "-n", "1000"]),
    ("logs/journal-previous-boot-end.txt", ["journalctl", "-b", "-1", "--no-pager", "-n", "300"]),
    ("logs/coredumps.txt", ["coredumpctl", "list", "--since=-7d", "--no-pager"]),
    ("logs/uupd.txt", ["journalctl", "-u", "uupd", "--no-pager", "-n", "300"]),
    ("logs/flatpak-setup.txt", ["journalctl", "-u", "hearth-flatpak-setup", "--no-pager", "-n", "300"]),
]

MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
IPV4 = re.compile(r"\b(?!127\.)(?!0\.0\.0\.0)(?:\d{1,3}\.){3}\d{1,3}\b")
# Candidates only: clock times like 20:50:12 look similar, see _ipv6().
IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(?![\w:])")
UNIQ = re.compile(r"^(U: Uniq=).+$", re.M)
SERIAL = re.compile(r"((?:serial|SerialNumber|serial_number|ID_SERIAL_SHORT)\s*[:=]\s*\"?)[^\"\s]+", re.I)


def _ipv6(m: re.Match) -> str:
    addr = m.group(0)
    if addr in ("::", "::1") or not ("::" in addr or addr.count(":") >= 5):
        return addr
    return "<ipv6>"


class Redactor:
    """Masks what identifies you or your network; keeps what explains bugs."""

    def __init__(self) -> None:
        self.words: list[tuple[str, str]] = []
        with contextlib.suppress(Exception):
            user = getpass.getuser()
            if len(user) > 2:
                self.words.append((user, "<user>"))
        with contextlib.suppress(Exception):
            host = socket.gethostname().split(".")[0]
            if len(host) > 2 and host not in ("localhost", "bazzite", "fedora"):
                self.words.append((host, "<pc>"))

    def __call__(self, text: str) -> str:
        for word, mask in self.words:
            text = re.sub(rf"\b{re.escape(word)}\b", mask, text)
        text = MAC.sub("<mac>", text)
        text = IPV6.sub(_ipv6, text)
        text = IPV4.sub("<ip>", text)
        text = SERIAL.sub(r"\1<serial>", text)
        return UNIQ.sub(r"\1<serial>", text)


def run(argv: list[str], timeout: float = 25) -> str:
    if not shutil.which(argv[0]):
        return f"({argv[0]} is not installed)\n"
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        return f"(timed out after {timeout:.0f}s)\n"
    except OSError as e:
        return f"(couldn't run: {e})\n"
    out = p.stdout
    if p.stderr.strip():
        out += f"\n--- stderr ---\n{p.stderr}"
    if p.returncode:
        out += f"\n(exit code {p.returncode})\n"
    return out


def _read(path: Path, limit: int = 2_000_000) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data[-limit:].decode(errors="replace")


def gpu_samples(count: int = 6, interval: float = 0.5) -> str:
    """AMD GPU load, clocks, temperature and power, sampled for a few seconds."""
    cards = sorted(Path("/sys/class/drm").glob("card[0-9]"))
    lines = []
    for n in range(count):
        for card in cards:
            dev = card / "device"
            busy = _read(dev / "gpu_busy_percent")
            if busy is None:
                continue
            sclk = next((l for l in (_read(dev / "pp_dpm_sclk") or "").splitlines() if "*" in l), "?")
            mclk = next((l for l in (_read(dev / "pp_dpm_mclk") or "").splitlines() if "*" in l), "?")
            vram_used, vram_total = _read(dev / "mem_info_vram_used"), _read(dev / "mem_info_vram_total")
            hw = next(iter((dev / "hwmon").glob("hwmon*")), None) if (dev / "hwmon").exists() else None
            temp = _read(hw / "temp1_input") if hw else None
            power = (_read(hw / "power1_average") or _read(hw / "power1_input")) if hw else None
            vram = f"{int(vram_used) >> 20}/{int(vram_total) >> 20} MiB" if vram_used and vram_total else "?"
            lines.append(
                f"t={n * interval:4.1f}s {card.name} busy={busy.strip()}% core={sclk.strip()} mem={mclk.strip()} "
                f"vram={vram} temp={int(temp) / 1000 if temp else '?'}C "
                f"power={int(power) / 1e6 if power else '?'}W "
                f"perf-level={(_read(dev / 'power_dpm_force_performance_level') or '?').strip()}")
        if n < count - 1:
            time.sleep(interval)
    return "\n".join(lines) + "\n" if lines else "(no AMD GPU statistics in /sys/class/drm)\n"


def displays() -> str:
    """Connected screens and the modes they offer (no EDID: it has serials)."""
    out = []
    for conn in sorted(Path("/sys/class/drm").glob("card*-*")):
        status = (_read(conn / "status") or "?").strip()
        if status != "connected":
            out.append(f"{conn.name}: {status}")
            continue
        modes = (_read(conn / "modes") or "").split()
        unique = list(dict.fromkeys(modes))
        out.append(f"{conn.name}: connected, {len(unique)} modes: {' '.join(unique[:24])}")
    return "\n".join(out) + "\n" if out else "(no display connectors found)\n"


def input_devices() -> str:
    return _read(Path("/proc/bus/input/devices")) or "(unreadable)\n"


def gamescope_state() -> str:
    """What gamescope is showing, and every window it knows about."""
    if not os.environ.get("DISPLAY"):
        return "(not running inside Game Mode, so gamescope isn't reachable)\n"
    from .gamescope import Gamescope

    gs = Gamescope.connect()
    if gs is None:
        return "(no gamescope on this display)\n"
    lines = []
    root = gs.root
    for name in ("GAMESCOPE_FOCUSED_APP", "GAMESCOPE_FOCUSED_WINDOW", "GAMESCOPECTRL_BASELAYER_APPID",
                 "GAMESCOPE_FOCUSABLE_APPS", "GAMESCOPE_CURSOR_VISIBLE_FEEDBACK", "GAMESCOPE_VRR_ENABLED",
                 "GAMESCOPE_DISPLAY_IS_EXTERNAL", "GAMESCOPE_XWAYLAND_SERVER_ID"):
        prop = root.get_full_property(gs.atom(name), 0)
        lines.append(f"{name} = {list(prop.value) if prop else None}")
    lines.append("")
    for win in gs.top_level_windows():
        with contextlib.suppress(Exception):
            game = gs.get_cardinal(win, "STEAM_GAME")
            attrs = win.get_attributes()
            lines.append(f"0x{win.id:x} appid={game} mapped={attrs.map_state == 2} pid={gs.client_pid(win)} "
                         f"class={gs.wm_class(win)} title={gs.window_title(win)!r}")
    return "\n".join(lines) + "\n"


def screenshot(timeout: float = 4.0) -> tuple[bytes, str] | None:
    """What's on screen, as PNG bytes and how it was taken.

    gamescope's own screenshot (the one Steam uses) captures exactly what's
    shown. If it doesn't arrive, grab the focused window, plus the Quick Menu
    if it's open, straight from X instead."""
    if not os.environ.get("DISPLAY"):
        return None
    from .gamescope import Gamescope

    gs = Gamescope.connect()
    if gs is None:
        return None
    target = Path("/tmp/gamescope.png")
    before = target.stat().st_mtime if target.exists() else 0
    gs.request_screenshot()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        time.sleep(0.2)
        if target.exists() and target.stat().st_mtime > before:
            time.sleep(0.3)  # let it finish writing
            return target.read_bytes(), "gamescope"
    with contextlib.suppress(Exception):
        png = _x11_capture(gs)
        if png:
            return png, "x11 (gamescope's screenshot didn't arrive)"
    return None


def _x11_capture(gs) -> bytes | None:
    import tempfile

    import pygame
    from Xlib import X

    def grab(win):
        geo = win.get_geometry()
        img = win.get_image(0, 0, geo.width, geo.height, X.ZPixmap, 0xFFFFFFFF)
        return pygame.image.frombuffer(img.data, (geo.width, geo.height), "BGRA").copy()

    focused = gs.root.get_full_property(gs.atom("GAMESCOPE_FOCUSED_WINDOW"), 0)
    if not focused or not focused.value[0]:
        return None
    frame = grab(gs.window(focused.value[0]))
    frame.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MAX)  # windows have no alpha
    overlay = gs.find_window("Hearth Quick Menu")
    if overlay is not None and (gs.get_cardinal(overlay, "_NET_WM_WINDOW_OPACITY") or 0):
        layer = grab(overlay)
        if layer.get_size() != frame.get_size():
            layer = pygame.transform.smoothscale(layer, frame.get_size())
        frame.blit(layer, (0, 0), special_flags=pygame.BLEND_PREMULTIPLIED)
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        pygame.image.save(frame, f.name)
        return Path(f.name).read_bytes()


def doctor_text() -> str:
    from . import ctl

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            ctl.run_doctor()
        except Exception as e:  # the report must still be written
            print(f"(doctor crashed: {e})")
    return buf.getvalue()


def summary(sections: dict[str, str]) -> str:
    """The first page: enough to see what this PC is and what went wrong."""
    def first(pattern: str, text: str, default: str = "?") -> str:
        m = re.search(pattern, text, re.M)
        return m.group(1).strip() if m else default

    pci = sections.get("hardware/pci.txt", "")
    gpus = re.findall(r"^\S+ (?:VGA compatible controller|Display controller|3D controller)(?: \[\w{4}\])?: (.+)$",
                      pci, re.M)
    driver = re.findall(r"VGA compatible controller.*\n(?:\t.*\n)*?\tKernel driver in use: (\S+)", pci)
    evts = events.read(400)
    crashes = [e for e in evts if e.get("event") in ("crash", "launch_failed") or
               (e.get("event") == "app_exit" and e.get("ended") == "failed")]
    status = updates.os_status()
    kernel = first(r"^Linux \S+ (\S+)", sections.get("os/uname.txt", ""))
    cpu = first(r"^Model name:\s*(.+)$", sections.get("hardware/cpu.txt", ""))
    vulkan = first(r"driverInfo\s*=\s*(.+)$", sections.get("graphics/vulkan.txt", ""))
    memory = first(r"^Mem:\s+(\S+)", sections.get("hardware/memory.txt", ""))
    uptime = sections.get("os/uptime.txt", "?").strip()
    lines = [
        f"Hearth report, {time.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        f"Hearth:  {updates.hearth_version()}",
        f"OS:      {status.image or '?'} ({status.booted or '?'})",
        f"Kernel:  {kernel}",
        f"CPU:     {cpu}",
        f"GPU:     {'; '.join(gpus) or '?'} (driver: {', '.join(driver) or '?'})",
        f"Vulkan:  {vulkan}",
        f"Memory:  {memory}",
        f"Uptime:  {uptime}",
        "",
        "Screens:",
        *("  " + l for l in sections.get("graphics/displays.txt", "").splitlines() if "connected," in l),
        "",
        "Recent failures (from the event timeline):",
        *(["  " + events.describe(e) for e in crashes[-15:]] or ["  none recorded"]),
        "",
        "Last 25 events:",
        *(["  " + events.describe(e) for e in evts[-25:]] or ["  none recorded"]),
        "",
        "Health check (hearthctl doctor):",
        *("  " + l for l in sections.get("hearth/doctor.txt", "").splitlines()),
        "",
        "Everything else is in the folders next to this file.",
    ]
    return "\n".join(lines) + "\n"


def collect(with_screenshot: bool = False, progress: Callable[[str], None] | None = None,
            runner: Callable[[list[str]], str] = run) -> tuple[dict[str, str], dict[str, bytes]]:
    say = progress or (lambda _msg: None)
    texts: dict[str, str] = {}
    blobs: dict[str, bytes] = {}
    if with_screenshot:
        say("screenshot")
        try:
            shot = screenshot()
        except Exception as e:  # the rest of the report matters more
            shot, texts["graphics/screenshot.txt"] = None, f"(screenshot failed: {e})\n"
        if shot:
            blobs["screen.png"], how = shot
            texts["graphics/screenshot.txt"] = f"screen.png taken by {how}\n"
    for name, argv in COMMANDS:
        say(name)
        texts[name] = runner(argv)
    say("gpu")
    texts["graphics/amdgpu-samples.txt"] = gpu_samples()
    texts["graphics/displays.txt"] = displays()
    texts["input/devices.txt"] = input_devices()
    with contextlib.suppress(Exception):
        texts["graphics/gamescope.txt"] = gamescope_state()
    with contextlib.suppress(OSError):
        texts["os/os-release.txt"] = Path("/etc/os-release").read_text()

    say("hearth")
    texts["hearth/doctor.txt"] = doctor_text()
    state_dir = logs.log_path().parent
    for f in sorted(state_dir.glob("hearth.log*")) + sorted(state_dir.glob("events.jsonl*")) + \
            sorted(state_dir.glob("crash-*.txt")):
        text = _read(f)
        if text is not None:
            texts[f"hearth/{f.name}"] = text
    for name, path in (("state.json", session.state_path()), ("version.json", Path("/usr/share/hearth/version.json")),
                       ("apps.toml (your changes)", cfg.user_config_path())):
        text = _read(path)
        if text is not None:
            texts[f"hearth/{name.split(' ')[0]}"] = text
    return texts, blobs


def write(texts: dict[str, str], blobs: dict[str, bytes], out_dir: Path) -> Path:
    redact = Redactor()
    texts = {name: redact(text) for name, text in texts.items()}
    texts["SUMMARY.txt"] = summary(texts)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = f"hearth-report-{stamp}"
    path = out_dir / f"{folder}.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in [(n, t.encode()) for n, t in texts.items()] + list(blobs.items()):
            info = tarfile.TarInfo(f"{folder}/{name}")
            info.size, info.mtime = len(data), int(time.time())
            tar.addfile(info, io.BytesIO(data))
    for old in sorted(out_dir.glob("hearth-report-*.tar.gz"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return path


def reports_dir() -> Path:
    return Path.home() / "hearth-reports"


def make(with_screenshot: bool = False, out_dir: Path | None = None,
         progress: Callable[[str], None] | None = None) -> Path:
    texts, blobs = collect(with_screenshot, progress)
    path = write(texts, blobs, out_dir or reports_dir())
    events.record("report", file=path.name, size_kb=path.stat().st_size // 1024, screenshot="screen.png" in blobs)
    return path

