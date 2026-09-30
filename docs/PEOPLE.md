# People: everyone with their own home screen

With one person on the PC nothing is asked and nothing changes. Add a second
person and Hearth starts on **Who's playing?**, one tile per person.

## Setting it up

1. Settings → **People** → **Add a person**.
2. Type your name, then a 4-digit PIN: you're the **admin**.
3. Type their name. Add more with **Add a person**.

For each person, on the same page:
- **Name** and **Colour** (their tile on Who's playing?).
- **PIN**: optional, 4 digits. Without one, anyone can pick them.
- **Admin**: can open Settings and Desktop Mode, and their PIN lets others
  past their limits. An admin needs a PIN; there's always at least one.
- **Steam account**: the account Steam signs in to for them. Leave it on
  *Choose on Steam* for someone new: Steam asks them to sign in (tick
  *Remember me*), and Hearth remembers that account for them.
- **Remove**: their favorites, play times and Discord go; games stay. With
  one person left, Hearth goes back to not asking.

Limits for each person (game time a day, bedtime, locked tiles) are in
Settings → **Family** ([Family](FAMILY.md)).

## What's each person's own, and what's shared

| Their own | Shared by the household |
|---|---|
| Favorites, tile order, hidden tiles | ROMs, emulators and ES-DE |
| Continue row, play times, last played | Installed Steam games (downloaded once) |
| Steam sign-in (their account's library and play times) | Apps, the look (livery), sounds |
| Discord sign-in | Wi-Fi, Bluetooth, TV and audio settings |
| Game-time limits, bedtime, locked tiles | YouTube, Twitch, Kodi, Jellyfin, Plex |

## Switching

- **Switch person** in the System row goes back to Who's playing? (B to stay).
- Switching closes games paused with Quick Resume, Steam and Discord, then
  opens the next person's: their Steam account the next time Steam starts,
  and their Discord.
- Only an admin can open **Settings** and **Desktop Mode**; anyone else is
  asked for an admin's PIN.

## How it works

People are Hearth's own profiles on the PC's one account, not separate Linux
accounts: they keep the household's things apart on the TV, and the admin
PIN guards Settings and Desktop Mode, but anyone with the account's password
(in Desktop Mode or over SSH) can see everything. The list is in
`~/.config/hearth/people.json` (PINs only as salted hashes); each person's
own state is in `~/.local/state/hearth/people/<id>/`, and their Discord data
waits in `~/.var/app-people/<id>/` while someone else uses the TV. The first
person keeps the files Hearth used before there were people.
