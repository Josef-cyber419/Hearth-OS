"""Optional UI sounds."""

import struct

import pygame

from hearth import sounds, ui
from hearth.config import Config, Row, App
from hearth.model import Home, Nav


def test_tones_are_short_quiet_and_fade_out():
    pcm = sounds.tone([(1000, 0.02)])
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    assert len(samples) == int(sounds.RATE * 0.02)
    assert max(abs(s) for s in samples) <= 32767 * sounds.VOLUME
    assert abs(samples[-1]) < 200  # ends silent: no click


def test_what_plays_when(monkeypatch):
    played = []
    monkeypatch.setattr(sounds, "play", played.append)
    pygame.display.init()
    pygame.font.init()
    try:
        surface = pygame.display.set_mode((1280, 720))
        apps = tuple(App(id=i, name=i.title(), command=("true",)) for i in ("kodi", "plex"))
        screen = ui.HomeScreen(surface, Home(Config(rows=(Row("Watch", apps),))), "Hearth")

        def press(nav):
            before = screen.sound_state()
            opened = screen.handle(nav)
            screen.play_sound(nav, before, opened)

        press(Nav.RIGHT)
        press(Nav.RIGHT)  # at the end already: nothing moved, nothing plays
        press(Nav.SEARCH)
        press(Nav.BACK)
        press(Nav.SELECT)
        assert played == ["move", "select", "back", "select"]
    finally:
        pygame.quit()


def test_off_by_default_and_quiet_without_audio(monkeypatch):
    sounds.enable(False)
    sounds.play("move")  # nothing happens
    sounds.enable(True)
    monkeypatch.setattr(sounds, "_failed", False)
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)

    def broken(*a, **k):
        raise pygame.error("no audio device")

    monkeypatch.setattr(pygame.mixer, "init", broken)
    sounds.play("move")  # doesn't raise
    assert sounds._failed
    sounds.enable(False)
