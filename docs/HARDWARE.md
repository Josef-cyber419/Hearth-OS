# Hardware that makes a difference

Ordered roughly by how much it improves a living-room PC for the money.

## Must-haves

### GPU: AMD
Hearth is built for AMD Radeon. Bazzite's Game Mode (gamescope) works best
there: HDR, VRR, and the Steam Deck-style performance overlay all work with
the open-source drivers. Intel Arc works but is less tested. NVIDIA isn't
supported yet. The full list is in [COMPATIBILITY.md](COMPATIBILITY.md).

**The HDMI 2.1 catch (AMD):** the HDMI Forum doesn't allow HDMI 2.1 in AMD's
open-source Linux driver, so AMD's HDMI port tops out at HDMI 2.0 (4K60, no 4K120,
no HDMI-VRR). If you want 4K120 with HDR on a TV, use the card's **DisplayPort
output with an active DP 1.4 → HDMI 2.1 adapter**. Cable Matters' adapter is the
one most people use; update its firmware. VRR through adapters is hit or miss.

### A way to use your TV remote: Pulse-Eight USB-CEC adapter (~$40)
PC graphics cards don't support HDMI-CEC, the protocol that lets TVs and
consoles control each other. This adapter plugs inline between the PC and TV and
adds it. It makes the biggest single difference to feeling like a real smart-TV
device:
- your **TV remote's arrows/OK/Back** drive Hearth and Kodi
- the **TV turns on and switches to the PC** when it wakes, and turns off when
  it sleeps

Hearth sets it up automatically (see `image/system_files/usr/lib/udev/rules.d`).
Some users report the passthrough limiting 4K HDR bandwidth; check reviews
against the resolution you want. If it's a problem for you, a FLIRC gives you
remote control, but not TV power/input control.

### Or: FLIRC USB IR receiver (~$25)
A tiny USB stick you "teach" any IR remote's buttons, and it shows up as a
keyboard. Use the TV's own remote or a cheap media remote. Program one button as
**Home** (`KEY_HOMEPAGE`); Hearth treats it as "go home" from any app.

### Controllers
- **8BitDo Ultimate 2 / Ultimate 2.4G**: uses a USB 2.4GHz dongle, so no
  Bluetooth pairing hassle, and works with Linux out of the box.
- **Xbox Wireless Controller**: works over Bluetooth. Bazzite includes the
  `xone` driver for Microsoft's USB wireless dongle, which has lower latency.
- **DualSense (PS5)**: Bluetooth or USB. Gyro and haptics work in many games
  through Steam Input.

### Networking: Ethernet
Wired Ethernet, if you can. It matters most for Moonlight/Sunshine streaming and
big game downloads.

## Game-changers for emulation

### Wii: Mayflash DolphinBar (~$30), yes, it's worth it
A USB sensor bar with a built-in Bluetooth adapter for **real Wii Remotes**:
genuine pointer aiming, motion controls, speaker and rumble, with none of the
Bluetooth pairing trouble. It also works as a sensor bar for Wii Remotes used
as light guns in Wii rail shooters.

**Setup:**
1. Put it centred above or below the TV and plug it **straight into the PC**
   (not a hub).
2. Press its mode button until the LED shows **mode 4**, and leave it there.
3. Pair each remote: press the DolphinBar's sync button, then the red sync
   button in the remote's battery cover. The remote rumbles and lights its
   player LED when Hearth sees it.
4. Once, in Desktop Mode: Dolphin → Controllers → set each Wii Remote to
   **Real Wii Remote** and tick **Continuous Scanning**.

`hearthctl doctor` checks the DolphinBar is in mode 4 and usable. (The image
includes the device permissions Dolphin needs for it, and for the official
GameCube controller adapter.)

**The Wii Remote also works in Hearth itself**, like a TV remote with a pointer:

| Wii Remote | Home screen and apps | Quick Menu |
|---|---|---|
| Point | Highlights the tile you aim at | |
| D-pad | Arrow keys | Move |
| A (or 2) | Open / Enter | Select |
| B (or 1) | Back / Escape | Back |
| − / + | Options (favourite, move, hide a tile) / Menu | Previous / next tab |
| Home | Tap: Quick Menu. Hold: close the app and go home | Close |

**Settings → Wii Remote** has the rest: where the sensor bar is (above or below
the TV), pointer speed and steadiness, holding the remote sideways (NES style),
mouse mode, **Flip up/down** (if the pointer goes up when you aim down), and
**Calibrate the pointer**: aim at two targets and the pointer lands exactly
where you point, whatever your TV size and seating distance.

While a Wii game is paused for Quick Resume, Hearth takes the remotes back from
Dolphin, and gives them to Dolphin again when you pick the game up.

**As a mouse**, the pointer moves the mouse, A clicks and 2 right-clicks. That's
automatic in Discord, and Quick Menu → System → *Wii Remote pointer as mouse*
switches it for whatever's in front, like a browser in Desktop Mode or a PC
game's menus (remembered for that app). Set when it's on in `apps.toml`:

```toml
[wii_remote]
mouse = "apps"     # "apps" (Discord and other pointer apps), "always" or "never"
enabled = true     # false: Hearth leaves Wii Remotes alone entirely
```

While **Dolphin** is running, Hearth lets go of the remotes so Wii games get
them, and takes them back when Dolphin closes. In a Wii game, Home is the game's
Home menu; use a controller's Guide button (or Dolphin's hotkey) to leave.

### Light guns for retro arcade/console shooters
Old light guns only work with CRT TVs. Modern alternatives:
- **Sinden Lightgun**: uses a camera plus a white border drawn around the game.
  Works on any TV, with official Linux support.
- **GUN4IR** (DIY or pre-built): IR LEDs around the TV. Very accurate, lowest
  latency, needs a small install.
- **Retro Shooter RS3 Reaper**: prebuilt, IR-based, recoil options.

Pair with RetroArch or MAME for Time Crisis, House of the Dead,
Duck Hunt, and so on.

### Arcade stick or retro-style pads
8BitDo's retro receivers let original SNES/Genesis/PS controllers work
wirelessly, which is great for authenticity.

## Capture card: play real consoles through Hearth

An Elgato capture card turns Hearth into the hub for **the consoles nobody can
emulate yet**: PS5, Xbox Series, Switch 2. Plug the console into the card, and
an **HDMI Input** tile appears on the home screen. It shows the console full
screen with its sound, so everything runs through one HDMI cable and one
home screen. (The card still works for recording or streaming too, e.g. with
OBS from Desktop Mode.)

- **Which card**: the USB models from HD60 S+ onward (**HD60 X**, **4K X**,
  4K S) are standard video devices and work on Linux with no drivers. The 4K X
  captures 4K60 HDR. Avoid Elgato's PCIe cards (4K60 Pro, 4K Pro): they have no
  Linux drivers.
- **Settings**: resolution, frame rate and device in `/etc/hearth/capture.conf`.
  The default is 1080p60, the safe choice for HD60 X. Set `3840x2160` for a 4K X.
- **Latency**: expect roughly 2–3 frames of added delay. That's fine for most
  games. For competitive shooters or rhythm games, connect the card's
  **HDMI passthrough** port to a second TV input instead, which has zero delay.
- **HDCP**: capture only works without copy protection. On PS5, turn off
  *Settings → System → HDMI → Enable HDCP*. Switch and Xbox games work as-is.
  Streaming apps (Netflix etc.) on those consoles stay blocked, which is expected.

## Quality of life

- **Bluetooth**: an Intel AX210/AX211 Wi-Fi + Bluetooth card is the most
  reliable choice on Linux. It helps a lot when you use several Bluetooth
  controllers at once. Avoid no-name Bluetooth dongles.
- **Keyboard with trackpad** (e.g. Logitech K400 Plus): for the occasional trip
  into Desktop Mode, sign-ins, and typing searches. Keep it in a drawer.
- **Storage**: NVMe SSD, 2 TB or more if you keep a Steam library and ROMs.
  A drive added later (inside, or USB) is set up from Settings → Storage: see
  [STORAGE.md](STORAGE.md).
- **Audio**: TV's eARC to a soundbar or AV receiver. Enable passthrough in Kodi
  for Dolby Atmos / DTS:X from your media library.
- **Small quiet case with good airflow**: it lives next to the TV. Tune fan
  curves in the BIOS so it's silent while idle and during video playback.
- **Wake from controller/remote**: enable "wake on USB" in the BIOS so a remote
  or controller dongle can wake the PC from sleep, like a console.
