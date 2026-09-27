"""Controller as a mouse, for apps without a TV interface (Discord).

Left stick moves the pointer, right stick scrolls, A clicks, X right-clicks,
the d-pad sends arrow keys and B sends Escape. Output goes through a virtual
input device (uinput), which gamescope treats like a real mouse and keyboard.
"""

from __future__ import annotations

import logging
import math

import pygame

log = logging.getLogger("hearth")

DEADZONE = 0.15
SPEED = 1400.0  # pixels per second at full tilt
SCROLL_RATE = 12.0  # wheel clicks per second at full tilt

# linux/input-event-codes.h
EV_KEY, EV_REL = 0x01, 0x02
REL_X, REL_Y, REL_WHEEL = 0x00, 0x01, 0x08
BTN_LEFT, BTN_RIGHT = 0x110, 0x111
KEY_ESC, KEY_ENTER = 1, 28
KEY_UP, KEY_LEFT, KEY_RIGHT, KEY_DOWN = 103, 105, 106, 108

BUTTONS = {
    pygame.CONTROLLER_BUTTON_A: BTN_LEFT,
    pygame.CONTROLLER_BUTTON_X: BTN_RIGHT,
    pygame.CONTROLLER_BUTTON_B: KEY_ESC,
    pygame.CONTROLLER_BUTTON_DPAD_UP: KEY_UP,
    pygame.CONTROLLER_BUTTON_DPAD_DOWN: KEY_DOWN,
    pygame.CONTROLLER_BUTTON_DPAD_LEFT: KEY_LEFT,
    pygame.CONTROLLER_BUTTON_DPAD_RIGHT: KEY_RIGHT,
    pygame.CONTROLLER_BUTTON_Y: KEY_ENTER,
}


def curve(v: float) -> float:
    """Deadzone plus a quadratic response: precise when gentle, fast when pushed."""
    if abs(v) < DEADZONE:
        return 0.0
    m = min(1.0, (abs(v) - DEADZONE) / (1 - DEADZONE))
    return math.copysign(m * m, v)


def make_uinput():
    """A virtual mouse+keyboard, or None if uinput isn't available."""
    try:
        from evdev import UInput

        return UInput(
            {EV_REL: [REL_X, REL_Y, REL_WHEEL], EV_KEY: [BTN_LEFT, BTN_RIGHT, *BUTTONS.values()]},
            name="Hearth controller pointer",
        )
    except Exception as e:
        log.info("pointer: no uinput (%s)", e)
        return None


class Pointer:
    def __init__(self, device) -> None:
        self.dev = device
        self.speed = 1.0  # the Settings app's "controller mouse speed"
        self.axes = {"lx": 0.0, "ly": 0.0, "ry": 0.0}
        self._carry = {"x": 0.0, "y": 0.0, "wheel": 0.0}

    def reset(self) -> None:
        self.axes = dict.fromkeys(self.axes, 0.0)

    def handle(self, event: pygame.event.Event) -> None:
        if self.dev is None:
            return
        if event.type == pygame.CONTROLLERAXISMOTION:
            name = {pygame.CONTROLLER_AXIS_LEFTX: "lx", pygame.CONTROLLER_AXIS_LEFTY: "ly",
                    pygame.CONTROLLER_AXIS_RIGHTY: "ry"}.get(event.axis)
            if name:
                self.axes[name] = event.value / 32767
        elif event.type in (pygame.CONTROLLERBUTTONDOWN, pygame.CONTROLLERBUTTONUP):
            code = BUTTONS.get(event.button)
            if code is not None:
                self.dev.write(EV_KEY, code, 1 if event.type == pygame.CONTROLLERBUTTONDOWN else 0)
                self.dev.syn()

    def tick(self, dt: float) -> None:
        """Move the pointer for the time since the last frame."""
        if self.dev is None:
            return
        moves = {
            "x": curve(self.axes["lx"]) * SPEED * self.speed * dt,
            "y": curve(self.axes["ly"]) * SPEED * self.speed * dt,
            "wheel": -curve(self.axes["ry"]) * SCROLL_RATE * dt,
        }
        wrote = False
        for key, code in (("x", REL_X), ("y", REL_Y), ("wheel", REL_WHEEL)):
            total = self._carry[key] + moves[key]
            whole = int(total)
            self._carry[key] = total - whole
            if whole:
                self.dev.write(EV_REL, code, whole)
                wrote = True
        if wrote:
            self.dev.syn()
