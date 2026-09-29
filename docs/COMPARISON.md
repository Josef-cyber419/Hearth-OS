# Hearth next to smart TVs and consoles

What the home screens people use every day do well, whether Hearth does it,
and what's worth borrowing next. Compared with: Google TV, Apple TV (tvOS),
Roku, LG webOS / Samsung Tizen, Xbox, PlayStation 5, Nintendo Switch and
Steam's Big Picture / Game Mode.

## What they do better, and where Hearth stands

| Idea | Who does it best | Hearth |
|---|---|---|
| **Your favourites up top**, in your order | Google TV (favourite apps row), Apple TV (top row + Top Shelf), Roku (move channels), Xbox (Pins) | **Now**: press **X** on any tile (app or game) to star it; a **Favorites** row sits at the top. |
| **Rearrange tiles** where they are | Apple TV (hold to jiggle, then move), Roku (Move channel), Xbox (Move pin) | **Now**: **Y → Move**, then Left/Right, A to keep, B to put it back. Remembered per row; Settings → Home screen resets it. |
| **The screen reacts to what you're on**: backdrop art, colour | PS5 (full-screen game art), Xbox (game art behind the dashboard), Google TV (big featured banner) | **Now**: the background glows with the focused game's art (blurred) or the app's colour, fading across as you move. |
| **Status at a glance**: controller batteries, network | PS5 and Xbox (controller battery in the corner), Switch (battery, Wi-Fi) | **Now**: controller battery levels next to the clock, highlighted when low. Wi-Fi strength: next. |
| **Pick up where you left off**, instantly | Xbox (Quick Resume), PS5 (cards), Google TV (Continue watching) | **Yes**: Quick Resume row (up to 3 paused games), Continue row of recently played games. |
| **A panel over whatever's playing** | PS5 Control Center, Xbox Guide, Switch Quick Settings, Steam QAM | **Yes**: Quick Menu (audio, per-app volume, Discord, power, updates, quit game), with mouse and tab-row navigation. |
| **One remote for everything** | Apple TV and Roku (HDMI-CEC), consoles (controller) | **Yes**: controller, TV remote over CEC, Wii Remote, keyboard. On-screen hints follow what you use. |
| **Looks after the TV** | Apple TV (aerial screen saver), LG (OLED care), all (sleep timers) | **Partly**: dark drifting-clock screen saver, sleep when idle. Next: an ambient mode with your games' art. |
| **Universal search** across apps and games | Google TV, Apple TV, Roku, PS5 | **Not yet**. Hearth has the pieces (on-screen keyboard, the game library): a Search tile over games and apps is a good next step. |
| **Profiles**: each person's favourites, recents, avatar | Every console and TV | **Not yet**. Next: per-person favourites and Continue, chosen at start-up or from the Quick Menu. |
| **Game details page**: playtime, last played, actions | PS5 game hub, Xbox game page, Steam | **Not yet**. Next: Y → *Details* with playtime, last played, "Remove from Continue", "Open in ES-DE". |
| **Groups/folders** of tiles | Xbox (Groups), Apple TV (folders) | **Not yet**. Rows play this part today; custom rows can be added in `apps.toml`. Next: make a row from the home screen. |
| **Sounds**: a soft click as you move, a chime on launch | PS5, Switch, Xbox | **Not yet**. Next: optional UI sounds (off by default, one switch in Settings). |
| **Notifications**: toast for "download done", "controller low" | Every console | **Partly**: update-ready badge. Next: a small toast for low controller battery and finished installs. |
| **Now playing** controls for music and video | Apple TV, Google TV | **Partly**: per-app volume in the Quick Menu. Next: play/pause/skip for what's playing (MPRIS). |
| **Premium streaming at full quality** | TVs and sticks (certified DRM) | **Can't** on any home-built PC (see STREAMING.md). YouTube (VacuumTube) and Twitch (VacuumStream) have TV-style apps; for Netflix and similar, a stick on another input. |

## Where Hearth is already ahead

- **Emulation built in**: every console from NES to Switch and PS3 through
  ES-DE, standalone emulators set up and tuned for your TV, and real Wii
  Remotes as a pointer. No TV or console does this.
- **Your Steam and emulated games side by side**: one Library, one Continue
  row, one Favorites row, across Steam, ES-DE and PC ports in `~/Games`.
- **No ads, no sponsored tiles, no tracking.** Google TV, Roku, webOS and
  Tizen all fill their home screens with promoted content.
- **Everything can be changed** and nothing is locked: rows, tiles, colours
  (liveries), and it's all plain files you can back up.
- **Rolls back**: every update can be undone, and problem reports are one
  button.

## Next, in order of what you'd notice most

1. **Search**: one tile, type or pick letters with the controller, results
   from games and apps.
2. **Game details** (Y on a game): playtime, last played, quick actions.
3. **Low-battery and "install finished" toasts.**
4. **Optional UI sounds.**
5. **Ambient screen saver** with slowly panning game art.
6. **Profiles.**
7. **Make a row from the home screen** (a folder of favourites).
8. **Now-playing controls** in the Quick Menu.
