"""Play a Watch Next item from where you left off, and keep the server up to
date on how far you got.

    python3 -m hearth.watchplay <jellyfin|plex|kodi> <id> <position> <runtime> <title>

Jellyfin and Plex stream straight from your server in mpv (full screen,
controller works: A pause, D-pad seek, B/Back quit), reporting the position
every few seconds so every other screen picks up where you left off. Kodi
items open in Kodi, which resumes them itself.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import time

from . import watchnext

log = logging.getLogger("hearth.watchplay")

REPORT_SECONDS = 10.0
KODI_RPC = ("127.0.0.1", 9090)


def mpv_command(url: str, start: float, title: str, ipc: str) -> list[str]:
    return ["mpv", "--fs", "--force-window=immediate", f"--start={max(0, int(start))}",
            f"--force-media-title={title}", f"--input-ipc-server={ipc}", "--input-gamepad=yes",
            "--keep-open=no", "--really-quiet", "--hwdec=auto-safe", url]


def ask_mpv(ipc: str, prop: str):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        s.connect(ipc)
        s.sendall(json.dumps({"command": ["get_property", prop]}).encode() + b"\n")
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    for line in buf.splitlines():
        reply = json.loads(line)
        if "error" in reply and "event" not in reply:
            return reply.get("data") if reply["error"] == "success" else None
    return None


def play_stream(url: str, start: float, title: str, report, popen=subprocess.Popen,
                ask=ask_mpv, sleep=time.sleep) -> float:
    """Run mpv until it closes, calling report(event, position, paused)
    ("start", "progress", "stopped"). Returns the last position."""
    ipc = os.path.join(tempfile.gettempdir(), f"hearth-mpv-{os.getpid()}.sock")
    proc = popen(mpv_command(url, start, title, ipc))
    position, paused = start, False
    _safe(report, "start", position, False)
    last = time.monotonic()
    while proc.poll() is None:
        sleep(1.0)
        try:
            pos = ask(ipc, "time-pos")
            paused = bool(ask(ipc, "pause"))
            if isinstance(pos, (int, float)):
                position = float(pos)
        except (OSError, ValueError):
            pass
        if time.monotonic() - last >= REPORT_SECONDS:
            last = time.monotonic()
            _safe(report, "progress", position, paused)
    _safe(report, "stopped", position, False)
    return position


def _safe(report, *args) -> None:
    try:
        report(*args)
    except Exception as e:  # the film matters more than the server hearing about it
        log.warning("report: %s", e)


def play_kodi(path: str, run=subprocess.Popen, connect=socket.create_connection, wait: float = 30.0,
              sleep=time.sleep) -> int:
    """Open Kodi and ask it (over its JSON-RPC port) to resume `path`."""
    proc = run(["flatpak", "run", watchnext.KODI])
    end = time.monotonic() + wait
    while time.monotonic() < end and proc.poll() is None:
        try:
            with connect(KODI_RPC, timeout=1.0) as s:
                s.sendall(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "Player.Open",
                                      "params": {"item": {"file": path}, "options": {"resume": True}}}).encode())
            break
        except OSError:
            sleep(1.0)
    else:
        log.info("kodi: no JSON-RPC (Settings > Services > Control: allow remote control); opened Kodi only")
    return proc.wait()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="hearth-watchplay: %(message)s")
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 5:
        print(__doc__)
        return 2
    source, item_id, position, runtime, title = args[0], args[1], float(args[2]), float(args[3]), args[4]
    if source == "kodi":
        return play_kodi(item_id)
    account = watchnext.accounts().get(source)
    if not account:
        print(f"Not connected to {source}: Settings > Home screen", file=sys.stderr)
        return 1
    if source == "jellyfin":
        url = watchnext.jellyfin_stream(account, item_id)

        def report(event, pos, paused):
            watchnext.jellyfin_report(account, item_id, event, pos, paused)
    elif source == "plex":
        url = watchnext.plex_stream(account, item_id)

        def report(event, pos, paused):
            state = {"start": "playing", "progress": "paused" if paused else "playing"}.get(event, "stopped")
            watchnext.plex_report(account, item_id, state, pos, runtime)
    else:
        return 2
    play_stream(url, position, title, report)
    try:
        watchnext.cache_path().unlink()  # the row has moved on
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
