# Field tests: checking Hearth on the real PC

What the Claude Code session on the living-room PC (the "field session", see
CLAUDE.md) runs after each update, and how to report what it finds. It's in
tiers: tier 0 is safe any time; later tiers use the TV, so they need the
owner's go-ahead and, for some, their hands.

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

## Tier 3: hardware (owner's hands)

| # | Do | Pass if |
|---|---|---|
| 3.1 | Each controller: `hearthctl buttons`, owner presses A, B, Guide | Every button reported; Guide tap opens the Quick Menu in Game Mode |
| 3.2 | Controller batteries | Shown by the clock; `hearthctl check` lists them |
| 3.3 | Wii Remote on the DolphinBar | Pointer moves over tiles; A opens; `hearthctl doctor` says mode 4 |
| 3.4 | TV remote (CEC) | Arrows and OK drive the home screen |
| 3.5 | TV on another input, owner presses Guide | TV switches to Hearth (CEC adapter only) |
| 3.6 | Quick Menu → System → Sleep; wake with the controller | PC sleeps (TV to standby with CEC), wakes to the home screen, controller works |
| 3.7 | A game running, 5 minutes: Quick Menu → Stats, `hearthctl footprint` | Temperatures below the "slowing down" warning; Hearth under 2% while the game runs |

## Tier 4: system (only when asked)

- **Updates**: `hearthctl update` when one is due: output ends with
  "ready: restart to finish" or "already up to date"; never a lock error.
- **Desktop Mode round trip**: Settings → Desktop Mode, then back to Game Mode:
  lands on Hearth.
- Never roll back, reset settings, reformat drives or change the network
  without the owner asking.

## Reporting

One field report (a GitHub issue labelled `field-report`, see CLAUDE.md) per
run, titled "Field test <version> <date>":

1. The `hearthctl check` summary (its "Needs attention" list).
2. A table of every test run: number, pass/fail, one line of detail.
3. For each failure: what happened, the screenshot's description, the
   evidence (events, log lines, command output), and the likely cause.
4. Anything odd that no test covered.

A failure that's clearly separate (e.g. one app never shows its window) can
also get an issue of its own, so it can be fixed and closed separately.
