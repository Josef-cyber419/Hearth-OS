import pygame
import pytest

from hearth.input import AXIS_REPEAT_DELAY_MS, AXIS_REPEAT_RATE_MS, InputMapper
from hearth.model import Nav


def ev(type_, **kw):
    return pygame.event.Event(type_, **kw)


def test_keyboard_and_remote_keys():
    m = InputMapper()
    assert m.translate(ev(pygame.KEYDOWN, key=pygame.K_RIGHT)) is Nav.RIGHT
    assert m.translate(ev(pygame.KEYDOWN, key=pygame.K_RETURN)) is Nav.SELECT
    assert m.translate(ev(pygame.KEYDOWN, key=pygame.K_AC_BACK)) is Nav.BACK
    assert m.translate(ev(pygame.KEYDOWN, key=pygame.K_F12)) is None


def test_controller_buttons():
    m = InputMapper()
    assert m.translate(ev(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_A)) is Nav.SELECT
    assert m.translate(ev(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_START)) is Nav.MENU


def test_stick_edge_and_repeat():
    m = InputMapper()
    axis = pygame.CONTROLLER_AXIS_LEFTX
    assert m.translate(ev(pygame.CONTROLLERAXISMOTION, axis=axis, value=30000), now_ms=0) is Nav.RIGHT
    # Still held: no new event, but repeats kick in after the delay.
    assert m.translate(ev(pygame.CONTROLLERAXISMOTION, axis=axis, value=31000), now_ms=10) is None
    assert m.repeat(AXIS_REPEAT_DELAY_MS - 1) is None
    assert m.repeat(AXIS_REPEAT_DELAY_MS) is Nav.RIGHT
    assert m.repeat(AXIS_REPEAT_DELAY_MS + AXIS_REPEAT_RATE_MS) is Nav.RIGHT
    # Released: repeats stop.
    assert m.translate(ev(pygame.CONTROLLERAXISMOTION, axis=axis, value=0), now_ms=2000) is None
    assert m.repeat(5000) is None


def test_joystick_fallback_hat():
    m = InputMapper()
    assert m.translate(ev(pygame.JOYHATMOTION, instance_id=9, hat=0, value=(0, 1))) is Nav.UP
    assert m.translate(ev(pygame.JOYBUTTONDOWN, instance_id=9, button=0)) is Nav.SELECT


def test_held_dpad_repeats_until_released():
    m = InputMapper()
    down = ev(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_DPAD_RIGHT)
    assert m.translate(down, now_ms=0) is Nav.RIGHT
    assert m.repeat(AXIS_REPEAT_DELAY_MS - 1) is None
    assert m.repeat(AXIS_REPEAT_DELAY_MS) is Nav.RIGHT
    m.translate(ev(pygame.CONTROLLERBUTTONUP, button=pygame.CONTROLLER_BUTTON_DPAD_RIGHT), now_ms=900)
    assert m.repeat(5000) is None


def test_held_key_repeats_but_select_does_not():
    m = InputMapper()
    m.translate(ev(pygame.KEYDOWN, key=pygame.K_RETURN), now_ms=0)
    assert m.repeat(5000) is None
    m.translate(ev(pygame.KEYDOWN, key=pygame.K_DOWN), now_ms=0)
    assert m.repeat(AXIS_REPEAT_DELAY_MS) is Nav.DOWN
    m.reset()
    assert m.repeat(9000) is None


def test_stick_dead_zone_setting():
    from hearth import input as input_, pointer

    try:
        input_.set_deadzone(15)
        assert input_.axis_threshold() == input_.AXIS_THRESHOLD  # menus: unchanged by default
        input_.set_deadzone(40)
        assert input_.axis_threshold() == pytest.approx(0.65)  # a drifting stick needs a bigger push
        assert pointer.curve(0.3, 0.4) == 0.0 and pointer.curve(0.3, 0.15) > 0
        assert pointer.curve(1.0, 0.4) == 1.0
    finally:
        input_.set_deadzone(15)


def test_stick_dead_zone_is_a_setting():
    from hearth import config as cfg

    assert cfg.parse({"rows": []}).stick_deadzone == 15
    assert cfg.parse({"rows": [], "controllers": {"stick_deadzone": 30}}).stick_deadzone == 30
