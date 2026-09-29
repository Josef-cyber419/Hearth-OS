"""Watch Next: films and episodes you're partway through, from your own media
servers and Kodi, in one row on the home screen.

- Jellyfin: connected with Quick Connect (a code on the TV, approved from the
  Jellyfin app on your phone), found on the network by itself.
- Plex: connected with a code at plex.tv/link.
- Kodi: read from Kodi's own library database, nothing to set up.

Everything is fetched in the background into a small cache, so the home
screen never waits on the network. Picking one plays it from where you left
off (see watchplay.py) and tells the server how far you got.
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger("hearth.watchnext")

LIMIT = 12  # items in the row
REFRESH_SECONDS = 5 * 60
TIMEOUT = 6.0
PLEX_TV = "https://plex.tv"
KODI = "tv.kodi.Kodi"
DISCOVERY_PORT = 7359  # Jellyfin answers "who is JellyfinServer?" here


@dataclass
class Item:
    source: str  # "jellyfin" | "plex" | "kodi"
    id: str  # the source's id for it (Kodi: the file's path)
    title: str  # "The Bear" / "Dune"
    subtitle: str = ""  # "S2 · E4 · Fishes"
    position: float = 0.0  # seconds in
    runtime: float = 0.0  # seconds long (0: unknown)
    art: str | None = None  # a cached picture
    art_url: str | None = None  # where the picture comes from
    played_at: float = 0.0  # when it was last watched (for mixing sources)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def progress(self) -> float:
        return min(1.0, self.position / self.runtime) if self.runtime else 0.0

    @property
    def left(self) -> str:
        """ "38 min left" """
        if not self.runtime:
            return ""
        minutes = max(1, round((self.runtime - self.position) / 60))
        return f"{minutes // 60} h {minutes % 60} min left" if minutes >= 60 else f"{minutes} min left"


# -- where things are kept ------------------------------------------------------


def _config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "hearth"


def _cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "hearth"


def accounts_path() -> Path:
    return _config_dir() / "media-accounts.json"


def cache_path() -> Path:
    return _cache_dir() / "watchnext.json"


def accounts() -> dict:
    try:
        data = json.loads(accounts_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_accounts(data: dict) -> None:
    """Sign-in tokens: readable by you only."""
    path = accounts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def set_account(name: str, account: dict | None) -> None:
    data = accounts()
    if account is None:
        data.pop(name, None)
    else:
        data[name] = account
    save_accounts(data)
    try:
        cache_path().unlink()  # the row changes: fetch it again
    except OSError:
        pass


def device_id() -> str:
    """This PC's id towards media servers (kept, so they see one device)."""
    data = accounts()
    if not data.get("device_id"):
        data["device_id"] = str(uuid.uuid4())
        save_accounts(data)
    return data["device_id"]


# -- HTTP ------------------------------------------------------------------------


def _request(url: str, method: str = "GET", headers: dict | None = None, body: dict | None = None,
             timeout: float = TIMEOUT):
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Accept": "application/json", "Content-Type": "application/json",
                                          **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (the user's own servers)
        raw = r.read()
    return json.loads(raw) if raw.strip() else None


def _version() -> str:
    try:
        from . import updates

        return updates.hearth_version()
    except Exception:
        return "dev"


# -- Jellyfin --------------------------------------------------------------------


def jellyfin_auth(token: str | None = None) -> dict:
    fields = f'Client="Hearth", Device="{socket.gethostname() or "Hearth"}", DeviceId="{device_id()}", ' \
             f'Version="{_version()}"'
    if token:
        fields += f', Token="{token}"'
    return {"Authorization": f"MediaBrowser {fields}", "X-Emby-Authorization": f"MediaBrowser {fields}"}


def discover_jellyfin(timeout: float = 2.0, port: int = DISCOVERY_PORT) -> list[dict]:
    """Jellyfin servers on this network: [{"Address": "http://…:8096", "Name": …}]."""
    found: dict[str, dict] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.3)
        try:
            s.sendto(b"who is JellyfinServer?", ("255.255.255.255", port))
        except OSError as e:
            log.info("jellyfin discovery: %s", e)
            return []
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                info = json.loads(data)
            except ValueError:
                continue
            if isinstance(info, dict) and info.get("Address"):
                found[info["Address"]] = info
    return list(found.values())


def normalize_server(address: str) -> str:
    address = address.strip().rstrip("/")
    if not address.startswith(("http://", "https://")):
        address = "http://" + address
    parsed = urllib.parse.urlparse(address)
    if not parsed.port and parsed.scheme == "http":
        address = f"{address}:8096"
    return address


def quick_connect_start(server: str) -> dict:
    """Ask the server for a Quick Connect code: {"Code": "123456", "Secret": …}."""
    try:
        return _request(f"{server}/QuickConnect/Initiate", "POST", jellyfin_auth())
    except urllib.error.HTTPError as e:
        if e.code not in (404, 405):
            raise
        return _request(f"{server}/QuickConnect/Initiate", "GET", jellyfin_auth())  # Jellyfin 10.8


def quick_connect_finish(server: str, secret: str) -> dict | None:
    """Once the code is approved on another device: the account to keep."""
    state = _request(f"{server}/QuickConnect/Connect?" + urllib.parse.urlencode({"Secret": secret}),
                     headers=jellyfin_auth())
    if not (state or {}).get("Authenticated"):
        return None
    auth = _request(f"{server}/Users/AuthenticateWithQuickConnect", "POST", jellyfin_auth(), {"Secret": secret})
    user = auth.get("User") or {}
    try:
        name = (_request(f"{server}/System/Info/Public") or {}).get("ServerName") or server
    except (OSError, ValueError):
        name = server
    return {"server": server, "token": auth["AccessToken"], "user_id": user.get("Id"), "user": user.get("Name"),
            "name": name}


def _ticks(v) -> float:
    return (v or 0) / 10_000_000


def jellyfin_items(account: dict) -> list[Item]:
    server, token, uid = account["server"], account["token"], account["user_id"]
    h = jellyfin_auth(token)
    fields = "Fields=RunTimeTicks,UserData&EnableImageTypes=Backdrop,Primary,Thumb"
    try:
        resume = _request(f"{server}/UserItems/Resume?userId={uid}&Limit={LIMIT}&MediaTypes=Video&{fields}",
                          headers=h)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        resume = _request(f"{server}/Users/{uid}/Items/Resume?Limit={LIMIT}&MediaTypes=Video&{fields}", headers=h)
    items = list((resume or {}).get("Items") or [])
    try:
        nextup = _request(f"{server}/Shows/NextUp?userId={uid}&Limit={LIMIT}&{fields}", headers=h)
        series = {i.get("SeriesId") for i in items if i.get("SeriesId")}
        items += [i for i in (nextup or {}).get("Items") or [] if i.get("SeriesId") not in series]
    except (OSError, ValueError) as e:
        log.info("jellyfin next up: %s", e)
    out = []
    for i in items[:LIMIT]:
        data = i.get("UserData") or {}
        if i.get("Type") == "Episode":
            title = i.get("SeriesName") or i.get("Name") or "?"
            subtitle = f"S{i.get('ParentIndexNumber', '?')} · E{i.get('IndexNumber', '?')} · {i.get('Name', '')}"
        else:
            title, subtitle = i.get("Name") or "?", str(i.get("ProductionYear") or "")
        art_id = i.get("ParentBackdropItemId") if i.get("ParentBackdropImageTags") else i.get("Id")
        kind = "Backdrop" if (i.get("BackdropImageTags") or i.get("ParentBackdropImageTags")) else "Primary"
        played = data.get("LastPlayedDate") or ""
        out.append(Item("jellyfin", i["Id"], title, subtitle.strip(" ·"), _ticks(data.get("PlaybackPositionTicks")),
                        _ticks(i.get("RunTimeTicks")),
                        art_url=f"{server}/Items/{art_id}/Images/{kind}?maxWidth=640&quality=85",
                        played_at=_iso_time(played)))
    return out


def _iso_time(text: str) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(text).timestamp()  # "2026-09-28T20:14:03.1234567Z"
    except ValueError:
        return 0.0


def jellyfin_report(account: dict, item_id: str, event: str, position: float, paused: bool = False) -> None:
    """event: "start", "progress" or "stopped"."""
    path = {"start": "/Sessions/Playing", "progress": "/Sessions/Playing/Progress",
            "stopped": "/Sessions/Playing/Stopped"}[event]
    _request(account["server"] + path, "POST", jellyfin_auth(account["token"]),
             {"ItemId": item_id, "PositionTicks": int(position * 10_000_000), "IsPaused": paused,
              "PlayMethod": "DirectStream", "CanSeek": True})


def jellyfin_stream(account: dict, item_id: str) -> str:
    return f"{account['server']}/Videos/{item_id}/stream?" + urllib.parse.urlencode(
        {"static": "true", "api_key": account["token"]})


# -- Plex ------------------------------------------------------------------------


def plex_headers(token: str | None = None) -> dict:
    h = {"X-Plex-Product": "Hearth", "X-Plex-Version": _version(), "X-Plex-Client-Identifier": device_id(),
         "X-Plex-Device-Name": socket.gethostname() or "Hearth", "X-Plex-Platform": "Linux"}
    if token:
        h["X-Plex-Token"] = token
    return h


def plex_pin_start(base: str = PLEX_TV) -> dict:
    """A code to enter at plex.tv/link: {"id": …, "code": "ABCD"}."""
    return _request(f"{base}/api/v2/pins?strong=false", "POST", plex_headers())


def plex_pin_finish(pin_id, base: str = PLEX_TV) -> dict | None:
    pin = _request(f"{base}/api/v2/pins/{pin_id}", headers=plex_headers())
    token = (pin or {}).get("authToken")
    if not token:
        return None
    servers = plex_servers(token, base)
    return {"token": token, "servers": servers, "name": servers[0]["name"] if servers else "Plex"}


def plex_servers(token: str, base: str = PLEX_TV) -> list[dict]:
    """Your Plex servers, with the addresses to try (on this network first)."""
    resources = _request(f"{base}/api/v2/resources?includeHttps=1&includeRelay=0", headers=plex_headers(token))
    out = []
    for r in resources or []:
        if "server" not in (r.get("provides") or ""):
            continue
        conns = sorted(r.get("connections") or [], key=lambda c: (not c.get("local"), c.get("relay", False)))
        out.append({"name": r.get("name") or "Plex", "token": r.get("accessToken") or token,
                    "uris": [c["uri"] for c in conns if c.get("uri")]})
    return out


def _plex_get(server: dict, path: str):
    """GET from the first of a server's addresses that answers (remembering it)."""
    last: Exception | None = None
    for uri in list(server["uris"]):
        sep = "&" if "?" in path else "?"
        try:
            data = _request(f"{uri}{path}{sep}X-Plex-Token={server['token']}", headers=plex_headers(server["token"]),
                            timeout=4)
        except (OSError, ValueError) as e:
            last = e
            continue
        server["uris"].remove(uri)
        server["uris"].insert(0, uri)
        return uri, data
    raise OSError(f"no answer from {server['name']}: {last}")


def plex_items(account: dict) -> list[Item]:
    out = []
    for server in account.get("servers") or []:
        try:
            uri, data = _plex_get(server, "/library/onDeck")
        except OSError as e:
            log.info("plex: %s", e)
            continue
        for m in ((data or {}).get("MediaContainer") or {}).get("Metadata") or []:
            parts = [p for media in m.get("Media") or [] for p in media.get("Part") or []]
            if not parts:
                continue
            if m.get("type") == "episode":
                title = m.get("grandparentTitle") or m.get("title") or "?"
                subtitle = f"S{m.get('parentIndex', '?')} · E{m.get('index', '?')} · {m.get('title', '')}"
            else:
                title, subtitle = m.get("title") or "?", str(m.get("year") or "")
            art = m.get("grandparentArt") or m.get("art") or m.get("thumb")
            out.append(Item("plex", f"{server['name']}/{m['ratingKey']}", title, subtitle.strip(" ·"),
                            (m.get("viewOffset") or 0) / 1000, (m.get("duration") or 0) / 1000,
                            art_url=f"{uri}{art}?X-Plex-Token={server['token']}" if art else None,
                            played_at=float(m.get("lastViewedAt") or 0)))
    return out


def plex_find(account: dict, item_id: str) -> tuple[dict, str]:
    name, _, rating_key = item_id.rpartition("/")
    for server in account.get("servers") or []:
        if server["name"] == name:
            return server, rating_key
    raise LookupError(item_id)


def plex_stream(account: dict, item_id: str) -> str:
    server, rating_key = plex_find(account, item_id)
    uri, data = _plex_get(server, f"/library/metadata/{rating_key}")
    meta = ((data or {}).get("MediaContainer") or {}).get("Metadata") or [{}]
    part = meta[0]["Media"][0]["Part"][0]["key"]
    return f"{uri}{part}?X-Plex-Token={server['token']}"


def plex_report(account: dict, item_id: str, state: str, position: float, runtime: float) -> None:
    """state: "playing", "paused" or "stopped"."""
    server, rating_key = plex_find(account, item_id)
    q = urllib.parse.urlencode({"ratingKey": rating_key, "key": f"/library/metadata/{rating_key}", "state": state,
                                "time": int(position * 1000), "duration": int(runtime * 1000)})
    _plex_get(server, f"/:/timeline?{q}")
    if state == "stopped" and runtime and position >= runtime * 0.92:
        _plex_get(server, f"/:/scrobble?key={rating_key}&identifier=com.plexapp.plugins.library")


# -- Kodi ------------------------------------------------------------------------


def kodi_db(home: Path | None = None) -> Path | None:
    home = home or Path.home()
    for base in (home / ".var/app" / KODI / "data/userdata/Database", home / ".kodi/userdata/Database"):
        dbs = sorted(base.glob("MyVideos*.db"), key=lambda p: int("".join(c for c in p.stem if c.isdigit()) or 0))
        if dbs:
            return dbs[-1]
    return None


def kodi_items(home: Path | None = None) -> list[Item]:
    db = kodi_db(home)
    if db is None:
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
    try:
        rows = con.execute("""
            SELECT p.strPath || f.strFilename, b.timeInSeconds, b.totalTimeInSeconds, f.lastPlayed,
                   m.c00, e.c00, t.c00, e.c12, e.c13
            FROM bookmark b JOIN files f ON b.idFile = f.idFile JOIN path p ON f.idPath = p.idPath
            LEFT JOIN movie m ON m.idFile = f.idFile
            LEFT JOIN episode e ON e.idFile = f.idFile LEFT JOIN tvshow t ON e.idShow = t.idShow
            WHERE b.type = 1 ORDER BY f.lastPlayed DESC LIMIT ?""", (LIMIT,)).fetchall()
    finally:
        con.close()
    out = []
    for path, pos, total, last, movie, episode, show, season, number in rows:
        if show:
            title, subtitle = show, f"S{season} · E{number} · {episode or ''}"
        else:
            title, subtitle = movie or Path(path).stem, ""
        out.append(Item("kodi", path, title, subtitle.strip(" ·"), float(pos or 0), float(total or 0),
                        played_at=_kodi_time(last)))
    return out


def _kodi_time(text) -> float:
    try:
        return time.mktime(time.strptime(text, "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError):
        return 0.0


# -- the row -----------------------------------------------------------------------


def fetch() -> list[Item]:
    """Everything in progress, most recently watched first (slow: network)."""
    acc = accounts()
    items: list[Item] = []
    for name, get in (("jellyfin", jellyfin_items), ("plex", plex_items)):
        if acc.get(name):
            try:
                items += get(acc[name])
            except Exception as e:  # a server being off never matters much
                log.info("watch next: %s: %s", name, e)
    try:
        items += kodi_items()
    except (OSError, sqlite3.Error) as e:
        log.info("watch next: kodi: %s", e)
    items.sort(key=lambda i: i.played_at, reverse=True)
    return items[:LIMIT]


def _art_file(item: Item) -> Path:
    safe = "".join(c if c.isalnum() else "_" for c in item.key)[:120]
    return _cache_dir() / "watchnext-art" / f"{safe}.jpg"


def fetch_art(item: Item) -> None:
    if not item.art_url:
        return
    path = _art_file(item)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        headers = jellyfin_auth(accounts().get("jellyfin", {}).get("token")) if item.source == "jellyfin" else {}
        try:
            req = urllib.request.Request(item.art_url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
                path.write_bytes(r.read())
        except OSError as e:
            log.info("watch next art: %s", e)
            return
    item.art = str(path)


def refresh() -> list[Item]:
    items = fetch()
    for item in items:
        fetch_art(item)
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched": time.time(), "items": [asdict(i) for i in items]}))
    return items


def cached() -> tuple[float, list[Item]]:
    """(when it was fetched, the items) from the cache, instantly."""
    try:
        data = json.loads(cache_path().read_text())
        return float(data.get("fetched", 0)), [Item(**i) for i in data.get("items", [])]
    except (OSError, ValueError, TypeError):
        return 0.0, []


_refreshing = threading.Lock()


def refresh_soon() -> None:
    """Fetch again in the background if the cache is old (never waits)."""
    fetched, _ = cached()
    if time.time() - fetched < REFRESH_SECONDS or not _refreshing.acquire(blocking=False):
        return

    def run():
        try:
            refresh()
        except Exception:
            log.exception("watch next")
        finally:
            _refreshing.release()

    threading.Thread(target=run, daemon=True, name="watchnext").start()


def as_app(item: Item):
    import sys

    from .config import App

    colors = {"jellyfin": "#5a3e8f", "plex": "#cc7b19", "kodi": "#17b2e7"}
    names = {"jellyfin": "Jellyfin", "plex": "Plex", "kodi": "Kodi"}
    episode = re.match(r"S(\S+) · E(\S+)", item.subtitle)
    label = " · ".join(x for x in (f"S{episode[1]} E{episode[2]}" if episode else "", item.left) if x)
    return App(id=f"watch:{item.key}", name=item.title, command=(sys.executable, "-m", "hearth.watchplay",
                                                                  item.source, item.id, str(item.position),
                                                                  str(item.runtime), item.title),
               color=colors.get(item.source, "#3a3f58"), art=item.art,
               platform=label or names.get(item.source, item.source), progress=item.progress or None)


def row():
    """The Watch Next row from the cache (and a background refresh if it's old)."""
    from .config import Row

    refresh_soon()
    _, items = cached()
    return Row("Watch next", tuple(as_app(i) for i in items)) if items else None
