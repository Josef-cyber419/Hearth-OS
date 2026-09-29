# Adding a drive

A drive added after install, inside the PC or over USB, is set up from
**Settings → Storage**, with the controller. From there it can hold Steam
games and your ROMs.

## Setting it up

Open Settings → Storage. Each drive other than the one Hearth runs from is
listed with what's on it now. Pick **Look for drives again** after plugging
one in.

- **Erase it and set it up for games**: deletes everything on the drive and
  formats it for Linux (ext4). Hearth asks you to press A a second time, and
  that prompt names the drive it will erase. Use this for a drive from
  Windows: NTFS and exFAT don't work well for Steam games on Linux.
- **Use it for games (keeps its files)**: offered when the drive already has
  a Linux filesystem (ext4, btrfs or xfs). Nothing on it changes.

Either way the drive is mounted at `/var/mnt/games` (or its label, or
`games2`...) now and at every start-up. If it's unplugged, start-up carries on
without it; plug it back in and restart.

## Putting things on it

Once a drive is set up, its entry has:

- **Steam games on it**: adds `SteamLibrary` on the drive as a Steam library
  folder. When installing a game, choose it in Steam's install dialog. To move
  games already installed, use Steam → Settings → Storage. Steam must be closed
  while the library list changes (Quick Menu → Close Steam). Turning this off
  works only once no games are installed there.
- **ROMs on it**: moves your ROMs folder onto the drive, with progress shown,
  and links `~/ROMs` to it. ES-DE and the emulators find everything as before.
  Turning it off moves the ROMs back. If a file with the same name is already
  on the other side, the move stops without overwriting anything.
- **Stop using it**: unmounts it and stops mounting it at start-up. Nothing on
  it is erased. Turn off Steam games and ROMs first.

## How it works

Finding drives needs no special rights (`lsblk`). Erasing, mounting and
releasing go through `/usr/libexec/hearth/hearth-storage`, which runs as root
without a password (a TV remote can't type one), through a rule in
`/etc/sudoers.d/hearth`. It does only these three things, checks its arguments,
and refuses:

- the drive the system runs from, including any partition on it;
- anything mounted anywhere except `/var/mnt` or `/run/media`, where drives
  are normally mounted, since something else is using it.

A mount entry Hearth adds to `/etc/fstab` looks like:

```
UUID=… /var/mnt/games ext4 defaults,nofail,x-systemd.device-timeout=10s,x-hearth 0 0
```

`x-hearth` marks it as Hearth's; `nofail` means a missing drive never stops
start-up.

From a terminal, the same steps are:

```sh
sudo /usr/libexec/hearth/hearth-storage format /dev/sdX games   # erases /dev/sdX
sudo /usr/libexec/hearth/hearth-storage use /dev/sdX1 games     # keeps files
sudo /usr/libexec/hearth/hearth-storage release /dev/sdX1
```
