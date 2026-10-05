"""The Quick Menu's actions on the hub (hearth.overlay.Actions)."""

import threading
import time

from hearth import overlay, session


def test_home_from_an_app_does_not_wait_for_the_app_to_close(monkeypatch):
    """Kodi or Heroic take seconds to quit: the menu used to sit frozen
    meanwhile (field report #65)."""
    session.update(lambda s: s.update(foreground={"id": "kodi", "name": "Kodi", "unit": "hearth-kodi.scope"},
                                      focus="foreground"))
    gate, stopped = threading.Event(), []

    def stop_entry(info):
        gate.wait(5)
        stopped.append(info["id"])

    monkeypatch.setattr(session, "stop_entry", stop_entry)
    thawed = []
    actions = overlay.Actions.__new__(overlay.Actions)
    actions.o = type("O", (), {"thaw": lambda self: thawed.append(True)})()
    t0 = time.monotonic()
    actions.go_home()
    assert time.monotonic() - t0 < 1 and thawed and stopped == []
    gate.set()
    for _ in range(100):
        if stopped:
            break
        time.sleep(0.02)
    assert stopped == ["kodi"]
