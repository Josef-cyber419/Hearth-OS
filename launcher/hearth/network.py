"""Network status and Wi-Fi, through NetworkManager's command-line tool (nmcli).

Bazzite manages networking with NetworkManager, and it lets the person
logged in at the TV change Wi-Fi without a password prompt.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

Runner = Callable[[list[str]], tuple[int, str, str]]


def _run(argv: list[str], timeout: float = 30) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, errors="replace")
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def available() -> bool:
    return shutil.which("nmcli") is not None


def fields(line: str) -> list[str]:
    """Split nmcli's terse (-t) output: ':' separates fields, '\\:' is a colon."""
    out, cur, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


@dataclass
class Status:
    connected: bool = False
    kind: str | None = None  # "ethernet" | "wifi"
    connection: str | None = None  # the connection's name (the network's name for Wi-Fi)
    device: str | None = None
    address: str | None = None

    def describe(self) -> str:
        if not self.connected:
            return "Not connected"
        how = "Ethernet" if self.kind == "ethernet" else f"Wi-Fi: {self.connection}"
        return f"{how} · {self.address}" if self.address else how


@dataclass
class Network:
    ssid: str
    signal: int
    secure: bool
    in_use: bool = False
    saved: bool = False

    def describe(self) -> str:
        state = "Connected" if self.in_use else "Saved" if self.saved else "Secured" if self.secure else "Open"
        return f"{state} · signal {self.signal}%"


def status(run: Runner = _run) -> Status:
    rc, out, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
    if rc:
        return Status()
    best = None
    for line in out.splitlines():
        dev, kind, state, conn = (fields(line) + ["", "", "", ""])[:4]
        if state != "connected" or kind not in ("ethernet", "wifi"):
            continue
        if best is None or (kind == "ethernet" and best.kind != "ethernet"):
            best = Status(True, kind, conn, dev)
    if best is None:
        return Status()
    rc, out, _ = run(["nmcli", "-t", "-g", "IP4.ADDRESS", "device", "show", best.device])
    if not rc and out.strip():
        best.address = out.strip().split("|")[0].strip().split("/")[0]
    return best


def wifi_enabled(run: Runner = _run) -> bool | None:
    rc, out, _ = run(["nmcli", "radio", "wifi"])
    return None if rc else out.strip() == "enabled"


def set_wifi(on: bool, run: Runner = _run) -> bool:
    return run(["nmcli", "radio", "wifi", "on" if on else "off"])[0] == 0


def saved_wifi(run: Runner = _run) -> set[str]:
    rc, out, _ = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    if rc:
        return set()
    return {f[0] for f in map(fields, out.splitlines()) if len(f) > 1 and f[1] == "802-11-wireless"}


def networks(rescan: bool = False, run: Runner = _run) -> list[Network]:
    """Wi-Fi networks in range, strongest first, one entry per name."""
    rc, out, _ = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                      "--rescan", "yes" if rescan else "auto"])
    if rc:
        return []
    saved = saved_wifi(run)
    found: dict[str, Network] = {}
    for line in out.splitlines():
        in_use, ssid, signal, security = (fields(line) + ["", "", "", ""])[:4]
        if not ssid:
            continue  # hidden networks
        net = Network(ssid, int(signal or 0), security not in ("", "--"), in_use == "*", ssid in saved)
        old = found.get(ssid)
        if old is None or net.in_use or (net.signal > old.signal and not old.in_use):
            found[ssid] = net
    return sorted(found.values(), key=lambda n: (not n.in_use, -n.signal))


def connect(ssid: str, password: str | None = None, saved: bool = False, run: Runner = _run) -> tuple[bool, str]:
    if saved and password is None:
        argv = ["nmcli", "connection", "up", "id", ssid]
    else:
        argv = ["nmcli", "device", "wifi", "connect", ssid] + (["password", password] if password else [])
    rc, out, err = run(argv)
    if rc == 0:
        return True, f"Connected to {ssid}"
    text = (err or out).strip()
    if "Secrets were required" in text or "802-1x" in text or "password" in text.lower():
        return False, "Wrong password?"
    return False, text.splitlines()[-1][:80] if text else "Couldn't connect"


def forget(ssid: str, run: Runner = _run) -> bool:
    return run(["nmcli", "connection", "delete", "id", ssid])[0] == 0


def _ping(host: str, run: Runner) -> float | None:
    rc, out, _ = run(["ping", "-c", "3", "-W", "2", "-q", host])
    m = re.search(r"= [\d.]+/([\d.]+)/", out)
    return float(m.group(1)) if rc == 0 and m else None


def test(run: Runner = _run, resolve: Callable[[str], bool] | None = None) -> str:
    """A quick check of the local network, the internet and name lookups."""
    import socket

    rc, out, _ = run(["ip", "-4", "route", "show", "default"])
    m = re.search(r"default via (\S+)", out) if rc == 0 else None
    if not m:
        return "No router found: check the cable or Wi-Fi"
    router = _ping(m.group(1), run)
    internet = _ping("1.1.1.1", run)

    def lookup(name: str) -> bool:
        try:
            socket.getaddrinfo(name, 443)
            return True
        except OSError:
            return False

    dns = (resolve or lookup)("store.steampowered.com")
    parts = [f"Router {router:.0f} ms" if router is not None else "Router not answering"]
    parts.append(f"internet {internet:.0f} ms" if internet is not None else "no internet")
    parts.append("names OK" if dns else "name lookups failing (DNS)")
    return " · ".join(parts)


# -- IP address and DNS (for the connection in use) ----------------------------

DNS_PRESETS = {  # name: servers (primary, backup)
    "Cloudflare": ("1.1.1.1", "1.0.0.1"),
    "Google": ("8.8.8.8", "8.8.4.4"),
    "Quad9": ("9.9.9.9", "149.112.112.112"),
}


@dataclass
class IpConfig:
    method: str = "auto"  # "auto" (DHCP) | "manual"
    address: str = ""  # "192.168.1.50/24" when manual
    gateway: str = ""
    dns: tuple[str, ...] = ()  # set here, instead of the router's
    ignore_auto_dns: bool = False

    @property
    def dns_choice(self) -> str:
        """"Automatic", a preset's name, or "Custom"."""
        if not self.dns:
            return "Automatic"
        return next((name for name, servers in DNS_PRESETS.items() if self.dns == servers), "Custom")


def ip_config(connection: str, run: Runner = _run) -> IpConfig | None:
    rc, out, _ = run(["nmcli", "-g", "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns,ipv4.ignore-auto-dns",
                      "connection", "show", "id", connection])
    if rc:
        return None
    lines = (out.splitlines() + [""] * 5)[:5]
    method, addresses, gateway, dns, ignore = (line.strip() for line in lines)
    split = [s.strip() for s in re.split(r"[,\s]+", dns.replace("\\", "")) if s.strip()]
    return IpConfig("manual" if method == "manual" else "auto", addresses.split(",")[0].strip(), gateway,
                    tuple(split), ignore == "yes")


def validate(address: str, prefix: int, gateway: str) -> str | None:
    """Why a manual setting won't work, or None."""
    import ipaddress

    try:
        ip = ipaddress.IPv4Address(address)
    except ValueError:
        return f"{address or 'The address'} isn't an IP address (like 192.168.1.50)"
    if not 8 <= prefix <= 30:
        return "The subnet prefix is usually 24"
    net = ipaddress.IPv4Network(f"{address}/{prefix}", strict=False)
    if ip in (net.network_address, net.broadcast_address) or ip.is_loopback or ip.is_multicast:
        return f"{address} can't be used for this PC"
    try:
        gw = ipaddress.IPv4Address(gateway)
    except ValueError:
        return f"{gateway or 'The router'} isn't an IP address (usually your router, like 192.168.1.1)"
    if gw not in net:
        return f"The router {gateway} isn't on the same network as {address}/{prefix}"
    if gw == ip:
        return "The address and the router can't be the same"
    return None


def parse_dns(text: str) -> tuple[str, ...] | str:
    """Servers typed in (spaces or commas between them), or why they won't do."""
    import ipaddress

    servers = tuple(s for s in re.split(r"[,\s]+", text.strip()) if s)
    if not servers:
        return "Type one or two server addresses, like 1.1.1.1"
    for s in servers:
        try:
            ipaddress.ip_address(s)
        except ValueError:
            return f"{s} isn't an IP address"
    return servers


def _apply(connection: str, settings: list[str], run: Runner) -> tuple[bool, str]:
    rc, out, err = run(["nmcli", "connection", "modify", "id", connection, *settings])
    if rc:
        return False, ((err or out).strip().splitlines() or ["Couldn't change the settings"])[-1][:90]
    rc, out, err = run(["nmcli", "connection", "up", "id", connection])
    if rc:
        return False, "Saved, but reconnecting failed: " + ((err or out).strip().splitlines() or ["?"])[-1][:70]
    return True, "Done: reconnected with the new settings"


def set_automatic(connection: str, run: Runner = _run) -> tuple[bool, str]:
    return _apply(connection, ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", ""], run)


def set_manual(connection: str, address: str, prefix: int, gateway: str, run: Runner = _run) -> tuple[bool, str]:
    problem = validate(address, prefix, gateway)
    if problem:
        return False, problem
    return _apply(connection, ["ipv4.method", "manual", "ipv4.addresses", f"{address}/{prefix}",
                               "ipv4.gateway", gateway], run)


def set_dns(connection: str, servers: tuple[str, ...] | None, run: Runner = _run) -> tuple[bool, str]:
    """None: the router's (automatic). Otherwise these, instead of the router's."""
    servers = servers or ()
    v4 = [s for s in servers if ":" not in s]
    v6 = [s for s in servers if ":" in s]
    return _apply(connection, ["ipv4.dns", ",".join(v4), "ipv4.ignore-auto-dns", "yes" if v4 else "no",
                               "ipv6.dns", ",".join(v6), "ipv6.ignore-auto-dns", "yes" if v6 else "no"], run)


def gateway(run: Runner = _run) -> str:
    rc, out, _ = run(["ip", "-4", "route", "show", "default"])
    m = re.search(r"default via (\S+)", out) if rc == 0 else None
    return m.group(1) if m else ""
