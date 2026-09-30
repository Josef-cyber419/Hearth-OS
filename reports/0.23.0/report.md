# Hearth OS 0.23.0: progress report

_30 September 2026 · made by `tools/progress_report.py`_

Hearth OS turns a living-room PC into a TV-style home screen for Steam, emulation, streaming apps and Quick Resume, driven by a controller, a TV remote or a Wii Remote. It's built on Bazzite and installs as a system image that updates itself and can always be rolled back. It runs on AMD and Intel graphics; NVIDIA is left for later.

Tested on: Ryzen 7 5800X3D, Radeon RX 6750 XT, 24 GB, 256 GB SATA SSD, Xbox controller, Wii Remotes on a DolphinBar.

## At a glance

| | 0.23.0 | Change since 0.22.4 |
|---|--:|--:|
| Lines of code | 15,486 | +1 |
| Automated tests | 381 | – |
| Lines of docs | 1,800 | +27 |
| Guides in docs/ | 14 | – |
| Pull requests merged | 26 | |
| Versions released | 26 | |

Lines of code by part (blank lines not counted):

| Part | Lines |
|---|--:|
| Home screen, Quick Menu and settings (Python) | 12,941 |
| System image (scripts, services, config) | 1,163 |
| Build and tools | 1,382 |
| Tests | 5,368 |

## What's new in 0.23.0

- **GitHub's `gh` command is built in**, so Claude Code on the PC can file field reports without installing anything.

## What's working

| Area | What it does | Status |
|---|---|---|
| Home screen | TV-style rows, liveries, a backdrop from the focused game, controller batteries and network by the clock | ✅ Confirmed on the PC |
| Emulation | ES-DE with a tile per console; emulators tuned for the GPU and TV | ✅ Confirmed on the PC (Dolphin working) |
| Wii Remote | DolphinBar pointer on the home screen and as a mouse; handed to Dolphin for Wii games | ✅ Confirmed on the PC (pointer working) |
| Quick Resume | Hold Guide to pause a game and pick it up later (up to 3) | 🟡 Shipped |
| Quick Menu | Guide button panel: audio, per-app volume, Discord, stats, power, updates, screenshots | 🟡 Shipped |
| Streaming | YouTube (VacuumTube), Twitch (VacuumStream), Kodi, Jellyfin, Plex, Moonlight | 🟡 Shipped |
| Game stores | Epic Games (Heroic), Battle.net, EA app and Ubisoft Connect (Lutris) tiles; their games in the Library | 🟡 Shipped |
| Customising | Favorites with X, move tiles, hide tiles, liveries, sounds | 🟡 Shipped |
| Search and details | Search every app and game; Y on a game for play time and last played | 🟡 Shipped |
| Settings | Wi-Fi, static IP and DNS, Bluetooth, audio devices, storage (format and use a new drive) | 🟡 Shipped |
| Captures | Screenshots from the Quick Menu, a gallery tile, in the screen saver | 🟡 Shipped |
| Watch next | Shows and films in progress from Jellyfin, Plex and Kodi; resumes and reports back | 🟡 Shipped |
| Family | Daily game-time limit, bedtime and locked tiles behind a PIN | 🟡 Shipped |
| Privacy | No ads or tracking; a guide to turn off the TV's own tracking, by make | 🟡 Shipped |
| TV control (CEC) | TV on and to the right input on wake and on Guide; standby with the PC | 🟡 Shipped |
| Performance | Hearth idles under 2% of one core and about 300 MB; hearthctl footprint | 🟡 Shipped |
| Updates | Automatic, versioned, with releases on GitHub, a what's-new card and rollback | 🟡 Shipped |
| Phone as a remote | A web page with a d-pad and keyboard, paired with a code on the TV | ⚪ Not started |
| Profiles, folders | Per-person favorites; groups of tiles | ⚪ Not started (deferred for now) |
| NVIDIA graphics | A separate image with NVIDIA's driver | ⚪ Not started (deferred: AMD and Intel first) |
| Netflix and similar | DRM limits these to low quality on any home-built PC | ⛔ Not possible |

**Confirmed** means reported working on the real PC; **Shipped** means built, tested and released, but not yet reported on.

## Open issues

| Issue | Where it stands | What's needed |
|---|---|---|
| Steam "Switch to Desktop" can still hang | Holding Guide for 4 s always gets you home; the cause isn't known | hearthctl status and hearthctl logs right after it happens |
| Recent updates not yet tried on the PC | Built and tested in a virtual display | Update, then try the checklist in the release notes |

## Next

- Your phone as a remote, with a keyboard for search and Wi-Fi passwords.
- Fix what turns up on the real PC.
- When wanted: profiles and groups of tiles; NVIDIA support.

## Every version

| Version | Date | Lines of code | Tests | Docs (lines) | Guides | Pull requests |
|---|---|--:|--:|--:|--:|--:|
| 0.23.0 | 2026-09-30 | 15,486 | 381 | 1,800 | 14 | 26 |
| [0.22.4](../0.22.4/report.md) | 2026-09-30 | 15,485 | 381 | 1,773 | 14 | 26 |
| [0.22.2](../0.22.2/report.md) | 2026-09-30 | 15,066 | 374 | 1,556 | 13 | 26 |
| [0.22.1](../0.22.1/report.md) | 2026-09-30 | 15,008 | 370 | 1,548 | 13 | 25 |
| [0.22.0](../0.22.0/report.md) | 2026-09-29 | 15,005 | 369 | 1,544 | 13 | 24 |
| [0.21.0](../0.21.0/report.md) | 2026-09-29 | 13,506 | 334 | 1,371 | 11 | 23 |
| 0.20.0 | 2026-09-29 | 12,533 | 312 | 1,260 | 10 | 20 |
| 0.19.0 | 2026-09-29 | 11,984 | 291 | 1,120 | 9 | 19 |
| 0.18.0 | 2026-09-29 | 11,370 | 270 | 1,067 | 8 | 18 |
| [0.17.0](../0.17.0/report.pdf) | 2026-09-29 | 11,288 | 268 | 1,034 | 8 | 17 |
| 0.16.0 | 2026-09-29 | 10,159 | 233 | 1,022 | 8 | 16 |
| 0.15.0 | 2026-09-29 | 9,817 | 223 | 971 | 7 | 15 |
| 0.14.0 | 2026-09-29 | 9,741 | 218 | 969 | 7 | 14 |
| 0.13.0 | 2026-09-29 | 9,507 | 205 | 954 | 7 | 13 |
| 0.12.0 | 2026-09-27 | 9,474 | 201 | 954 | 7 | 12 |
| 0.11.0 | 2026-09-27 | 9,339 | 195 | 953 | 7 | 11 |
| 0.10.0 | 2026-09-27 | 9,326 | 194 | 940 | 7 | 10 |
| 0.9.0 | 2026-09-27 | 9,111 | 179 | 906 | 7 | 9 |
| 0.8.0 | 2026-09-27 | 9,072 | 173 | 904 | 7 | 8 |
| 0.7.0 | 2026-09-27 | 8,970 | 165 | 901 | 7 | 7 |
| 0.6.0 | 2026-09-27 | 8,931 | 163 | 901 | 7 | 6 |
| 0.5.0 | 2026-09-27 | 8,836 | 157 | 897 | 7 | 5 |
| 0.4.0 | 2026-09-27 | 8,598 | 144 | 888 | 7 | 4 |
| 0.3.0 | 2026-09-27 | 8,597 | 141 | 886 | 7 | 3 |
| 0.2.0 | 2026-09-27 | 8,336 | 132 | 865 | 7 | 2 |
| 0.1.0 | 2026-09-25 | 4,155 | 66 | 703 | 7 | 1 |
