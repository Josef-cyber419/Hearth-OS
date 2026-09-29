# Epic Games, GOG and Battle.net

Steam isn't the only store on the home screen. Two more tiles in the **Play**
row cover the other big PC stores. Both apps are installed on first boot, or
on the next start after updating.

## Epic Games (and GOG, Amazon): Heroic

The **Epic Games** tile opens [Heroic Games Launcher](https://heroicgameslauncher.com),
which runs Windows games with Proton, the same way Steam does. It has its own
controller navigation.

1. Open the tile, sign in to Epic (and to GOG or Amazon if you use them).
2. Install games from Heroic's library. To put them on a second drive set up in
   Settings → Storage, choose a folder under `/var/mnt/…` when installing.
   Heroic already has access there.

Installed Epic and GOG games also appear in Hearth's **Library** (under *Epic
Games* and *GOG*), in **Continue** once played, and in **Search**. Starting one
from Hearth launches it through Heroic directly. When you quit the game,
Heroic's window stays open. Hold **Guide** to go home.

## Battle.net: Lutris

The **Battle.net** tile runs Battle.net under [Lutris](https://lutris.net),
which Bazzite recommends for it:

1. The first time, the tile opens Lutris's **Battle.net installer**. Pick
   *Install* and follow it (the controller works as a mouse), then sign in.
2. After that, the tile starts Battle.net directly. Install and play games
   from Battle.net as usual.

Games you add to Lutris (Battle.net's among them, and anything else Lutris
installs) show in Hearth's Library under *Battle.net* or *PC*, with Lutris's
own play time. They start straight from Hearth.

## What doesn't work

Games whose anti-cheat blocks Linux won't run with any launcher, Steam
included, such as Fortnite and some competitive shooters. Check
[Are We Anti-Cheat Yet?](https://areweanticheatyet.com) or
[ProtonDB](https://www.protondb.com) before buying.
