"""Drive Hearth inside real gamescope, verify each step, and record a video.

Exit status is non-zero if any check fails.

Frames: gamescope decides what's on screen (GAMESCOPE_FOCUSED_WINDOW, the
overlay's opacity); pixels come from each window in Xwayland; the overlay is
alpha-blended on top the way gamescope composites it. Audio: the real
PipeWire output (TV and headset monitors).
"""
import json, os, pathlib, subprocess, sys, tarfile, threading, time
sys.path.insert(0, "/src/launcher")
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
from Xlib import X, XK
from Xlib.ext import xtest
from hearth.gamescope import Gamescope, HOME_APPID, OPAQUE, appid_for

OUT = "/lab/demo"
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    if f.endswith((".png", ".wav", ".json", ".txt")):
        os.remove(os.path.join(OUT, f))
ENV = {**os.environ, "XDG_RUNTIME_DIR": "/run/user/0", "XDG_STATE_HOME": "/lab/state",
       "XDG_CONFIG_HOME": "/lab/config", "HOME": "/lab/home", "PYTHONPATH": "/src/launcher"}
pygame.display.init(); pygame.font.init()
FONT = pygame.font.SysFont("dejavusans", 26, bold=True)
SMALL = pygame.font.SysFont("dejavusans", 17)

gs = Gamescope.connect()
checks = []
caption = ["", ""]


def check(desc, ok):
    checks.append((desc, bool(ok)))
    print(("PASS " if ok else "FAIL ") + desc, flush=True)


def root_prop(g, name):
    p = g.root.get_full_property(g.atom(name), X.AnyPropertyType)
    return list(p.value) if p and len(p.value) else []


def state():
    return json.load(open("/run/user/0/hearth/state.json"))


def pactl(*a):
    return subprocess.run(["pactl", *a], capture_output=True, text=True, env=ENV).stdout


def pjson(kind):
    return json.loads(pactl("-f", "json", "list", kind))


def ctl(*a):
    subprocess.run([sys.executable, "-m", "hearth.ctl", *a], env=ENV, check=True)


def wait_for(desc, pred, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                check(desc, True)
                return True
        except Exception:
            pass
        time.sleep(0.1)
    check(desc, False)
    return False


def key(name, pause=0.35):
    d = gs.d
    code = d.keysym_to_keycode(XK.string_to_keysym(name))
    xtest.fake_input(d, X.KeyPress, code); d.sync()
    time.sleep(0.05)
    xtest.fake_input(d, X.KeyRelease, code); d.sync()
    time.sleep(pause)


def say(title, sub=""):
    caption[0], caption[1] = title, sub
    print(f"\n== {title}", flush=True)


def title_of_focus(g):
    fw = root_prop(g, "GAMESCOPE_FOCUSED_WINDOW")
    return g.window_title(g.window(fw[0])) if fw else None


class Recorder(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.g = Gamescope.connect()
        self.frames = []
        self.running = True

    def grab(self, wid):
        win = self.g.window(wid)
        geo = win.get_geometry()
        img = win.get_image(0, 0, geo.width, geo.height, X.ZPixmap, 0xFFFFFFFF)
        return pygame.image.frombuffer(img.data, (geo.width, geo.height), "BGRA").copy(), geo.depth

    def run(self):
        overlay = None
        t0 = time.time()
        while self.running:
            t = time.time() - t0
            frame = pygame.Surface((1280, 720))
            try:
                fw = root_prop(self.g, "GAMESCOPE_FOCUSED_WINDOW")
                if fw:
                    surf, depth = self.grab(fw[0])
                    surf.fill((0, 0, 0, 255), special_flags=pygame.BLEND_RGBA_MAX)
                    frame.blit(surf, (0, 0))
                if overlay is None:
                    overlay = self.g.find_window("Hearth Quick Menu")
                if overlay is not None:
                    op = self.g.get_cardinal(overlay, "_NET_WM_WINDOW_OPACITY") or 0
                    if op:
                        surf, _ = self.grab(overlay.id)
                        frame.blit(surf, (0, 0), special_flags=pygame.BLEND_PREMULTIPLIED)
            except Exception as e:
                print("frame error", e)
            if caption[0]:
                bar = pygame.Surface((1280, 74), pygame.SRCALPHA)
                bar.fill((0, 0, 0, 175))
                frame.blit(bar, (0, 646))
                frame.blit(FONT.render(caption[0], True, (255, 255, 255)), (24, 652))
                frame.blit(SMALL.render(caption[1], True, (200, 205, 220)), (24, 688))
            tag = SMALL.render("real gamescope 3.16 · Steam mode · real PipeWire", True, (255, 214, 150))
            frame.blit(tag, (14, 10))
            path = f"{OUT}/f{len(self.frames):05d}.png"
            pygame.image.save(frame, path)
            self.frames.append((t, path))
            time.sleep(max(0, 0.08 - (time.time() - t0 - t)))


def sink_volume(name):
    s = next(s for s in pjson("sinks") if s["name"] == name)
    return int(list(s["volume"].values())[0]["value_percent"].rstrip("%"))


def stream(app):
    return next((s for s in pjson("sink-inputs") if s["properties"].get("application.name") == app), None)


# --- audio capture from both outputs -------------------------------------------
audio = [subprocess.Popen(["parecord", "-d", f"{dev}.monitor", "--file-format=wav", f"{OUT}/{dev}.wav"], env=ENV)
         for dev in ("tv_hdmi", "headset")]
rec = Recorder()
rec.start()
t_start = time.time()

# A known starting point: TV speakers at 60%, headset at 70%.
pactl("set-default-sink", "tv_hdmi")
pactl("set-sink-volume", "tv_hdmi", "60%")
pactl("set-sink-volume", "headset", "70%")
time.sleep(1)

# 1. boot
say("Power on: Game Mode starts Hearth", "Hearth tags its window so gamescope (Steam mode) will show it")
wait_for("gamescope focuses the home screen", lambda: root_prop(gs, "GAMESCOPE_FOCUSED_APP") == [HOME_APPID])
time.sleep(2.5)

# 2. browse
say("Browse with a controller or TV remote", "Rows remember where you were")
for k in ("Right", "Right", "Down", "Right", "Up", "Left", "Left"):
    key(k, 0.55)
time.sleep(0.5)

# 3. launch
say("Launch a game", "It runs full screen; gamescope switches to it")
key("Return", 0.2)
wait_for("gamescope shows the game", lambda: root_prop(gs, "GAMESCOPE_FOCUSED_APP") == [appid_for("game")]
         and title_of_focus(gs) == "Fake Game")
wait_for("game's audio is playing", lambda: stream("Fake Game") is not None)
time.sleep(2.5)

# 4. quick menu
say("Tap Guide: the Quick Menu slides in over the game", "The game shows through; gamescope gives the menu the input")
ctl("menu")
qm = gs.find_window("Hearth Quick Menu")
wait_for("overlay visible and has input", lambda: gs.get_cardinal(qm, "STEAM_INPUT_FOCUS") == 1
         and gs.get_cardinal(qm, "_NET_WM_WINDOW_OPACITY") == OPAQUE)
time.sleep(2)

# 5. volume
say("Audio: turn the TV volume up", "Hold right to keep going")
before = sink_volume("tv_hdmi")
for _ in range(3):
    key("Right", 0.45)
wait_for(f"TV volume went up from {before}%", lambda: sink_volume("tv_hdmi") == before + 15)
time.sleep(0.8)

# 6. output switch
say("Switch output to the headset", "Everything already playing moves with it")
key("Down", 0.5)
key("Right", 0.3)
wait_for("default output is now the headset", lambda: pactl("get-default-sink").strip() == "headset")
hs_index = next(s["index"] for s in pjson("sinks") if s["name"] == "headset")
wait_for("the game's sound moved to the headset", lambda: stream("Fake Game")["sink"] == hs_index)
time.sleep(1.5)

# 7. mixer
say("Mixer: volume for each app", "Turn just the game down")
key("e", 0.8)
for _ in range(4):
    key("Left", 0.35)
wait_for("game stream at 80%", lambda: list(stream("Fake Game")["volume"].values())[0]["value_percent"] == "80%")
time.sleep(1)

# 8. discord
say("Discord tab: start Discord in the background", "")
key("e", 0.9)
key("Return", 0.2)
wait_for("gamescope shows Discord", lambda: root_prop(gs, "GAMESCOPE_FOCUSED_APP") == [appid_for("discord")])
say("Discord runs alongside the game", "Your controller works as a mouse here")
wait_for("Discord's voice and mic streams exist",
         lambda: stream("WEBRTC VoiceEngine") is not None and any(
             o["properties"].get("application.name") == "WEBRTC VoiceEngine" for o in pjson("source-outputs")))
time.sleep(3)

# 9. call controls
say("Quick Menu over Discord: call controls", "Mute your mic and deafen, even with Discord hidden")
ctl("menu")
wait_for("menu open", lambda: state()["overlay_open"])
time.sleep(1.2)
key("Down", 0.5); key("Return", 0.8)
wait_for("mic muted in Discord's call", lambda: all(o["mute"] for o in pjson("source-outputs")
                                                  if o["properties"].get("application.name") == "WEBRTC VoiceEngine"))
key("Down", 0.5); key("Return", 0.8)
wait_for("Discord deafened", lambda: stream("WEBRTC VoiceEngine")["mute"])
say("Back to the game", "")
key("Up", 0.4); key("Up", 0.4); key("Return", 0.3)
wait_for("gamescope shows the game again", lambda: root_prop(gs, "GAMESCOPE_FOCUSED_APP") == [appid_for("game")])
time.sleep(2)

# 10. close the game
say("System tab: close the game", "Anything that ends what you're doing asks twice")
ctl("menu")
wait_for("menu open", lambda: state()["overlay_open"])
time.sleep(0.8)
key("e", 0.8)  # the menu remembers the Discord tab; System is next
key("Down", 0.6)
key("Return", 0.9)
key("Return", 0.3)
wait_for("game closed, back home", lambda: state()["foreground"] is None
         and root_prop(gs, "GAMESCOPE_FOCUSED_APP") == [HOME_APPID])
say("Home again", "Discord keeps running in the background (green dot)")
check("Discord still running", "discord" in state()["background"])
time.sleep(3.5)

# 11. pointing (what a Wii Remote does): aim at a tile, press A
say("Point at a tile, press A", "A Wii Remote on a DolphinBar: the pointer highlights what you aim at")
from hearth.ui import Theme  # noqa: E402
from hearth.wiiinput import XTestSink  # noqa: E402

th = Theme((1280, 720))
aim = XTestSink(gs.d)
tx = (th.margin + th.tile_w / 2) / 1280  # Kodi: first tile of the second row
ty = (th.header_h + th.row_h + th.row_title_h + th.tile_h / 2) / 720
for i in range(1, 25):  # glide there like a hand would
    aim.move(0.75 + (tx - 0.75) * i / 24, 0.3 + (ty - 0.3) * i / 24)
    time.sleep(0.03)
time.sleep(0.8)
key("Return", 0.3)
wait_for("gamescope opens the tile pointed at (Kodi)",
         lambda: root_prop(gs, "GAMESCOPE_FOCUSED_APP") == [appid_for("kodi")])
time.sleep(1.5)
ctl("home")
wait_for("back home", lambda: state()["foreground"] is None
         and root_prop(gs, "GAMESCOPE_FOCUSED_APP") == [HOME_APPID])
time.sleep(1)

# 12. the Settings app, with the remote
say("Settings", "Every option with a remote: looks, Wii Remote, Bluetooth, Wi-Fi...")
key("Tab", 0.5)  # Menu jumps to the System row; Settings is its first tile
key("Return", 1.2)
wait_for("Settings opened", lambda: '"settings_open"' in pathlib.Path("/lab/state/hearth/events.jsonl").read_text())
for _ in range(3):
    key("Down", 1.1)  # Home screen, Controllers, Wii Remote
key("Right", 1.0)
for _ in range(4):
    key("Down", 0.5)  # through the Wii Remote options
time.sleep(0.8)
key("Escape", 0.6)
for _ in range(3):
    key("Up", 0.5)
say("Settings: change the livery", "It applies straight away, everywhere")
key("Return", 0.8)
key("Right", 1.6)  # Martini
key("Right", 1.6)  # British Racing Green
wait_for("livery saved", lambda: json.load(open("/lab/config/hearth/settings.json"))["theme"]["livery"] == "brg")
key("Escape", 0.4)
key("Escape", 1.5)
wait_for("home screen back", lambda: root_prop(gs, "GAMESCOPE_FOCUSED_APP") == [HOME_APPID])
ctl("menu")
wait_for("Quick Menu open in the new livery", lambda: state()["overlay_open"]
         and "settings changed; reloaded" in open("/lab/state/hearth/hearth.log").read())
time.sleep(2)
ctl("menu")
time.sleep(1)

# 13. a troubleshooting report, with a screenshot
say("Report a problem", "hearthctl report: logs, hardware, timeline and a screenshot in one file")
ctl("report", "--screenshot", "-o", f"{OUT}/reports")
bundle = sorted(pathlib.Path(f"{OUT}/reports").glob("hearth-report-*.tar.gz"))[-1]
with tarfile.open(bundle) as tar:
    files = {n.split("/", 1)[1]: n for n in tar.getnames()}
    shown = tar.extractfile(files["graphics/gamescope.txt"]).read().decode()
    if "screen.png" in files:
        open(f"{OUT}/report-screen.png", "wb").write(tar.extractfile(files["screen.png"]).read())
check("report has a screenshot", "screen.png" in files)
check("report shows what gamescope is focusing", "GAMESCOPE_FOCUSED_APP = [" in shown and "Hearth" in shown)
check("report has the event timeline", "hearth/events.jsonl" in files)
time.sleep(1)

rec.running = False
rec.join()
for p in audio:
    p.terminate()
time.sleep(0.5)
json.dump({"frames": rec.frames, "checks": checks, "audio_offset": 0}, open(f"{OUT}/result.json", "w"))
passed = sum(ok for _, ok in checks)
print(f"\n{passed}/{len(checks)} checks passed; {len(rec.frames)} frames")
sys.exit(0 if passed == len(checks) else 1)
