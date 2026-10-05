# Changelog

Every release of Hearth OS, newest first. Versions are `0.MINOR.PATCH`
while Hearth is young: each set of changes merged into `main` is a new minor
version, and a fix on its own is a patch. The version shows in Settings →
System and `hearthctl status`. Each one is tagged (`v0.20.0`) and published as
a GitHub release and as an image tag (`ghcr.io/<owner>/hearth-os:0.20.0`).

## 0.24.0 (2026-10-03)

- **Cast from your phone**: the PC shows up on your Wi-Fi as a screen and a
  speaker. AirPlay from an iPhone, iPad or Mac (a video, photos, music or
  the whole screen: it comes to the front, and goes away when you stop),
  Spotify Connect (pick the PC in the Spotify app; Premium), and YouTube
  with a TV code. Settings → Casting names it and turns each part on or
  off; Quick Menu → System → Stop casting drops the phone.
- **Your phone as a remote**: Settings → Phone remote shows a code and a QR
  code; the page (nothing to install) has a d-pad, the buttons and a
  keyboard, so Wi-Fi passwords, searches and sign-ins are typed on the phone.
  `hearthctl type` types from a terminal the same way.
- **Your photos in the screen saver**: a folder, or a plugged-in drive's
  pictures, on their own or mixed with your games' art, the right way up
  (Settings → Home screen).
- **Accessibility**: Settings → Accessibility: larger text (two sizes) and a
  high-contrast look, each person's own.
- **A new livery, Girth OS**: wider by design. Settings → Appearance; the
  header says so, and the tiles really are wider.
- **Two icons on the desktop**: **Hearth** goes back to the TV, and **Steam
  Gaming Mode** starts Game Mode with Steam's own interface for that one
  session (Hearth is back the next time). Bazzite's "Return to Gaming Mode"
  stays and lands on Hearth too.
- **Fixes from the third field run**: the system drive can no longer be
  offered for erasing when lsblk lists partitions flat (util-linux 2.41);
  spotifyd installs again (its checksum file is named after the build), and
  Settings says so when the install failed; `hearthctl type` and the phone
  keyboard no longer drop doubled letters; Home from the Quick Menu over
  Kodi or Heroic closes the menu at once; Search's delete hint names
  Backspace with a keyboard; long names are cut or wrapped instead of drawn
  under switches, values and percentages, also at the larger text sizes;
  arrows the font hasn't got draw as chevrons; a controller whose battery
  level is unknown no longer shows an empty outline.

## 0.23.0 (2026-10-01)

- **Pictures on the tiles**: Settings is a gearbox, Sleep a moon, Restart a
  lap of a circuit, Power Off an engine start button, and so on. Apps from
  Flathub show their own icon.
- **Fixes from the first field tests on the PC**:
  - Steam: when a game started from its tile ends, Steam closes and you're
    back home, instead of stuck in Steam's menus. Holding a controller's
    Home button works on pads that send it as a Menu key (GuliKit).
  - PC ports (AppImages in ~/Games, like Dusklight) now show up instead of
    staying on "Starting…", and close cleanly instead of crashing.
  - The Quick Menu no longer freezes or crashes when audio stops answering
    (after a trip to Desktop Mode).
  - Restart and Power Off warn while an update is still downloading.
  - Wi-Fi shows its real signal on newer kernels.
  - Home (Quick Menu or `hearthctl home`) closes Settings, and `hearthctl
    status` says when Settings is open.
  - Lighter when idle: a Wii Remote lying still and the screen saver use a
    fraction of the processor they did.
  - More logs kept (up to 1 GB), so a crash can be looked into afterwards;
    updates write their progress to their own log.
  - `hearthctl check`, `press` and `screenshot` are more accurate, and
    `hearthctl windows` shows why an app hasn't reached the screen.
- **Fixes from the second field run** (on this version's first build):
  - Electron apps (VacuumTube, Twitch, Discord) close cleanly from the Quick
    Menu instead of crashing, and games that take a while to start get a
    "taking a while to start" note with how to get back home.
  - Settings' sidebar fits every category on the screen; a game picture
    saved as a palette PNG no longer makes the home screen crash.
  - Game art tries again a few minutes after a boot without network,
    instead of waiting six hours; Wi-Fi checks no longer stall the screen.
  - `hearthctl screenshot` can't hand back the previous picture, and
    `hearthctl press` reaches a game on gamescope's second display.
- **People**: add everyone in the household (Settings → People). Hearth
  then starts on "Who's playing?", with an optional 4-digit PIN each. Each
  person has their own favorites, Continue row, play times, Steam account
  and Discord; ROMs, apps and installed games are shared. An admin sets each
  person's game time, bedtime and locked tiles, and only an admin opens
  Settings and Desktop Mode. With one person, nothing changes. "Who's
  playing?" comes back after the PC has slept, and from Quick Menu → System
  → Switch person; each person can have their own colour scheme.
- **Erasing a drive asks for your password** (Settings → Storage), the
  one Desktop Mode and `sudo` use. Using a drive as it is doesn't.
- **Game art finds itself**: emulated games without a picture get one from
  libretro's free thumbnail library, in the background. `hearthctl art`
  fetches them now; off in Settings → Home screen.
- **GitHub's `gh` command and `tmux` are built in**, so Claude Code on the
  PC can file field reports, and keeps working if the SSH connection drops
  (`tmux new -A -s claude`).

## 0.22.4 (2026-09-30)

- **`hearthctl check`**: every safe check in one report: setup, failed
  services and errors, apps that crashed or never showed their window, how
  smooth the home screen is, memory, temperatures, disk, network, devices
  and the library. Saved in `~/.local/state/hearth/checks/`.
- **`hearthctl press`** sends buttons to what's on the TV, and `hearthctl
  screenshot` now works over SSH too, for testing from another computer.
  The test plan is in docs/FIELD_TESTS.md.

## 0.22.3 (2026-09-30)

- **PC ports show up**: a game from `~/Games` (like the Dusklight port) could
  run with sound but stay behind the "Starting…" screen, because it opened a
  Wayland window Hearth can't bring to the front. PC ports are now always
  started on X11, whatever library they use for their window.

## 0.22.2 (2026-09-30)

- **One update at a time**: starting an update while one is already
  downloading (Bazzite's automatic one, or an earlier press) now says
  "already downloading" and waits for it, instead of failing on its lock and
  reporting "update failed". And while one downloads, Hearth no longer says
  the PC is up to date.
- **ES-DE's update check** no longer fails when the network is busy or
  GitLab can't be reached; the installed ES-DE is kept.

## 0.22.1 (2026-09-30)

- **A failed update says why**: `hearthctl update` shows the updater's output
  as it runs, and Settings → System → Check for updates writes it to
  `hearthctl logs`, instead of throwing it away.

## 0.22.0 (2026-09-29)

- **Watch next**: films and episodes you're partway through on Jellyfin, Plex
  and Kodi, in a row with progress bars; pick one to carry on where you
  stopped. Connect in Settings → Home screen with a code on your phone.
- **Family**: a daily game-time limit, a bedtime and locked tiles, with a PIN
  (Settings → Family). Films and TV apps don't count.
- **EA app and Ubisoft Connect** tiles; their games join the Library.
- **Privacy**: Settings → Privacy shows how to turn off your TV's own
  tracking, for its make.
- **The TV follows you**: pressing Guide switches the TV to Hearth, and waking
  keeps trying until the TV answers (with a CEC adapter).
- **Lighter**: an idle home screen stops redrawing and keeps less in memory;
  all of Hearth idles under 2% of one core. `hearthctl footprint` shows what's
  using the PC.

## 0.21.0 (2026-09-29)

- **Captures**: take a screenshot of whatever's playing from the Quick Menu
  (System → Take a screenshot) or with `hearthctl screenshot`. A Captures tile
  shows them all: view one full screen, flip through, delete ones you don't
  want. They're kept in your Pictures folder, named after the game.
- **Your screenshots in the screen saver**, mixed in with your games' art.
- **What's new**: after an update, the home screen shows once what the new
  version brought (like this).
- **Network by the clock**: Wi-Fi signal bars, a plug when wired, or
  "offline" when there's no connection.
- **A simpler install guide** and a **hardware compatibility** list: AMD and
  Intel graphics are supported; NVIDIA is left for later.
- **A progress report for every version**, with lines of code, tests and
  what's working, in `reports/`.

## 0.20.0 (2026-09-29)

- **Epic Games and Battle.net**: an Epic Games tile (Heroic, also GOG and
  Amazon) and a Battle.net tile (Lutris: installs Battle.net the first time,
  then starts it). Their installed games join the Library, Continue and Search
  and start directly.
- **Settings → Network**: a static IP address (address, subnet, router,
  checked before applying) and DNS servers (automatic, Cloudflare, Google,
  Quad9 or your own). Choosing only picks; Apply reconnects.
- **Settings → Audio**: where sound plays and which microphone is used for
  every app, volumes, mic mute, and a test sound.
- Versions: this changelog, a version number in Settings and `hearthctl`,
  and a tag and GitHub release for every version, back to 0.1.0.

## 0.19.0 (2026-09-29)

- **Settings → Storage**: set up drives added after install. Erase and format
  one (with a second press that names the drive), or use one that's already
  formatted for Linux. Put Steam games on it (a Steam library folder) and your
  ROMs (moved with progress; ES-DE finds them as before). Never touches the
  drive the system runs from.

## 0.18.0 (2026-09-29)

- **Live and staging**: `main` is what's released (`:latest`), and `staging`
  is for trying new work first (`:staging`, mirroring `main` for now).
  `hearthctl channel` shows or switches which one a PC follows.
- Docs brought up to date (project status on real hardware, update channels).

## 0.17.0 (2026-09-29)

- **Search**: the View button (Share, −, or "/") or the Search tile finds any
  app or game as you type.
- **Game details**: Y on a game shows play time, last played and times started.
- **Quick Menu → Stats**: CPU and GPU load, temperatures, clocks and power, with
  a plain warning when the PC is running hot or slowing down.
- **Now playing** controls in the Quick Menu's Audio tab; **notices** over games
  (low controller battery, app installed, update ready); optional **UI
  sounds**; an **ambient screen saver** of your games' art.

## 0.16.0 (2026-09-29)

- **Favorites row**: X stars any tile. **Move tiles** with Y → Move.
- The backdrop glows with the focused game's art or the app's colour;
  controller batteries show by the clock.
- A comparison with smart TVs and consoles, and what to build next.

## 0.15.0 (2026-09-29)

- **Twitch** tile through VacuumStream, controller-first, kept up to date and
  checksum-verified.

## 0.14.0 (2026-09-29)

- Fixes from the first reports on the TV: Discord stays open in the
  background (Flatpak scopes), the Wii Remote works again after Dolphin, the
  Quick Menu can be used with a mouse, and button hints follow the controller
  you last used.

## 0.13.0 (2026-09-29)

- The Quick Menu restarts itself if it crashes, and never leaves the
  controller blocked.

## 0.12.0 (2026-09-27)

- The Guide button keeps working when controllers disconnect and reconnect.
  `hearthctl buttons` shows live what Hearth sees.

## 0.11.0 (2026-09-27)

- PC games: a disc image in the game's folder is passed to the port
  (Dusklight, the Twilight Princess port).

## 0.10.0 (2026-09-27)

- Wii Remote pointer up/down fixed; controller stick dead zone setting; quit a
  game back to ES-DE from the Quick Menu; hold Guide 4 s to escape Steam; PC
  games and AppImages from `~/Games` get tiles.

## 0.9.0 (2026-09-27)

- Steam's "Switch to Desktop" never hangs and lands back in Hearth.

## 0.8.0 (2026-09-27)

- Wii Remote infrared pointer fix; the Windows key opens the Quick Menu; rest
  the pointer at the screen edge to scroll the home screen.

## 0.7.0 (2026-09-27)

- ES-DE: the emulator choice is written where ES-DE 3.4 reads it.

## 0.6.0 (2026-09-27)

- RetroArch's menu moved off the Guide button; hold Guide on the desktop to go
  back to Hearth.

## 0.5.0 (2026-09-27)

- Steam's "Switch to Desktop" returns to Hearth; ES-DE finds its emulators.

## 0.4.0 (2026-09-27)

- Fixed first-boot app installs.

## 0.3.0 (2026-09-27)

- **Quick Resume**: hold Guide to pause a game and pick it up later, where you
  left off.

## 0.2.0 (2026-09-27)

- The racing look (liveries), diagnostics and problem reports, Wii Remotes on
  a DolphinBar, the Settings app, the game library, and emulators tuned for
  the PC and TV.

## 0.1.0 (2026-09-25)

- The first build: a TV-style home screen on a custom Bazzite image, with
  Steam, emulation through ES-DE, remote-friendly streaming apps, an HDMI
  input tile, and the Quick Menu over games (audio, per-app volume, Discord,
  power). AMD/Intel graphics.
