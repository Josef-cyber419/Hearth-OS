"""Watch Next: in-progress shows from Jellyfin, Plex and Kodi, and playing
them from where you stopped (against a fake server)."""

import json
import sqlite3
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from hearth import config as cfg
from hearth import library, watchnext, watchplay


class FakeServer(BaseHTTPRequestHandler):
    """Just enough Jellyfin and Plex."""

    seen: list = []
    approved = False

    def log_message(self, *a):
        pass

    def reply(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        FakeServer.seen.append(("GET", url.path, q, dict(self.headers)))
        if url.path == "/QuickConnect/Connect":
            return self.reply({"Authenticated": FakeServer.approved})
        if url.path == "/System/Info/Public":
            return self.reply({"ServerName": "Den"})
        if url.path == "/UserItems/Resume":
            return self.reply({}, 404)  # an older Jellyfin: falls back
        if url.path == "/Users/u1/Items/Resume":
            return self.reply({"Items": [
                {"Id": "ep1", "Type": "Episode", "Name": "Fishes", "SeriesName": "The Bear", "SeriesId": "s1",
                 "ParentIndexNumber": 2, "IndexNumber": 6, "RunTimeTicks": 66 * 60 * 10**7,
                 "UserData": {"PlaybackPositionTicks": 20 * 60 * 10**7, "LastPlayedDate": "2026-09-28T20:00:00Z"},
                 "ParentBackdropItemId": "s1", "ParentBackdropImageTags": ["x"]}]})
        if url.path == "/Shows/NextUp":
            return self.reply({"Items": [
                {"Id": "ep9", "Type": "Episode", "Name": "Other", "SeriesName": "The Bear", "SeriesId": "s1"},
                {"Id": "ep20", "Type": "Episode", "Name": "Pilot", "SeriesName": "Severance", "SeriesId": "s2",
                 "ParentIndexNumber": 1, "IndexNumber": 1, "RunTimeTicks": 57 * 60 * 10**7, "UserData": {}}]})
        if url.path == "/api/v2/pins/7":
            return self.reply({"id": 7, "code": "ABCD", "authToken": "plex-token" if FakeServer.approved else None})
        if url.path == "/api/v2/resources":
            port = self.server.server_address[1]
            return self.reply([{"name": "Attic", "provides": "server", "accessToken": "server-token",
                                "connections": [{"uri": "http://10.255.255.1:1", "local": False},
                                                {"uri": f"http://127.0.0.1:{port}", "local": True}]},
                               {"name": "Phone", "provides": "client"}])
        if url.path == "/library/onDeck":
            return self.reply({"MediaContainer": {"Metadata": [
                {"ratingKey": "42", "type": "movie", "title": "Dune", "year": 2021, "viewOffset": 3_600_000,
                 "duration": 9_300_000, "lastViewedAt": 1790000000, "art": "/library/metadata/42/art/1",
                 "Media": [{"Part": [{"key": "/library/parts/9/file.mkv"}]}]}]}})
        if url.path == "/library/metadata/42":
            return self.reply({"MediaContainer": {"Metadata": [
                {"Media": [{"Part": [{"key": "/library/parts/9/file.mkv"}]}]}]}})
        if url.path.startswith(("/:/timeline", "/:/scrobble")):
            return self.reply({})
        if "/Images/" in url.path or "/art/" in url.path:
            self.send_response(200)
            self.end_headers()
            return self.wfile.write(b"jpeg")
        self.reply({}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"null")
        FakeServer.seen.append(("POST", url.path, body, dict(self.headers)))
        if url.path == "/QuickConnect/Initiate":
            return self.reply({"Code": "123456", "Secret": "sec"})
        if url.path == "/Users/AuthenticateWithQuickConnect":
            return self.reply({"AccessToken": "jf-token", "User": {"Id": "u1", "Name": "Sam"}})
        if url.path == "/api/v2/pins":
            return self.reply({"id": 7, "code": "ABCD"})
        if url.path.startswith("/Sessions/Playing"):
            return self.reply({})
        self.reply({}, 404)


@pytest.fixture
def server():
    FakeServer.seen, FakeServer.approved = [], False
    httpd = HTTPServer(("127.0.0.1", 0), FakeServer)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_jellyfin_quick_connect(server):
    qc = watchnext.quick_connect_start(server)
    assert qc["Code"] == "123456"
    assert watchnext.quick_connect_finish(server, "sec") is None  # not approved yet
    FakeServer.approved = True
    account = watchnext.quick_connect_finish(server, "sec")
    assert account == {"server": server, "token": "jf-token", "user_id": "u1", "user": "Sam", "name": "Den"}
    auth = [h for m, p, _, h in FakeServer.seen if p == "/QuickConnect/Initiate"][0]["Authorization"]
    assert auth.startswith("MediaBrowser Client=\"Hearth\"") and "DeviceId=" in auth


def test_jellyfin_items_in_progress_then_next_up(server):
    account = {"server": server, "token": "jf-token", "user_id": "u1"}
    items = watchnext.jellyfin_items(account)
    assert [i.id for i in items] == ["ep1", "ep20"]  # The Bear's next-up is left out: it's already there
    bear = items[0]
    assert (bear.title, bear.subtitle) == ("The Bear", "S2 · E6 · Fishes")
    assert bear.position == 1200 and bear.runtime == 3960 and bear.left == "46 min left"
    assert bear.art_url == f"{server}/Items/s1/Images/Backdrop?maxWidth=640&quality=85"
    assert bear.played_at > 0


def test_plex_link_and_on_deck(server, monkeypatch):
    assert watchnext.plex_pin_start(server) == {"id": 7, "code": "ABCD"}
    assert watchnext.plex_pin_finish(7, server) is None
    FakeServer.approved = True
    account = watchnext.plex_pin_finish(7, server)
    assert account["token"] == "plex-token" and [s["name"] for s in account["servers"]] == ["Attic"]
    local = account["servers"][0]["uris"][0]
    assert local.startswith("http://127.0.0.1")  # on this network first
    items = watchnext.plex_items(account)
    assert [(i.title, i.position, i.runtime) for i in items] == [("Dune", 3600.0, 9300.0)]
    assert items[0].id == "Attic/42"
    assert watchnext.plex_stream(account, "Attic/42") == f"{local}/library/parts/9/file.mkv?X-Plex-Token=server-token"


def kodi(home: Path) -> None:
    db = home / ".var/app/tv.kodi.Kodi/data/userdata/Database/MyVideos131.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE path (idPath INTEGER PRIMARY KEY, strPath TEXT);
        CREATE TABLE files (idFile INTEGER PRIMARY KEY, idPath INTEGER, strFilename TEXT, lastPlayed TEXT);
        CREATE TABLE bookmark (idBookmark INTEGER PRIMARY KEY, idFile INTEGER, timeInSeconds REAL,
                               totalTimeInSeconds REAL, type INTEGER);
        CREATE TABLE movie (idMovie INTEGER PRIMARY KEY, idFile INTEGER, c00 TEXT);
        CREATE TABLE tvshow (idShow INTEGER PRIMARY KEY, c00 TEXT);
        CREATE TABLE episode (idEpisode INTEGER PRIMARY KEY, idFile INTEGER, idShow INTEGER, c00 TEXT,
                              c12 TEXT, c13 TEXT);
        INSERT INTO path VALUES (1, '/media/films/'), (2, '/media/tv/');
        INSERT INTO files VALUES (1, 1, 'Heat.mkv', '2026-09-27 21:00:00'), (2, 2, 'bb.s01e03.mkv', '2026-09-28 19:00:00'),
                                 (3, 1, 'Done.mkv', '2026-09-20 19:00:00');
        INSERT INTO bookmark VALUES (1, 1, 3000, 10200, 1), (2, 2, 600, 2800, 1), (3, 3, 50, 100, 0);
        INSERT INTO movie VALUES (1, 1, 'Heat'), (2, 3, 'Done');
        INSERT INTO tvshow VALUES (1, 'Bluey');
        INSERT INTO episode VALUES (1, 2, 1, 'Hotel', '1', '3');
    """)
    con.commit()
    con.close()


def test_kodi_in_progress_from_its_library(tmp_path):
    kodi(tmp_path)
    items = watchnext.kodi_items(tmp_path)
    assert [(i.title, i.subtitle, i.id) for i in items] == [
        ("Bluey", "S1 · E3 · Hotel", "/media/tv/bb.s01e03.mkv"), ("Heat", "", "/media/films/Heat.mkv")]
    assert watchnext.kodi_items(tmp_path / "nobody") == []


def test_row_on_the_home_screen_from_the_cache(tmp_path, monkeypatch, shipped_config):
    monkeypatch.setenv("HOME", str(tmp_path))
    kodi(tmp_path)
    monkeypatch.setattr(watchnext, "refresh_soon", lambda: None)
    assert watchnext.row() is None  # nothing fetched yet: no row, and the home screen didn't wait
    watchnext.refresh()
    config = library.with_game_rows(cfg.load(shipped_config), games=[])
    row = next(r for r in config.rows if r.title == "Watch next")
    bluey = row.apps[0]
    assert bluey.name == "Bluey" and bluey.platform == "S1 E3 · 37 min left" and bluey.progress == 600 / 2800
    assert bluey.command[-5:] == ("kodi", "/media/tv/bb.s01e03.mkv", "600.0", "2800.0", "Bluey")
    off = library.with_game_rows(replace(cfg.load(shipped_config), home_watch=False), games=[])
    assert all(r.title != "Watch next" for r in off.rows)


def test_accounts_are_private(tmp_path):
    watchnext.set_account("plex", {"token": "t"})
    assert watchnext.accounts()["plex"] == {"token": "t"}
    assert watchnext.accounts_path().stat().st_mode & 0o077 == 0
    watchnext.set_account("plex", None)
    assert "plex" not in watchnext.accounts()


def test_playing_reports_progress_and_the_stop(monkeypatch):
    positions = iter([600.0, 610.0, 620.0])
    reports = []

    class Mpv:
        polls = 0

        def poll(self):
            Mpv.polls += 1
            return None if Mpv.polls <= 3 else 0

    clock = iter(range(0, 1000, 11))
    monkeypatch.setattr(watchplay.time, "monotonic", lambda: next(clock))
    launched = []
    last = watchplay.play_stream("http://x/stream", 600, "The Bear", lambda *a: reports.append(a),
                                 popen=lambda cmd: (launched.append(cmd), Mpv())[1],
                                 ask=lambda ipc, prop: next(positions) if prop == "time-pos" else False,
                                 sleep=lambda s: None)
    assert "--start=600" in launched[0] and "--force-media-title=The Bear" in launched[0]
    assert reports[0] == ("start", 600, False) and reports[-1] == ("stopped", 620.0, False)
    assert any(r[0] == "progress" for r in reports) and last == 620.0


def test_jellyfin_reports_reach_the_server(server):
    account = {"server": server, "token": "jf-token", "user_id": "u1"}
    watchnext.jellyfin_report(account, "ep1", "stopped", 1500.5)
    method, path, body, headers = FakeServer.seen[-1]
    assert (method, path) == ("POST", "/Sessions/Playing/Stopped")
    assert body["ItemId"] == "ep1" and body["PositionTicks"] == 15_005_000_000
    assert 'Token="jf-token"' in headers["Authorization"]
    assert watchnext.jellyfin_stream(account, "ep1") == f"{server}/Videos/ep1/stream?static=true&api_key=jf-token"


def test_kodi_items_open_in_kodi_and_resume(monkeypatch):
    sent, attempts = [], []

    class Kodi:
        def poll(self):
            return None

        def wait(self):
            return 0

    class Sock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def sendall(self, data):
            sent.append(json.loads(data))

    def connect(addr, timeout):
        attempts.append(addr)
        if len(attempts) < 3:
            raise ConnectionRefusedError  # Kodi is still starting
        return Sock()

    ran = []
    assert watchplay.play_kodi("/media/tv/bb.s01e03.mkv", run=lambda cmd: (ran.append(cmd), Kodi())[1],
                               connect=connect, sleep=lambda s: None) == 0
    assert ran == [["flatpak", "run", "tv.kodi.Kodi"]] and len(attempts) == 3
    assert sent[0]["method"] == "Player.Open"
    assert sent[0]["params"] == {"item": {"file": "/media/tv/bb.s01e03.mkv"}, "options": {"resume": True}}
