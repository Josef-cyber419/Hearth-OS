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

- **TV home screen**: rows of tiles (Play / Watch / System), clock, confirm
  dialogs for power actions. Scales cleanly from 720p to 4K.
- **Your games up front**: a **Continue** row of what you played last and a
  **Pinned** row of favourites, across Steam and every emulated console, with
  their artwork. Press Y on any game to pin it. The **Library** tile lists
  every installed Steam game and every ROM, by platform. Games start directly:
  Steam ones open Big Picture and launch, emulated ones open their emulator.
- **Emulators tuned for your PC and TV**: Vulkan, upscaling to your TV's
  resolution, stutter-free shaders ([docs/EMULATION.md](docs/EMULATION.md#tuned-for-your-pc)).
- **Heritage racing look**: tiles painted like period race cars (deep enamel,
  twin stripes, a number roundel), condensed signwriter type, and a choice of
  liveries: Gulf, Martini, British Racing Green, Rosso, Silver Arrow. Motion is
  eased and frame-rate independent: a stripe sweep at power-on, tiles that
  cascade in, a focus stripe that glides between tiles, and a launch where the
  tile opens out to fill the screen. `motion = "reduced"` turns the decoration off.
- **Works with anything you hold**: Xbox/PlayStation/8BitDo controllers (SDL
  GameController mappings), TV remotes over HDMI-CEC, IR remotes via FLIRC,
  keyboards, and **Wii Remotes** on a DolphinBar: point at a tile to pick it,
  and use the pointer as a mouse where you want one. Dolphin gets them back
  for Wii games.
- **Quick Menu, over any game**: tap the controller's **Guide** button for a
  panel over whatever's playing, in the same livery, with the game paused. Switch audio
  output and microphone, set volumes, mix per-app volume, run Discord in the
  background (mute, deafen, voice volume, or bring it up with the controller as a
  mouse), and sleep/restart/power off. See [docs/QUICK_MENU.md](docs/QUICK_MENU.md).
- **Always a way home**: hold the controller's **Guide** button for 1.5s, or
  press **Home** on a remote, to close the current app and return. In Steam, use
  *Power → Switch to Desktop*, which Hearth turns into "back to home".
- **Remote-friendly apps only**: every default tile uses a TV/console interface
  (see [Streaming services](docs/STREAMING.md) for why Netflix and similar
  services aren't there, and the options for adding them).
- **Your TV follows the PC**: with a CEC adapter, the TV turns on and switches
  input when the PC wakes, and goes to standby when it sleeps.
- **Settings app, with the remote**: a Settings tile with everything in one
  place: livery, motion and clock; which tiles show; the Guide button and
  controller-as-mouse speed; the Wii Remote (sensor bar position, pointer
  speed and steadiness, sideways hold, mouse mode, and a two-target pointer
  calibration); emulator tuning; Bluetooth pairing; Wi-Fi with an on-screen
  keyboard and a connection test; hardware, temperatures, storage, updates and
  problem reports. Also the things TVs and consoles are expected to have: a
  screen saver (OLED-friendly), sleep when idle, screen edges for TVs that
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

1. **Emulation**: see [docs/EMULATION.md](docs/EMULATION.md) for how the game
   menu works, adding games, and which consoles run well.
1. **Hardware**: see [docs/HARDWARE.md](docs/HARDWARE.md). An AMD GPU and a
   Pulse-Eight CEC adapter or FLIRC make the biggest difference.
2. **Install**: see [docs/INSTALL.md](docs/INSTALL.md). You install Bazzite, then
   switch it to the Hearth image with one command. Dual-boot setup is covered there too.

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

Early. The launcher is tested and the image build checks its own
assumptions, but nothing has been run on real hardware yet. See
[the checklist](docs/ARCHITECTURE.md#verify-on-real-hardware) of what to
confirm first.

## Repository layout

```
Containerfile                 OS image: Bazzite + Hearth
image/build.sh                runs inside the image build
image/system_files/           files copied into the image, laid out like /
launcher/hearth/              the home screen / session hub (Python)
launcher/tests/               tests (headless, run in CI)
docs/                         install, hardware, architecture
.github/workflows/build.yml   tests + builds and publishes the image to GHCR
```
