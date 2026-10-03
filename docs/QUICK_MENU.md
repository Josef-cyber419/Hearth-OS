# Quick Menu

**Tap the Guide button** (Xbox / PS / Home button) in any app, or on the home
screen, and the Quick Menu slides in over what's playing. The game shows
through behind it and is paused until you close the menu. A remote's **Menu**
key (e.g. programmed on a FLIRC) opens it too, and so does tapping a keyboard's
**Windows** key on its own (not as part of a shortcut).

| Button | Does |
|---|---|
| LB / RB | Switch tabs |
| Up / Down | Choose an entry |
| Left / Right | Adjust a slider, change a device |
| A | Toggle, mute a slider, run an action |
| B, Start, or tap Guide | Close |
| Up from the top entry | Onto the tabs: Left / Right switch tabs, Down goes back |

**With a mouse** (after the Windows key, say): Hearth's own pointer appears,
pointing at an entry picks it, a click uses it or opens a tab, the wheel
scrolls or turns a slider, and a right click closes the menu.

Button hints follow what you used last: Xbox, PlayStation or Nintendo names,
keyboard keys, or a Wii Remote's buttons (Settings → Controllers → *Button
names on screen* can fix one instead).

**Hold Guide** (1.5 s) to go home with the game paused for **Quick Resume**
(or closed, if you set Settings → Controllers → *Holding Guide in a game* to
close), or to leave Discord and go back to your game. In Steam, Guide is
Steam's own; hold it for **4 s** to close Steam and come home (a way out if
Steam ever hangs).

## Tabs

- **Audio**: first, **what's playing** in any media app (VacuumTube, Twitch,
  Spotify, Kodi, a browser…): A plays/pauses, Left/Right skip. Then the
  volume of the current output, which **output** to use (TV
  speakers, soundbar, headset…), which **microphone**, mic level, mute mic.
  Switching output also moves everything already playing to it.
- **Mixer**: a volume slider for each app playing sound, e.g. game,
  Discord voice, music. A mutes that app.
- **Discord**: start Discord in the background, bring it to the front ("Show
  Discord"), and while you're in a call: **mute my mic**, **deafen**, **voice
  volume**. The call controls work at the audio level, so they work with
  Discord hidden. Mute and deafen last for the current call. (PipeWire
  remembers app volumes between sessions, but Hearth clears a remembered
  Discord mute, so a new call never starts silently muted.)
- **Stats**: how hard the PC is working, live: processor and graphics load
  and temperature (plus the GPU's hotspot, clock and power), memory and video
  memory. The top line says in plain words whether it's cool, warm, or hot
  enough to be slowing down (throttling), and why.
- **System**: resume, **Quit game, back to ES-DE** (while a game runs from
  ES-DE: closes just the emulator, ES-DE stays on your list), **Home, keep
  <game> paused** (Quick Resume: it waits
  in a row on the home screen and carries on where you were), close the
  current app, **Stop casting** (while a phone is casting to the screen:
  drops it; see [CASTING.md](CASTING.md)), **take a screenshot** (the menu
  closes first, so it's just the game; see them with the **Captures** tile),
  check for updates, report a
  problem, sleep, restart, power off. With a Wii Remote connected, also
  *Wii Remote pointer as mouse* for the app in front. Anything that ends what
  you're doing asks you to press A again.

**Notices** appear top right over whatever's playing, for a few seconds, and
never take the game's input: a controller running low on battery, an app
that just finished installing, an update ready to finish on restart, a
screenshot saved.

A Wii Remote on a DolphinBar opens the Quick Menu with a tap of **Home**; see
[HARDWARE.md](HARDWARE.md#wii-mayflash-dolphinbar-30-yes-its-worth-it).

## Discord with a controller

Discord has no TV interface, so while it's in front your controller works as a
mouse:

| Control | Does |
|---|---|
| Left stick | Move the pointer (push further to go faster) |
| Right stick | Scroll |
| A / X | Left / right click |
| D-pad | Arrow keys |
| Y / B | Enter / Escape |

Join a voice channel, then tap Guide → Discord → *Back to <game>*. The call
keeps going in the background.

## Settings

In `~/.config/hearth/apps.toml` (copy it from `/usr/share/hearth/apps.toml`):

```toml
[quick_menu]
pause_game = false  # keep the game running while the menu is open
```

Steam keeps its own Guide-button menu (Quick Access), so tapping Guide in Steam
opens Steam's menu rather than Hearth's.
