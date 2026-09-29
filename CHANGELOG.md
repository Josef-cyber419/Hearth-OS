# Changelog

Every release of Hearth OS, newest first. Versions are `0.MINOR.PATCH`
while Hearth is young: each set of changes merged into `main` is a new minor
version, and a fix on its own is a patch. The version shows in Settings →
System and `hearthctl status`. Each one is tagged (`v0.20.0`) and published as
a GitHub release and as an image tag (`ghcr.io/<owner>/hearth-os:0.20.0`).

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
