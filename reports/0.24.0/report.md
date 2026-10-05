# Hearth OS 0.24.0: progress report

_3 October 2026 · made by `tools/progress_report.py`_

Hearth OS turns a living-room PC into a TV-style home screen for Steam, emulation, streaming apps and Quick Resume, driven by a controller, a TV remote or a Wii Remote. It's built on Bazzite and installs as a system image that updates itself and can always be rolled back. It runs on AMD and Intel graphics; NVIDIA is left for later.

Tested on: Ryzen 7 5800X3D, Radeon RX 6750 XT, 24 GB, 256 GB SATA SSD, Xbox controller, Wii Remotes on a DolphinBar.

## At a glance

| | 0.24.0 | Change since 0.23.0 |
|---|--:|--:|
| Lines of code | 18,808 | +1,547 |
| Automated tests | 517 | +59 |
| Lines of docs | 2,121 | +142 |
| Guides in docs/ | 16 | +1 |
| Pull requests merged | 28 | |
| Versions released | 27 | |

Lines of code by part (blank lines not counted):

| Part | Lines |
|---|--:|
| Home screen, Quick Menu and settings (Python) | 16,042 |
| System image (scripts, services, config) | 1,366 |
| Build and tools | 1,400 |
| Tests | 7,206 |

## What's new in 0.24.0

- **Cast from your phone**: the PC shows up on your Wi-Fi as a screen and a speaker. AirPlay from an iPhone, iPad or Mac (a video, photos, music or the whole screen: it comes to the front, and goes away when you stop), Spotify Connect (pick the PC in the Spotify app; Premium), and YouTube with a TV code. Settings → Casting names it and turns each part on or off; Quick Menu → System → Stop casting drops the phone.
- **Your phone as a remote**: Settings → Phone remote shows a code and a QR code; the page (nothing to install) has a d-pad, the buttons and a keyboard, so Wi-Fi passwords, searches and sign-ins are typed on the phone. `hearthctl type` types from a terminal the same way.
- **Your photos in the screen saver**: a folder, or a plugged-in drive's pictures, on their own or mixed with your games' art, the right way up (Settings → Home screen).
- **Accessibility**: Settings → Accessibility: larger text (two sizes) and a high-contrast look, each person's own.
- **Two icons on the desktop**: **Hearth** goes back to the TV, and **Steam Gaming Mode** starts Game Mode with Steam's own interface for that one session (Hearth is back the next time). Bazzite's "Return to Gaming Mode" stays and lands on Hearth too.
- **Fixes from the third field run**: the system drive can no longer be offered for erasing when lsblk lists partitions flat (util-linux 2.41); spotifyd installs again (its checksum file is named after the build), and Settings says so when the install failed; `hearthctl type` and the phone keyboard no longer drop doubled letters; Home from the Quick Menu over Kodi or Heroic closes the menu at once; Search's delete hint names Backspace with a keyboard; long names are cut or wrapped instead of drawn under switches, values and percentages, also at the larger text sizes; arrows the font hasn't got draw as chevrons; a controller whose battery level is unknown no longer shows an empty outline.

## What's working

| Area | What it does | Status |
|---|---|---|
| Home screen | TV-style rows, liveries, a drawing or icon on every tile, a backdrop from the focused game, controller batteries and network by the clock | ✅ Confirmed on the PC |
| Emulation | ES-DE with a tile per console; emulators tuned for the GPU and TV; game art found automatically | ✅ Confirmed on the PC (Dolphin working) |
| Wii Remote | DolphinBar pointer on the home screen and as a mouse; handed to Dolphin for Wii games | ✅ Confirmed on the PC (pointer working) |
| Quick Resume | Hold Guide to pause a game and pick it up later (up to 3) | ✅ Confirmed on the PC |
| Quick Menu | Guide button panel: audio, per-app volume, Discord, stats, power, updates, screenshots | ✅ Confirmed on the PC |
| Streaming | YouTube (VacuumTube), Twitch (VacuumStream), Kodi, Jellyfin, Plex, Moonlight | ✅ Confirmed on the PC |
| Game stores | Epic Games (Heroic), Battle.net, EA app and Ubisoft Connect (Lutris) tiles; their games in the Library | 🟡 Shipped |
| Customising | Favorites with X, move tiles, hide tiles, liveries, sounds | ✅ Confirmed on the PC |
| Search and details | Search every app and game; Y on a game for play time and last played | ✅ Confirmed on the PC |
| Settings | Wi-Fi, static IP and DNS, Bluetooth, audio devices, storage (format and use a new drive) | ✅ Confirmed on the PC |
| Captures | Screenshots from the Quick Menu, a gallery tile, in the screen saver | ✅ Confirmed on the PC |
| Watch next | Shows and films in progress from Jellyfin, Plex and Kodi; resumes and reports back | 🟡 Shipped |
| Family | Daily game-time limit, bedtime and locked tiles behind a PIN, per person | 🟡 Shipped |
| Privacy | No ads or tracking; a guide to turn off the TV's own tracking, by make | 🟡 Shipped |
| TV control (CEC) | TV on and to the right input on wake and on Guide; standby with the PC | 🟡 Shipped |
| Performance | Hearth idles under 2% of one core and about 300 MB; hearthctl footprint | ✅ Confirmed on the PC |
| Updates | Automatic, versioned, with releases on GitHub, a what's-new card and rollback | ✅ Confirmed on the PC |
| People | Who's playing? (at start, after sleep, from the Quick Menu) with optional PINs; own favorites, colour scheme, Continue, Steam and Discord; limits set by an admin | 🟡 Shipped |
| Casting **new** | AirPlay (video, photos, music, screen mirroring), Spotify Connect, YouTube with a TV code; Quick Menu → Stop casting | 🟡 Shipped |
| Phone remote **new** | A page on the home network with a d-pad, the buttons and a keyboard, paired with a code and QR code on the TV | 🟡 Shipped |
| Accessibility **new** | Larger text (two sizes) and a high-contrast look, each person's own; your own photos in the screen saver | 🟡 Shipped |
| Folders | Groups of tiles | ⚪ Not started (deferred for now) |
| NVIDIA graphics | A separate image with NVIDIA's driver | ⚪ Not started (deferred: AMD and Intel first) |
| Netflix and similar | DRM limits these to low quality on any home-built PC | ⛔ Not possible |

**Confirmed** means reported working on the real PC; **Shipped** means built, tested and released, but not yet reported on.

## Open issues

| Issue | Where it stands | What's needed |
|---|---|---|
| A Steam game started cold from its tile stayed on Steam's spinner (Sekiro) | Seen once in the field tests (#40); the cause isn't known yet | The same game from Steam's own Game Mode, and PROTON_LOG=1 |
| Steam "Switch to Desktop" can still hang | Holding Guide for 4 s always gets you home; the cause isn't known | hearthctl status and hearthctl logs right after it happens |
| 0.24.0 not yet tried on the PC | Casting, the phone remote, photos in the screen saver and accessibility are built and tested in a virtual display | Update to the staging build, then the field tests again (docs/FIELD_TESTS.md) |

## Next

- Fix what turns up on the real PC.
- Spoken menus; picture and sound settings (frame-rate matching, night mode); RetroAchievements; save backups.
- When wanted: groups of tiles; NVIDIA support.

## Every version

| Version | Date | Lines of code | Tests | Docs (lines) | Guides | Pull requests |
|---|---|--:|--:|--:|--:|--:|
| [0.24.0](../0.24.0/report.md) | 2026-10-03 | 18,808 | 517 | 2,121 | 16 | 28 |
| [0.23.0](../0.23.0/report.md) | 2026-10-01 | 17,261 | 458 | 1,979 | 15 | 28 |
| [0.22.4](../0.22.4/report.md) | 2026-09-30 | 15,485 | 381 | 1,773 | 14 | 27 |
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
