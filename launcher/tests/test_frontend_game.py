"""Quit the game inside ES-DE, keep ES-DE on its list."""

import signal
from pathlib import Path

from hearth import quickmenu, session


def fake_proc(tmp_path: Path, tree: dict[int, tuple[int, str]]) -> Path:
    for pid, (ppid, name) in tree.items():
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "stat").write_text(f"{pid} ({name}) S {ppid} {pid} {pid} 0 -1\n")
    return tmp_path


# hearth-emulation -> AppImage runtime -> es-de -> sh -> flatpak -> bwrap -> dolphin-emu
TREE = {
    100: (1, "hearth-emulati"), 101: (100, "ES-DE.AppImage"), 102: (101, "es-de"),
    200: (102, "sh"), 201: (200, "flatpak"), 202: (201, "bwrap"), 203: (202, "dolphin-emu"),
    999: (1, "unrelated"),
}


def test_finds_the_game_under_es_de(tmp_path):
    proc = fake_proc(tmp_path, TREE)
    name, pids = session.frontend_game({"pid": 100}, proc)
    assert name == "ES-DE" and sorted(pids) == [200, 201, 202, 203]


def test_no_game_while_browsing_the_list(tmp_path):
    proc = fake_proc(tmp_path, {k: v for k, v in TREE.items() if k < 200})
    assert session.frontend_game({"pid": 100}, proc) is None


def test_not_a_frontend(tmp_path):
    proc = fake_proc(tmp_path, {300: (1, "kodi.bin"), 301: (300, "python3")})
    assert session.frontend_game({"pid": 300}, proc) is None
    assert session.frontend_game(None, proc) is None


def test_names_with_spaces_and_brackets(tmp_path):
    (tmp_path / "5").mkdir()
    (tmp_path / "5" / "stat").write_text("5 (Web Content (x)) S 1 5 5\n")
    assert session._processes(tmp_path)[5] == (1, "Web Content (x)")


def test_quit_game_asks_then_forces():
    sent, alive = [], {200, 203}
    session.quit_game([200, 203], wait=0.2, kill=lambda p, s: sent.append((p, s)),
                      alive=lambda p: p in alive, sleep=lambda s: alive.discard(200))
    assert (200, signal.SIGTERM) in sent and (203, signal.SIGTERM) in sent
    assert (203, signal.SIGKILL) in sent and (200, signal.SIGKILL) not in sent


def test_quick_menu_offers_quit_game():
    class Acts:
        def __getattr__(self, name):
            return lambda *a: None

    fg = {"id": "emulation", "name": "Emulation", "resumable": True}
    ids = lambda **kw: [i.key for i in quickmenu._system_tab(quickmenu.Context(None, None, {"foreground": fg}, Acts(), **kw)).items]  # noqa: E731
    assert "quit-game" in ids(frontend="ES-DE")
    assert "quit-game" not in ids()
