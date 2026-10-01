# Family: play-time limits, bedtime and locked tiles

Settings → **Family** sets house rules. With one person on the PC they apply
to everyone, under one household PIN (below). Once you've added people
(Settings → **People**, see [People](PEOPLE.md)), each person who isn't an
admin has their own limits, set by an admin on the same page ("Limits
for"), and any admin's PIN lets them past a limit.

## Setting it up

1. Settings → Family → **Set a PIN to start**. Pick four digits.
2. Choose what you want:
   - **Game time each day**: 30 minutes up to 4 hours, or no limit. Only time
     in games counts (Steam, emulation, the other stores, your library's
     games), and only while a game is on screen. A game paused with Quick
     Resume doesn't count, and neither do films, YouTube, Twitch or other TV
     apps. It resets every day.
   - **Bedtime**: from 20:00, 21:00, 22:00 or 23:00 until 07:00, games need
     the PIN.
   - **When time's up**: **Remind** (a notice over the game) or **Close the
     game**, which warns a minute first so there's time to save.
   - **Locked tiles**: any tile can always need the PIN, whatever the time
     (e.g. Discord, or Desktop Mode).

The Family page itself needs the PIN each time you open Settings.

## What happens

- **Five minutes before** time's up, a notice appears over the game.
- **When time's up** (or at bedtime), another notice. With *Close the game*,
  the game closes a minute later.
- **Starting a game** after that asks for the PIN on the home screen. Change
  each digit with **Up/Down**, move with **Left/Right**, **A** to check.
  A keyboard's or TV remote's number keys work too.
- **The right PIN** starts it and gives **30 minutes more** (locked tiles just
  open).

## Good to know

- Forgot the PIN? In Desktop Mode, remove the `"family"` section from
  `~/.config/hearth/settings.json` (this also turns the limits off). It's meant
  to keep a house rule, not to stop someone who can use Desktop Mode, so lock
  the **Desktop Mode** tile too if that matters.
- Today's game time is kept in `~/.local/state/hearth/family.json`. The PIN is
  stored only as a salted hash.
