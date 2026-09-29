"""Turn keyboard, TV remote (HDMI-CEC / FLIRC) and gamepad events into Nav actions.

TV remotes arrive as keyboard events: HDMI-CEC through the kernel's rc-cec keymap,
a FLIRC USB IR receiver as a plain USB keyboard. Gamepads use SDL's
GameController API so button positions are consistent across controller brands.
"""

from __future__ import annotations

import pygame

from . import style
from .model import Nav


def wii_recently(within: float = 1.5) -> bool:
    import time

    from . import session

    try:
        return time.time() - float(session.read().get("wii_input_at") or 0) < within
    except Exception:
        return False

KEYS = {
    pygame.K_UP: Nav.UP,
    pygame.K_DOWN: Nav.DOWN,
    pygame.K_LEFT: Nav.LEFT,
    pygame.K_RIGHT: Nav.RIGHT,
    pygame.K_w: Nav.UP,
    pygame.K_s: Nav.DOWN,
    pygame.K_a: Nav.LEFT,
    pygame.K_d: Nav.RIGHT,
    pygame.K_RETURN: Nav.SELECT,
    pygame.K_KP_ENTER: Nav.SELECT,
    pygame.K_SPACE: Nav.SELECT,
    pygame.K_ESCAPE: Nav.BACK,
    pygame.K_BACKSPACE: Nav.BACK,
    pygame.K_AC_BACK: Nav.BACK,
    pygame.K_MENU: Nav.MENU,
    pygame.K_TAB: Nav.MENU,
    pygame.K_q: Nav.TAB_PREV,
    pygame.K_e: Nav.TAB_NEXT,
    pygame.K_PAGEUP: Nav.TAB_PREV,
    pygame.K_PAGEDOWN: Nav.TAB_NEXT,
    pygame.K_o: Nav.OPTIONS,
    pygame.K_F2: Nav.OPTIONS,
    pygame.K_f: Nav.FAVORITE,
    pygame.K_F3: Nav.FAVORITE,
}

BUTTONS = {
    pygame.CONTROLLER_BUTTON_DPAD_UP: Nav.UP,
    pygame.CONTROLLER_BUTTON_DPAD_DOWN: Nav.DOWN,
    pygame.CONTROLLER_BUTTON_DPAD_LEFT: Nav.LEFT,
    pygame.CONTROLLER_BUTTON_DPAD_RIGHT: Nav.RIGHT,
    pygame.CONTROLLER_BUTTON_A: Nav.SELECT,
    pygame.CONTROLLER_BUTTON_B: Nav.BACK,
    pygame.CONTROLLER_BUTTON_START: Nav.MENU,
    pygame.CONTROLLER_BUTTON_GUIDE: Nav.MENU,
    pygame.CONTROLLER_BUTTON_LEFTSHOULDER: Nav.TAB_PREV,
    pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: Nav.TAB_NEXT,
    pygame.CONTROLLER_BUTTON_Y: Nav.OPTIONS,
    pygame.CONTROLLER_BUTTON_X: Nav.FAVORITE,
}

# Fallback for devices SDL has no GameController mapping for (Linux xpad layout).
JOY_BUTTONS = {0: Nav.SELECT, 1: Nav.BACK, 2: Nav.FAVORITE, 3: Nav.OPTIONS, 4: Nav.TAB_PREV, 5: Nav.TAB_NEXT,
               7: Nav.MENU}

AXIS_THRESHOLD = 0.6
# Settings → Controllers → Stick dead zone (a fraction of full tilt). Menus need
# a push well past it before a stick counts as a direction.
deadzone = 0.15


def set_deadzone(percent: int) -> None:
    global deadzone
    deadzone = max(0.0, min(0.5, percent / 100))


def axis_threshold() -> float:
    return max(AXIS_THRESHOLD, min(0.9, deadzone + 0.25))
AXIS_REPEAT_DELAY_MS = 400
AXIS_REPEAT_RATE_MS = 120
DIRECTIONS = {Nav.UP, Nav.DOWN, Nav.LEFT, Nav.RIGHT}


class InputMapper:
    """Stateful translator: analog sticks need edge detection, and held
    directions (stick, d-pad, arrow keys) auto-repeat."""

    def __init__(self) -> None:
        self._stick: Nav | None = None
        self._stick_next_ms = 0
        self._held: Nav | None = None
        self._held_next_ms = 0
        self._devices: dict[int, object] = {}
        self.swap_confirm = False  # Settings → Controllers → Confirm button: right (Nintendo)

    def open_devices(self) -> None:
        if not pygame.joystick.get_init():
            pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            self._open(i)

    def _open(self, index: int) -> None:
        try:
            from pygame._sdl2 import controller
        except ImportError:  # pragma: no cover - very old pygame
            controller = None
        if controller is not None and not controller.get_init():
            controller.init()
        if controller is not None and controller.is_controller(index):
            dev = controller.Controller(index)
            self._devices[dev.as_joystick().get_instance_id()] = dev
        else:
            dev = pygame.joystick.Joystick(index)
            self._devices[dev.get_instance_id()] = dev

    def _button(self, button: int) -> int:
        """Nintendo layout: confirm with the right-hand button, back with the bottom one."""
        if self.swap_confirm and button in (pygame.CONTROLLER_BUTTON_A, pygame.CONTROLLER_BUTTON_B):
            return pygame.CONTROLLER_BUTTON_B if button == pygame.CONTROLLER_BUTTON_A else pygame.CONTROLLER_BUTTON_A
        return button

    def _is_controller(self, instance_id: int) -> bool:
        dev = self._devices.get(instance_id)
        return dev is not None and not isinstance(dev, pygame.joystick.JoystickType)

    def family(self, instance_id: int | None) -> str:
        """Which kind of controller an event came from, for button hints."""
        dev = self._devices.get(instance_id) if instance_id is not None else None
        try:
            name = dev.name if hasattr(dev, "name") and isinstance(dev.name, str) else dev.get_name()
        except Exception:  # unknown or gone
            name = ""
        return style.controller_family(name)

    def note(self, event: pygame.event.Event) -> None:
        """Remember what was used last, so on-screen hints can match it."""
        t = event.type
        if t in (pygame.CONTROLLERBUTTONDOWN, pygame.JOYBUTTONDOWN):
            style.note_input(self.family(getattr(event, "instance_id", None)))
        elif t == pygame.KEYDOWN:
            # A Wii Remote reaches apps as key presses (wiiinput); the Quick
            # Menu process notes when it last sent some.
            style.note_input("wii" if wii_recently() else "keyboard")

    def translate(self, event: pygame.event.Event, now_ms: int = 0) -> Nav | None:
        self.note(event)
        t = event.type
        if t == pygame.KEYDOWN:
            return self._press(KEYS.get(event.key), now_ms)
        if t == pygame.KEYUP:
            self._release(KEYS.get(event.key))
            return None
        if t == pygame.CONTROLLERDEVICEADDED or t == pygame.JOYDEVICEADDED:
            if t == pygame.JOYDEVICEADDED:
                self._open(event.device_index)
            return None
        if t == pygame.CONTROLLERBUTTONDOWN:
            return self._press(BUTTONS.get(self._button(event.button)), now_ms)
        if t == pygame.CONTROLLERBUTTONUP:
            self._release(BUTTONS.get(self._button(event.button)))
            return None
        if t == pygame.CONTROLLERAXISMOTION:
            if event.axis == pygame.CONTROLLER_AXIS_LEFTX:
                return self._stick_axis(event.value / 32767, Nav.LEFT, Nav.RIGHT, now_ms)
            if event.axis == pygame.CONTROLLER_AXIS_LEFTY:
                return self._stick_axis(event.value / 32767, Nav.UP, Nav.DOWN, now_ms)
            return None
        # Raw joystick events are also emitted for GameController devices;
        # only honour them for devices without a mapping to avoid double input.
        instance = getattr(event, "instance_id", None)
        if instance is not None and self._is_controller(instance):
            return None
        if t == pygame.JOYBUTTONDOWN:
            return JOY_BUTTONS.get(event.button)
        if t == pygame.JOYHATMOTION:
            x, y = event.value
            if x:
                return Nav.RIGHT if x > 0 else Nav.LEFT
            if y:
                return Nav.UP if y > 0 else Nav.DOWN
            return None
        if t == pygame.JOYAXISMOTION and event.axis in (0, 1):
            neg, pos = (Nav.LEFT, Nav.RIGHT) if event.axis == 0 else (Nav.UP, Nav.DOWN)
            return self._stick_axis(event.value, neg, pos, now_ms)
        return None

    def _press(self, nav: Nav | None, now_ms: int) -> Nav | None:
        if nav in DIRECTIONS:
            self._held, self._held_next_ms = nav, now_ms + AXIS_REPEAT_DELAY_MS
        return nav

    def _release(self, nav: Nav | None) -> None:
        if nav is not None and nav == self._held:
            self._held = None

    def _stick_axis(self, value: float, neg: Nav, pos: Nav, now_ms: int) -> Nav | None:
        if abs(value) < axis_threshold():
            if self._stick in (neg, pos):
                self._stick = None
            return None
        direction = pos if value > 0 else neg
        if direction != self._stick:
            self._stick = direction
            self._stick_next_ms = now_ms + AXIS_REPEAT_DELAY_MS
            return direction
        return None

    def repeat(self, now_ms: int) -> Nav | None:
        """Called every frame: emits a repeat while a direction stays held."""
        if self._stick is not None and now_ms >= self._stick_next_ms:
            self._stick_next_ms = now_ms + AXIS_REPEAT_RATE_MS
            return self._stick
        if self._held is not None and now_ms >= self._held_next_ms:
            self._held_next_ms = now_ms + AXIS_REPEAT_RATE_MS
            return self._held
        return None

    def reset(self) -> None:
        """Forget held directions (e.g. when input focus moves elsewhere)."""
        self._stick = self._held = None
