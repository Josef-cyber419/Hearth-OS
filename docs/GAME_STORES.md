# Epic Games, GOG, Battle.net, EA and Ubisoft

Steam isn't the only store on the home screen. More tiles in the **Play** row
cover the other big PC stores, so all your games end up in one Library. The
apps behind them (Heroic and Lutris) are installed on first boot, or on the
next start after updating.

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

## Battle.net, EA app and Ubisoft Connect: Lutris

The **Battle.net**, **EA app** and **Ubisoft Connect** tiles run those apps
under [Lutris](https://lutris.net), which Bazzite recommends for them:

1. The first time, a tile opens Lutris's **installer** for its app. Pick
   *Install* and follow it (the controller works as a mouse), then sign in.
2. After that, the tile starts the app directly. Install and play games from
   it as usual.

Games you add to Lutris show in Hearth's Library under *Battle.net*, *EA*,
*Ubisoft* or *PC*, with Lutris's own play time, and start straight from
Hearth. (Lutris sorts them by store when you've linked the store in Lutris's
*Sources*; games installed from inside the store app itself show under *PC*.)

**Bought on Steam?** EA and Ubisoft games bought on Steam need nothing extra:
Steam starts the EA app or Ubisoft Connect for them by itself. The tiles are
for games bought from EA or Ubisoft directly, or with EA Play and Ubisoft+.

## What doesn't work

Games whose anti-cheat blocks Linux won't run with any launcher, Steam
included, such as Fortnite, EA's games using its Javelin anti-cheat
(Battlefield 6, EA Sports FC) and some other competitive shooters. Check
[Are We Anti-Cheat Yet?](https://areweanticheatyet.com) or
[ProtonDB](https://www.protondb.com) before buying.
