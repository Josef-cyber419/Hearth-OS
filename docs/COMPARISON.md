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
| **Status at a glance**: controller batteries, network | PS5 and Xbox (controller battery in the corner), Switch (battery, Wi-Fi) | **Now**: controller battery levels next to the clock, highlighted when low, and the network: Wi-Fi bars, wired, or "offline". |
| **Pick up where you left off**, instantly | Xbox (Quick Resume), PS5 (cards), Google TV (Continue watching) | **Yes**: Quick Resume row (up to 3 paused games), Continue row of recently played games. |
| **A panel over whatever's playing** | PS5 Control Center, Xbox Guide, Switch Quick Settings, Steam QAM | **Yes**: Quick Menu (audio, per-app volume, Discord, power, updates, quit game), with mouse and tab-row navigation. |
| **One remote for everything** | Apple TV and Roku (HDMI-CEC), consoles (controller) | **Yes**: controller, TV remote over CEC, Wii Remote, keyboard. On-screen hints follow what you use. |
| **Looks after the TV** | Apple TV (aerial screen saver), LG (OLED care), all (sleep timers) | **Now**: an ambient screen saver of your games' art, slowly drifting and dimmed, with the time (or just the time), and sleep when idle. |
| **Universal search** across apps and games | Google TV, Apple TV, Roku, PS5 | **Now**: the View button (Share / −, or "/"), or the Search tile: type with the controller or a keyboard; every tile and every game, matched by words, initials or platform. |
| **Profiles**: each person's favourites, recents, avatar | Every console and TV | **Not yet**. Next: per-person favourites and Continue, chosen at start-up or from the Quick Menu. |
| **Game details page**: playtime, last played, actions | PS5 game hub, Xbox game page, Steam | **Now**: Y on a game shows its art, platform, last played, play time (Steam's own count, Hearth's for the rest) and times started, with Play, Favorite, Move and Remove from Continue. |
| **Groups/folders** of tiles | Xbox (Groups), Apple TV (folders) | **Not yet**. Rows play this part today; custom rows can be added in `apps.toml`. Next: make a row from the home screen. |
| **Sounds**: a soft click as you move, a chime on launch | PS5, Switch, Xbox | **Now**: optional (Settings → Home screen → Sounds): a soft tick as focus moves, chimes to open and go back. |
| **Notifications**: toast for "download done", "controller low" | Every console | **Now**: small notices over whatever's playing (without taking its input): controller battery low / very low, an app that just finished installing, an update ready. |
| **Now playing** controls for music and video | Apple TV, Google TV | **Now**: the Quick Menu's Audio tab leads with what's playing (any MPRIS app: VacuumTube, Twitch, Spotify, Kodi…): A plays/pauses, Left/Right skip. |
| **System monitor**: load, temperatures, throttling | Steam Deck (performance overlay), Xbox/PS5 (warnings only) | **Now**: Quick Menu → Stats: CPU and GPU load, temperatures (GPU hotspot too), clocks, power, memory and video memory, with a plain warning when a chip is at its limit or slowing down to cool off. |
| **Captures**: screenshots over any game, and a gallery | Xbox (Capture & share), PS5 (Create button), Switch (Album), Steam (screenshots, now in its screensaver too) | **Now**: Quick Menu → System → Take a screenshot (or `hearthctl screenshot`); a Captures tile to view and delete them; they show in the screen saver too. Next: a button shortcut, and short video clips. |
| **Notes after an update**: what's new | Switch (News), consoles and tvOS (release notes) | **Now**: once after each update, the home screen shows what that version brought; every version is in CHANGELOG.md and on GitHub's releases. |
| **Your phone as a remote**, with a keyboard | Google TV and Apple TV (phone remote apps with typing), Roku (app), Steam (Steam Link) | **Not yet**. Next: a page on the home network (a code on the TV to pair) with a d-pad and a keyboard for search and Wi-Fi passwords. |
| **Continue watching across apps** (a universal watchlist) | Google TV (some services), Apple TV (the TV app); Roku users have asked for years | **Now**: a Watch next row from Jellyfin, Plex and Kodi, with progress bars; it resumes on the spot and tells your server how far you got. |
| **Parental controls** that are simple | Switch (phone app), Xbox and PlayStation (family accounts, all different) | **Now**: Settings → Family: a daily game-time limit (films don't count), a bedtime, locked tiles, one PIN, no accounts. |
| **One touch play**: the TV follows the console | PS5, Xbox, Apple TV (over HDMI-CEC) | **Now**, with a CEC adapter: Guide switches the TV to Hearth, and waking retries until the TV answers. |
| **Every store in one place** | Nobody on PC: GOG Galaxy and Playnite try, on Windows | **Now**: Steam, Epic, GOG, Amazon, Battle.net, EA and Ubisoft games in one Library, Continue and Search. |
| **Game-sharing between systems** | Switch 2 (virtual game cards), PS5/Xbox (home console) | **Not planned**: Steam Family Sharing and Remote Play cover this for PC games. |
| **Premium streaming at full quality** | TVs and sticks (certified DRM) | **Can't** on any home-built PC (see STREAMING.md). YouTube (VacuumTube) and Twitch (VacuumStream) have TV-style apps; for Netflix and similar, a stick on another input. |

## Gaps the others leave (what people complain about)

Looked at in September 2026: what owners of smart TVs and consoles most often
complain about or ask for, and what Hearth does about it.

| Complaint | Hearth |
|---|---|
| **Ads on the home screen**: Google TV shows a sponsored row by default (May 2026), Hisense plays ads when you turn on or switch inputs, Samsung sells home-screen space, Roku pushes its own channel, PS5 owners objected to its news feed | None, ever: no ads, no sponsored tiles, nothing sent about what you watch or play. |
| **The TV watches what's on screen** (automatic content recognition), even from HDMI, and sells it | Settings → Privacy: detects the TV's make over HDMI-CEC and shows where to turn it off. |
| **Smart TVs get slower every year** | Nothing runs in the background that you didn't start; Hearth idles under 2% of one core ([PERFORMANCE.md](PERFORMANCE.md)); every update can be rolled back. |
| **No watchlist across apps** | Watch next, from Jellyfin, Plex and Kodi. |
| **Too many PC launchers** | One Library for all of them. |
| **Parental controls are confusing, and different on every device** | One page, one PIN, three rules. |
| **The TV stays on the wrong input** (CEC is unreliable) | Keeps asking until the TV answers, and Guide brings it back. |
| **Folders and themes** (Switch owners, since 2017) | Liveries today; folders when wanted. |

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

## Next

Done: search, game details, notices, UI sounds, the ambient screen saver,
now-playing controls, a system monitor, captures, what's new after updates,
the network by the clock, Watch next, Family limits, the TV privacy check,
one touch play, and every PC store in one Library. Next up: **your phone as
a remote** (with a keyboard). Still to come, when wanted: **profiles** and
**groups/folders** of tiles.

Looked at in September 2026: Steam's September update (Big Art Mode, a
screensaver of game art and screenshots, a default-to-desktop switch), tvOS 26
(Liquid Glass, profiles shown automatically), Switch 2 (GameChat, virtual game
cards), Google TV's 2026 plans, and owners' complaints about smart-TV ads and
tracking, console parental controls, CEC input switching and PC launchers.
