# Field tests: checking Hearth on the real PC

What the Claude Code session on the living-room PC (the "field session", see
CLAUDE.md) runs after each update, and how to report what it finds. It's in
tiers: tier 0 is safe any time; later tiers use the TV, so they need the
owner's go-ahead and, for some, their hands.

## Starting a run

The owner says something like "run the field tests for 0.23.0; I'm OK with
tiers 1 to 3; file as you go". Before tier 1:

1. `hearthctl status`: the version. Check out the matching code so what you
   read is what's running: `git checkout main && git pull` for a release,
   `git checkout staging && git pull` if `hearthctl channel` says staging.
2. `gh auth status` (else the owner runs `gh auth login`), and
   `gh issue list --label field-report --state open` to see what's still
   open from last time: those get re-checked (below), not re-filed.
3. **One session at a time.** Two sessions on the same run file the same
   problem twice.
4. Run inside tmux (`tmux new -A -s claude`) so a dropped SSH connection
   doesn't end the run.
5. Start a fresh session for a fresh run (`claude`). `claude --continue`
   reopens the most recent session, which may be last night's run; `claude
   --resume` lets you pick one by name. If a run is interrupted, resume it
   with `--resume` and pick today's.

The repo's `.claude/settings.json` pre-approves the read-only commands this
plan uses (hearthctl's checks, journalctl, xprop, gh issue...), so a run
doesn't stall on prompts once the owner has left; anything that changes the
PC still asks.

Throughout:

- **See the TV**: `hearthctl screenshot` saves what's on screen to
  `~/Pictures/Hearth/`; look at the PNG. Do this after every step that
  changes the screen: it's the evidence.
- **Press buttons**: `hearthctl press down down a` sends buttons to what's
  in front (up down left right a b x y view menu lb rb, plus `guide` and
  `home`). Wait a second or two, then screenshot.
- **Follow along**: `hearthctl events -n 30` shows what Hearth just did (app
  started, window appeared after N s, crashed...); `hearthctl logs -n 100`
  has the details.
- Before tier 1: `hearthctl events -n 1` and note the time, so the report can
  show everything that happened during the run.
- **Something never reached the screen?** `hearthctl windows` shows what
  gamescope sees on every display (:0 and the games' :1): its focus
  properties, each window with the app id tagged on it and who owns it,
  and a verdict for the app in front. Run it at 10 s and 60 s and put both
  in the report.

## Tier 0: automatic (any time, touches nothing)

```sh
hearthctl check
```

One report covering:
- the version and update state, and `hearthctl doctor`'s checks;
- failed services, with their logs;
- errors since boot and in Hearth's own log;
- crashed apps, and apps that started but never showed a window;
- home screen smoothness;
- memory, CPU, temperatures, disk, graphics;
- the network (and whether GitHub, ghcr.io and Flathub are reachable);
- controllers, input devices, the TV over CEC, audio;
- the game library and Watch next.

Anything marked ❌ or ⚠️ goes in the report with its evidence.

## Tier 1: the home screen (owner says OK; nobody watching anything)

| # | Do | Pass if |
|---|---|---|
| 1.1 | `hearthctl press home`, screenshot | Home screen, rows drawn, clock and network icon top right, no error message |
| 1.2 | `press right right down` then screenshot | Focus moved; backdrop changed to the focused tile |
| 1.3 | Leave it 1 minute, then `hearthctl footprint` | Hearth under 2% of a core, about 300 MB |
| 1.4 | `press view`, `press a` (types nothing yet), screenshot, `press b` | Search opens and closes |
| 1.5 | On a game tile: `press y`, screenshot, `press b` | Details card: platform, last played, play time |
| 1.6 | `press x` on a tile, screenshot, `press x` again | Favorites row appears, then goes |
| 1.7 | `press guide`, screenshot; `press rb` ×4 with a screenshot each; `press guide` | Quick Menu: Audio, Mixer, Discord, Stats (numbers, not "?"), System; closes |
| 1.8 | Open Settings (the tile), step through each category with screenshots, `press b` out | Every page draws; nothing says "Failed" |
| 1.9 | Settings → Privacy | TV make shown (with a CEC adapter) and steps listed |
| 1.10 | Settings → Family: don't change it; screenshot | Asks for a PIN, or offers to set one |
| 1.11 | Captures tile (if there): open, `press right`, `press b` | Gallery, full view, back |

## Re-checking last time's reports (with the owner's OK for the tiers involved)

For every open issue labelled `field-report`, read its last comment from the
cloud session: it names the version with the fix and how to check it. Do
that check on this version, then **comment on the issue** (don't file a new
one):

- `Verified on <version>: <one line of evidence>` (the cloud session closes it), or
- `Still happening on <version>:` with the evidence the issue asked for.

An issue that says it needs more data (for example a Steam game that stayed
on Steam's spinner, or a controller whose buttons need reading) is a step in
this run: gather what it asks for and comment with it.

## New in this version (owner OK)

Read the top entry of CHANGELOG.md and try each item, one line per item in
the run's report. Things to know:

- **Casting** (0.24.0): `hearthctl check` → Network says whether the AirPlay
  and Spotify receivers run, avahi is up and an H.264 decoder exists;
  `hearthctl status` shows "Casting: …" while a phone's picture is on screen.
  Trying it needs the owner's phone (tier 3): AirPlay a video and a photo,
  mirror the screen, then stop on the phone (Hearth should go back by
  itself); cast while a game runs; hold Guide during a cast; Quick Menu →
  System → Stop casting. Spotify: pick the PC in the Spotify app (Premium),
  check the Quick Menu's Now playing and volume. YouTube: link with the TV
  code, then cast from the phone with the tile open. Screenshot each.
- **Phone remote** (0.24.0): `hearthctl status` prints the address and code
  (so does Settings → Phone remote, with a QR code). From any phone on the
  Wi-Fi: open the address, type the code, then try every button and type into
  Search and into a Wi-Fi password box. `hearthctl type "text"` uses the same
  path from SSH. Five wrong codes should make a new one.
- **Photos in the screen saver**: put a few JPEGs from a phone (some taken
  sideways) in `~/Pictures/<folder>` (or plug in a USB stick with a DCIM
  folder), choose *Your photos* or *Games and photos* in Settings → Home
  screen, set the saver to 5 minutes, wait: upright pictures, the folder
  name as the caption, the time drifting.
- **Accessibility**: Settings → Accessibility → text size *Larger* and
  *High contrast*: screenshot the home screen, the Quick Menu and Settings;
  nothing should overlap or run off the screen. With People set up, check a
  second person keeps the standard look.

- **People** (Settings → People): adding a second person makes the owner the
  admin and Hearth starts on "Who's playing?". Test with the owner present:
  add a person, set their PIN, pick them on the picker, check Steam signs in
  to the right account (needs two Steam accounts), check the Switch person
  tile, then remove the test person. Their files come back to one-person
  mode.
- **Erasing a drive asks for the password**: only on a spare USB stick the
  owner plugs in for it, with the owner typing. Try a wrong password first
  (nothing should happen), then the right one.
- **Game art**: `hearthctl art` fetches pictures for emulated games without
  one; count found, and check a few tiles afterwards.
- **Emblems**: the System row's tiles have drawings; screenshot them.

## Tier 2: apps and games (owner OK; one at a time)

For **each tile** in Play and Watch, and for one game each from the Library
(a Steam game, an emulated game, a PC port in ~/Games, an Epic/GOG game if
any):

1. Open it (navigate and `press a`, or ask the owner).
2. After 10 s and 30 s: screenshot. **Pass**: the app itself is on screen,
   not Hearth's "Starting…" view. **If not**: `hearthctl events -n 20`,
   `hearthctl status`, and while it's stuck find its process (`ps -ef`) and
   check whether it's connected over Wayland or X11:
   `ls -l /proc/<pid>/fd | grep -iE 'wayland|X11'`.
3. `press guide`: the Quick Menu opens over it (screenshot); `press guide`
   again closes it.
4. Ask the owner to hold Guide: back home, and for games the Quick Resume
   row shows it (screenshot). Pick it again: it carries on.
5. Close it (Quick Menu → System → Close): it's gone from `hearthctl status`.

Streaming apps: play 30 seconds of something; sound and picture, and Quick
Menu → Audio shows it under "now playing". Store tiles (EA, Ubisoft,
Battle.net): the Lutris installer or the app opens; no need to install.

**A Steam game from its tile** (Steam not running first, then again with
Steam already running): after 30 s and 2 min, `hearthctl windows`, and note
whether the TV shows Steam's spinner ("B: Abort game") or the game. When it
ends, the home screen should come back within 5 s. If the game stays on the
spinner, also save `~/.local/share/Steam/logs/console-linux.txt` and the
game's Proton log (`PROTON_LOG=1` set in the game's launch options in
Steam, then `~/steam-<appid>.log`) and attach the last 100 lines of each.

## Tier 3: hardware (owner's hands)

| # | Do | Pass if |
|---|---|---|
| 3.1 | Each controller: `hearthctl buttons`, owner presses A, B, Guide | Every button reported; Guide tap opens the Quick Menu in Game Mode |
| 3.1b | A controller `hearthctl doctor` says has no Guide button (GuliKit and the like): `hearthctl buttons`, owner presses Home, Select, Start, and says which mode the pad is in (its switch or button combination) | The codes each one sends go in the report (`hearthctl buttons` prints them), so Hearth can be taught the pad |
| 3.2 | Controller batteries | Shown by the clock; `hearthctl check` lists them |
| 3.3 | Wii Remote on the DolphinBar | Pointer moves over tiles; A opens; `hearthctl doctor` says mode 4 |
| 3.4 | TV remote (CEC) | Arrows and OK drive the home screen |
| 3.5 | TV on another input, owner presses Guide | TV switches to Hearth (CEC adapter only) |
| 3.6 | Quick Menu → System → Sleep; wake with the controller | PC sleeps (TV to standby with CEC), wakes to the home screen, controller works |
| 3.7 | A game running, 5 minutes: Quick Menu → Stats, `hearthctl footprint` | Temperatures below the "slowing down" warning; Hearth under 2% while the game runs |

## Tier 4: system (only when asked)

- **Updates**: `hearthctl update` when one is due: output ends with
  "ready: restart to finish" or "already up to date"; never a lock error.
- **Desktop Mode round trip**: Settings → Desktop Mode, then the **Hearth**
  icon on the desktop: lands on Hearth. Again with the **Steam Gaming Mode**
  icon: lands in Steam's interface; when Steam exits (Power → Exit), Game
  Mode comes back with Hearth, not Steam. Both icons are on the desktop
  (`~/Desktop`) after the first desktop login; Bazzite's own "Return to
  Gaming Mode" is still there and lands on Hearth too.
- Never roll back, reset settings, reformat drives or change the network
  without the owner asking.

## Reporting

One field report (a GitHub issue labelled `field-report`, see CLAUDE.md) per
run, titled "Field test <version> <date>":

1. The `hearthctl check` summary (its "Needs attention" list); attach the
   saved report with `--body-file` or as a second comment.
2. A table of every test run: number, pass/fail, one line of detail.
3. For each failure: what happened, the screenshot's description, the
   evidence (events, log lines, command output, `hearthctl windows` for
   anything that never showed), and the likely cause.
4. Anything odd that no test covered.
5. The steps that needed the owner and weren't done, so they can be next time.

A failure that's clearly separate (e.g. one app never shows its window) also
gets an issue of its own, so it can be fixed and closed separately. **Search
first**: `gh issue list --label field-report --state all --search "<words>"`;
if it's there already, comment on it instead. File as you go, not at the end.
