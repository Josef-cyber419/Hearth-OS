# Updates, troubleshooting and recovery

Everything below is run from a terminal: Desktop Mode (System → Desktop Mode
→ Konsole), or over SSH from another computer (turn SSH on once with
`sudo systemctl enable --now sshd`).

## hearthctl

| Command | What it does |
|---|---|
| `hearthctl doctor` | Checks every part of the setup and says how to fix what's wrong: Game Mode hook, controllers, audio, apps and emulators, updates. **Start here.** |
| `hearthctl status` | What's running and in front, versions, whether an update is waiting. |
| `hearthctl report` | Saves everything needed to fix a problem in one file. See [Reporting a problem](#reporting-a-problem). |
| `hearthctl events` | The timeline of what happened: apps started and closed (and how), crashes, how long apps took to appear, how smooth the menus ran. |
| `hearthctl logs` / `logs -f` | The home screen's and Quick Menu's log (`-f` follows it live). |
| `hearthctl update` | Install OS and app updates now. Restart to finish. |
| `hearthctl rollback` | Go back to the previous OS version on the next restart. |
| `hearthctl menu` / `home` | Open the Quick Menu / close the current app, e.g. over SSH if a controller dies. |
| `hearthctl buttons` | Live view of the buttons Hearth acts on (Guide, a remote's Home/Menu, the Windows key): which devices have them, every press and release, and what Hearth makes of it (tap = Quick Menu, hold = home). Controllers that connect or wake while it runs show up. If Guide stops working, run it (over SSH, or in Desktop Mode) and press Guide: no line means the press never reaches Hearth. |
| `hearthctl wii-test` | Live view of each Wii Remote on the DolphinBar: the buttons Hearth reads, and how many sensor-bar dots its camera sees (2 when aimed at the TV). Run it in Desktop Mode. |
| `hearthctl emulation-setup` | Make ES-DE use Hearth's emulators and download missing RetroArch cores ("can't find emulator core"). |
| `hearthctl pause` | Go home and keep the game paused (Quick Resume). `hearthctl status` lists paused games. |
| `hearthctl disable` / `enable` | Make Game Mode start Steam directly / Hearth again. |
| `hearthctl dev PATH` / `dev --off` | Run the launcher from a source checkout (see below). |

## Updates

**Automatic.** Bazzite's updater (`uupd`) runs in the background. It downloads
new OS images (rebuilt daily by this repo's CI) and updates Flatpak apps.
ES-DE checks for updates weekly. An update is applied when you next restart;
the home screen shows **"Update ready: restart to finish"** when one is waiting.

**Manually:** Quick Menu → System → *Check for updates*, or `hearthctl update`.

**Changed your mind?** Every update keeps the previous version. Pick it in the
boot menu, or run `hearthctl rollback` and restart.

## Reporting a problem

When something goes wrong, save a report **right away**, while it's still
fresh in the logs:

- **From the couch:** Quick Menu → System → **Report a problem**. It includes
  a screenshot of what's on screen (with the menu over it).
- **From a terminal:** `hearthctl report`, or `hearthctl report --screenshot`
  in Game Mode.

It takes about half a minute and saves a file like
`hearth-report-20260925-2105.tar.gz` in the **hearth-reports** folder in your
home folder (the last 10 are kept). To send it: Desktop Mode → Dolphin →
Home → hearth-reports, and attach the file to a chat or an issue, with a line
on what happened and roughly when.

What's in it (`SUMMARY.txt` is the first page):

| Part | Why it helps |
|---|---|
| Hearth's log, event timeline and crash traces | What Hearth did, what failed, how long apps took to appear, frame rates of the home screen and Quick Menu, hard crashes inside SDL or drivers |
| This boot's session, warning and kernel logs; errors and the last lines from the **previous** boot | Game Mode, Steam and gamescope messages, GPU driver (amdgpu) errors, and what happened just before a freeze or forced restart |
| GPU load, clocks, temperature and power (sampled for 3 s); Vulkan and OpenGL drivers; connected screens and their modes | Performance and display problems |
| What gamescope is showing and every window it knows about | Black screens, the wrong app in front, the Quick Menu not appearing |
| Audio devices and streams; controllers, Bluetooth devices, capture cards | Sound, input and HDMI-in problems |
| OS version and updates, Flatpak apps, failed services, crash dumps list | Broken updates and apps |
| `hearthctl doctor` output, your `apps.toml` changes | The setup as Hearth sees it |

**Private details are masked**: your user name, the PC's name, IP and MAC
addresses (network and Bluetooth), and device serial numbers. It doesn't
collect passwords, browser data, Steam or Discord account files, or your
saves; logs can mention the names of apps and games you ran. Nothing is
uploaded: the file stays on the PC until you send it. Open it first if you
want to see exactly what's inside.

## When something's wrong

- **A tile is missing**: `hearthctl doctor` lists every hidden tile and why
  (usually an app still installing on first boot).
- **The home screen crashed**: it recovers by itself and shows the error. If
  it crashes 5 times within a minute, Game Mode falls back to Desktop Mode
  on its own. Check `hearthctl logs`.
- **The Quick Menu doesn't open**: `hearthctl doctor` checks the controller's
  Guide button is readable and the Quick Menu process is running.
- **No sound / wrong speaker**: Quick Menu → Audio → Output.
- **Need Steam without Hearth for a while**: `hearthctl disable`, restart.
  `hearthctl enable` brings Hearth back.
- **A bad OS update**: `hearthctl rollback` (or the boot menu), restart.

## Customising the home screen

**The easy way: the Settings tile** (System row). It covers the look, which
tiles show, controllers, Wii Remote, Bluetooth, Wi-Fi and system information,
all with a controller or remote. Its choices are saved in
`~/.config/hearth/settings.json` and win over `apps.toml`. Delete that file to
go back to the defaults.

**By hand:** your changes live in `~/.config/hearth/apps.toml` and are layered over the
defaults, so new default tiles still appear after updates. Only write what you
want to change:

```toml
hide = ["plex", "android"]        # remove default tiles

[theme]
livery = "martini"                # gulf, martini, brg, rosso or silver
motion = "reduced"                # no intro or launch zoom; menus move instantly

[quick_menu]
pause_game = false                # keep games running under the Quick Menu

[[rows]]
title = "Watch"                   # an existing row: change it
  [[rows.apps]]
  id = "kodi"                     # an existing tile: change only these fields
  color = "#0f6fa8"
  [[rows.apps]]
  id = "vlc"                      # a new tile
  name = "VLC"
  flatpak = "org.videolan.VLC"

[[rows]]
title = "Retro"                   # a new row (goes before System)
  [[rows.apps]]
  id = "retroarch"
  name = "RetroArch"
  flatpak = "org.libretro.RetroArch"
```

All tile options are listed at the top of `/usr/share/hearth/apps.toml`.
Changes show up the next time you return to the home screen. Add
`replace = true` to ignore the defaults entirely.

## Changing Hearth itself

Two ways, depending on how permanent the change is:

- **Try it on the TV now**: clone this repo on the PC, then
  `hearthctl dev ~/test-os-thing/launcher` and restart Game Mode. The home
  screen and Quick Menu run from your checkout. Edit, restart Game Mode to
  test, and `hearthctl dev --off` to go back.
- **Ship it**: push to `main`. CI runs the tests, builds the image, and the PC
  picks it up with its next automatic update.

Develop on any computer without the TV: see "Try the home screen" in the
README, and run `pytest` in `launcher/`. To see your change inside real
gamescope, with a recorded video, run `tools/gamescope-lab/run.sh` (needs
Docker; see its README).

For more detail in the log, set `HEARTH_LOG_LEVEL=debug` (e.g. in
`~/.config/environment.d/hearth.conf`). It records every Quick Menu input and
every audio change. The end-to-end test runs the real
home screen and Quick Menu on a virtual display (Xvfb) with fake apps; set
`HEARTH_E2E_SHOTS=/some/dir` to save screenshots of each step.
