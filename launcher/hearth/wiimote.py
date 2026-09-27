"""Wii Remotes through a Mayflash DolphinBar (mode 4), read directly.

In mode 4 the DolphinBar hands each paired Wii Remote to the PC as a USB HID
device speaking the remote's own protocol (the one Dolphin uses), and its
LEDs act as the sensor bar. This module finds those devices, switches on the
remote's IR camera, and turns its reports into buttons and a pointer.

Protocol reference: https://wiibrew.org/wiki/Wiimote
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

NINTENDO = 0x057E
REMOTES = (0x0306, 0x0330)  # Wii Remote, Wii Remote Plus
USB_BUS = 0x0003  # the DolphinBar; Bluetooth-paired remotes belong to the kernel's driver

# Core buttons: the two bytes after the report ID, as one big-endian number.
LEFT, RIGHT, DOWN, UP, PLUS = 0x0100, 0x0200, 0x0400, 0x0800, 0x1000
TWO, ONE, B, A, MINUS, HOME = 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0080
BUTTON_MASK = LEFT | RIGHT | DOWN | UP | PLUS | TWO | ONE | B | A | MINUS | HOME
NAMES = {LEFT: "left", RIGHT: "right", DOWN: "down", UP: "up", PLUS: "plus", TWO: "2", ONE: "1",
         B: "b", A: "a", MINUS: "minus", HOME: "home"}

REPORT_BUTTONS_ACCEL_IR = 0x33  # buttons, accelerometer, 4 IR dots (extended format)
IR_WIDTH, IR_HEIGHT = 1024, 768
# The Wii's own "level 3" camera sensitivity.
IR_SENSITIVITY = (bytes([0x02, 0x00, 0x00, 0x71, 0x01, 0x00, 0xAA, 0x00, 0x64]), bytes([0x63, 0x03]))
QUIET_SECONDS = 3.0  # no reports for this long: the remote went to sleep or out of range


@dataclass
class Dot:
    x: int
    y: int
    size: int


def buttons_of(report: bytes) -> int | None:
    """The buttons held, from any report that carries them."""
    if len(report) < 3 or report[0] in (0x3D,) or not (0x20 <= report[0] <= 0x3F):
        return None
    return ((report[1] << 8) | report[2]) & BUTTON_MASK


def ir_dots(report: bytes) -> list[Dot]:
    """IR dots from a 0x33 report (extended format: 3 bytes per dot)."""
    if len(report) < 18 or report[0] != REPORT_BUTTONS_ACCEL_IR:
        return []
    dots = []
    for i in range(4):
        b0, b1, b2 = report[6 + i * 3: 9 + i * 3]
        if b0 == b1 == b2 == 0xFF:
            continue
        dots.append(Dot(b0 | ((b2 >> 4) & 3) << 8, b1 | ((b2 >> 6) & 3) << 8, b2 & 0x0F))
    return dots


BASE_GAIN = 1.6  # how much of the camera's view spans the screen at 100% speed
# Aiming at the middle of the screen, the sensor bar is this far off the middle
# of the camera's view (as a fraction of its height) when the bar is below or
# above the TV.
BAR_OFFSET = 0.18
CALIBRATION_TARGETS = ((0.1, 0.1), (0.9, 0.9))  # where the calibration targets are on screen


@dataclass
class Aim:
    """Turns the sensor bar's dots, as the camera sees them, into a place on
    the screen (0..1 on each axis), steadied against hand tremor.

    Calibrated (two targets aimed at from the couch), it maps the camera's
    view onto the screen exactly; otherwise it estimates from the sensor
    bar's position and the speed setting."""

    gain: float = BASE_GAIN
    smoothing: float = 0.45  # 0 = raw, towards 1 = steadier but laggier
    offset: float = BAR_OFFSET  # +: bar below the TV, -: above
    calibration: tuple[float, float, float, float] | None = None
    x: float | None = None
    y: float | None = None
    raw: tuple[float, float] | None = None  # the bar's middle, in camera coordinates
    _pair: tuple[Dot, Dot] | None = None  # the last two dots seen together, left one first

    def update(self, dots: list[Dot]) -> tuple[float, float] | None:
        if not dots:
            self.x = self.y = self.raw = None
            return None
        dots = sorted(dots, key=lambda d: -d.size)[:2]
        if len(dots) == 2:
            a, b = sorted(dots, key=lambda d: d.x)
            mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
            self._pair = (a, b)
        elif self._pair is not None:
            # One dot out of view: work out which one we still see (the one
            # nearest where a dot was) and keep the pair's last spacing.
            d, (a, b) = dots[0], self._pair
            sx, sy = (b.x - a.x) / 2, (b.y - a.y) / 2
            is_left = (d.x - a.x) ** 2 + (d.y - a.y) ** 2 <= (d.x - b.x) ** 2 + (d.y - b.y) ** 2
            mx, my = (d.x + sx, d.y + sy) if is_left else (d.x - sx, d.y - sy)
        else:
            mx, my = dots[0].x, dots[0].y
        self.raw = (mx, my)
        tx, ty = self.to_screen(mx, my)
        tx, ty = min(1.0, max(0.0, tx)), min(1.0, max(0.0, ty))
        if self.x is None or self.y is None:
            self.x, self.y = tx, ty
        else:
            k = 1 - self.smoothing
            self.x += (tx - self.x) * k
            self.y += (ty - self.y) * k
        return self.x, self.y


    def to_screen(self, mx: float, my: float) -> tuple[float, float]:
        if self.calibration:
            x1, y1, x2, y2 = self.calibration
            (sx1, sy1), (sx2, sy2) = CALIBRATION_TARGETS
            return (sx1 + (mx - x1) / (x2 - x1) * (sx2 - sx1),
                    sy1 + (my - y1) / (y2 - y1) * (sy2 - sy1))
        # The camera sees the bar move the opposite way to where you point.
        return (0.5 + (0.5 - mx / IR_WIDTH) * self.gain,
                0.5 + (0.5 - my / IR_HEIGHT + self.offset) * self.gain)

    def configure(self, speed: int = 100, steadiness: int = 45, bar: str = "below",
                  calibration: tuple[float, float, float, float] | None = None) -> None:
        self.gain = BASE_GAIN * speed / 100
        self.smoothing = max(0.0, min(0.9, steadiness / 100))
        self.offset = BAR_OFFSET if bar == "below" else -BAR_OFFSET
        self.calibration = calibration if calibration and calibration[0] != calibration[2] \
            and calibration[1] != calibration[3] else None


def calibration_from(first: tuple[float, float], second: tuple[float, float]) -> tuple[float, float, float, float] | None:
    """Camera positions of the bar while aiming at the two targets. None if
    they're too close together to be real aims at opposite corners."""
    (x1, y1), (x2, y2) = first, second
    if abs(x2 - x1) < IR_WIDTH * 0.08 or abs(y2 - y1) < IR_HEIGHT * 0.08:
        return None
    return (round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1))


@dataclass
class Remote:
    """One DolphinBar slot. It exists whether or not a remote is paired to it."""

    path: str
    fd: int | None = None
    buttons: int = 0
    connected: bool = False
    aim: Aim = field(default_factory=Aim)
    pointer: tuple[float, float] | None = None
    _last_report: float = 0.0
    _last_probe: float = 0.0
    player: int = 1

    def open(self) -> bool:
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
            return True
        except OSError as e:
            log.info("wii remote: can't open %s: %s", self.path, e)
            return False

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = None
        self.connected = False
        self.buttons = 0
        self.pointer = None

    def send(self, *data: int) -> bool:
        if self.fd is None:
            return False
        try:
            os.write(self.fd, bytes(data))
            return True
        except OSError:
            return False  # an empty slot doesn't accept writes

    def write_register(self, address: int, data: bytes) -> bool:
        payload = data.ljust(16, b"\0")
        ok = self.send(0x16, 0x04, (address >> 16) & 0xFF, (address >> 8) & 0xFF, address & 0xFF, len(data), *payload)
        time.sleep(0.03)  # the remote needs a moment per register write
        return ok

    def probe(self, now: float) -> None:
        """Ask a quiet slot whether a remote is there (it answers with a status report)."""
        if now - self._last_probe >= 2.0:
            self._last_probe = now
            self.send(0x15, 0x00)

    def start(self) -> None:
        """Player LED, a short rumble so you know it's working, IR camera on,
        and continuous reports of buttons + IR."""
        led = 0x10 << ((self.player - 1) % 4)
        self.send(0x11, led | 0x01)  # bit 0 of every output report is the rumble motor
        time.sleep(0.12)
        self.send(0x11, led)
        self.send(0x13, 0x04)
        self.send(0x1A, 0x04)
        self.write_register(0xB00030, b"\x08")
        self.write_register(0xB00000, IR_SENSITIVITY[0])
        self.write_register(0xB0001A, IR_SENSITIVITY[1])
        self.write_register(0xB00033, b"\x03")  # extended IR format, for report 0x33
        self.write_register(0xB00030, b"\x08")
        self.set_reporting()

    def set_reporting(self) -> None:
        self.send(0x12, 0x04, REPORT_BUTTONS_ACCEL_IR)  # 0x04: send continuously, not just on change

    def read(self, now: float) -> bool:
        """Drain pending reports. Returns True if anything arrived."""
        if self.fd is None:
            return False
        got = False
        while True:
            try:
                report = os.read(self.fd, 64)
            except BlockingIOError:
                break
            except OSError:
                self.close()
                break
            if not report:
                break
            got = True
            self._last_report = now
            if report[0] == 0x20:
                # Status report: after one, the remote stops sending until
                # the reporting mode is set again (an extension was plugged in,
                # or we probed a newly paired remote).
                if not self.connected:
                    self.connected = True
                    self.start()
                else:
                    self.set_reporting()
            buttons = buttons_of(report)
            if buttons is not None:
                self.connected = True
                self.buttons = buttons
            if report[0] == REPORT_BUTTONS_ACCEL_IR:
                self.pointer = self.aim.update(ir_dots(report))
        if self.connected and now - self._last_report > QUIET_SECONDS:
            self.connected = False
            self.buttons = 0
            self.pointer = None
        return got


def find(sys_class: Path = Path("/sys/class/hidraw")) -> list[str]:
    """/dev/hidraw paths for Wii Remote slots on a DolphinBar (mode 4)."""
    out = []
    for node in sorted(sys_class.glob("hidraw*")):
        try:
            uevent = (node / "device" / "uevent").read_text()
        except OSError:
            continue
        for line in uevent.splitlines():
            if line.startswith("HID_ID="):
                bus, vendor, product = (int(p, 16) for p in line.split("=", 1)[1].split(":"))
                if bus == USB_BUS and vendor == NINTENDO and product in REMOTES:
                    out.append(f"/dev/{node.name}")
    return out


def dolphin_running(proc: Path = Path("/proc")) -> bool:
    """Dolphin talks to the remotes itself; Hearth lets go while it runs."""
    for comm in proc.glob("[0-9]*/comm"):
        try:
            if comm.read_text().startswith("dolphin-emu"):
                return True
        except OSError:
            continue
    return False
