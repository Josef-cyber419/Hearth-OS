# Architecture

## Boot flow

```
firmware (UEFI) ──► GRUB ──► Bazzite (Fedora Atomic, Hearth image)
                               │
                               ▼
                   SDDM autologin → Game Mode session
                   gamescope-session-plus <ogui-steam|steam>
                   │  sources /usr/share/gamescope-session-plus/sessions.d/<session>   (Bazzite's)
                   │  then    /etc/gamescope-session-plus/sessions.d/<session>         (Hearth's: CLIENTCMD=/usr/bin/hearth)
                   ▼
                   gamescope (compositor: HDR, VRR, scaling) ──► hearth (session hub)
                                                                  ├──► hearth.overlay (Quick Menu, window tagging)
                                                                  │
                             ┌────────────────────────────────────┤ loop:
                             │  1. show home screen (pygame/SDL2)  │
                             │  2. user picks a tile               │
                             │  3. close window, run app, wait     │
                             │  4. app exits → back to 1           │
                             └────────────────────────────────────┘
```

Hearth replaces only the *client command* of Bazzite's Game Mode session.
gamescope, and all of Bazzite's per-device tuning, stays exactly as it was.
Steam becomes a tile: `hearth-steam` runs it with the same flags the stock
session uses (`-gamepadui -steamos3 -steampal -steamdeck`).

`gamescope-session-plus` has a safety net: if its client exits within 60
seconds five times in a row, it resets to the desktop session. So a broken
Hearth update can't leave you with a black screen; you land in Desktop Mode,
where `sudo bootc rollback` is one command away.

## Talking to gamescope

In Game Mode, gamescope runs with `--steam`, and Steam normally does two jobs
Hearth now does itself (read from gamescope's `steamcompmgr.cpp`):

- **Which windows can be shown.** Only windows with a `STEAM_GAME` app ID can
  be focused. The overlay process tags every new window with its app's ID
  (from the window's PID, traced via the X-Resource extension to its systemd
  scope; or its `WM_CLASS`). The home screen tags its own window.
- **Which app is in front.** Setting `GAMESCOPECTRL_BASELAYER_APPID` on the
  root window picks it. Hearth sets it when switching between home, the
  running app and background apps like Discord. It removes it while Steam is
  in front, so Steam can manage focus itself.

The **Quick Menu** is a `STEAM_OVERLAY` window, the same kind as Steam's Quick
Access menu. gamescope draws it above everything; `STEAM_INPUT_FOCUS` gives it
input while open; `_NET_WM_WINDOW_OPACITY` hides it. It uses a 32-bit (ARGB)
visual and the SDL renderer, so it has real per-pixel transparency and the
game shows through.

## Apps run in systemd scopes

Each app Hearth starts runs in its own systemd user scope
(`hearth-app-<id>_<n>.scope`, or `hearth-bg-…` for background apps). A scope
covers the app and everything it spawns, except that Flatpak moves each app it
starts into a scope of its own (`app-flatpak-<id>-<pid>.scope`). So pausing,
closing and "is it still running" act on Hearth's scope plus any Flatpak scope
the app's processes are in (`session.app_units`), and an app counts as running
while the process Hearth started (`flatpak run`) does. That enables:
- **Pause**: the Quick Menu freezes the game's cgroup while it's open
  (`systemctl --user freeze`) and thaws it on close. Turn this off with
  `[quick_menu] pause_game = false` in `apps.toml`.
- **Quick Resume**: holding Guide (or the Quick Menu's "Home, keep … paused",
  or `hearthctl pause`) sets `suspend_request`; the hub freezes the scope,
  moves the game from `foreground` to `suspended` in the state file and
  shows the home screen with a Quick Resume row. Picking it thaws the scope
  and the hub waits on it again, exactly as after a launch. With more than
  `[home] quick_resume` games paused, the oldest is closed (the home screen
  asks first). Without systemd scopes the process group gets SIGSTOP/SIGCONT
  instead. Frozen games keep their RAM and VRAM, which is why the limit is
  small; they survive the hub restarting and the PC sleeping, not a reboot.
- **Close**: "Close <game>" (and holding Guide, when set to close) stop the whole scope.
- **Window ownership**: `/proc/<pid>/cgroup` names the scope, so the app ID.

State shared between the hub and the overlay lives in
`$XDG_RUNTIME_DIR/hearth/state.json` (what's in front, what's running, whether
the menu is open), written under a file lock.

## Components

| Path | Role |
|---|---|
| `launcher/hearth/hub.py` | Main loop. Loads config, shows the home screen, runs the chosen app in its own scope, starts background apps, keeps the overlay running, shows an error if an app fails to start. |
| `launcher/hearth/overlay.py` | Quick Menu process: Guide gestures, open/close and pause, window tagging, controller-as-mouse for background apps. |
| `launcher/hearth/quickmenu.py` / `quickmenu_view.py` | Quick Menu contents and actions (tested without a display) / its drawing. |
| `launcher/hearth/audio.py` | Output/input devices, volumes and per-app streams via `pactl -f json` (PipeWire). |
| `launcher/hearth/gamescope.py` | X11 properties: `STEAM_GAME` tags, `GAMESCOPECTRL_BASELAYER_APPID` focus, overlay flags. |
| `launcher/hearth/session.py` | Shared state file, systemd scopes (spawn, freeze, thaw, stop), which app owns a PID. |
| `launcher/hearth/library.py` | Games from Steam (appmanifests, `localconfig.vdf` play times, Steam's artwork cache) and from `~/ROMs` with ES-DE's gamelists (names, favourites, play times, scraped artwork). Launch commands follow ES-DE's defaults for the installed emulators. Builds the Favorites (with `layout.py`: favourites and your tile order, kept in settings.json) and Continue rows, and the Library. |
| `launcher/hearth/emutune.py` | Recommended emulator settings for the PC and TV: edits only its own keys in configs the emulator already wrote, with a backup. |
| `launcher/hearth/settings_app.py` | The Settings app (the Settings tile, command `hearth:settings`): runs in the home screen's window; categories, options, on-screen keyboard, Wii Remote calibration; slow work in background threads. |
| `launcher/hearth/settings.py` | Settings made in the app, in `~/.config/hearth/settings.json`, layered over `apps.toml` (a bad file is ignored rather than breaking the home screen). The Quick Menu process notices changes and applies them at once. |
| `launcher/hearth/network.py` / `bluetooth.py` | Wi-Fi and connection status through NetworkManager (`nmcli`); pairing and connecting through `bluetoothctl`. |
| `launcher/hearth/wiimote.py` | Wii Remotes on a DolphinBar (mode 4), read directly over hidraw: IR camera setup, buttons, and the sensor bar's dots turned into a pointer. |
| `launcher/hearth/wiiinput.py` | Wii Remote → Quick Menu navigation, or keys and pointer (via XTest) for the app in front; Home tap/hold; hands the remotes to Dolphin while it runs. |
| `launcher/hearth/pointer.py` | Controller → virtual mouse/keyboard (uinput) for apps without a TV interface. |
| `launcher/hearth/updates.py` | OS version and staged updates (`rpm-ostree status`), running updates through `hearth-update`. |
| `launcher/hearth/ctl.py` | `hearthctl`: status, doctor, logs, update, rollback, enable/disable, dev mode. |
| `launcher/hearth/logs.py` | Log to the journal and `~/.local/state/hearth/hearth.log` (rotated); stack traces of hard crashes to `crash-*.txt`. |
| `launcher/hearth/events.py` | The event timeline (`~/.local/state/hearth/events.jsonl`): launches, exits and how they ended, time to first window, Quick Menu use, frame-rate summaries, crashes. |
| `launcher/hearth/report.py` | `hearthctl report` / Quick Menu → Report a problem: one `.tar.gz` with system details, logs, the timeline and a screenshot, with personal details masked. |
| `usr/libexec/hearth/hearth-update` | Root helper (narrow sudoers rule): run Bazzite's `uupd`, or `bootc rollback`. |
| `launcher/hearth/ui.py` | Rendering (tiles, rows, header, confirm dialog) and the intro and launch transitions. Sizes derived from screen height; above 1080p it draws at 1080p and SDL scales on the GPU. |
| `launcher/hearth/style.py` | The shared look: liveries, the bundled Barlow typeface (SIL Open Font License, `launcher/hearth/fonts/`), stripes, roundels, and frame-rate independent easing. |
| `launcher/hearth/model.py` | Navigation state (rows remember their column). No pygame, easy to test. |
| `launcher/hearth/input.py` | Keyboard / CEC / FLIRC / gamepad → `Nav` actions, stick auto-repeat. |
| `launcher/hearth/homebutton.py` | While an app runs, watches `/dev/input` (read-only) for Guide held 1.5s or `KEY_HOMEPAGE`, then closes the app. |
| `launcher/hearth/config.py` | `apps.toml` parsing and "is this app installed?" checks. |
| `usr/libexec/hearth/hearth-steam` | Runs Steam's console UI inside the current gamescope. |
| `usr/libexec/hearth/shims/steamos-session-select` | On `PATH` for apps started by Hearth. Turns an app's `steamos-session-select plasma` into "exit Steam → Hearth home" (older Steam clients). |
| `usr/libexec/hearth/hearth-twitch-update` + user timer, `hearth-twitch` | Installs/updates VacuumStream (the Twitch tile) in `~/Applications` from its GitHub releases, checked against the release's SHA256SUMS; the tile starts it as an X11 window. |
| `usr/libexec/hearth/hearth-run-game` | Starts a PC game from `~/Games` (found by `library.port_games`): from its own folder, making it executable if needed; AppImages unpack themselves if FUSE is missing. |
| `usr/libexec/hearth/hearth-steam`, `hearth-session` | Runs Steam. Steam's "Switch to Desktop" logs out; to come back, `hearth-steam` keeps `~/.local/state/hearth/steam-in-hearth` fresh while Steam runs (kept if the session stops it, removed if Steam closes itself), and the desktop's `hearth-desktop-guide` switches straight back to Game Mode if it finds it under a minute old (used once, so it can't loop). If SteamOS Manager's one-time desktop login file (`/etc/sddm.conf.d/zzt-steamos-temp-login.conf`) appears, it's cleared through the `hearth-session` root helper. The logout isn't blocked: an earlier version refused it, which hung Steam. |
| `usr/libexec/hearth/hearth-desktop` | Real Desktop Mode, via Bazzite's session switcher. |
| `usr/libexec/hearth/hearth-cec` + udev/systemd units | Pulse-Eight USB-CEC: register as a playback device, wake/standby the TV on resume/suspend/shutdown. |
| `usr/libexec/hearth/hearth-esde-update` + user timer | Installs/updates the ES-DE AppImage in `~/Applications` (checksum-verified) and creates `~/ROMs` and `~/BIOS`. |
| `usr/libexec/hearth/hearth-capture` | Full-screen, low-latency mpv view of an Elgato capture card, with its audio looped to the speakers via PipeWire. |
| `usr/libexec/hearth/hearth-flatpak-setup` | First-boot Flathub installs from `flatpaks.list` and `emulators.list`, and gives emulators access to `~/ROMs`, `~/BIOS` and other drives. Each app is attempted until it succeeds once, then never again (so uninstalling sticks). |

### Why Python + SDL2 for the home screen?

SDL2 has the best gamepad support on Linux (the same mappings Steam uses),
draws directly under gamescope with no desktop toolkit, and `python3-pygame`
is packaged in Fedora. The UI is small enough that a game-style immediate-mode
renderer is simpler than a widget toolkit.

### Why a hub loop, not app switching?

gamescope shows one app full-screen at a time, and TV users expect "close app →
home". Running apps one at a time from a loop gives exactly that, frees the GPU
and controllers for the app, and makes failures easy to report (the next home
screen shows what went wrong).

## Testing

- **Unit tests** (`launcher/tests/`): config parsing and layering, navigation,
  input mapping, audio (against recorded `pactl` output), Quick Menu logic,
  session state, updates, `hearthctl`.
- **X11 integration** (`test_x11.py`, needs Xvfb): gamescope window
  properties, and the real overlay opening with true transparency.
- **End to end** (`test_e2e.py`, needs Xvfb): the real hub and overlay with
  fake apps, driven by key presses and `hearthctl`: launch a game, open the
  Quick Menu over it, start Discord in the background, switch back, go home.
  Each step is checked through the properties gamescope reads.
  `HEARTH_E2E_SHOTS=dir` saves composited screenshots.

- **Real gamescope** (`tools/gamescope-lab/`, needs Docker): Hearth as the
  client of gamescope 3.16 in Steam mode, with real PipeWire, driven through a
  scripted session with 26 checks and recorded to video. It confirms that
  gamescope accepts and focuses Hearth's tagged windows, follows its
  front-app list between home, game and Discord, shows the Quick Menu overlay
  with input focus, and that audio switching, per-app volume, and Discord
  mute/deafen change the real PipeWire streams, that pointing at a tile and
  pressing A opens it (the path a Wii Remote's input takes), that the Settings
  app opens from its tile and a livery change reaches the home screen and the
  Quick Menu at once, and that a problem report captures the screen and
  gamescope's state.

What none of these cover is real GPU rendering, real controllers, and
pausing games (systemd scopes). That's the list below.

## Verify on real hardware

These couldn't be tested without a real machine. On the first real install
(Ryzen 7 5800X3D + RX 6750 XT): the image builds and boots into Hearth,
ES-DE and Dolphin run games, and the Wii Remote pointer works. Steam's
*Switch to Desktop* can still hang there (hold Guide for 4 s to get home;
root cause still open). The rest, in order:

1. **The image builds** against current `bazzite-deck:stable`. `image/build.sh`
   fails loudly if Bazzite's Game Mode session isn't one Hearth overrides.
2. **Hearth and its apps appear in Game Mode.** Verified in real gamescope
   3.16 (Steam mode) in the lab. Confirm on the real GPU, and with Bazzite's
   gamescope build, that the home screen, Kodi, ES-DE and Discord each come to
   the front.
3. **Steam from the tile** behaves like normal Game Mode: Quick Access menu,
   performance overlay, sleep, game launching.
4. **Steam → Switch to Desktop** never hangs and lands back in Hearth: the
   session logs out, the desktop starts, and `hearth-desktop-guide` finds
   `hearth-steam`'s fresh marker (`~/.local/state/hearth/steam-in-hearth`) and
   switches straight back to Game Mode (journal: "came from Steam's Switch to
   Desktop"). Hearth's own Desktop Mode tile clears the marker first. If Steam
   hangs anyway, holding Guide for 4 s (hub's `ESCAPE_HOLD_SECONDS`) stops
   Steam's scope and returns home.
5. **Hold Guide** closes VacuumTube/Kodi/ES-DE and returns home. The session user
   needs read access to controller event devices. logind normally grants this
   to the active seat, but confirm it.
6. **CEC**: TV remote keys arrive as arrow/Enter keys. Bazzite also runs
   steamos-manager's CEC service, so check the two don't conflict over `/dev/cec0`.
7. **Remote in each app**: VacuumTube, Jellyfin (`--tv`) and Plex HTPC respond
   to the TV remote's keys (via CEC/FLIRC), not just a controller.
8. **Emulation**: ES-DE starts full screen under gamescope, launches the
   Flatpak emulators, and they can read games from `~/ROMs`, including when it's
   a link to another drive.
9. **HDMI Input**: mpv shows the card at the configured resolution, and the
   audio loopback finds the card's input.
10. **Quick Menu**: tapping Guide shows it over a game, with the game visible
    through it; the game pauses (the user systemd manager can freeze scopes)
    and resumes; audio device switching and per-app volume work through
    `pactl`; closing a game from it returns home.
    **Quick Resume**: holding Guide in a game pauses it (`hearthctl status`
    lists it; `systemctl --user status hearth-app-*` shows the scope frozen)
    and picking its tile brings it back at the same spot, sound included.
11. **Wii Remotes** (DolphinBar in mode 4): `hearthctl doctor` finds the
    slots; a paired remote rumbles and lights its LED; the pointer tracks the
    screen the right way round (if not, Settings → Wii Remote → Calibrate the
    pointer fixes direction, speed and offset); keys reach Kodi and ES-DE;
    Dolphin gets the remotes while it runs and Hearth takes them back after.
12. **Discord**: starts in the background, comes to the front from the menu,
    the controller moves a pointer there (needs write access to
    `/dev/uinput`), and mute/deafen affect its call.
13. **Settings → Network**: the Wi-Fi list fills in, and connecting with a
    password works without a password prompt from NetworkManager (it allows
    the active local session by default). **Settings → Bluetooth**: a
    controller in pairing mode shows up in a search and pairs.
14. **Android tile** appears after `ujust setup-waydroid` (it looks for
   `/var/lib/waydroid/waydroid.cfg`) and Bazzite's `waydroid-launcher` displays
   under Hearth's gamescope session.

## Ideas / roadmap

- Real artwork: tile icons from each app's Flatpak metadata or SteamGridDB.
- Settings tile: Wi-Fi, Bluetooth controller pairing, display/audio output, all
  with a controller.
- "Continue playing" row: recent Steam games and recently played emulated games.
- Phone remote: small web page / Home Assistant integration to launch tiles, wake
  the TV, or show what's playing.
- Ambient mode: photo or clock screensaver after idle time on the home screen.
- Profiles: per-person home screens and parental controls.
- Syncthing tile or service for ROM, save and screenshot sync between devices.
