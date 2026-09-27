"""hearthctl: check, debug and update Hearth from a terminal (Desktop Mode,
or over SSH from another computer).

  hearthctl status          what's running, versions, pending update
  hearthctl doctor          check every part of the setup, with fixes
  hearthctl logs [-f]       Hearth's log (home screen + Quick Menu)
  hearthctl events [-n N]   timeline: launches, exits, crashes, frame rates
  hearthctl report          save everything needed to fix a problem, in one file
  hearthctl update          install OS + app updates now (restart to finish)
  hearthctl rollback        go back to the previous OS version
  hearthctl menu | home     open the Quick Menu / close the app and go home
  hearthctl pause           go home, keep the game paused (Quick Resume)
  hearthctl emulation-setup point ES-DE at the installed emulators, fetch RetroArch cores
  hearthctl disable|enable  boot Game Mode straight into Steam / into Hearth
  hearthctl dev PATH|--off  run the launcher from a source checkout
"""

from __future__ import annotations

import argparse
import glob
import importlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config as cfg
from . import events, logs, session, updates

SESSION_OVERRIDES = Path("/etc/gamescope-session-plus/sessions.d")
LISTS = [Path("/usr/share/hearth/flatpaks.list"), Path("/usr/share/hearth/emulators.list")]


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def disabled_flag() -> Path:
    return config_home() / "hearth" / "disabled"


def dev_path_file() -> Path:
    return config_home() / "hearth" / "dev-path"


# -- doctor --------------------------------------------------------------------


@dataclass
class Check:
    name: str
    status: str  # "ok" | "warn" | "fail" | "info"
    detail: str
    fix: str = ""


SYMBOLS = {"ok": ("✓", "32"), "warn": ("!", "33"), "fail": ("✗", "31"), "info": ("·", "36")}


def check_modules() -> list[Check]:
    out = []
    for module, why, package in (("pygame", "home screen and Quick Menu", "python3-pygame"),
                                 ("Xlib", "showing apps and the Quick Menu in Game Mode", "python3-xlib"),
                                 ("evdev", "Guide button and controller-as-mouse", "python3-evdev")):
        try:
            mod = importlib.import_module(module)
            version = getattr(mod, "__version__", getattr(mod, "version", ""))
            out.append(Check(f"Python module {module}", "ok", f"{version}".strip() or "installed"))
        except ImportError:
            out.append(Check(f"Python module {module}", "fail", f"missing: needed for {why}",
                             f"the image should include {package}; rebuild it"))
    return out


def check_session() -> list[Check]:
    out = []
    hooked = [p.name for p in SESSION_OVERRIDES.glob("*") if "/usr/bin/hearth" in p.read_text(errors="replace")] \
        if SESSION_OVERRIDES.is_dir() else []
    if disabled_flag().exists():
        out.append(Check("Game Mode", "warn", "Hearth is disabled; Game Mode starts Steam directly",
                         "hearthctl enable, then restart"))
    elif hooked:
        out.append(Check("Game Mode", "ok", f"starts Hearth (sessions: {', '.join(sorted(hooked))})"))
    else:
        out.append(Check("Game Mode", "fail", "no Hearth session override found",
                         f"expected files in {SESSION_OVERRIDES}; is this the Hearth image?"))
    in_gs = bool(os.environ.get("GAMESCOPE_WAYLAND_DISPLAY"))
    out.append(Check("Running inside Game Mode", "info", "yes" if in_gs else
                     "no (normal from Desktop Mode or SSH; checks below that need Game Mode are skipped)"))
    overlay = subprocess.run(["pgrep", "-f", "hearth.overlay"], capture_output=True).returncode == 0
    if in_gs:
        out.append(Check("Quick Menu process", "ok" if overlay else "fail",
                         "running" if overlay else "not running", "" if overlay else "see: hearthctl logs"))
    out.append(Check("App scopes (pause/close)", "ok" if session.scopes_available() else "warn",
                     "systemd user scopes available" if session.scopes_available() else
                     "systemd user manager not reachable: games can't be paused",
                     "" if session.scopes_available() else "run hearthctl from your own login, not sudo"))
    return out


def check_config() -> list[Check]:
    if not cfg.SYSTEM_CONFIG.exists():
        return [Check("Home screen config", "fail", f"{cfg.SYSTEM_CONFIG} is missing",
                      "the image is incomplete; rebuild or roll back")]
    try:
        config = cfg.load()
    except (OSError, cfg.ConfigError) as e:
        return [Check("Home screen config", "fail", str(e), f"fix or remove {cfg.user_config_path()}")]
    apps = [a for row in config.rows for a in row.apps]
    hidden = [(a, a.missing()) for a in apps if a.missing()]
    source = "defaults + your changes" if cfg.user_config_path().exists() else "defaults"
    out = [Check("Home screen config", "ok", f"{len(apps) - len(hidden)} tiles shown, {len(hidden)} hidden ({source})")]
    for app, why in hidden:
        out.append(Check(f"  {app.name} tile hidden", "info", why))
    return out


def check_audio() -> list[Check]:
    from .audio import Audio

    try:
        snap = Audio().snapshot()
    except (OSError, RuntimeError, ValueError) as e:
        return [Check("Audio (PipeWire)", "fail", f"pactl failed: {e}", "is pipewire-pulse running?")]
    out_dev, in_dev = snap.output(), snap.input()
    return [Check("Audio (PipeWire)", "ok" if out_dev else "warn",
                  f"output: {out_dev.label if out_dev else 'none'}; mic: {in_dev.label if in_dev else 'none'}; "
                  f"{len(snap.playback)} apps playing")]


def check_input() -> list[Check]:
    out = []
    try:
        import evdev
    except ImportError:
        return out
    guide = []
    unreadable = 0
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            if 0x13C in dev.capabilities().get(1, []):
                guide.append(dev.name)
            dev.close()
        except OSError:
            unreadable += 1
    if guide:
        out.append(Check("Guide button", "ok", "found on: " + ", ".join(sorted(set(guide)))))
    else:
        out.append(Check("Guide button", "warn", "no controller with a Guide button is readable" +
                         (f" ({unreadable} devices not readable)" if unreadable else ""),
                         "connect a controller; input access is granted to the logged-in seat"))
    uinput = os.access("/dev/uinput", os.W_OK)
    out.append(Check("Controller as mouse (uinput)", "ok" if uinput else "warn",
                     "available" if uinput else "/dev/uinput not writable: no pointer in Discord",
                     "" if uinput else "needs the steam-devices udev rules (Bazzite includes them)"))
    return out


def check_wii() -> list[Check]:
    from . import wiimote

    slots = wiimote.find()
    if slots:
        blocked = [p for p in slots if not os.access(p, os.R_OK | os.W_OK)]
        if blocked:
            return [Check("Wii Remotes (DolphinBar)", "fail",
                          f"found in mode 4, but {len(blocked)} of {len(slots)} slots can't be opened",
                          "the image's udev rule (70-hearth-nintendo.rules) grants access: unplug and "
                          "replug the DolphinBar, or restart")]
        note = " (Dolphin has them right now)" if wiimote.dolphin_running() else ""
        return [Check("Wii Remotes (DolphinBar)", "ok",
                      f"mode 4, {len(slots)} slots, usable by Dolphin and Hearth{note}",
                      "pair a remote: press the DolphinBar's sync button, then the red button in the remote")]
    names = _read_text("/proc/bus/input/devices").lower()
    if "mayflash" in names or "dolphinbar" in names:
        return [Check("Wii Remotes (DolphinBar)", "warn", "plugged in, but not in mode 4",
                      "press the DolphinBar's mode button until LED 4 lights (mode 4 is for Dolphin and Hearth)")]
    return [Check("Wii Remotes (DolphinBar)", "info", "none plugged in")]


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def installed_flatpaks() -> set[str]:
    try:
        out = subprocess.run(["flatpak", "list", "--app", "--columns=application"], capture_output=True, text=True)
        return set(out.stdout.split())
    except OSError:
        return set()


def check_apps() -> list[Check]:
    wanted = []
    for path in LISTS:
        if path.exists():
            wanted += [line.strip() for line in path.read_text().splitlines()
                       if line.strip() and not line.startswith("#")]
    have = installed_flatpaks()
    missing = [a for a in wanted if a not in have]
    out = []
    if wanted:
        out.append(Check("Default apps & emulators", "ok" if not missing else "warn",
                         f"{len(wanted) - len(missing)}/{len(wanted)} installed" +
                         (f"; missing: {', '.join(missing)}" if missing else ""),
                         "" if not missing else
                         "they install on boot with internet; check: journalctl -u hearth-flatpak-setup"))
    esde = Path.home() / "Applications/ES-DE.AppImage"
    systems = sorted({Path(p).parent.name for p in glob.glob(str(Path.home() / "ROMs/*/*"))
                      if not p.endswith(("systeminfo.txt", "metadata.txt"))})
    out.append(Check("Emulation (ES-DE)", "ok" if esde.exists() else "warn",
                     ("installed" if esde.exists() else "not installed yet") +
                     f"; consoles with games: {', '.join(systems) if systems else 'none yet'}",
                     "" if esde.exists() else "systemctl --user start hearth-esde-update"))
    card = glob.glob("/dev/v4l/by-id/usb-Elgato*-video-index0")
    out.append(Check("Capture card", "info", Path(card[0]).name if card else "none plugged in"))
    out.append(Check("HDMI-CEC", "info", "adapter found (/dev/cec0)" if Path("/dev/cec0").exists() else "no adapter"))
    return out


def check_updates() -> list[Check]:
    status = updates.os_status()
    out = [Check("Hearth version", "info", updates.hearth_version())]
    if status.image:
        out.append(Check("OS image", "info", f"{status.image} ({status.booted})"))
    if status.update_ready:
        out.append(Check("Update", "warn", f"{status.staged} downloaded", "restart to finish updating"))
    auto = subprocess.run(["systemctl", "is-enabled", "uupd.timer"], capture_output=True, text=True).stdout.strip()
    out.append(Check("Automatic updates", "ok" if auto == "enabled" else "warn",
                     f"uupd.timer {auto or 'not found'}", "" if auto == "enabled" else "sudo systemctl enable --now uupd.timer"))
    return out


def run_doctor() -> int:
    checks = []
    for group in (check_updates, check_session, check_modules, check_config, check_audio, check_input, check_wii,
                  check_apps):
        try:
            checks += group()
        except Exception as e:  # a broken check shouldn't hide the others
            checks.append(Check(group.__name__.replace("check_", "").title(), "fail", f"check crashed: {e}"))
    color = sys.stdout.isatty()
    for c in checks:
        symbol, code = SYMBOLS[c.status]
        mark = f"\033[{code}m{symbol}\033[0m" if color else symbol
        print(f"{mark} {c.name}: {c.detail}")
        if c.fix:
            print(f"    → {c.fix}")
    failed = sum(c.status == "fail" for c in checks)
    print(f"\n{failed} problem(s) found." if failed else "\nNo problems found.")
    return 1 if failed else 0


# -- other commands ------------------------------------------------------------


def cmd_status() -> int:
    state = session.read()
    fg = state["foreground"]
    print(f"Hearth {updates.hearth_version()}")
    os_status = updates.os_status()
    if os_status.image:
        print(f"OS: {os_status.image} ({os_status.booted})")
    if os_status.update_ready:
        print(f"Update {os_status.staged} downloaded: restart to finish")
    front = state["focus"]
    front_name = (state["background"].get(front, {}).get("name") if front in state["background"]
                  else (fg or {}).get("name") or "Home screen")
    print(f"In front: {front_name}" + (" (paused)" if state["paused"] else ""))
    if fg:
        print(f"Running: {fg['name']}" + (f" [{fg['unit']}]" if fg.get("unit") else f" [pid {fg.get('pid')}]"))
    for bg in state["background"].values():
        print(f"In background: {bg['name']}")
    for paused in reversed(state.get("suspended", [])):
        print(f"Quick Resume: {paused['name']} (paused)")
    print(f"Quick Menu: {'open' if state['overlay_open'] else 'closed'}")
    print(f"Log: {logs.log_path()}")
    return 0


def cmd_logs(follow: bool, lines: int) -> int:
    path = logs.log_path()
    if not path.exists():
        print(f"No log yet at {path}")
        return 1
    return subprocess.call(["tail", "-n", str(lines), *(["-F"] if follow else []), str(path)])


def cmd_events(lines: int, as_json: bool) -> int:
    evts = events.read(lines)
    if not evts:
        print(f"No events yet ({events.path()})")
        return 1
    for e in evts:
        print(json.dumps(e) if as_json else events.describe(e))
    return 0


def cmd_report(screenshot: bool, out: str | None) -> int:
    from . import report

    print("Collecting system details, logs and Hearth's timeline (about half a minute)…")
    path = report.make(with_screenshot=screenshot, out_dir=Path(out).expanduser() if out else None,
                       progress=lambda step: print(f"  {step}", flush=True) if sys.stdout.isatty() else None)
    print(f"\nSaved: {path} ({path.stat().st_size // 1024} KB)")
    print("Your user name, the PC's name and network/Bluetooth addresses are masked.")
    print("Send this file with a description of what went wrong (and roughly when).")
    return 0


def cmd_request(kind: str) -> int:
    session.update(lambda s: s["requests"].append(kind))
    return 0


def cmd_update() -> int:
    print("Updating the OS and apps (this can take a while)…")
    ok = updates.run_helper("apply")
    updates.update_esde()
    status = updates.os_status()
    if not ok:
        print("Update failed. Details above; for more: journalctl -b -u uupd")
        return 1
    print(f"Update {status.staged} is ready: restart to finish." if status.update_ready else "Already up to date.")
    return 0


def cmd_rollback(yes: bool) -> int:
    status = updates.os_status()
    if not status.rollback:
        print("No previous version to go back to.")
        return 1
    if not yes and input(f"Go back to {status.rollback} on next restart? [y/N] ").lower() != "y":
        return 1
    ok = updates.run_helper("rollback")
    print("Done: restart to use the previous version." if ok else "Rollback failed.")
    return 0 if ok else 1


def cmd_emulation_setup(download: bool, quiet: bool) -> int:
    from . import esde

    report = None if quiet else print
    esde.setup(download=download, report=report)
    if not quiet:
        missing = esde.missing_cores() if download else []
        print("Missing cores: " + ", ".join(missing) if missing else "ES-DE and RetroArch are set up.")
    return 0


def cmd_enable(enable: bool) -> int:
    flag = disabled_flag()
    if enable:
        flag.unlink(missing_ok=True)
        print("Game Mode will start Hearth. Restart (or log out) to apply.")
    else:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
        print("Game Mode will start Steam directly. Restart (or log out) to apply. Undo: hearthctl enable")
    return 0


def cmd_dev(path: str | None, off: bool) -> int:
    f = dev_path_file()
    if off:
        f.unlink(missing_ok=True)
        print("Using the launcher built into the image. Restart Game Mode to apply.")
        return 0
    src = Path(path).expanduser().resolve()
    if not (src / "hearth" / "__init__.py").exists():
        print(f"{src} doesn't contain the hearth package (expected {src}/hearth/__init__.py)")
        return 1
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(str(src))
    print(f"Game Mode will run the launcher from {src}. Restart Game Mode to apply. Undo: hearthctl dev --off")
    return 0


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    parser = argparse.ArgumentParser(prog="hearthctl", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("doctor")
    p = sub.add_parser("logs")
    p.add_argument("-f", "--follow", action="store_true")
    p.add_argument("-n", "--lines", type=int, default=60)
    p = sub.add_parser("events")
    p.add_argument("-n", "--lines", type=int, default=50)
    p.add_argument("--json", action="store_true", help="raw JSON lines")
    p = sub.add_parser("report")
    p.add_argument("--screenshot", action="store_true", help="include a screenshot (only works in Game Mode)")
    p.add_argument("-o", "--out", help="folder to save to (default: ~/hearth-reports)")
    sub.add_parser("update")
    p = sub.add_parser("rollback")
    p.add_argument("-y", "--yes", action="store_true")
    sub.add_parser("menu")
    sub.add_parser("home")
    sub.add_parser("pause")
    sub.add_parser("enable")
    sub.add_parser("disable")
    p = sub.add_parser("emulation-setup")
    p.add_argument("--no-download", action="store_true", help="don't download RetroArch cores")
    p.add_argument("--quiet", action="store_true")
    p = sub.add_parser("dev")
    p.add_argument("path", nargs="?")
    p.add_argument("--off", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "doctor":
        return run_doctor()
    if args.cmd == "logs":
        return cmd_logs(args.follow, args.lines)
    if args.cmd == "events":
        return cmd_events(args.lines, args.json)
    if args.cmd == "report":
        return cmd_report(args.screenshot, args.out)
    if args.cmd == "update":
        return cmd_update()
    if args.cmd == "rollback":
        return cmd_rollback(args.yes)
    if args.cmd in ("menu", "home", "pause"):
        return cmd_request(args.cmd)
    if args.cmd in ("enable", "disable"):
        return cmd_enable(args.cmd == "enable")
    if args.cmd == "emulation-setup":
        return cmd_emulation_setup(not args.no_download, args.quiet)
    if args.cmd == "dev":
        if not args.off and not args.path:
            parser.error("dev needs a PATH (the launcher directory of a checkout) or --off")
        return cmd_dev(args.path, args.off)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
