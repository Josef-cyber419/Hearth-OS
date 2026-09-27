# Emulation

## What you'll see

The **Emulation** tile opens [ES-DE](https://es-de.org), a controller-driven
game menu:

1. **Console screen**: a row of console logos. **A console only appears once
   it has at least one game**, so the screen grows as you add games.
2. **Game list**: pick a console to see its games with box art, screenshots,
   descriptions and video previews (after you download artwork, below).
3. **Play**: pick a game and it opens in the right emulator automatically. Quit
   the game and you're back in the list.

Press B on the console screen to go back to the Hearth home screen.

## Adding games (in Desktop Mode)

The plan: use the desktop for maintenance, and the TV screen for playing.

1. On the Hearth home screen, choose **System → Desktop Mode**.
2. Open the file manager (Dolphin). Your home folder has:
   - `ROMs/`: one folder per console. On the first run ES-DE offers to
     create them all (*Create directories*). Or create them yourself with the
     names below.
   - `BIOS/`: BIOS, firmware and key files that some consoles need.
3. Copy games into the matching console folder, e.g. `ROMs/ps2/`,
   `ROMs/gc/`, `ROMs/switch/`.
4. Click **Return to Gaming Mode** on the desktop. The console appears in the
   Emulation menu.
5. **Artwork**: in ES-DE press Start → *Scraper*, create a free ScreenScraper
   account, and let it download box art and videos for everything.

**Games on a second drive?** Bazzite mounts extra drives under `/run/media`
or `/var/mnt`. Make a `ROMs` folder on the drive, then replace `~/ROMs` with a
link to it (in a terminal: `rm -r ~/ROMs && ln -s /var/mnt/games/ROMs ~/ROMs`,
with your drive's path). Emulators already have permission to read those
locations.

Only use games, BIOS files and keys you've dumped from hardware you own.

## Consoles, emulators and your hardware

The emulators are installed automatically on first boot (from
[`emulators.list`](../image/system_files/usr/share/hearth/emulators.list)). ES-DE
finds each one on its own, and Hearth makes ES-DE use the standalone emulators
it installed (Dolphin, PCSX2, DuckStation, PPSSPP, melonDS, Azahar, RMG, MAME)
rather than RetroArch cores, and downloads the RetroArch cores for the rest
(NES, SNES, Game Boy/Color/Advance, Genesis/Mega Drive/Master System, Dreamcast,
Saturn). If ES-DE ever says it can't find an emulator core, run
`hearthctl emulation-setup` in Desktop Mode. A different emulator chosen in
ES-DE (Other settings → Alternative emulators) is kept.

Performance is estimated for a **Ryzen 7 5800X3D** with an **RX 6750 XT** and
24 GB of RAM. That's strong for emulation: the X3D's large cache particularly
helps the PS3 and Switch emulators, and the graphics card upscales older
consoles to 4K.

| Console | Folder | Emulator | Needs from you | Expect |
|---|---|---|---|---|
| NES, SNES, Game Boy / Color / Advance | `nes`, `snes`, `gb`, `gbc`, `gba` | RetroArch | – | Perfect |
| Nintendo 64 | `n64` | Rosalie's Mupen GUI | – | Excellent, upscaled |
| GameCube / Wii | `gc`, `wii` | Dolphin | – | Excellent, 4K |
| Wii U | `wiiu` | Cemu | Keys for encrypted dumps | Very good |
| Nintendo DS | `nds` | melonDS | DS BIOS/firmware (optional) | Perfect |
| Nintendo 3DS | `n3ds` | Azahar | Decrypted games | Excellent |
| **Nintendo Switch** | `switch` | Eden | `prod.keys` + firmware from **your** Switch | Most games full speed at 1.5–2x resolution. The heaviest (e.g. Tears of the Kingdom) at 1x |
| PlayStation | `psx` | DuckStation | PS1 BIOS | Perfect, upscaled |
| PlayStation 2 | `ps2` | PCSX2 | PS2 BIOS | Excellent, 4K |
| PSP | `psp` | PPSSPP | – | Perfect |
| **PlayStation 3** | `ps3` | RPCS3 | PS3 firmware (free from Sony) | Most of the library full speed; a few very demanding games dip |
| PS Vita | `psvita` | Vita3K (manual, below) | Vita firmware | Good for supported games |
| **PlayStation 4** | `ps4` | shadPS4 | PS4 firmware modules | Experimental. A growing list of lighter games |
| Original Xbox | `xbox` | xemu | Xbox BIOS, MCPX boot ROM, HDD image | Good |
| **Xbox 360** | `xbox360` | Xenia (manual, below) | – | Experimental on Linux: some games great, many with glitches |
| Arcade | `arcade`, `mame` | MAME / RetroArch | Matching ROM sets | Excellent |
| Xbox One / Series, PS5, Switch 2 | – | No working emulators exist | – | Use the real console through the **HDMI Input** tile ([HARDWARE.md](HARDWARE.md#capture-card-play-real-consoles-through-hearth)) |

## Tuned for your PC

Hearth sets up the emulators for your hardware and TV, so games look sharp and
don't stutter the first time an effect appears. It happens automatically once
each emulator has run for the first time (it needs to create its own settings
file first), and you can re-apply it any time from **Settings → Emulation**,
where you also choose the target: *Auto* (your TV), 1080p, 1440p or 4K.

What it sets (only these; everything else stays yours, and the first change
keeps a `.hearth-backup` copy of the file):

| Emulator | Graphics | Resolution (1080p / 1440p / 4K TV) | Also |
|---|---|---|---|
| DuckStation (PS1) | Vulkan | 5x / 6x / 9x | PGXP geometry correction (no wobbly polygons), starts full screen |
| PCSX2 (PS2) | Vulkan | 3x / 4x / 5x | 16x texture filtering, multi-threaded VU (uses the extra cores), starts full screen |
| Dolphin (GameCube, Wii) | Vulkan | 3x / 3x / 5x | Asynchronous "ubershaders" (no shader stutter), 16x filtering, full screen |
| PPSSPP (PSP) | Vulkan | 4x / 6x / 8x | 16x filtering, full screen |
| RetroArch (retro consoles) | Vulkan | native (pixel-perfect) | Full screen, low-latency video |

For the rest, set these once in each emulator (Desktop Mode, or from ES-DE):

| Emulator | Recommended on a 5800X3D + RX 6750 XT |
|---|---|
| **RPCS3** (PS3) | Renderer Vulkan (default). Resolution scale 150% (200% for lighter games). Keep SPU decoder *Recompiler (LLVM)* and *Async with Shader Interpreter* shaders, both defaults. |
| **Eden** (Switch) | Vulkan, Docked mode, Resolution 2x (1.5x or 1x for the heaviest games), *Use asynchronous shader building* on, ASTC decoding on the GPU. |
| **Cemu** (Wii U) | Vulkan, *Async shader compile* on, VSync *Match screen refresh rate*. Resolution through Graphic Packs: each game's *Resolution* pack at 1440p (4K is fine for most). |
| **Azahar** (3DS) | Vulkan, internal resolution 5x (1440p) or 6x, *Async shader compilation* on, screen layout *Large screen* or *Side by side* for a TV. |
| **xemu** (Xbox) | Vulkan, render scale 3x (4x for 4K). |

### The Wii U GamePad screen

Wii U games expect a second screen in your hands. Hearth shows one window at
a time, so use Cemu's single-screen view: map a controller button to
*Toggle GamePad view* in Cemu's input settings. When a game needs touch, the
GamePad view accepts a mouse click as a tap, so a Wii Remote in mouse mode
(Quick Menu → System → *Wii Remote pointer as mouse*) lets you point and tap
the GamePad screen on your TV.

A real Wii U GamePad can't practically be used with a PC: the projects that
pair one (drc-sim, pc2drc) are unmaintained or archived, need a real Wii U to
pair, a specific rt2800usb 5 GHz USB Wi-Fi adapter, and kernel patches that an
immutable, auto-updating OS like this one can't keep applied.

### Not installed automatically

These have no Flathub package. Download the AppImage in Desktop Mode, put it
in `~/Applications/`, and ES-DE finds it:
- **Vita3K** (PS Vita): `Vita3K-x86_64.AppImage` from vita3k.org.
- **Xenia Canary / Xenia Edge** (Xbox 360): see ES-DE's user guide for its
  Linux options. It currently runs best through Proton.

## One-time setup per emulator

Do this once in Desktop Mode, from the app menu:
- **Controllers**: most emulators pick up an Xbox-style controller
  automatically. Dolphin, Cemu, RPCS3 and Eden may need one mapping pass
  (Settings → Controllers).
- **BIOS / firmware / keys**: each emulator has a setting for where these
  live. Point it at the matching folder in `~/BIOS`.
- **RetroArch's own menu** (save states, shaders, core options): click **both
  sticks** (L3 + R3). Guide stays Hearth's (tap: Quick Menu, hold: home), so
  Hearth moves RetroArch's menu off it.
- **Exit shortcut**: set a controller shortcut to quit the game back to ES-DE,
  e.g. Select + Start. RetroArch, PCSX2, DuckStation and Dolphin all support one.

**Holding the Guide button always gets you back to the Hearth home screen.** With
Quick Resume on (the default), the game is paused, not closed: it waits in the
Quick Resume row and carries on exactly where you were. If you've set holding
Guide to close instead (Settings → Controllers), it closes the emulator *and*
ES-DE without saving, so save in-game first or use the emulator's exit shortcut.

## Wii Remotes

With a Mayflash DolphinBar in mode 4, real Wii Remotes pair through the
DolphinBar itself. In Dolphin → Controllers, set each Wii Remote to *Real Wii
Remote*. See [HARDWARE.md](HARDWARE.md).
