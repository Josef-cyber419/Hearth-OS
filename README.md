# Hearth OS

A living-room PC that behaves like a smart TV and a console at the same time.

Power it on and you land on a **TV-style home screen**, driven by a controller or
your TV remote. Pick **Steam** to get the full Steam Deck-style console UI, or go
straight to **emulation, Kodi, YouTube, Jellyfin, Plex, Moonlight**, and more.
Close the app and you're back home. Every app on the home screen is chosen to
work with just a controller or a TV remote, with no keyboard or mouse needed.

```
 power on ──► Hearth home screen ──► Steam (Big Picture / Game Mode)
                 ▲      │       ├──► Emulation (ES-DE: a tile per console, PS1 → Switch)
                 │      │       ├──► Kodi · YouTube · Jellyfin · Plex · Android
                 │      │       ├──► Moonlight (stream from another PC)
                 │      │       ├──► HDMI Input (PS5/Switch 2 via capture card)
                 │      │       └──► Desktop Mode (KDE Plasma)
                 └──────┘  app exits, or hold the Guide button
```

## How it's built

Hearth doesn't write an OS from scratch. It **orchestrates** existing pieces:

| Layer | What | Why |
|---|---|---|
| Base OS | [Bazzite](https://bazzite.gg) (`bazzite-deck`), Fedora Atomic | Gaming drivers, Steam, gamescope, HDR/VRR, controller support, atomic updates with rollback |
| Image | [`Containerfile`](Containerfile) | Hearth *is* a container image layered on Bazzite, built by CI and installed with `bootc switch` |
| Session | [`/etc/gamescope-session-plus/sessions.d/`](image/system_files/etc/gamescope-session-plus/sessions.d) | Hearth replaces Steam as the first app in Bazzite's Game Mode and keeps every Game Mode setting |
| Home screen | [`launcher/`](launcher) (Python + SDL2) | 10-foot UI, gamepad/remote/keyboard input, runs apps and returns home |
| Apps | Flatpaks + small scripts in [`/usr/libexec/hearth`](image/system_files/usr/libexec/hearth) | Kodi, ES-DE + emulators, Moonlight, VacuumTube (YouTube's TV interface), Jellyfin and Plex in TV mode |
| Extras | HDMI-CEC, first-boot app installer | See below |

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Features

- **TV home screen**: rows of tiles (Play / Watch / System), clock,
  controller batteries and the network (Wi-Fi bars, wired or offline), confirm
  dialogs for power actions, and a backdrop that glows with the focused game's
  art or app's colour. Scales cleanly from 720p to 4K. After an update it
  shows once **what's new** in that version.
- **Watch next**: a row of the films and episodes you're partway through on
  **Jellyfin**, **Plex** and **Kodi**, with a progress bar; pick one and it
  carries on where you stopped, and your server hears how far you got.
  Connecting takes a code on your phone, no typing passwords
  ([STREAMING.md](docs/STREAMING.md#watch-next-carry-on-where-you-stopped)).
- **Family**: a daily game-time limit, a bedtime and locked tiles, behind a
  PIN, for the whole household; films and TV apps don't count against it
  ([FAMILY.md](docs/FAMILY.md)); everyone in the household can have their own
  home screen, Steam and Discord, picked on "Who's playing?" ([PEOPLE.md](docs/PEOPLE.md)).
- **Private, and light**: no ads, no sponsored tiles, nothing sent about what
  you watch or play. Settings → Privacy shows how to turn off your **TV's own
  tracking**, for its make. Hearth itself idles at under 2% of one processor
  core and about 300 MB ([PERFORMANCE.md](docs/PERFORMANCE.md)).
- **Cast from your phone**: the PC shows up as a screen and a speaker on the
  home network, for AirPlay (video, photos, music, screen mirroring from an
  iPhone, iPad or Mac), Spotify Connect, and YouTube with a TV code
  ([CASTING.md](docs/CASTING.md)).
- **Your phone as a remote**: a page on your network with a d-pad, the
  buttons and a keyboard, paired once with a code (and a QR code) on the TV:
  Wi-Fi passwords, searches and sign-ins typed on the phone (Settings →
  Phone remote).
- **Accessibility**: larger text and a high-contrast look, each person's own
  (Settings → Accessibility); the screen saver can show your own photos.
- **Captures**: take a screenshot over any game from the Quick Menu; the
  **Captures** tile shows them all (full screen, flip through, delete), and
  they appear in the screen saver. Kept in `~/Pictures/Hearth`.
- **Find anything**: the **View** button (Share on PlayStation, − on Switch)
  or the Search tile searches every app and game as you type, with the
  controller or a keyboard. **Y** on a game shows its details: play time,
  last played, platform.
- **Make it yours**: press **X** on any tile (app or game) to star it into the
  **Favorites** row at the top; **Y → Move** rearranges tiles in a row. How
  Hearth compares with smart TVs and consoles, and what's next:
  [docs/COMPARISON.md](docs/COMPARISON.md).
- **Every PC store in one Library**: an Epic Games tile (Heroic, also GOG and
  Amazon), and Battle.net, EA app and Ubisoft Connect tiles (Lutris). Their
  installed games join Steam's in the Library, Continue and Search, and start
  directly. See
  [docs/GAME_STORES.md](docs/GAME_STORES.md).
- **Your games up front**: a **Continue** row of what you played last, across
  Steam and every emulated console, with their artwork. The **Library** tile lists
  every installed Steam game and every ROM, by platform. Games start directly:
  Steam ones open Big Picture and launch, emulated ones open their emulator.
- **Emulators tuned for your PC and TV**: Vulkan, upscaling to your TV's
  resolution, stutter-free shaders ([docs/EMULATION.md](docs/EMULATION.md#tuned-for-your-pc)).
- **Heritage racing look**: tiles painted like period race cars (deep enamel,
  twin stripes, a number roundel), condensed signwriter type, and a choice of
  liveries: Gulf, Martini, British Racing Green, Rosso, Silver Arrow, and
  Girth OS (wider by design). Motion is
  eased and frame-rate independent: a stripe sweep at power-on, tiles that
  cascade in, a focus stripe that glides between tiles, and a launch where the
  tile opens out to fill the screen. `motion = "reduced"` turns the decoration off.
- **Works with anything you hold**: Xbox/PlayStation/8BitDo controllers (SDL
  GameController mappings), TV remotes over HDMI-CEC, IR remotes via FLIRC,
  keyboards, and **Wii Remotes** on a DolphinBar: point at a tile to pick it
  (rest the pointer near the top or bottom edge to scroll the rows), and use
  the pointer as a mouse where you want one. Dolphin gets them back
  for Wii games.
- **Quick Menu, over any game**: tap the controller's **Guide** button (or a
  keyboard's **Windows** key) for a panel over whatever's playing, in the same livery, with the game paused. Switch audio
  output and microphone, set volumes, mix per-app volume, run Discord in the
  background (mute, deafen, voice volume, or bring it up with the controller as a
  mouse), play/pause/skip what's playing, watch **CPU and GPU load and
  temperatures** (it says plainly if the PC is running hot or slowing down), and
  sleep/restart/power off. Small notices pop up over games for a controller
  running low or an app that finished installing. See
  [docs/QUICK_MENU.md](docs/QUICK_MENU.md).
- **Quick Resume, like an Xbox**: hold **Guide** in a game and it pauses where
  you are and you're back home; it waits in a **Quick Resume** row on top (up to
  3 games), and picking it carries on instantly, with nothing reloading. Y on
  it closes it. Steam manages its own games and isn't paused this way.
- **Always a way home**: hold the controller's **Guide** button for 1.5s, or
  press **Home** on a remote, to go home (keeping the game paused, or closing
  it: Settings → Controllers). In Steam, use *Power → Switch to Desktop*, which
  Hearth turns into "back to home", or hold **Guide for 4 s**, which closes
  Steam whatever state it's in. In Desktop Mode, holding Guide goes back to
  Hearth too, as does the **Hearth** icon on the desktop; the **Steam Gaming
  Mode** icon next to it starts Game Mode with Steam's own interface, for
  that one session.
- **PC ports and AppImages as tiles**: drop an AppImage (e.g. a decompiled
  Twilight Princess port) in `~/Games` and it gets a tile in a **PC games**
  row. See [EMULATION.md](docs/EMULATION.md#pc-ports-appimages-straight-on-the-home-screen).
- **Quit just the game in ES-DE**: Quick Menu → System → *Quit game, back to
  ES-DE* closes the emulator and leaves you on your game list.
- **Remote-friendly apps only**: every default tile uses a TV/console interface
  (see [Streaming services](docs/STREAMING.md) for why Netflix and similar
  services aren't there, and the options for adding them).
- **Your TV follows the PC**: with a CEC adapter, the TV turns on and switches
  input when the PC wakes (trying again until the TV answers), goes to standby
  when it sleeps, and, like a console, **pressing Guide brings the TV to
  Hearth** if someone left it on another input.
- **Settings app, with the remote**: a Settings tile with everything in one
  place: livery, motion and clock; which tiles show; **audio** (where sound
  plays, which microphone, with a test sound); the Guide button,
  stick dead zone and controller-as-mouse speed; the Wii Remote (sensor bar position, pointer
  speed and steadiness, sideways hold, mouse mode, and a two-target pointer
  calibration); emulator tuning; Bluetooth pairing; Wi-Fi with an on-screen
  keyboard, a connection test, a **static IP address** and **DNS servers**
  (Cloudflare, Google, Quad9 or your own); **drives added after install**, set up for
  Steam games and ROMs ([STORAGE.md](docs/STORAGE.md)); hardware,
  temperatures, updates and problem reports. Also the things TVs and consoles are expected to have: a
  screen saver with your games' art (OLED-friendly), optional UI sounds, sleep when idle, screen edges for TVs that
  crop, Nintendo-style confirm button, and Xbox, PlayStation or Nintendo
  button names on screen. Changes apply at once.
- **Customisable without rebuilding**: copy
  [`apps.toml`](image/system_files/usr/share/hearth/apps.toml) to
  `~/.config/hearth/apps.toml` and edit. Tiles for apps that aren't installed are
  hidden automatically.
- **Updates itself**: OS and apps update automatically in the background (the
  home screen tells you when a restart will finish one), or on demand from the
  Quick Menu. Every update can be rolled back.
- **Easy to fix**: `hearthctl doctor` checks the whole setup and tells you how to
  fix problems; `hearthctl logs` has the details. **Report a problem** (Quick
  Menu → System, or `hearthctl report`) saves logs, hardware details, a
  screenshot and a timeline of what happened into one file you can send, with
  personal details masked. See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Getting started

1. **Check your PC**: Hearth needs **AMD or Intel graphics** (NVIDIA isn't
   supported yet). [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) lists what's
   supported, and [docs/HARDWARE.md](docs/HARDWARE.md) the add-ons that make
   the biggest difference (a Pulse-Eight CEC adapter or FLIRC, a DolphinBar).
2. **Install**: follow [docs/INSTALL.md](docs/INSTALL.md), about 30 minutes:
   install Bazzite from a USB stick, then switch it to Hearth with one command.
3. **Emulation**: see [docs/EMULATION.md](docs/EMULATION.md) for how the game
   menu works, adding games, and which consoles run well.

### Try the home screen on any Linux or macOS machine

```sh
cd launcher
pip install -e '.[dev]'
python -m hearth --windowed --dry-run --show-all \
    --config ../image/system_files/usr/share/hearth/apps.toml
```

`--dry-run` prints commands instead of running them. Arrow keys and Enter
navigate; Tab jumps to the System row; Esc on the first tile quits.

### Run the tests

```sh
cd launcher && SDL_VIDEODRIVER=dummy pytest -q
```

With `Xvfb` installed, this includes an end-to-end run of the real home screen
and Quick Menu with fake apps (`tests/test_e2e.py`).

### See it in real gamescope, no TV needed

```sh
tools/gamescope-lab/run.sh   # needs Docker → tools/gamescope-lab/out/hearth-demo.mp4
```

Runs Hearth inside real gamescope (Steam mode) with real PipeWire, plays
through a session with 26 checks, and records a video. See
[tools/gamescope-lab](tools/gamescope-lab/README.md).

## Project status

Hearth runs day to day on a living-room PC (Ryzen 7 5800X3D, Radeon RX 6750
XT, 24 GB, ASUS TUF A520M) with an Xbox controller and a Wii Remote on a
DolphinBar. Emulation (ES-DE and Dolphin) and the Wii Remote pointer are
confirmed working there. What still needs checking on real hardware is in
[the checklist](docs/ARCHITECTURE.md#verify-on-real-hardware); the latest
[progress report](reports/README.md) has the full picture: one per version, with
lines of code, tests and what's working, and the history of every version.

## Versions

Hearth is at the version in [`VERSION`](VERSION) (shown in Settings → System
and `hearthctl status`); [CHANGELOG.md](CHANGELOG.md) says what each one
brought. A change merged into `main` bumps it (a new minor version, or a patch
for a fix on its own) and adds its changelog entry. CI then tags it
(`v0.20.0`), publishes a GitHub release with those notes, and pins an image to
it (`ghcr.io/<owner>/hearth-os:0.20.0`), so any version can be installed or
gone back to with `bootc switch`. Versions from before tagging began (0.1.0 to
0.19.0) are published too once the repository has a `RELEASE_TOKEN` secret (a
fine-grained token with Contents and Workflows read/write): GitHub doesn't let
the workflow's own token tag commits that old.

## Branches and updates

| Branch | What it is | Image | PCs following it |
|---|---|---|---|
| `main` | **Live**: what's released | `ghcr.io/<owner>/hearth-os:latest` | every install, by default |
| `staging` | **Testing**: for trying new work before it goes live (mirrors `main` for now) | `ghcr.io/<owner>/hearth-os:staging` | only ones switched with `hearthctl channel staging` |

For now there's one PC, so changes are merged straight into `main` and
`staging` mirrors it: every build of `main` also publishes `:staging` and
moves the `staging` branch along. When more devices run Hearth, turning off
`MIRROR_STAGING` in the [build workflow](.github/workflows/build.yml) makes
`staging` the place new work lands first, to be tried before it's merged into
`main`. Images are built and tested by CI on every push, and `main` is also
rebuilt daily to pick up Bazzite and Fedora updates.

## Repository layout

```
Containerfile                 OS image: Bazzite + Hearth
image/build.sh                runs inside the image build
image/system_files/           files copied into the image, laid out like /
launcher/hearth/              the home screen / session hub (Python)
launcher/tests/               tests (headless, run in CI)
docs/                         install, hardware, architecture
reports/                      a progress report per version (tools/progress_report.py)
tools/gamescope-lab/          run Hearth in real gamescope in Docker, no TV needed
.github/workflows/build.yml   tests + builds and publishes the image to GHCR
```
