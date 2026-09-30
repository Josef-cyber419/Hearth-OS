import os
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO = Path(__file__).resolve().parents[2]
SHIPPED_CONFIG = REPO / "image/system_files/usr/share/hearth/apps.toml"


@pytest.fixture
def shipped_config():
    return SHIPPED_CONFIG


@pytest.fixture(autouse=True)
def runtime_dir(tmp_path, monkeypatch):
    """Keep session state (hearth/state.json), logs and the event timeline
    inside each test's temp dir."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / "run").mkdir()
    return tmp_path / "run"


@pytest.fixture(autouse=True)
def no_art_downloads(monkeypatch):
    """Tests never go online for game art (test_artfind.py tests it offline)."""
    from hearth import artfind

    monkeypatch.setattr(artfind, "find_soon", lambda games: None)
