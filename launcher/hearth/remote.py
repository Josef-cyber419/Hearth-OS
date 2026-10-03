"""Your phone as a remote: a page on the home network with a d-pad, the
buttons and a keyboard (Settings → Phone remote).

The hub serves it on port 8420. The first visit asks for the code shown on
the TV; a phone that got it right is remembered (a token in its browser,
and in ~/.config/hearth/remote-phones.json), so pairing is a once-only
thing. Buttons and typed text go to whatever is in front through
gamescope's X server (drive.Keys), exactly like a keyboard plugged into the
PC, so sign-ins inside apps work too, not only Hearth's own screens.

Five wrong codes in a row make a new one. Nothing about the home is sent
anywhere: the page is plain HTML, served by Hearth, on your network only.
"""

from __future__ import annotations

import json
import logging
import secrets
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from . import session

log = logging.getLogger("hearth")

PORT = 8420
CODE_TRIES = 5  # wrong codes in a row before pairing pauses
LOCKOUT_SECONDS = 60  # how long it pauses
TOKEN_NAME = "hearth"
COOKIE_DAYS = 365
ADDRESS_SECONDS = 30  # how long a looked-up address is reused

active: "Remote | None" = None  # the server in this process (Settings and hearthctl ask it)


def phones_path() -> Path:
    from . import settings

    return settings.path().parent / "remote-phones.json"


def local_address() -> str | None:
    """This PC's address on the home network (the one the default route uses)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # a documentation address: nothing is sent
            return s.getsockname()[0]
    except OSError:
        return None


def hostname() -> str:
    return (socket.gethostname() or "hearth").split(".")[0]


def qr_matrix(text: str) -> list[list[bool]] | None:
    """The QR code for a text as rows of dark/light, or None without the
    qrcode library (python3-qrcode is in the image; it isn't needed to run)."""
    try:
        import qrcode
    except ImportError:
        return None
    q = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(text)
    q.make(fit=True)
    return [[bool(cell) for cell in row] for row in q.get_matrix()]


class Remote:
    """What the server knows: the code, the phones paired so far, and where
    buttons go. `keys` makes a drive.Keys when first needed (None when
    there's no Game Mode display, e.g. in a window); `enabled` is asked on
    every request so Settings can turn the remote off at once."""

    def __init__(self, keys: Callable[[], object | None], enabled: Callable[[], bool] = lambda: True,
                 port: int = PORT, phones: Path | None = None) -> None:
        self._keys_factory = keys
        self._keys = None
        self.enabled = enabled
        self.port = port
        self.phones_path = phones or phones_path()
        self.tokens: set[str] = self._load_phones()
        self.code = ""
        self.failures = 0
        self.locked_until = 0.0  # pairing paused after too many wrong codes
        self._address: tuple[float, str | None] | None = None
        self.new_code()

    # -- pairing ---------------------------------------------------------------

    def new_code(self) -> str:
        self.code = f"{secrets.randbelow(900000) + 100000}"
        self.failures = 0
        self.locked_until = 0.0
        self.publish()
        return self.code

    def locked_for(self, now: float | None = None) -> int:
        """Seconds until pairing is allowed again (0: now)."""
        return max(0, int(self.locked_until - (time.monotonic() if now is None else now) + 0.999))

    def pair(self, code: str, now: float | None = None) -> str | None:
        """A token for a phone that typed the code; None (and a strike) if
        not. Five wrong in a row pause pairing for a minute: the code stays,
        so the person on the sofa can still read and type it, and a device
        guessing gets nowhere (a million codes at five a minute)."""
        now = time.monotonic() if now is None else now
        if now < self.locked_until:
            return None
        if code.strip() == self.code:
            token = secrets.token_hex(16)
            self.tokens.add(token)
            self._save_phones()
            self.failures = 0
            self.publish()  # hearthctl status and Settings show how many phones are paired
            return token
        self.failures += 1
        if self.failures >= CODE_TRIES:
            log.info("phone remote: %d wrong codes, pairing paused for %ds", self.failures, LOCKOUT_SECONDS)
            self.locked_until = now + LOCKOUT_SECONDS
            self.failures = 0
        return None

    def forget_phones(self) -> None:
        self.tokens.clear()
        self._save_phones()
        self.publish()

    def paired(self, cookie_header: str | None) -> bool:
        for part in (cookie_header or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == TOKEN_NAME and value in self.tokens:
                return True
        return False

    def _load_phones(self) -> set[str]:
        try:
            data = json.loads(self.phones_path.read_text())
            return {t for t in data.get("tokens", []) if isinstance(t, str)}
        except (OSError, ValueError, AttributeError):
            return set()

    def _save_phones(self) -> None:
        from .settings import write_json

        try:
            write_json(self.phones_path, {"tokens": sorted(self.tokens)}, private=True)
        except OSError as e:
            log.warning("phone remote: couldn't save paired phones: %s", e)

    # -- what the TV shows ---------------------------------------------------------

    def address(self) -> str | None:
        """This PC's address, looked up now and then (not on every page build)."""
        now = time.monotonic()
        if self._address is None or now - self._address[0] > ADDRESS_SECONDS:
            self._address = (now, local_address())
        return self._address[1]

    def url(self) -> str:
        return f"http://{self.address() or hostname() + '.local'}:{self.port}"

    def info(self) -> dict:
        return {"url": self.url(), "name_url": f"http://{hostname()}.local:{self.port}", "code": self.code,
                "port": self.port, "phones": len(self.tokens)}

    def publish(self) -> None:
        """Tell hearthctl status (and the Settings app) where the page is."""
        try:
            info = self.info()
            session.update(lambda s: s.__setitem__("remote", info))
        except OSError:
            pass

    # -- doing things ---------------------------------------------------------------

    def keys(self):
        if self._keys is None:
            try:
                self._keys = self._keys_factory()
            except Exception:  # noqa: BLE001 - a display that can't be opened is "not in Game Mode"
                log.exception("phone remote: keys")
                self._keys = None
        return self._keys

    def press(self, name: str) -> str | None:
        keys = self.keys()
        if keys is None:
            return "The TV isn't in Game Mode"
        return keys.press(name)

    def type(self, text: str) -> str | None:
        keys = self.keys()
        if keys is None:
            return "The TV isn't in Game Mode"
        return keys.type(text[:500])

    def in_front(self) -> str:
        """What the TV is showing, for the page's title."""
        try:
            state = session.read()
        except OSError:
            return "Hearth"
        fg, focus = state.get("foreground"), state.get("focus")
        if focus in state.get("background", {}):
            return state["background"][focus].get("name") or "Hearth"
        if fg:
            return fg.get("name") or "Hearth"
        return "Settings" if state.get("screen") == "settings" else "Home screen"


# -- the page ------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<meta name="theme-color" content="#0b1016">
<title>Hearth remote</title>
<style>
:root { --ink:#0b1016; --panel:#141c25; --text:#f1ebde; --dim:#8b97a2; --accent:#f3812a; --second:#8cc4e6; }
* { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
html,body { margin:0; background:var(--ink); color:var(--text); font:17px/1.3 -apple-system,"Segoe UI",Roboto,sans-serif;
  touch-action:manipulation; overscroll-behavior:none; user-select:none; -webkit-user-select:none; }
main { max-width:440px; margin:0 auto; padding:14px 14px 32px; }
h1 { font-size:14px; letter-spacing:.25em; text-transform:uppercase; color:var(--dim); margin:4px 0 2px; }
#front { font-size:24px; font-weight:600; margin:0 0 14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
#front b { color:var(--accent); font-weight:600; }
button { appearance:none; border:0; border-radius:16px; background:var(--panel); color:var(--text);
  font:inherit; font-weight:600; letter-spacing:.06em; text-transform:uppercase; cursor:pointer; }
button:active { background:var(--accent); color:var(--ink); }
.pad { display:grid; grid-template-columns:1fr 1fr 1fr; grid-template-rows:1fr 1fr 1fr; gap:8px; width:100%;
  aspect-ratio:1; max-width:260px; margin:0 auto 14px; }
.pad button { font-size:28px; }
.pad .c { background:var(--accent); color:var(--ink); border-radius:50%; font-size:22px; }
.row { display:grid; grid-auto-flow:column; grid-auto-columns:1fr; gap:8px; margin-bottom:8px; }
.row button { padding:16px 0; font-size:15px; }
.row .b { color:var(--second); }
.guide { background:#1e2a36; }
.kb { margin-top:16px; display:flex; gap:8px; }
.kb input { flex:1; min-width:0; border:0; border-radius:14px; padding:14px; font:inherit; background:#fff; color:#111; }
.kb button { padding:0 18px; }
.hint { color:var(--dim); font-size:14px; margin:10px 0 0; }
#pair { display:none; margin-top:20px; }
#pair input { width:100%; font-size:34px; letter-spacing:.3em; text-align:center; padding:14px; border-radius:14px; border:0; }
#pair button { width:100%; margin-top:10px; padding:16px; font-size:16px; }
.err { color:var(--accent); min-height:1.3em; }
.stripe { height:5px; background:linear-gradient(90deg, var(--accent) 60%, var(--second) 60%); border-radius:3px; margin-bottom:14px; width:90px; }
</style></head>
<body><main>
<div class="stripe"></div>
<h1>Hearth</h1>
<p id="front">On the TV: <b>…</b></p>
<section id="pair">
  <p>Enter the code from the TV (Settings → Phone remote).</p>
  <input id="code" inputmode="numeric" pattern="[0-9]*" maxlength="6" placeholder="000000" autocomplete="one-time-code">
  <button id="pairbtn">Pair this phone</button>
  <p class="err" id="err"></p>
</section>
<section id="remote" style="display:none">
  <div class="pad">
    <span></span><button data-b="up">▲</button><span></span>
    <button data-b="left">◀</button><button class="c" data-b="a">A</button><button data-b="right">▶</button>
    <span></span><button data-b="down">▼</button><span></span>
  </div>
  <div class="row"><button class="b" data-b="b">B back</button><button data-b="x">X</button><button data-b="y">Y</button></div>
  <div class="row"><button data-b="lb">LB</button><button data-b="view">View</button><button data-b="menu">Menu</button><button data-b="rb">RB</button></div>
  <div class="row"><button class="guide" data-b="guide">Guide · Quick Menu</button><button class="guide" data-b="home">Home</button></div>
  <form class="kb" id="kb"><input id="text" placeholder="Type here, then Send" autocapitalize="off" autocorrect="off">
    <button type="submit">Send</button></form>
  <div class="row" style="margin-top:8px"><button data-t="&#10;">Enter</button><button data-b="backspace">Delete</button></div>
  <p class="hint">Sends to what's on the TV: Hearth's search, a Wi-Fi password, or an app's sign-in box.</p>
  <p class="err" id="err2"></p>
</section>
<script>
const $ = s => document.querySelector(s);
const buzz = () => { try { navigator.vibrate && navigator.vibrate(8); } catch (e) {} };
async function post(path, data) {
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'},
    body:new URLSearchParams(data)});
  if (r.status === 401) { show(false); throw new Error('Pair this phone first'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ('Error ' + r.status));
  return j;
}
function show(paired) { $('#pair').style.display = paired ? 'none' : 'block'; $('#remote').style.display = paired ? 'block' : 'none'; }
async function refresh() {
  try {
    const r = await fetch('/me'); const j = await r.json();
    if (r.status === 503) { $('#front b').textContent = 'the phone remote is turned off in Settings'; show(false);
      $('#pair').style.display = 'none'; return; }
    $('#front b').textContent = j.front; show(j.paired);
  } catch (e) { $('#front b').textContent = 'not reachable'; }
}
$('#pairbtn').onclick = async () => {
  $('#err').textContent = '';
  try { await post('/pair', {code: $('#code').value}); $('#code').value = ''; refresh(); }
  catch (e) { $('#err').textContent = e.message; }
};
document.querySelectorAll('[data-b]').forEach(b => b.addEventListener('click', async () => {
  buzz(); $('#err2').textContent = '';
  try { await post('/press', {b: b.dataset.b}); } catch (e) { $('#err2').textContent = e.message; }
}));
document.querySelectorAll('[data-t]').forEach(b => b.addEventListener('click', async () => {
  buzz(); try { await post('/type', {text: b.dataset.t}); } catch (e) { $('#err2').textContent = e.message; }
}));
$('#kb').onsubmit = async (ev) => {
  ev.preventDefault(); const t = $('#text').value; if (!t) return; buzz();
  try { await post('/type', {text: t}); $('#text').value = ''; } catch (e) { $('#err2').textContent = e.message; }
};
refresh(); setInterval(refresh, 4000);
</script>
</main></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "Hearth"
    remote: Remote  # set on the server

    def log_message(self, fmt, *args):  # quiet: the hub's log is for Hearth, not every tap
        pass

    def _send(self, status: int, body: bytes, kind: str = "application/json", cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", f"{TOKEN_NAME}={cookie}; Max-Age={COOKIE_DAYS * 86400}; Path=/; SameSite=Strict")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict, cookie: str | None = None) -> None:
        self._send(status, json.dumps(data).encode(), cookie=cookie)

    def _form(self) -> dict[str, str]:
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 10000)
        except ValueError:
            length = 0
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def do_GET(self) -> None:  # noqa: N802 (http.server's naming)
        remote = self.remote
        path = urlsplit(self.path).path
        if not remote.enabled():
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "The phone remote is turned off in Settings"})
            return
        if path == "/":
            self._send(HTTPStatus.OK, PAGE.encode(), "text/html")
        elif path == "/me":
            self._json(HTTPStatus.OK, {"paired": remote.paired(self.headers.get("Cookie")), "front": remote.in_front()})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        remote = self.remote
        path = urlsplit(self.path).path
        if not remote.enabled():
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "The phone remote is turned off in Settings"})
            return
        form = self._form()
        if path == "/pair":
            wait = remote.locked_for()
            token = None if wait else remote.pair(form.get("code", ""))
            if wait or remote.locked_for():
                self._json(HTTPStatus.TOO_MANY_REQUESTS,
                           {"error": f"Too many tries: wait {remote.locked_for() or 1} seconds"})
            elif token is None:
                time.sleep(0.5)  # a wrong code costs a moment
                self._json(HTTPStatus.FORBIDDEN, {"error": "That's not the code on the TV"})
            else:
                self._json(HTTPStatus.OK, {"paired": True}, cookie=token)
            return
        if not remote.paired(self.headers.get("Cookie")):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Pair this phone first"})
            return
        if path == "/press":
            problem = remote.press(form.get("b", ""))
        elif path == "/type":
            problem = remote.type(form.get("text", ""))
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if problem:
            self._json(HTTPStatus.CONFLICT, {"error": problem})
        else:
            self._json(HTTPStatus.OK, {"ok": True})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(remote: Remote, host: str = "0.0.0.0") -> Server:
    """Start answering (in a background thread); the server, for its port."""
    global active

    class Bound(Handler):
        pass

    Bound.remote = remote
    server = Server((host, remote.port), Bound)
    remote.port = server.server_address[1]  # port 0 picks one (tests)
    remote.publish()
    threading.Thread(target=server.serve_forever, daemon=True, name="phone-remote").start()
    active = remote
    return server


def start(enabled: Callable[[], bool], port: int = PORT) -> Server | None:
    """The hub's phone remote, if the port is free. Keys open on first use."""
    from .drive import Keys

    remote = Remote(Keys.connect, enabled, port)
    try:
        server = serve(remote)
    except OSError as e:
        log.warning("phone remote: can't listen on port %d: %s", port, e)
        return None
    log.info("phone remote at %s (code %s)", remote.url(), remote.code)
    return server


def wait_for(server: Server, seconds: float = 0.5) -> None:
    """Give a just-started server a moment (tests)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=0.1).close()
            return
        except OSError:
            time.sleep(0.02)
