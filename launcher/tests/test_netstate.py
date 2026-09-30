"""The network indicator by the clock."""

import pygame

from hearth import config as cfg
from hearth import netstate, ui
from hearth.model import Home

WIRELESS = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
wlp5s0: 0000   52.  -58.  -256        0      0      0      0     12        0
"""


def fake_sys(tmp_path, ifaces):
    """ifaces: {name: (operstate, kind)} with kind "wifi" | "wired" | "virtual"."""
    root = tmp_path / "net"
    for name, (state, kind) in ifaces.items():
        d = root / name
        d.mkdir(parents=True)
        (d / "operstate").write_text(state + "\n")
        if kind != "virtual":
            (d / "device").mkdir()
        if kind == "wifi":
            (d / "wireless").mkdir()
    (tmp_path / "wireless").write_text(WIRELESS)
    return root, tmp_path / "wireless"


def test_wifi_with_signal(tmp_path):
    sys, wl = fake_sys(tmp_path, {"lo": ("unknown", "virtual"), "wlp5s0": ("up", "wifi"),
                                  "enp4s0": ("down", "wired"), "docker0": ("up", "virtual")})
    link = netstate.link(sys, wl)
    assert link == netstate.Link("wifi", 74) and link.bars == 3


def test_wired_wins(tmp_path):
    sys, wl = fake_sys(tmp_path, {"wlp5s0": ("up", "wifi"), "enp4s0": ("up", "wired")})
    assert netstate.link(sys, wl) == netstate.Link("wired")


def test_not_connected(tmp_path):
    sys, wl = fake_sys(tmp_path, {"wlp5s0": ("down", "wifi"), "tailscale0": ("up", "virtual")})
    assert netstate.link(sys, wl).kind == "none"
    assert netstate.link(tmp_path / "nowhere", wl).kind == "none"


def test_bars():
    assert [netstate.Link("wifi", s).bars for s in (0, 20, 45, 70, 100)] == [1, 1, 2, 3, 4]
    assert netstate.Link("wired").bars == 0 and netstate.Link("wifi", None).bars == 1


def test_drawn_in_the_status_bar(monkeypatch):
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((1280, 720))
        for link in (netstate.Link("wifi", 60), netstate.Link("wired"), netstate.Link("none")):
            monkeypatch.setattr(netstate, "link", lambda link=link: link)
            scr = ui.HomeScreen(surface, Home(cfg.Config(rows=())), "Hearth")
            scr.draw()
            assert scr._link == link
    finally:
        pygame.quit()


def test_wifi_strength_from_networkmanager_without_proc_wireless(tmp_path, monkeypatch):
    # Field report #38: kernel 7.2 has no /proc/net/wireless, so it said 0 bars.
    iface = tmp_path / "sys" / "wlp5s0"
    (iface / "device").mkdir(parents=True)
    (iface / "wireless").mkdir()
    (iface / "operstate").write_text("up\n")
    link = netstate.link(tmp_path / "sys", tmp_path / "missing", nm=lambda: 49)
    assert link == netstate.Link("wifi", 49) and link.bars == 2
    monkeypatch.setattr(netstate, "_nm_cache", (-100.0, None))
    assert netstate._nm_signal(run=lambda: "  :72\n*:49\n") == 49
    assert netstate._nm_signal(run=lambda: "*:90\n") == 49  # cached for a while
